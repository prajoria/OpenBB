"""Data layer for the Portfolio App.

Fetches raw data from MySQL into pandas DataFrames.

──────────────────────────────────────────────────────────────────────
 DATA ACCESS POLICY  (read this before adding any new queries)
──────────────────────────────────────────────────────────────────────
 • **Portfolio tables** — ``Portfolio_Positions``, ``Account_Owner``,
   ``ESPP_Plan`` — may be queried directly via the portfolio ``db``
   module (``from db import query``).

 • **Market / price data** (``equity_historical`` and any other tables
   owned by the ``openbb_fmp_cached`` provider) must **NEVER** be
   accessed with raw SQL.  Always go through the provider's API
   functions:
       - ``get_equity_historical_sync()``  — full OHLCV history
       - ``get_latest_prices_sync()``      — most-recent close
   These functions handle gap detection, automatic FMP API fetching,
   and cache storage transparently.
──────────────────────────────────────────────────────────────────────

All business logic (grouping, aggregation, computed columns) belongs
in the service layer using DataFrame operations.
"""

import logging
import math
from typing import Optional

import numpy as np
import pandas as pd

from db import query

# fmp_cached provider API — gap-detect + auto-fetch + cache pipeline.
# NEVER import execute_query / fmp_query here for equity_historical;
# use only the high-level sync helpers below.
try:
    from openbb_fmp_cached.models.equity_historical import (
        get_equity_historical_sync,
        get_latest_prices_sync,
    )
    _HAS_FMP_CACHED = True
except ImportError:
    _HAS_FMP_CACHED = False

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  DataFrame utilities
# --------------------------------------------------------------------------- #

def _to_df(rows: list[dict]) -> pd.DataFrame:
    """Convert query result rows to a pandas DataFrame."""
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def df_to_records(df: pd.DataFrame) -> list[dict]:
    """Convert a DataFrame to a JSON-serializable list of dicts.

    Handles: NaN/NaT → None, numpy int/float → Python native,
    Timestamps → ISO strings.
    """
    if df.empty:
        return []
    df = df.copy()
    df = df.where(df.notna(), None)
    records = []
    for row in df.to_dict(orient="records"):
        clean = {}
        for k, v in row.items():
            if isinstance(v, np.integer):
                clean[k] = int(v)
            elif isinstance(v, np.floating):
                v = float(v)
                clean[k] = None if math.isnan(v) else v
            elif isinstance(v, float) and math.isnan(v):
                clean[k] = None
            elif isinstance(v, np.bool_):
                clean[k] = bool(v)
            elif isinstance(v, pd.Timestamp):
                clean[k] = v.isoformat()
            else:
                clean[k] = v
        records.append(clean)
    return records


def filter_df(
    df: pd.DataFrame,
    account: Optional[str] = None,
    owner: Optional[str] = None,
    symbol: Optional[str] = None,
) -> pd.DataFrame:
    """Apply common filters to a positions DataFrame."""
    if df.empty:
        return df
    if account and "account_name" in df.columns:
        df = df[df["account_name"] == account]
    if owner and "owner" in df.columns:
        df = df[df["owner"] == owner]
    if symbol and "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    return df


# --------------------------------------------------------------------------- #
#  Raw data fetchers (no aggregation — just SELECT + JOIN)
# --------------------------------------------------------------------------- #

def get_positions_df(snapshot_date: Optional[str] = None) -> pd.DataFrame:
    """
    Fetch all portfolio positions joined with owner info.

    Returns the latest snapshot per account by default, or a specific
    snapshot_date if provided.  One row per lot — no aggregation.
    """
    sql = """
        SELECT pp.account_name, ao.owner, pp.symbol, pp.description,
               pp.quantity, pp.avg_cost_basis, pp.cost_basis_total,
               pp.current_value, pp.total_gain_loss, pp.pct_gain_loss,
               pp.term, pp.acquired, pp.share_source, pp.snapshot_date,
               pp.grant_date, pp.transfer_avail_date
        FROM Portfolio_Positions pp
        LEFT JOIN Account_Owner ao ON pp.account_name = ao.account_name
    """
    params: list = []
    if snapshot_date:
        sql += " WHERE DATE(pp.snapshot_date) = %s"
        params.append(snapshot_date)
    else:
        sql += """ WHERE pp.snapshot_date = (
            SELECT MAX(pp2.snapshot_date)
            FROM Portfolio_Positions pp2
            WHERE pp2.account_name = pp.account_name
        )"""
    return _to_df(query(sql, tuple(params)))


def get_all_snapshots_df() -> pd.DataFrame:
    """Fetch all position rows across every snapshot (for trend analysis)."""
    sql = """
        SELECT pp.account_name, pp.symbol, pp.quantity,
               pp.cost_basis_total, pp.current_value, pp.total_gain_loss,
               pp.snapshot_date
        FROM Portfolio_Positions pp
        ORDER BY pp.snapshot_date
    """
    return _to_df(query(sql))


def get_espp_df() -> pd.DataFrame:
    """Fetch all ESPP purchase records."""
    sql = """
        SELECT purchase_date, offering_period_start, offering_period_end,
               fmv_offering_start, fmv_purchase_date, purchase_price,
               purchase_quantity, purchase_value, discount_pct, bargain_element,
               qualified_disposition_date, purchase_deposit_to, symbol
        FROM ESPP_Plan
        ORDER BY purchase_date DESC
    """
    return _to_df(query(sql))


def get_equity_historical_df(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Fetch historical equity prices via the fmp_cached provider API.

    Uses ``get_equity_historical_sync`` which runs the full
    gap-detect → FMP API fetch → cache store pipeline so stale or
    missing data is automatically refreshed.

    Returns an empty DataFrame when the fmp_cached provider is not
    installed (equity_historical must never be queried with raw SQL).
    """
    if not _HAS_FMP_CACHED:
        logger.warning(
            "fmp_cached provider not available — cannot fetch equity "
            "historical data for %s",
            symbol,
        )
        return pd.DataFrame()

    rows = get_equity_historical_sync(
        symbol,
        start_date=start_date,
        end_date=end_date,
    )
    return _to_df(_normalise_fmp_rows(rows))


def get_latest_prices_df(
    symbols: Optional[list[str]] = None,
    *,
    as_of_date=None,
    verbose: bool = False,
    progress_callback: Optional[callable] = None,
) -> pd.DataFrame:
    """Get the most recent close price for every requested symbol.

    Uses ``get_latest_prices_sync`` from the fmp_cached provider API
    which runs the full gap-detect → FMP-fetch → cache-store pipeline.

    Parameters
    ----------
    symbols : list[str] | None
        Ticker symbols to look up.  If ``None``, derives the list from
        ``Portfolio_Positions`` (a portfolio table we may query directly).
    as_of_date : date | str | None
        Return the most-recent close on or before this date.
        Accepts ``datetime.date`` or ``'YYYY-MM-DD'`` string.
        Defaults to today when ``None``.
    verbose : bool
        If ``True``, print per-symbol progress to stdout.
    progress_callback : callable | None
        Called as ``progress_callback(i, total, symbol, result_row)``
        after each symbol is processed.

    Returns
    -------
    pd.DataFrame
        Columns: ``symbol``, ``close``, ``price_date``.
    """
    import time as _time

    if not _HAS_FMP_CACHED:
        logger.warning(
            "fmp_cached provider not available — cannot fetch latest prices",
        )
        return pd.DataFrame(columns=["symbol", "close", "price_date"])

    if not symbols:
        # Derive symbols from Portfolio_Positions (portfolio table — OK)
        sym_rows = query(
            "SELECT DISTINCT symbol FROM Portfolio_Positions ORDER BY symbol"
        )
        symbols = [r["symbol"] for r in sym_rows]
        if not symbols:
            return pd.DataFrame(columns=["symbol", "close", "price_date"])

    total = len(symbols)
    if verbose:
        date_label = str(as_of_date) if as_of_date else "today"
        print(f"Fetching latest prices for {total} symbols (as of {date_label}) ...")

    all_rows: list[dict] = []
    t0 = _time.perf_counter()

    for i, sym in enumerate(symbols, 1):
        sym_t0 = _time.perf_counter()
        rows = get_latest_prices_sync([sym], as_of_date=as_of_date)
        elapsed = _time.perf_counter() - sym_t0

        row = rows[0] if rows else None
        if verbose:
            if row:
                print(
                    f"  [{i}/{total}] {sym:<8s} → "
                    f"${row.get('close', 0):>10,.2f}  "
                    f"({row.get('price_date', '?')})  "
                    f"[{elapsed:.1f}s]"
                )
            else:
                print(f"  [{i}/{total}] {sym:<8s} → NO DATA  [{elapsed:.1f}s]")

        if progress_callback:
            progress_callback(i, total, sym, row)

        all_rows.extend(rows)

    if verbose:
        wall = _time.perf_counter() - t0
        print(
            f"Done — {len(all_rows)}/{total} prices fetched "
            f"in {wall:.1f}s"
        )

    return _to_df(_normalise_fmp_rows(all_rows))


def _normalise_fmp_rows(rows: list) -> list[dict]:
    """Convert Decimal / date values returned by fmp_cached DictCursor."""
    from datetime import date, datetime
    from decimal import Decimal

    result = []
    for row in (rows or []):
        d = {}
        for col, val in row.items():
            if isinstance(val, Decimal):
                d[col] = float(val)
            elif isinstance(val, (date, datetime)):
                d[col] = val.isoformat()
            else:
                d[col] = val
        result.append(d)
    return result


def check_db() -> bool:
    """Quick DB connectivity check."""
    try:
        query("SELECT 1 AS ok")
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
#  Option-list helpers (for widget dropdowns)
# --------------------------------------------------------------------------- #

def get_distinct_symbols() -> list[dict]:
    """Distinct ticker symbols for widget dropdowns."""
    rows = query("SELECT DISTINCT symbol FROM Portfolio_Positions ORDER BY symbol")
    return [{"value": r["symbol"], "label": r["symbol"]} for r in rows]


def get_distinct_accounts() -> list[dict]:
    """Distinct account names for widget dropdowns."""
    rows = query("SELECT DISTINCT account_name FROM Portfolio_Positions ORDER BY account_name")
    return [{"value": r["account_name"], "label": r["account_name"]} for r in rows]


def get_distinct_owners() -> list[dict]:
    """Distinct owners for widget dropdowns."""
    rows = query("SELECT DISTINCT owner FROM Account_Owner ORDER BY owner")
    return [{"value": r["owner"], "label": r["owner"]} for r in rows]
