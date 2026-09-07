"""Tools/refresh_etf_holdings_cache.py - daily warmer for the fmp_cached etf_holdings cache.

Sibling to Tools/fetch_position_history.py. Where fetch_position_history pre-warms
the equity_historical cache for Portfolio_Positions symbols, this tool pre-warms
the etf_holdings cache for the ETFs techtrade.scan needs (the 11 GICS sector
SPDRs) plus any ETFs you actually hold.

The tool is a thin orchestrator. It calls obb.etf.holdings(symbol=X,
provider="fmp_cached") for each ETF and lets the provider's multi-tier fallback
chain (FMP -> issuer-file -> SEC N-PORT, the latter two arriving with #97)
populate the cache. This tool knows nothing about which tier feeds each ETF.

Design: docs/superpowers/specs/2026-06-26-refresh-etf-holdings-cache-design.md

Usage:
    python Tools/refresh_etf_holdings_cache.py --dry-run             # plan only
    python Tools/refresh_etf_holdings_cache.py                       # SPDRs + portfolio
    python Tools/refresh_etf_holdings_cache.py --etfs IVV,VOO,QQQ    # add extras
    python Tools/refresh_etf_holdings_cache.py --skip-portfolio      # SPDRs + --etfs only
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Windows console encoding (cp1252 default crashes on Unicode in log lines).
# Mirrors Tools/fetch_position_history.py exactly (L10).
# ---------------------------------------------------------------------------
if sys.platform == "win32" and sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Make the fmp_cached / techtrade source trees importable when run as a script
# (no editable install required). Mirrors fetch_position_history.py.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIRS = [
    _PROJECT_ROOT / "openbb_platform" / "providers" / "fmp_cached",
    _PROJECT_ROOT / "openbb_platform" / "providers" / "fmp",
    _PROJECT_ROOT / "openbb_platform" / "core",
    _PROJECT_ROOT / "openbb_platform" / "platform",
]
_ext_root = _PROJECT_ROOT / "openbb_platform" / "extensions"
if _ext_root.is_dir():
    _SRC_DIRS.extend(d for d in _ext_root.iterdir() if d.is_dir())
_obbext_root = _PROJECT_ROOT / "openbb_platform" / "obbject_extensions"
if _obbext_root.is_dir():
    _SRC_DIRS.extend(d for d in _obbext_root.iterdir() if d.is_dir())
for _d in _SRC_DIRS:
    _p = str(_d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Load .env so FMP_API_KEY etc. reach os.environ before any provider call.
# Mirrors the #93 review-fix lesson learned for Tools/enrich_cusip_figi.py.
try:
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv(_PROJECT_ROOT / ".env", override=True)
except ImportError:  # pragma: no cover - python-dotenv in dev deps
    pass


logger = logging.getLogger("refresh_etf_holdings_cache")


# ---------------------------------------------------------------------------
# ETF universe (L3, L4, L9)
# ---------------------------------------------------------------------------

# SPDR_SECTORS is derived from GICS_SECTOR_ETFS.values() at module load so the
# two declarations can't drift (L9). If the techtrade import fails (e.g. the
# extension is not installed), fall back to the documented set and rely on the
# regression test (test_spdr_sectors_matches_techtrade_gics_sector_etfs) to
# catch any drift in CI.
try:
    from openbb_techtrade.engine.screener import GICS_SECTOR_ETFS  # noqa: PLC0415

    SPDR_SECTORS: tuple[str, ...] = tuple(sorted(GICS_SECTOR_ETFS.values()))
except ImportError:  # pragma: no cover - extension absent in some environments
    SPDR_SECTORS = (
        "XLB",
        "XLC",
        "XLE",
        "XLF",
        "XLI",
        "XLK",
        "XLP",
        "XLRE",
        "XLU",
        "XLV",
        "XLY",
    )

# Built-in ETF detection set for Portfolio_Positions filtering (L4).
# Small + explicit; extend via --etfs for one-offs.
KNOWN_ETFS: frozenset[str] = frozenset(
    set(SPDR_SECTORS)
    | {
        "SPY",
        "VOO",
        "IVV",
        "QQQ",
        "DIA",
        "VTI",
        "VXUS",
        "VEU",
        "VEA",
        "VWO",
        "BND",
        "AGG",
        "BNDX",
        "TLT",
        "IEF",
        "GLD",
        "SLV",
        "ARKK",
        "ARKW",
        "ARKG",
    }
)


# ---------------------------------------------------------------------------
# DB helpers (Portfolio_Positions read; same _connect pattern as
# fetch_position_history.py for consistency)
# ---------------------------------------------------------------------------


def _connect(database: str | None = None):
    """Open a MySQL connection via the fmp_cached database helper.

    Returns the connection object; caller is responsible for closing.
    Mirrors fetch_position_history._connect, lazily imported so the module
    can be imported in test environments without a live DB.
    """
    from openbb_fmp_cached.utils.database import get_connection  # noqa: PLC0415

    return get_connection(database=database) if database else get_connection()


def list_portfolio_etfs(database: str | None = None) -> list[str]:
    """Distinct Portfolio_Positions.symbol values that are in KNOWN_ETFS.

    Returns ``[]`` on any DB error (table absent, connection failure) so the
    scheduled run can still proceed with the SPDR universe.
    """
    try:
        conn = _connect(database)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Portfolio_Positions read skipped (connect failed): %s", exc)
        return []
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT symbol FROM Portfolio_Positions")
            rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Portfolio_Positions read failed: %s", exc)
        return []
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    symbols: set[str] = set()
    for row in rows or []:
        sym = row.get("symbol") if isinstance(row, dict) else (row[0] if row else None)
        if sym and sym.upper() in KNOWN_ETFS:
            symbols.add(sym.upper())
    return sorted(symbols)


def resolve_universe(
    *,
    database: str | None,
    skip_portfolio: bool,
    extra_etfs: list[str] | None,
) -> list[str]:
    """Union of SPDR_SECTORS + (portfolio ETFs unless skip_portfolio) + extras.

    Returns a sorted, deduplicated, upper-cased list.
    """
    universe: set[str] = set(SPDR_SECTORS)
    if not skip_portfolio:
        universe |= set(list_portfolio_etfs(database))
    if extra_etfs:
        universe |= {s.strip().upper() for s in extra_etfs if s and s.strip()}
    return sorted(universe)


# ---------------------------------------------------------------------------
# Per-ETF provider call (L2, L7)
# ---------------------------------------------------------------------------


def refresh_one_etf(
    etf: str,
    *,
    dry_run: bool,
    api_key: str | None,  # noqa: ARG001 - signature compat; see _resolve_api_key NOTE
    holdings_fn: Callable[[str], Any] | None = None,
) -> tuple[str, int, str | None, float, str | None]:
    """Call obb.etf.holdings for one ETF; return a (status) tuple.

    Tuple shape: (etf, row_count, data_source, elapsed_ms, error_or_None).
    Errors are caught and returned in the tuple; this function never raises.
    Dry-run returns (etf, 0, None, 0.0, None) without calling obb.

    ``holdings_fn`` (default: a lazy ``obb.etf.holdings(symbol=etf,
    provider="fmp_cached")`` call) is injectable so tests and the jobs handler
    can exercise this per-ETF call without a live provider/network dependency.
    """
    if dry_run:
        return (etf, 0, None, 0.0, None)

    started = time.monotonic()
    try:
        if holdings_fn is not None:
            result = holdings_fn(etf)
        else:
            from openbb import obb  # noqa: PLC0415

            result = obb.etf.holdings(symbol=etf, provider="fmp_cached")
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.monotonic() - started) * 1000
        first_line = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
        return (etf, 0, None, elapsed_ms, first_line)

    elapsed_ms = (time.monotonic() - started) * 1000
    rows = list(getattr(result, "results", None) or [])
    data_source = None
    if rows:
        first = rows[0]
        data_source = getattr(first, "data_source", None)
        if data_source is None and isinstance(first, dict):
            data_source = first.get("data_source")
    return (etf, len(rows), data_source, elapsed_ms, None)


def refresh_universe(
    etfs: list[str],
    *,
    dry_run: bool,
    api_key: str | None,
    holdings_fn: Callable[[str], Any] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Refresh each ETF; aggregate stats.

    Returns ``{"requested": N, "populated": M, "errored": K, "empty": J,
    "cancelled": bool}``. Per-ETF outcomes are also logged at INFO so the run
    banner + scheduler log stay in sync.

    ``holdings_fn`` is forwarded to :func:`refresh_one_etf` so the provider call
    is injectable end-to-end. ``should_cancel`` is polled between ETFs
    (cooperative cancellation); when it returns ``True`` the loop stops and
    ``stats["cancelled"]`` is set, leaving any remaining ETFs unprocessed.
    """
    should_cancel = should_cancel or (lambda: False)
    stats: dict[str, Any] = {
        "requested": len(etfs),
        "populated": 0,
        "errored": 0,
        "empty": 0,
        "cancelled": False,
    }
    for etf in etfs:
        if should_cancel():
            stats["cancelled"] = True
            break

        result = refresh_one_etf(
            etf, dry_run=dry_run, api_key=api_key, holdings_fn=holdings_fn
        )
        _, row_count, data_source, elapsed_ms, error = result
        if error is not None:
            stats["errored"] += 1
            logger.warning(
                "%-6s [-]               rows=0       elapsed=%dms   ERROR: %s",
                etf,
                int(elapsed_ms),
                error,
            )
        elif row_count == 0 and not dry_run:
            stats["empty"] += 1
            logger.info(
                "%-6s [-]               rows=0       elapsed=%dms   (empty)",
                etf,
                int(elapsed_ms),
            )
        elif dry_run:
            logger.info(
                "%-6s [dry-run]                                 (would refresh)", etf
            )
        else:
            stats["populated"] += 1
            logger.info(
                "%-6s [%-15s] rows=%-7d elapsed=%dms",
                etf,
                data_source or "-",
                row_count,
                int(elapsed_ms),
            )
    return stats


class EtfHoldingsWarmResult(BaseModel):
    """Structured, JSON-safe outcome of one :func:`run_etf_holdings_warm` run.

    Never carries API keys/credentials — only ETF universes and counts.
    """

    model_config = ConfigDict(frozen=True)

    spdr_count: int = 0
    portfolio_etfs: list[str] = Field(default_factory=list)
    extras: list[str] = Field(default_factory=list)
    universe: list[str] = Field(default_factory=list)
    requested: int = 0
    populated: int = 0
    errored: int = 0
    empty: int = 0
    cancelled: bool = False
    elapsed_seconds: float = 0.0
    dry_run: bool = False

    def to_summary(self) -> dict[str, Any]:
        """Return a bounded, JSON-safe summary suitable for a core ``JobResult``."""
        return {
            "spdr_count": self.spdr_count,
            "portfolio_etf_count": len(self.portfolio_etfs),
            "extra_count": len(self.extras),
            "requested": self.requested,
            "populated": self.populated,
            "errored": self.errored,
            "empty": self.empty,
            "cancelled": self.cancelled,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "dry_run": self.dry_run,
        }


def run_etf_holdings_warm(
    *,
    database: str | None = None,
    extra_etfs: list[str] | None = None,
    skip_portfolio: bool = False,
    dry_run: bool = False,
    api_key: str | None = None,
    universe: list[str] | None = None,
    portfolio_etfs: list[str] | None = None,
    list_portfolio_etfs_fn: Callable[[str | None], list[str]] = list_portfolio_etfs,
    resolve_universe_fn: Callable[..., list[str]] = resolve_universe,
    holdings_fn: Callable[[str], Any] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> EtfHoldingsWarmResult:
    """Resolve the ETF universe and warm the ``etf_holdings`` cache.

    This is the structured, importable core of the ``refresh_etf_holdings_cache``
    CLI (extracted for issue #1934) so the jobs worker and tests can drive it
    directly without touching argv/stdout. Pass a pre-resolved ``universe``/
    ``portfolio_etfs`` (as the CLI does, to avoid a redundant DB read) or leave
    them unset to have this function resolve them itself (as the jobs handler
    does). The per-ETF provider call (``holdings_fn``) and universe resolution
    (``list_portfolio_etfs_fn``, ``resolve_universe_fn``) are injectable, and
    ``should_cancel`` is polled between ETFs for cooperative cancellation.
    """
    if portfolio_etfs is None:
        portfolio_etfs = [] if skip_portfolio else list_portfolio_etfs_fn(database)
    if universe is None:
        universe = resolve_universe_fn(
            database=database, skip_portfolio=skip_portfolio, extra_etfs=extra_etfs
        )

    started = time.monotonic()
    stats = refresh_universe(
        universe,
        dry_run=dry_run,
        api_key=api_key,
        holdings_fn=holdings_fn,
        should_cancel=should_cancel,
    )
    elapsed = time.monotonic() - started

    extras_normalized = sorted(
        {s.strip().upper() for s in (extra_etfs or []) if s and s.strip()}
    )

    return EtfHoldingsWarmResult(
        spdr_count=len(SPDR_SECTORS),
        portfolio_etfs=list(portfolio_etfs),
        extras=extras_normalized,
        universe=list(universe),
        requested=stats["requested"],
        populated=stats["populated"],
        errored=stats["errored"],
        empty=stats["empty"],
        cancelled=stats.get("cancelled", False),
        elapsed_seconds=elapsed,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )


def _resolve_api_key(api_key_arg: str | None) -> str | None:
    """FMP_API_KEY resolution: --api-key flag wins, else env, else None.

    Mirrors Tools/populate_cusip_map.py's pattern; user_settings is left to the
    provider's own internal resolver inside obb.etf.holdings.

    NOTE (bd-2k86): post-fix, ``main()`` is the single source of truth for
    plumbing the CLI flag — it exports ``os.environ['FMP_API_KEY']`` before
    the lazy ``from openbb import obb`` import fires, and the obb provider
    reads the env-var directly. This function is therefore vestigial in the
    current call graph: the returned value is threaded to ``refresh_one_etf``
    where it is marked ``# noqa: ARG001`` and discarded. Retained rather than
    deleted so any future refactor that wires the parameter into
    ``obb.etf.holdings(credentials=...)`` has a clean shape to fill in; do
    NOT re-enable the parameter chain WITHOUT also removing the env-var side
    channel above, otherwise the tool ends up with two config paths and
    silently re-introduces bd-2k86.
    """
    if api_key_arg:
        return api_key_arg
    return os.environ.get("FMP_API_KEY") or None


def main() -> int:
    """CLI entry point; returns process exit code (always 0 in normal runs)."""
    parser = argparse.ArgumentParser(
        description="Refresh the fmp_cached etf_holdings MySQL cache for "
        "the 11 GICS sector SPDRs + portfolio-held ETFs + extras.",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Target MySQL database (default: from DatabaseConfig)",
    )
    parser.add_argument(
        "--etfs",
        default=None,
        help="Extra comma-separated ETF tickers to refresh atop the defaults",
    )
    parser.add_argument(
        "--skip-portfolio",
        action="store_true",
        help="Skip Portfolio_Positions read; SPDRs + --etfs only",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print plan + resolved universe; no API calls, no DB writes",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=(
            "Override FMP_API_KEY for this run (exports to os.environ so the "
            "obb provider's own resolver picks it up). Precedence: this flag "
            "> repo .env (loaded via python-dotenv override=True at module "
            "import) > shell FMP_API_KEY > user_settings > none."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    # --database: set DB_NAME so DatabaseConfig (and therefore _connect) target
    # the chosen DB. Mirrors the #93 review-fix pattern for enrich_cusip_figi.py.
    if args.database:
        os.environ["DB_NAME"] = args.database

    # --api-key: export to os.environ['FMP_API_KEY'] BEFORE the lazy
    # ``from openbb import obb`` import fires inside refresh_one_etf so the
    # provider's own resolver picks it up. Pre-fix (bd-2k86) the flag was
    # documented as an override but had no runtime effect — the resolved
    # value was threaded to refresh_one_etf but marked ``# noqa: ARG001 -
    # reserved for future explicit-key plumbing`` and never reached obb.
    # Mirrors the --database → os.environ['DB_NAME'] pattern above.
    # ``.strip()`` guards against ``--api-key "  "`` polluting env with
    # whitespace that would then survive the credentials loader's
    # ``if not value`` truthy check and surface as an opaque provider error;
    # ``--api-key ""`` still no-ops silently (argparse-native falsy default).
    if args.api_key and args.api_key.strip():
        os.environ["FMP_API_KEY"] = args.api_key.strip()

    extras = (
        [s.strip() for s in args.etfs.split(",") if s and s.strip()]
        if args.etfs
        else []
    )

    portfolio_etfs = [] if args.skip_portfolio else list_portfolio_etfs(args.database)
    spdr_count = len(SPDR_SECTORS)
    universe = resolve_universe(
        database=args.database,
        skip_portfolio=args.skip_portfolio,
        extra_etfs=extras,
    )

    print("=" * 70)  # noqa: T201
    print("  REFRESH etf_holdings CACHE")  # noqa: T201
    print("=" * 70)  # noqa: T201
    print(f"  SPDR sectors  : {spdr_count} ({', '.join(SPDR_SECTORS)})")  # noqa: T201
    print(  # noqa: T201
        f"  Portfolio ETFs: {len(portfolio_etfs)} "
        f"({', '.join(portfolio_etfs) if portfolio_etfs else '-'})"
    )
    print(  # noqa: T201
        f"  Extra (--etfs): {len(extras)} "
        f"({', '.join(s.upper() for s in extras) if extras else '-'})"
    )
    print(f"  Total universe: {len(universe)}")  # noqa: T201
    if args.dry_run:
        print("\n  DRY RUN -- no API calls, no cache writes.")  # noqa: T201
    print("\n  Refreshing ...")  # noqa: T201

    api_key = _resolve_api_key(args.api_key)
    result = run_etf_holdings_warm(
        database=args.database,
        extra_etfs=extras,
        skip_portfolio=args.skip_portfolio,
        dry_run=args.dry_run,
        api_key=api_key,
        universe=universe,
        portfolio_etfs=portfolio_etfs,
    )

    print(f"\n{'=' * 70}")  # noqa: T201
    print("  RESULTS")  # noqa: T201
    print(f"{'=' * 70}")  # noqa: T201
    print(f"  Requested : {result.requested}")  # noqa: T201
    print(f"  Populated : {result.populated}")  # noqa: T201
    print(f"  Errored   : {result.errored}")  # noqa: T201
    print(f"  Empty     : {result.empty}")  # noqa: T201
    print(f"  Elapsed   : {result.elapsed_seconds:.1f}s")  # noqa: T201
    print("=" * 70)  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
