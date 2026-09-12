"""
Fetch Daily Equity History for Portfolio Positions

Reads distinct stock symbols from the Portfolio_Positions table and fetches
daily price history via the OpenBB fmp_cached provider.

The fmp_cached provider automatically caches data in MySQL with intelligent
gap detection — subsequent runs only fetch missing date ranges.

Important:
    This script pre-caches market price data (equity_historical) used by the
    Portfolio App. Portfolio tables themselves (Portfolio_Positions,
    Account_Owner, ESPP_Plan) must be populated by their own loaders.

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
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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
# Configure logging so fmp_cached progress messages are visible on console.
# Only applied when run as the CLI entry point -- importing this module as a
# library (e.g. the jobs worker's ``openbb_job_extension`` discovery, or
# tests) must not reconfigure the process-wide root logger out from under
# other jobs/handlers sharing the same process (issue #1934).
# ---------------------------------------------------------------------------
if __name__ == "__main__":
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


def get_portfolio_symbols(database: str = None) -> tuple[list[str], list[tuple[str, str]]]:
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


def _connect(database: str | None = None):
    """Get a DictCursor pymysql connection using DatabaseConfig defaults."""
    import pymysql
    from openbb_fmp_cached.utils.database import DatabaseConfig

    config = DatabaseConfig()
    params = config.connection_params
    if database:
        params["database"] = database
    return pymysql.connect(**params, cursorclass=pymysql.cursors.DictCursor)


def _previous_trading_day(ref_date: datetime.date) -> datetime.date:
    """Return previous weekday date (Mon->Fri), suitable as default freshness target."""
    d = ref_date - timedelta(days=1)
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d


def check_portfolio_app_readiness(symbols: list[str], database: str | None = None) -> dict:
    """Check whether Portfolio App required data is present and recent.

    Validates:
      1) required tables have rows (Portfolio_Positions, Account_Owner, ESPP_Plan)
      2) each symbol has a cached latest close in equity_historical
      3) latest close date is at least the previous trading day
    """
    target_date = _previous_trading_day(datetime.now().date())
    readiness: dict = {
        "target_date": str(target_date),
        "table_counts": {},
        "missing_price_symbols": [],
        "stale_price_symbols": [],
    }

    if not symbols:
        return readiness

    conn = _connect(database)
    try:
        with conn.cursor() as cur:
            for table_name in ("Portfolio_Positions", "Account_Owner", "ESPP_Plan"):
                cur.execute(f"SELECT COUNT(*) AS c FROM {table_name}")
                readiness["table_counts"][table_name] = cur.fetchone()["c"]

            placeholders = ", ".join(["%s"] * len(symbols))
            sql = f"""
                SELECT symbol, MAX(date) AS max_date
                FROM equity_historical
                WHERE symbol IN ({placeholders})
                GROUP BY symbol
            """
            cur.execute(sql, tuple(symbols))
            rows = cur.fetchall()
            max_by_symbol = {r["symbol"]: r["max_date"] for r in rows}

            for sym in symbols:
                max_date = max_by_symbol.get(sym)
                if max_date is None:
                    readiness["missing_price_symbols"].append(sym)
                    continue
                if max_date < target_date:
                    readiness["stale_price_symbols"].append((sym, str(max_date)))
    finally:
        conn.close()

    return readiness


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


def _fetch_one_symbol_history(
    symbol: str,
    *,
    start_date,
    end_date,
    credentials: dict | None,
    database: str | None = None,
) -> dict[str, Any]:
    """Fetch/cache one symbol's daily history via fmp_cached (default provider call).

    Uses fmp_cached's own ``_analyze_cache_gaps``, ``_fetch_from_fmp_sync``, and
    ``_store_in_database_cache`` — all synchronous, no async / aiohttp. Raises on
    failure so the caller (``fetch_history``) can classify it as a per-symbol
    skip-and-continue failure. Returns ``{"rows", "first", "last", "cache_tag"}``.

    This is the default ``fetch_one_fn`` for :func:`fetch_history`; tests and the
    jobs handler may inject a different callable with the same shape to avoid a
    live fmp_cached/MySQL dependency.
    """
    from openbb_fmp_cached.utils.database import database_override

    with database_override(database):
        return _fetch_one_symbol_history_in_scope(
            symbol,
            start_date=start_date,
            end_date=end_date,
            credentials=credentials,
        )


def _fetch_one_symbol_history_in_scope(
    symbol: str,
    *,
    start_date,
    end_date,
    credentials: dict | None,
) -> dict[str, Any]:
    """Execute one history fetch inside the caller's database scope."""
    from openbb_fmp_cached.models.equity_historical import (
        FMPCachedEquityHistoricalQueryParams,
        _analyze_cache_gaps,
        _fetch_from_fmp_sync,
        _store_in_database_cache,
    )

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

    rows = len(data)
    if rows:
        dates = [str(d.get("date", ""))[:10] for d in data if d.get("date")]
        first = min(dates) if dates else "N/A"
        last = max(dates) if dates else "N/A"
    else:
        first = last = "N/A"

    return {
        "rows": rows,
        "first": first,
        "last": last,
        "cache_tag": "CACHE" if not missing_ranges else "FETCH",
    }


def fetch_history(
    symbols: list[str],
    years: int = 10,
    dry_run: bool = False,
    *,
    database: str | None = None,
    fetch_one_fn: Callable[..., dict[str, Any]] | None = None,
    api_key_resolver: Callable[[], str | None] = _resolve_api_key,
    should_cancel: Callable[[], bool] | None = None,
):
    """Fetch daily equity history for a list of symbols.

    ``fetch_one_fn`` (default :func:`_fetch_one_symbol_history`) is called once
    per symbol and may be injected so tests/jobs can exercise this loop without a
    live fmp_cached/MySQL dependency. ``should_cancel`` is polled between symbols
    (cooperative cancellation) so a long-running warm can stop early without
    losing partial progress; failures at the item level are caught and recorded
    in ``stats["failed"]`` (skip-and-continue), never silently swallowed above
    that granularity. ``database`` is applied request-locally only to the default
    fmp_cached fetcher; injected collaborators retain their existing signature.

    Returns dict with stats, including ``"cancelled"`` when ``should_cancel``
    stopped the run before every symbol was processed.
    """
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=years * 365)

    stats: dict[str, Any] = {
        "total_symbols": len(symbols),
        "success": [],
        "failed": [],
        "total_rows": 0,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "cancelled": False,
    }

    if dry_run:
        return stats

    using_default_fetcher = fetch_one_fn is None
    if using_default_fetcher:
        from openbb_fmp_cached.utils.database import database_override, init_database

        # One-time database init (tables already exist; skipped via env var)
        try:
            with database_override(database):
                init_database()
        except Exception as e:
            print(f"  WARNING: Database init issue: {e}\n")
        fetch_one_fn = _fetch_one_symbol_history

    should_cancel = should_cancel or (lambda: False)
    api_key = api_key_resolver()
    credentials = {"fmp_api_key": api_key} if api_key else None

    total = len(symbols)
    for i, symbol in enumerate(symbols, 1):
        if should_cancel():
            stats["cancelled"] = True
            break

        t0 = time.time()
        try:
            fetch_kwargs = {
                "start_date": start_date,
                "end_date": end_date,
                "credentials": credentials,
            }
            if using_default_fetcher:
                fetch_kwargs["database"] = database
            outcome = fetch_one_fn(symbol, **fetch_kwargs)
            elapsed = time.time() - t0
            rows = outcome["rows"]
            first = outcome.get("first", "N/A")
            last = outcome.get("last", "N/A")
            cache_tag = outcome.get("cache_tag", "FETCH")

            stats["total_rows"] += rows
            stats["success"].append(symbol)
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


class PositionHistoryWarmResult(BaseModel):
    """Structured, JSON-safe outcome of one :func:`run_position_history_warm` run.

    Never carries API keys/credentials — only symbol lists, counts, dates, and
    readiness metadata are persisted.
    """

    model_config = ConfigDict(frozen=True)

    requested_symbols: int = 0
    skipped: list[dict[str, str]] = Field(default_factory=list)
    success: list[str] = Field(default_factory=list)
    failed: list[dict[str, str]] = Field(default_factory=list)
    total_rows: int = 0
    start_date: str = ""
    end_date: str = ""
    years: int = 0
    dry_run: bool = False
    cancelled: bool = False
    readiness: dict[str, Any] = Field(default_factory=dict)

    def to_summary(self) -> dict[str, Any]:
        """Return a bounded, JSON-safe summary suitable for a core ``JobResult``."""
        readiness_summary: dict[str, Any] = {}
        if self.readiness:
            readiness_summary = {
                "target_date": self.readiness.get("target_date"),
                "missing_price_symbol_count": len(
                    self.readiness.get("missing_price_symbols", [])
                ),
                "stale_price_symbol_count": len(
                    self.readiness.get("stale_price_symbols", [])
                ),
            }
        return {
            "requested_symbols": self.requested_symbols,
            "skipped_count": len(self.skipped),
            "success_count": len(self.success),
            "failed_count": len(self.failed),
            "total_rows": self.total_rows,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "years": self.years,
            "dry_run": self.dry_run,
            "cancelled": self.cancelled,
            "readiness": readiness_summary,
        }


def run_position_history_warm(
    *,
    symbols: list[str] | None = None,
    years: int = 5,
    database: str | None = None,
    dry_run: bool = False,
    skip_holiday_prestep: bool = False,
    get_symbols_fn: Callable[
        [str | None], tuple[list[str], list[tuple[str, str]]]
    ] = get_portfolio_symbols,
    holiday_prestep_fn: Callable[[int, int, str | None], None] = ensure_market_holidays,
    fetch_one_fn: Callable[..., dict[str, Any]] | None = None,
    api_key_resolver: Callable[[], str | None] = _resolve_api_key,
    readiness_fn: Callable[[list[str], str | None], dict] = check_portfolio_app_readiness,
    should_cancel: Callable[[], bool] | None = None,
) -> PositionHistoryWarmResult:
    """Resolve symbols, warm the ``equity_historical`` cache, and report readiness.

    This is the structured, importable core of the ``fetch_position_history`` CLI
    (extracted for issue #1934) so the jobs worker and tests can drive it directly
    without touching argv/stdout. Every provider/database access is injectable:
    symbol resolution (``get_symbols_fn``), the holiday pre-step
    (``holiday_prestep_fn``), the per-symbol fetch (``fetch_one_fn``), API key
    resolution (``api_key_resolver``), and readiness (``readiness_fn``).
    ``should_cancel`` is polled between symbols for cooperative cancellation.
    """
    should_cancel = should_cancel or (lambda: False)

    if symbols is not None:
        resolved_symbols = list(symbols)
        skipped: list[tuple[str, str]] = []
    else:
        resolved_symbols, skipped = get_symbols_fn(database)

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=years * 365)

    if not skip_holiday_prestep:
        holiday_prestep_fn(start_date.year, end_date.year, database)

    stats = fetch_history(
        resolved_symbols,
        years=years,
        dry_run=dry_run,
        database=database,
        fetch_one_fn=fetch_one_fn,
        api_key_resolver=api_key_resolver,
        should_cancel=should_cancel,
    )

    readiness: dict[str, Any] = {} if dry_run else readiness_fn(resolved_symbols, database)

    return PositionHistoryWarmResult(
        requested_symbols=len(resolved_symbols),
        skipped=[{"symbol": s, "reason": r} for s, r in skipped],
        success=list(stats["success"]),
        failed=[{"symbol": s, "error": e} for s, e in stats["failed"]],
        total_rows=stats["total_rows"],
        start_date=stats["start_date"],
        end_date=stats["end_date"],
        years=years,
        dry_run=dry_run,
        cancelled=stats.get("cancelled", False),
        readiness=readiness,
    )


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
    print("  Interval:      1d (daily)")
    print("  Provider:      fmp_cached (auto-caching)")
    print(f"  Holiday prep:  {'enabled' if not args.skip_holiday_prestep else 'skipped'}")
    print(f"  Symbols:       {len(symbols)}")
    if skipped:
        print(f"  Skipped:       {len(skipped)}")
        for sym, reason in skipped:
            print(f"    {sym:<14s} ({reason})")

    print("\n  Symbols to fetch:")
    for i, sym in enumerate(symbols):
        print(f"    {sym}", end="")
        if (i + 1) % 10 == 0:
            print()
    if len(symbols) % 10 != 0:
        print()

    if args.dry_run:
        print("\n  DRY RUN — no API calls will be made.")
        print(f"\n  Estimated API calls: {len(symbols)} (one per symbol, cached provider")
        print("  handles gap detection and incremental fetching internally).")
        print(f"\n  Expected rows per symbol: ~2,520 (252 trading days × {args.years} years)")
        print(f"  Expected total rows: ~{len(symbols) * 252 * args.years:,d}")
        print("\n  Note: fmp_cached will cache results in MySQL. Subsequent runs")
        print("  only fetch missing date ranges (incremental).")
        print("=" * 70)
        return

    print("\n  Fetching ...\n")

    result = run_position_history_warm(
        symbols=symbols,
        years=args.years,
        database=args.database,
        dry_run=False,
        skip_holiday_prestep=True,  # already ran above; avoid running it twice
    )

    print(f"\n{'=' * 70}")
    print("  RESULTS")
    print(f"{'=' * 70}")
    print(f"  Successful:    {len(result.success)} / {result.requested_symbols}")
    print(f"  Total rows:    {result.total_rows:,d}")
    if result.failed:
        print(f"  Failed ({len(result.failed)}):")
        for item in result.failed:
            print(f"    {item['symbol']:<10s} {item['error']}")

    readiness = result.readiness
    print("\n  Portfolio App readiness (DB/cache)")
    print(f"    Freshness target date: {readiness['target_date']}")
    for table_name, count in readiness["table_counts"].items():
        print(f"    {table_name:<20s} rows={count}")

    missing = readiness["missing_price_symbols"]
    stale = readiness["stale_price_symbols"]
    print(f"    Missing cached prices: {len(missing)}")
    if missing:
        for sym in missing[:20]:
            print(f"      - {sym}")
        if len(missing) > 20:
            print(f"      ... and {len(missing) - 20} more")

    print(f"    Stale cached prices:   {len(stale)}")
    if stale:
        for sym, max_date in stale[:20]:
            print(f"      - {sym}: last cached date {max_date}")
        if len(stale) > 20:
            print(f"      ... and {len(stale) - 20} more")

    if not missing and not stale:
        print("    Status: READY (cache coverage is current for portfolio symbols)")
    else:
        print("    Status: PARTIAL (see missing/stale symbols above)")

    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
