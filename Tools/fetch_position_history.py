"""
Fetch Daily Equity History for Portfolio Positions

Reads distinct stock symbols from the Portfolio_Positions table and fetches
10 years of daily price history via the OpenBB fmp_cached provider.

The fmp_cached provider automatically caches data in MySQL with intelligent
gap detection — subsequent runs only fetch missing date ranges.

Usage:
    python Tools/fetch_equity_history.py --dry-run     # plan only, no API calls
    python Tools/fetch_equity_history.py               # fetch all symbols
    python Tools/fetch_equity_history.py --symbols AAPL,MSFT  # specific symbols
    python Tools/fetch_equity_history.py --years 5     # custom lookback

Skipped Symbols:
    - CUSIPs / fund codes (digits-only prefixed, e.g. '09261F598')
    - Cash positions
    - Symbols known to be OTC/delisted that FMP may not cover
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Fix Windows console encoding (cp1252 can't handle Unicode emojis from libs)
# ---------------------------------------------------------------------------
if sys.platform == "win32" and sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Ensure fmp_cached provider is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIRS = [
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp_cached"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp"),
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

# Skip database/table creation — tables already exist.
# This avoids 67 redundant CREATE TABLE IF NOT EXISTS calls per symbol
# and the Windows cp1252 emoji crash in cache_schema.py.
os.environ.setdefault("FMP_CACHE_AUTO_CREATE_DB", "false")

# ---------------------------------------------------------------------------
# Configure logging so fmp_cached progress messages are visible on console
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="  %(levelname)-5s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Quiet noisy third-party loggers
for _quiet in ("urllib3", "openbb_core", "asyncio"):
    logging.getLogger(_quiet).setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Symbols to skip (CUSIPs, money-market funds, OTC/delisted)
# ---------------------------------------------------------------------------
# CUSIPs and fund codes are identified by leading digits
# Some OTC or very illiquid names may not have FMP coverage
SKIP_SYMBOLS = {
    "Cash",       # Cash balances, not equities
    "NSAV",       # OTC penny stock, likely no FMP coverage
    "MVVYF",      # OTC foreign, likely no FMP coverage
    "EADSF",      # OTC ADR (Airbus), may not have FMP coverage
    "NXDR",       # SPACs / defunct tickers
    "NHX202764",  # Fidelity internal codes
    "NHX203309",  # Fidelity internal codes
}


def _is_cusip(symbol: str) -> bool:
    """Check if a symbol looks like a CUSIP/fund code (starts with digit)."""
    return bool(symbol) and symbol[0].isdigit()


def ensure_market_holidays(start_year: int, end_year: int, database: str | None = None) -> None:
    """Ensure US market_holidays rows exist for the requested year range.

    This runs as a pre-step to improve cache gap detection accuracy and avoid
    unnecessary API lookups for market-closed dates.
    """
    import pymysql
    from openbb_fmp_cached.utils.database import DatabaseConfig

    try:
        from populate_market_holidays import compute_us_holidays
    except Exception as e:
        print(f"  WARNING: Could not import holiday pre-step helper: {e}")
        return

    rows = compute_us_holidays(start_year, end_year)
    if not rows:
        return

    config = DatabaseConfig()
    params = config.connection_params
    if database:
        params["database"] = database

    conn = pymysql.connect(**params)
    try:
        with conn.cursor() as cur:
            sql = """
                INSERT INTO market_holidays (holiday_date, market, holiday_name)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE holiday_name = VALUES(holiday_name)
            """
            cur.executemany(sql, rows)
            conn.commit()
            print(
                f"  Holiday pre-step: ensured {len(rows)} US market_holidays rows "
                f"for {start_year}-{end_year} in {params.get('database')}"
            )
    except Exception as e:
        print(f"  WARNING: Holiday pre-step failed: {e}")
    finally:
        conn.close()


def get_portfolio_symbols(database: str = None) -> list[str]:
    """Read distinct stock symbols from Portfolio_Positions, filtering out
    non-fetchable entries (CUSIPs, cash, OTC/delisted).

    Returns sorted list of ticker symbols.
    """
    import pymysql
    from openbb_fmp_cached.utils.database import DatabaseConfig

    config = DatabaseConfig()
    params = config.connection_params
    if database:
        params["database"] = database

    conn = pymysql.connect(**params, cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT symbol FROM Portfolio_Positions ORDER BY symbol"
            )
            all_symbols = [r["symbol"] for r in cur.fetchall()]
    finally:
        conn.close()

    # Filter
    tickers = []
    skipped = []
    for s in all_symbols:
        if _is_cusip(s):
            skipped.append((s, "CUSIP/fund code"))
        elif s in SKIP_SYMBOLS:
            skipped.append((s, "skip list"))
        else:
            tickers.append(s)

    return tickers, skipped


def _resolve_api_key() -> str | None:
    """Resolve FMP API key from user settings or environment."""
    try:
        from openbb_core.app.service.user_service import UserService
        user_service = UserService()
        user_settings = user_service.default_user_settings
        fmp_api_key = getattr(user_settings.credentials, "fmp_api_key", None)
        if fmp_api_key:
            key_val = (
                fmp_api_key.get_secret_value()
                if hasattr(fmp_api_key, "get_secret_value")
                else str(fmp_api_key)
            )
            print("  API key loaded from user settings.\n")
            return key_val
    except Exception as e:
        print(f"  WARNING: Could not load user settings: {e}")

    key_val = os.environ.get("FMP_API_KEY", "")
    if key_val:
        print("  API key loaded from FMP_API_KEY env var.\n")
        return key_val

    print("  WARNING: No FMP API key found. Cache-only mode.\n")
    return None


def fetch_history(symbols: list[str], years: int = 10, dry_run: bool = False):
    """Fetch daily equity history for a list of symbols.

    Uses fmp_cached's own ``_analyze_cache_gaps``, ``_fetch_from_fmp_sync``,
    and ``_store_in_database_cache`` — all synchronous.  No async / aiohttp.

    Returns dict with stats.
    """
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=years * 365)

    stats = {
        "total_symbols": len(symbols),
        "success": [],
        "failed": [],
        "total_rows": 0,
        "start_date": str(start_date),
        "end_date": str(end_date),
    }

    if dry_run:
        return stats

    # All imports from fmp_cached — sync MySQL + sync HTTP
    from openbb_fmp_cached.models.equity_historical import (
        FMPCachedEquityHistoricalQueryParams,
        _analyze_cache_gaps,
        _fetch_from_fmp_sync,
        _store_in_database_cache,
    )
    from openbb_fmp_cached.utils.database import init_database

    # One-time database init (tables already exist; skipped via env var)
    try:
        init_database()
    except Exception as e:
        print(f"  WARNING: Database init issue: {e}\n")

    api_key = _resolve_api_key()
    credentials = {"fmp_api_key": api_key} if api_key else None

    total = len(symbols)
    for i, symbol in enumerate(symbols, 1):
        t0 = time.time()
        try:
            query = FMPCachedEquityHistoricalQueryParams(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval="1d",
                adjustment="splits_only",
            )

            # --- fmp_cached: cache gap detection (sync MySQL) --------------
            try:
                cached_data, missing_ranges = _analyze_cache_gaps(query)
            except Exception as gap_err:
                print(f"    cache gap analysis failed: {gap_err}")
                cached_data, missing_ranges = [], [(start_date, end_date)]

            if not missing_ranges:
                data = cached_data
            else:
                if not credentials:
                    raise RuntimeError("No API key; cannot fetch missing data")

                # Always fetch the full date range in ONE API call.
                # FMP's /full endpoint returns all history regardless of
                # date params, so splitting by gap wastes API calls.
                overall_start = min(s for s, _ in missing_ranges)
                overall_end   = max(e for _, e in missing_ranges)
                total_gap_days = sum((e - s).days + 1 for s, e in missing_ranges)
                print(
                    f"    {len(missing_ranges)} gap(s), ~{total_gap_days} days "
                    f"-- fetching {overall_start} -> {overall_end}",
                    flush=True,
                )

                new_data: list[dict] = []
                fetch_query = FMPCachedEquityHistoricalQueryParams(
                    symbol=symbol,
                    start_date=overall_start,
                    end_date=overall_end,
                    interval=query.interval,
                    adjustment=query.adjustment,
                )
                try:
                    new_data = _fetch_from_fmp_sync(fetch_query, credentials)
                except Exception as fetch_err:
                    err_str = str(fetch_err)
                    if "No data found" in err_str or "EmptyData" in err_str:
                        pass  # no trading data in range (holidays only)
                    else:
                        raise

                # --- fmp_cached: store in MySQL cache (sync) ---------------
                if new_data:
                    print(f"    storing {len(new_data)} rows in cache ...", flush=True)
                    _store_in_database_cache(query, new_data)

                # Re-read complete data from cache
                try:
                    data, _ = _analyze_cache_gaps(query)
                except Exception:
                    data = cached_data + new_data

            elapsed = time.time() - t0
            rows = len(data)

            if rows:
                dates = [str(d.get("date", ""))[:10] for d in data if d.get("date")]
                first = min(dates) if dates else "N/A"
                last = max(dates) if dates else "N/A"
            else:
                first = last = "N/A"

            stats["total_rows"] += rows
            stats["success"].append(symbol)
            cache_tag = "CACHE" if not missing_ranges else "FETCH"
            print(
                f"  [{i:3d}/{total}] {symbol:<8s} "
                f"{rows:>6,d} rows  ({first} -> {last})  "
                f"{elapsed:.1f}s  [{cache_tag}]"
            )

        except Exception as e:
            elapsed = time.time() - t0
            err_msg = str(e)[:80]
            stats["failed"].append((symbol, err_msg))
            print(f"  [{i:3d}/{total}] {symbol:<8s}  FAILED ({elapsed:.1f}s): {err_msg}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Fetch daily equity history for portfolio positions"
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols to fetch (default: all from DB)",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=5,
        help="Number of years of history to fetch (default: 5)",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Target MySQL database name (default: from DatabaseConfig)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show plan only — do not make API calls",
    )
    parser.add_argument(
        "--skip-holiday-prestep",
        action="store_true",
        help="Skip market_holidays pre-step (not recommended)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  FETCH DAILY EQUITY HISTORY FOR PORTFOLIO POSITIONS")
    print("=" * 70)

    # Resolve symbols
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
        skipped = []
    else:
        symbols, skipped = get_portfolio_symbols(args.database)

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=args.years * 365)

    if not args.skip_holiday_prestep:
        ensure_market_holidays(start_date.year, end_date.year, args.database)

    # Print plan
    print(f"\n  Date range:    {start_date} -> {end_date} ({args.years} years)")
    print(f"  Interval:      1d (daily)")
    print(f"  Provider:      fmp_cached (auto-caching)")
    print(f"  Holiday prep:  {'enabled' if not args.skip_holiday_prestep else 'skipped'}")
    print(f"  Symbols:       {len(symbols)}")
    if skipped:
        print(f"  Skipped:       {len(skipped)}")
        for sym, reason in skipped:
            print(f"    {sym:<14s} ({reason})")

    print(f"\n  Symbols to fetch:")
    for i, sym in enumerate(symbols):
        print(f"    {sym}", end="")
        if (i + 1) % 10 == 0:
            print()
    if len(symbols) % 10 != 0:
        print()

    if args.dry_run:
        print(f"\n  DRY RUN — no API calls will be made.")
        print(f"\n  Estimated API calls: {len(symbols)} (one per symbol, cached provider")
        print(f"  handles gap detection and incremental fetching internally).")
        print(f"\n  Expected rows per symbol: ~2,520 (252 trading days × {args.years} years)")
        print(f"  Expected total rows: ~{len(symbols) * 252 * args.years:,d}")
        print(f"\n  Note: fmp_cached will cache results in MySQL. Subsequent runs")
        print(f"  only fetch missing date ranges (incremental).")
        print("=" * 70)
        return

    print(f"\n  Fetching ...\n")

    stats = fetch_history(symbols, years=args.years, dry_run=False)

    print(f"\n{'=' * 70}")
    print(f"  RESULTS")
    print(f"{'=' * 70}")
    print(f"  Successful:    {len(stats['success'])} / {stats['total_symbols']}")
    print(f"  Total rows:    {stats['total_rows']:,d}")
    if stats["failed"]:
        print(f"  Failed ({len(stats['failed'])}):")
        for sym, err in stats["failed"]:
            print(f"    {sym:<10s} {err}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
