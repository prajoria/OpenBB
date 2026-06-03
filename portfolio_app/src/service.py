"""
Portfolio Service — Pure DataFrame business logic.

All functions take DataFrames as input and return DataFrames as output.
No database access, no HTTP calls, no side effects.
Fully unit-testable with mock data.
"""

import pandas as pd


def positions_detail(
    df: pd.DataFrame,
    account: str | None = None,
    owner: str | None = None,
) -> pd.DataFrame:
    """Filter positions and sort by current value descending."""
    df = _filter(df, account=account, owner=owner)
    if not df.empty:
        df = df.sort_values("current_value", ascending=False)
    return df


def refresh_market_values(
    positions_df: pd.DataFrame,
    prices_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Recalculate current_value, total_gain_loss, pct_gain_loss using live prices.

    For each position lot:
      - current_value  = quantity × latest_close
      - total_gain_loss = current_value − cost_basis_total
      - pct_gain_loss   = (total_gain_loss / cost_basis_total) × 100

    If a symbol has no entry in prices_df, the original DB snapshot values
    are kept as a fallback.  A ``price_date`` column is added so the user
    can see how recent the price is (NaT when falling back to snapshot).

    Parameters
    ----------
    positions_df : DataFrame
        Raw positions with snapshot-era values.
    prices_df : DataFrame
        Must have columns: symbol, close, price_date.

    Returns
    -------
    DataFrame with refreshed value columns.
    """
    if positions_df.empty:
        return positions_df

    df = positions_df.copy()

    if prices_df.empty:
        # No prices available → keep DB values, mark price_date as NaT
        df["price_date"] = pd.NaT
        return df

    # Build a symbol → (close, price_date) lookup
    price_map = prices_df.set_index("symbol")[["close", "price_date"]]

    # Map latest price to each row; NaN where symbol has no price data
    df["_latest_price"] = df["symbol"].map(price_map["close"])
    df["price_date"] = df["symbol"].map(price_map["price_date"])

    # Only overwrite rows that have a valid latest price
    has_price = df["_latest_price"].notna()

    df.loc[has_price, "current_value"] = (
        df.loc[has_price, "quantity"] * df.loc[has_price, "_latest_price"]
    ).round(4)

    df.loc[has_price, "total_gain_loss"] = (
        df.loc[has_price, "current_value"] - df.loc[has_price, "cost_basis_total"]
    ).round(4)

    cost = df.loc[has_price, "cost_basis_total"].replace(0, float("nan"))
    df.loc[has_price, "pct_gain_loss"] = (
        (df.loc[has_price, "total_gain_loss"] / cost) * 100
    ).round(2).fillna(0)

    df = df.drop(columns=["_latest_price"])
    return df


def summary_by_symbol(
    df: pd.DataFrame,
    account: str | None = None,
    owner: str | None = None,
) -> pd.DataFrame:
    """Aggregate positions by symbol: total quantity, cost, value, gain, return %."""
    df = _filter(df, account=account, owner=owner)
    if df.empty:
        return pd.DataFrame()
    result = (
        df.groupby(["symbol", "description"], as_index=False)
        .agg(
            total_quantity=("quantity", "sum"),
            total_cost_basis=("cost_basis_total", "sum"),
            total_current_value=("current_value", "sum"),
            total_gain_loss=("total_gain_loss", "sum"),
        )
    )
    result["pct_return"] = _pct_return(result["total_gain_loss"], result["total_cost_basis"])
    return result.sort_values("total_current_value", ascending=False).reset_index(drop=True)


def allocation_by_account(
    df: pd.DataFrame,
    owner: str | None = None,
) -> pd.DataFrame:
    """Aggregate positions by account: symbol count, totals, return %."""
    df = _filter(df, owner=owner)
    if df.empty:
        return pd.DataFrame()
    result = (
        df.groupby(["account_name", "owner"], as_index=False)
        .agg(
            num_symbols=("symbol", "nunique"),
            total_value=("current_value", "sum"),
            total_cost_basis=("cost_basis_total", "sum"),
            total_gain_loss=("total_gain_loss", "sum"),
        )
    )
    result["pct_return"] = _pct_return(result["total_gain_loss"], result["total_cost_basis"])
    return result.sort_values("total_value", ascending=False).reset_index(drop=True)


def cost_basis_lots(
    df: pd.DataFrame,
    symbol: str | None = None,
    account: str | None = None,
) -> pd.DataFrame:
    """Select and sort per-lot cost basis detail."""
    df = _filter(df, symbol=symbol, account=account)
    cols = [
        "symbol", "account_name", "acquired", "term", "quantity",
        "avg_cost_basis", "cost_basis_total", "current_value",
        "total_gain_loss", "pct_gain_loss", "share_source",
        "grant_date", "transfer_avail_date",
    ]
    df = df[[c for c in cols if c in df.columns]]
    if not df.empty:
        df = df.sort_values(["symbol", "acquired"])
    return df.reset_index(drop=True)


def tax_summary(
    df: pd.DataFrame,
    owner: str | None = None,
) -> pd.DataFrame:
    """Short-term vs long-term gains/losses grouped by account and term."""
    df = _filter(df, owner=owner)
    df = df[df["term"].astype(str).str.strip() != ""]
    if df.empty:
        return pd.DataFrame()
    result = (
        df.groupby(["account_name", "owner", "term"], as_index=False)
        .agg(
            num_lots=("quantity", "count"),
            total_quantity=("quantity", "sum"),
            total_cost_basis=("cost_basis_total", "sum"),
            total_current_value=("current_value", "sum"),
            total_gain_loss=("total_gain_loss", "sum"),
        )
    )
    result["pct_return"] = _pct_return(result["total_gain_loss"], result["total_cost_basis"])
    return result.sort_values(["account_name", "term"]).reset_index(drop=True)


def performance_ranking(
    df: pd.DataFrame,
    owner: str | None = None,
) -> pd.DataFrame:
    """Top gainers/losers by percent return — only symbols with cost > 0."""
    df = _filter(df, owner=owner)
    if df.empty:
        return pd.DataFrame()
    result = (
        df.groupby(["symbol", "description"], as_index=False)
        .agg(
            total_quantity=("quantity", "sum"),
            total_cost_basis=("cost_basis_total", "sum"),
            total_current_value=("current_value", "sum"),
            total_gain_loss=("total_gain_loss", "sum"),
        )
    )
    result = result[result["total_cost_basis"] > 0].copy()
    result["pct_return"] = (
        (result["total_gain_loss"] / result["total_cost_basis"]) * 100
    ).round(2)
    return result.sort_values("pct_return", ascending=False).reset_index(drop=True)


def snapshot_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate snapshot rows into per-date totals for trendlines."""
    if df.empty:
        return pd.DataFrame()
    result = (
        df.groupby("snapshot_date", as_index=False)
        .agg(
            lots=("symbol", "count"),
            stocks=("symbol", "nunique"),
            accounts=("account_name", "nunique"),
            total_cost_basis=("cost_basis_total", "sum"),
            total_current_value=("current_value", "sum"),
            total_gain_loss=("total_gain_loss", "sum"),
        )
    )
    return result.sort_values("snapshot_date").reset_index(drop=True)


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def _filter(
    df: pd.DataFrame,
    account: str | None = None,
    owner: str | None = None,
    symbol: str | None = None,
) -> pd.DataFrame:
    """Apply common column filters."""
    if df.empty:
        return df
    if account and "account_name" in df.columns:
        df = df[df["account_name"] == account]
    if owner and "owner" in df.columns:
        df = df[df["owner"] == owner]
    if symbol and "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    return df


def _pct_return(gain: pd.Series, cost: pd.Series) -> pd.Series:
    """Compute percent return, handling zero cost gracefully."""
    return ((gain / cost.replace(0, float("nan"))) * 100).round(2).fillna(0)
