"""
Populate the ticker -> CUSIP cache (sec_13f_cusip_map) for a broad universe.

The SEC bulk 13F data set is keyed by CUSIP, not ticker. To answer
"which managers hold <ticker>?" the read helper ``resolve_cusip`` looks up a
ticker in ``sec_13f_cusip_map``. Out of the box only a small built-in seed
(B4) is populated, so coverage is limited to a handful of mega-caps.

This loader fills that table for the S&P 500 universe by:

  1. reading the constituents from the local ``sp500_constituents`` table
     (already populated -- no index-constituents API call), and
  2. resolving each ticker -> CUSIP via the FMP stable ``profile`` endpoint
     (which returns the security ``cusip``), then
  3. upserting ``(cusip, issuer_name, ticker, ...)`` rows via
     ``openbb_sec.utils.thirteen_f_index.upsert_cusip_map`` (idempotent).

Once populated, ``resolve_cusip`` covers the full index as a pure MySQL read --
no live API calls on the request hot path. Re-running is safe (idempotent
``INSERT ... ON DUPLICATE KEY UPDATE``); subsequent runs only refresh values.

Usage:
    python Tools/populate_cusip_map.py --dry-run            # plan only, no writes
    python Tools/populate_cusip_map.py                      # S&P 500 (sp500_constituents)
    python Tools/populate_cusip_map.py --symbols AAPL,MSFT  # explicit tickers
    python Tools/populate_cusip_map.py --limit 25           # first N (smoke test)

Notes:
    - Writes to the same database the 13F index lives in (DatabaseConfig
      default -> openbb_fmp_cache_test), via the thirteen_f_index helpers.
    - CUSIP identifiers are licensed (CUSIP Global Services / S&P). This cache
      is for local/personal use; do not redistribute the table publicly.
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Fix Windows console encoding (cp1252 can't handle Unicode emojis from libs)
# ---------------------------------------------------------------------------
if sys.platform == "win32" and sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Ensure fmp_cached / sec providers are importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIRS = [
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp_cached"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "sec"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "core"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "platform"),
]
_ext_root = os.path.join(PROJECT_ROOT, "openbb_platform", "extensions")
if os.path.isdir(_ext_root):
    for _d in os.listdir(_ext_root):
        _dp = os.path.join(_ext_root, _d)
        if os.path.isdir(_dp):
            _SRC_DIRS.append(_dp)
_obbext_root = os.path.join(PROJECT_ROOT, "openbb_platform", "obbject_extensions")
if os.path.isdir(_obbext_root):
    for _d in os.listdir(_obbext_root):
        _dp = os.path.join(_obbext_root, _d)
        if os.path.isdir(_dp):
            _SRC_DIRS.append(_dp)
for _p in _SRC_DIRS:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
except ImportError:
    pass

# Skip the 67-table existence check on the fmp_cached side; we only touch the
# three 13F tables, created on demand by init_thirteen_f_index().
os.environ.setdefault("FMP_CACHE_AUTO_CREATE_DB", "false")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="  %(levelname)-5s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
for _quiet in ("urllib3", "openbb_core", "asyncio"):
    logging.getLogger(_quiet).setLevel(logging.WARNING)

logger = logging.getLogger("populate_cusip_map")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FMP_STABLE = "https://financialmodelingprep.com/stable"
SOURCE_PROFILE = "fmp_profile"
SP500_TABLE = "sp500_constituents"
REQUEST_TIMEOUT = 20
DEFAULT_SLEEP = 0.3  # seconds between profile calls (FMP courtesy)


def _resolve_api_key() -> str | None:
    """Resolve FMP API key from user settings or environment."""
    try:
        from openbb_core.app.service.user_service import UserService

        user_settings = UserService().default_user_settings
        fmp_api_key = getattr(user_settings.credentials, "fmp_api_key", None)
        if fmp_api_key:
            key_val = (
                fmp_api_key.get_secret_value()
                if hasattr(fmp_api_key, "get_secret_value")
                else str(fmp_api_key)
            )
            logger.info("API key loaded from user settings.")
            return key_val
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not load user settings: %s", e)

    key_val = os.environ.get("FMP_API_KEY", "")
    if key_val:
        logger.info("API key loaded from FMP_API_KEY env var.")
        return key_val

    logger.warning("No FMP API key found.")
    return None


def get_sp500_symbols(database: str | None = None) -> list[tuple[str, str]]:
    """Read active S&P 500 ``(symbol, name)`` rows from the local
    ``sp500_constituents`` table -- no index-constituents API call.
    """
    import pymysql
    from openbb_fmp_cached.utils.database import DatabaseConfig

    params = DatabaseConfig().connection_params
    if database:
        params["database"] = database

    conn = pymysql.connect(**params, cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT symbol, security FROM {SP500_TABLE} "
                "WHERE is_active = 1 ORDER BY symbol"
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    out: list[tuple[str, str]] = []
    for r in rows:
        sym = (r.get("symbol") or "").strip().upper()
        name = (r.get("security") or "").strip()
        if sym:
            out.append((sym, name))
    return out


def fetch_cusip(symbol: str, api_key: str) -> tuple[str, str] | None:
    """Resolve a single ticker to (cusip, issuer_name) via FMP stable profile.

    Returns ``None`` if the profile is missing or has no CUSIP. Never raises for
    a single-symbol failure (so one bad ticker can't kill the batch).
    """
    import requests

    try:
        url = f"{FMP_STABLE}/profile?symbol={symbol}&apikey={api_key}"
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("%s: profile request failed: %s", symbol, str(e)[:80])
        return None

    if not isinstance(data, list) or not data:
        return None

    profile = data[0] or {}
    cusip = (profile.get("cusip") or "").strip()
    issuer = (profile.get("companyName") or profile.get("company") or "").strip()
    if not cusip:
        return None
    # CUSIP is a 9-char identifier; left-pad shorter values, reject longer.
    cusip = cusip.zfill(9)
    if len(cusip) != 9:
        logger.warning("%s: unexpected CUSIP %r -- skipping", symbol, cusip)
        return None
    return cusip, (issuer or symbol)


def populate(
    symbols: list[str],
    api_key: str,
    dry_run: bool = False,
    sleep: float = DEFAULT_SLEEP,
) -> dict:
    """Resolve each symbol to a CUSIP and upsert into sec_13f_cusip_map.

    Returns a stats dict.
    """
    from openbb_sec.utils.thirteen_f_index import (
        init_thirteen_f_index,
        upsert_cusip_map,
    )

    stats: dict = {
        "total": len(symbols),
        "resolved": [],
        "unresolved": [],
        "written": 0,
    }

    if dry_run:
        return stats

    init_thirteen_f_index()  # best-effort, idempotent
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    rows: list[tuple] = []
    total = len(symbols)
    for i, symbol in enumerate(symbols, 1):
        result = fetch_cusip(symbol, api_key)
        if result is None:
            stats["unresolved"].append(symbol)
            logger.info("[%3d/%3d] %-8s  no CUSIP", i, total, symbol)
        else:
            cusip, issuer = result
            # (cusip, issuer_name, ticker, title_class, figi, source, updated_at)
            rows.append((cusip, issuer, symbol, None, None, SOURCE_PROFILE, now))
            stats["resolved"].append(symbol)
            logger.info("[%3d/%3d] %-8s  %s  %s", i, total, symbol, cusip, issuer[:40])
        if sleep:
            time.sleep(sleep)

    if rows:
        stats["written"] = upsert_cusip_map(rows)
        logger.info("Upserted %d rows into sec_13f_cusip_map.", stats["written"])

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Populate the ticker->CUSIP cache (sec_13f_cusip_map)."
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Target MySQL database (default: from DatabaseConfig)",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated tickers to load (overrides the sp500_constituents table)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N symbols (smoke test)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP,
        help=f"Seconds to sleep between profile calls (default: {DEFAULT_SLEEP})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the plan only -- no API calls, no DB writes",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  POPULATE TICKER -> CUSIP CACHE (sec_13f_cusip_map)")
    print("=" * 70)

    api_key = _resolve_api_key()

    # Resolve the symbol universe (DB read -- cheap, allowed in dry-run too)
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        source_label = f"--symbols ({len(symbols)})"
    else:
        constituents = get_sp500_symbols(args.database)
        symbols = [s for s, _ in constituents]
        source_label = f"{SP500_TABLE} table ({len(symbols)} active)"

    if args.limit is not None:
        symbols = symbols[: args.limit]

    print(f"\n  Universe:    {source_label}")
    print(f"  To resolve:  {len(symbols)} symbols")
    print(f"  Profile EP:  {FMP_STABLE}/profile")
    print(f"  Target:      sec_13f_cusip_map (via thirteen_f_index helpers)")
    print(f"  Sleep:       {args.sleep}s between calls")

    if args.dry_run:
        print("\n  DRY RUN -- no API calls, no DB writes.")
        print("  Would resolve each symbol via FMP profile and upsert its CUSIP.")
        print("=" * 70)
        return

    if not api_key:
        print("\n  ERROR: no FMP API key; cannot resolve CUSIPs.")
        sys.exit(1)

    print("\n  Resolving ...\n")
    stats = populate(symbols, api_key, dry_run=False, sleep=args.sleep)

    print(f"\n{'=' * 70}")
    print("  RESULTS")
    print(f"{'=' * 70}")
    print(f"  Resolved:    {len(stats['resolved'])} / {stats['total']}")
    print(f"  Rows written: {stats['written']}")
    unresolved = stats["unresolved"]
    print(f"  Unresolved:  {len(unresolved)}")
    if unresolved:
        for sym in unresolved[:30]:
            print(f"    - {sym}")
        if len(unresolved) > 30:
            print(f"    ... and {len(unresolved) - 30} more")
    print("=" * 70)


if __name__ == "__main__":
    main()
