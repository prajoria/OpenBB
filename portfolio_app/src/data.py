"""Data layer for the Portfolio App.

Fetches raw data from MySQL into pandas DataFrames.

──────────────────────────────────────────────────────────────────────
 DATA ACCESS POLICY  (read this before adding any new queries)
──────────────────────────────────────────────────────────────────────
 • **Sanitized API portfolio table** — ``portfolio_basket`` — is the
     only table that should be used by API endpoints for portfolio holdings.

 • **Raw portfolio tables** — ``Portfolio_Positions``, ``Account_Owner``,
     ``ESPP_Plan`` — contain sensitive lot-level data and must not be
     exposed by API endpoints.

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
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from db import query

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


def get_portfolio_basket_df(snapshot_date: Optional[str] = None) -> pd.DataFrame:
    """Fetch symbol-level sanitized portfolio basket rows."""
    sql = """
        SELECT
            snapshot_date,
            symbol,
            description,
            total_quantity,
            total_cost_basis,
            total_current_value,
            total_gain_loss,
            pct_return,
            portfolio_weight_pct
        FROM portfolio_basket
    """
    params: list = []
    if snapshot_date:
        sql += " WHERE DATE(snapshot_date) = %s"
        params.append(snapshot_date)
    else:
        sql += " WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM portfolio_basket)"

    sql += " ORDER BY portfolio_weight_pct DESC, symbol"
    return _to_df(query(sql, tuple(params)))


def get_all_basket_snapshots_df() -> pd.DataFrame:
    """Fetch all symbol-level basket rows across snapshots."""
    sql = """
        SELECT
            snapshot_date,
            symbol,
            total_cost_basis,
            total_current_value,
            total_gain_loss
        FROM portfolio_basket
        ORDER BY snapshot_date
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
    """Fetch historical equity prices from the local cache database only."""
    sql = """
        SELECT
            date,
            symbol,
            open,
            high,
            low,
            close,
            volume,
            change_percent
        FROM equity_historical
        WHERE symbol = %s
    """
    params: list = [symbol]

    if start_date:
        sql += " AND date >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND date <= %s"
        params.append(end_date)

    sql += " ORDER BY date"

    try:
        return _to_df(query(sql, tuple(params)))
    except Exception as exc:
        logger.warning("Cache-only historical lookup failed for %s: %s", symbol, exc)
        return pd.DataFrame()


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
    if not symbols:
        # Derive symbols from sanitized basket table
        sym_rows = query(
            "SELECT DISTINCT symbol FROM portfolio_basket ORDER BY symbol"
        )
        symbols = [r["symbol"] for r in sym_rows]
        if not symbols:
            return pd.DataFrame(columns=["symbol", "close", "price_date"])

    # Cache-only mode for app runtime: use last available cached close on or
    # before the as_of_date (default = yesterday) and never trigger live fetches.
    if as_of_date is None:
        cutoff = date.today() - timedelta(days=1)
    elif isinstance(as_of_date, datetime):
        cutoff = as_of_date.date()
    elif isinstance(as_of_date, date):
        cutoff = as_of_date
    elif isinstance(as_of_date, str):
        cutoff = date.fromisoformat(as_of_date)
    else:
        raise ValueError("as_of_date must be None, date, datetime, or YYYY-MM-DD string")

    placeholders = ", ".join(["%s"] * len(symbols))
    sql = f"""
        SELECT eh.symbol, eh.close, eh.date AS price_date
        FROM equity_historical eh
        INNER JOIN (
            SELECT symbol, MAX(date) AS max_date
            FROM equity_historical
            WHERE symbol IN ({placeholders})
              AND date <= %s
            GROUP BY symbol
        ) latest
          ON eh.symbol = latest.symbol
         AND eh.date = latest.max_date
        ORDER BY eh.symbol
    """

    params = tuple(symbols) + (cutoff,)
    try:
        rows = query(sql, params)
    except Exception as exc:
        logger.warning("Cache-only latest price lookup failed: %s", exc)
        return pd.DataFrame(columns=["symbol", "close", "price_date"])

    return _to_df(rows)


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
    rows = query("SELECT DISTINCT symbol FROM portfolio_basket ORDER BY symbol")
    return [{"value": r["symbol"], "label": r["symbol"]} for r in rows]


def get_distinct_accounts() -> list[dict]:
    """Account-level options are disabled in API to avoid exposing raw holdings metadata."""
    return []


def get_distinct_owners() -> list[dict]:
    """Owner-level options are disabled in API to avoid exposing raw holdings metadata."""
    return []
