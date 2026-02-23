"""
Data layer for the Portfolio App.

Fetches raw data from MySQL into pandas DataFrames.
SQL queries are simple SELECTs with JOINs — no aggregation logic.
All business logic (grouping, aggregation, computed columns) belongs
in the API layer using DataFrame operations.
"""

import logging
import math
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
    """Fetch cached historical equity prices."""
    sql = """
        SELECT symbol, date, open, high, low, close, volume, change_percent
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
    sql += " ORDER BY date DESC LIMIT 2000"
    return _to_df(query(sql, tuple(params)))


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
