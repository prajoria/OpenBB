"""
Stock Analysis — Pure computation functions.

Extracted from Analysis/00. single_stock_analysis_playbook_template.ipynb.
All functions take DataFrames as input and return dicts or DataFrames as output.
No OpenBB imports, no HTTP calls, no side effects — fully unit-testable.

Phases implemented:
    Phase 1  — company profile summary (build_phase1_summary)
    Phase 2  — fundamental KPIs        (compute_fundamental_kpis)
    Phase 3  — technical indicators    (compute_technical_kpis)
    Phase 4  — valuation ratios        (compute_valuation_kpis)
    Phase 5  — risk metrics            (compute_risk_kpis)
    Phase 6  — peer-relative table     (compute_relative_table)
    Phase 7  — decision scoring        (compute_decision_scores)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
#  Shared helpers
# --------------------------------------------------------------------------- #

def first_available_value(df: pd.DataFrame, candidates: list[str], default=None):
    """Return the first non-null value from any of the candidate columns."""
    if df is None or df.empty:
        return default
    lower_map = {c.lower(): c for c in df.columns}
    for c in candidates:
        key = c.lower()
        if key in lower_map:
            series = df[lower_map[key]].dropna()
            if len(series):
                return series.iloc[0]
    return default


def latest_col_value(df: pd.DataFrame, candidates: list[str]) -> float:
    """Return the first numeric value from the first non-null candidate column (iloc[0] row)."""
    if df is None or df.empty:
        return np.nan
    lower_map = {str(c).lower(): c for c in df.columns}
    for cand in candidates:
        col = lower_map.get(cand.lower())
        if col is not None:
            series = pd.to_numeric(df[col], errors="coerce").dropna()
            if not series.empty:
                return float(series.iloc[0])
    return np.nan


def last_numeric(series_or_df) -> float:
    """Return the last non-NaN numeric value from a Series or single-row DataFrame."""
    if isinstance(series_or_df, pd.DataFrame):
        numeric = series_or_df.select_dtypes(include=["number"])
        if numeric.empty:
            return np.nan
        vals = numeric.tail(1).values.flatten()
        vals = [v for v in vals if pd.notna(v)]
        return float(vals[0]) if vals else np.nan
    if isinstance(series_or_df, pd.Series):
        ser = pd.to_numeric(series_or_df, errors="coerce").dropna()
        return float(ser.iloc[-1]) if len(ser) else np.nan
    return np.nan


def _safe_float(value) -> float:
    try:
        num = float(value)
        return num if pd.notna(num) else np.nan
    except Exception:
        return np.nan


def _sanitise(value):
    """Convert nan/inf to None so json.dumps never sees non-compliant floats."""
    if value is None:
        return None
    try:
        f = float(value)
        if not (f == f) or f == float("inf") or f == float("-inf"):  # nan or inf
            return None
        return f
    except (TypeError, ValueError):
        return value


def _sanitise_dict(d: dict) -> dict:
    """Recursively sanitise all float values in a dict."""
    return {k: _sanitise(v) if isinstance(v, (float, int)) else v for k, v in d.items()}


def _clamp(value: float, low: float = 0.0, high: float = 5.0) -> float:
    return max(low, min(high, value))


def _growth_from_two_rows(df: pd.DataFrame, candidates: list[str]) -> float:
    """YoY growth from two most-recent rows (row 0 = most recent)."""
    if df is None or df.empty or len(df) < 2:
        return np.nan
    now = latest_col_value(df.iloc[[0]], candidates)
    prev = latest_col_value(df.iloc[[1]], candidates)
    if pd.notna(now) and pd.notna(prev) and prev != 0:
        return float((now / prev) - 1)
    return np.nan


def _sort_by_period(df: pd.DataFrame) -> pd.DataFrame:
    """Sort a financial statement DataFrame descending by period_ending date."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    if "period_ending" in df.columns:
        df["period_ending"] = pd.to_datetime(df["period_ending"], errors="coerce")
        df = df.sort_values("period_ending", ascending=False).reset_index(drop=True)
    return df


def _extract_close_series(df: pd.DataFrame, symbol: str) -> pd.Series:
    """Extract a date-indexed close-price Series from a long-format historical DataFrame."""
    if df is None or df.empty:
        return pd.Series(dtype=float)
    temp = df.copy()
    if {"date", "symbol", "close"}.issubset(set(temp.columns)):
        temp = temp[temp["symbol"].astype(str).str.upper() == symbol.upper()].copy()
    if "date" in temp.columns:
        temp["date"] = pd.to_datetime(temp["date"], errors="coerce")
        temp = temp.sort_values("date").set_index("date")
    return pd.to_numeric(temp.get("close", pd.Series(dtype=float)), errors="coerce").dropna()


# --------------------------------------------------------------------------- #
#  Phase 1 — Company Profile
# --------------------------------------------------------------------------- #

SECTOR_ETF_MAP: dict[str, list[str]] = {
    "Technology": ["XLK", "VGT"],
    "Financial Services": ["XLF", "VFH"],
    "Financial": ["XLF", "VFH"],
    "Healthcare": ["XLV", "VHT"],
    "Health Care": ["XLV", "VHT"],
    "Industrials": ["XLI", "VIS"],
    "Consumer Cyclical": ["XLY", "VCR"],
    "Consumer Defensive": ["XLP", "VDC"],
    "Energy": ["XLE", "VDE"],
    "Basic Materials": ["XLB", "VAW"],
    "Utilities": ["XLU", "VPU"],
    "Real Estate": ["XLRE", "VNQ"],
    "Communication Services": ["XLC", "VOX"],
}


def build_phase1_summary(
    symbol: str,
    profile_df: pd.DataFrame,
    quote_df: pd.DataFrame,
    peers_df: pd.DataFrame,
) -> dict:
    """
    Compress profile, quote, and peer data into a compact business snapshot.

    Returns a dict suitable for JSON serialisation.
    """
    sector = first_available_value(profile_df, ["sector", "sector_name"], default="Unknown")
    industry = first_available_value(profile_df, ["industry", "industry_name"], default="Unknown")
    market_cap = first_available_value(quote_df, ["market_cap", "marketcap"], default=np.nan)
    name = first_available_value(
        profile_df,
        ["name", "company_name", "company", "long_name", "short_name"],
        default=symbol,
    )
    description = first_available_value(profile_df, ["description", "business_description"], default="")
    ceo = first_available_value(profile_df, ["ceo"], default="")
    employees = first_available_value(profile_df, ["full_time_employees", "employees"], default=np.nan)
    website = first_available_value(profile_df, ["website", "url"], default="")
    last_price = first_available_value(quote_df, ["last_price", "price", "close"], default=np.nan)
    change_pct = first_available_value(quote_df, ["change_percent", "change_pct", "percent_change"], default=np.nan)
    volume = first_available_value(quote_df, ["volume"], default=np.nan)
    peer_count = len(peers_df) if peers_df is not None else 0

    # Peer symbols list (up to 10)
    peer_symbols: list[str] = []
    if peers_df is not None and not peers_df.empty:
        peer_cols = [c for c in peers_df.columns if c.lower() in ["symbol", "peer", "ticker"]]
        if peer_cols:
            peer_symbols = (
                peers_df[peer_cols[0]].dropna().astype(str).tolist()[:10]
            )

    sector_etfs = SECTOR_ETF_MAP.get(str(sector), ["SPY"])

    return {
        "symbol": symbol,
        "name": name,
        "sector": sector,
        "industry": industry,
        "market_cap": _sanitise(_safe_float(market_cap)),
        "last_price": _sanitise(_safe_float(last_price)),
        "change_pct": _sanitise(_safe_float(change_pct)),
        "volume": _sanitise(_safe_float(volume)),
        "peer_count": peer_count,
        "peers": peer_symbols,
        "sector_etfs": sector_etfs,
        "ceo": ceo,
        "employees": _sanitise(_safe_float(employees)),
        "website": website,
        "description": str(description)[:500] if description else "",
    }


# --------------------------------------------------------------------------- #
#  Phase 2 — Fundamental KPIs
# --------------------------------------------------------------------------- #

def compute_fundamental_kpis(
    income_df: pd.DataFrame,
    balance_df: pd.DataFrame,
    cash_df: pd.DataFrame,
    ratios_df: pd.DataFrame,
) -> dict:
    """
    Derive interpretable KPIs from annual financial statements.

    Returns a dict with keys like "Revenue Growth (last)", "Gross Margin (last)", etc.
    Values are floats (ratios, not percentages) or NaN where unavailable.
    """
    income_sorted = _sort_by_period(income_df)
    balance_sorted = _sort_by_period(balance_df)
    cash_sorted = _sort_by_period(cash_df)

    kpis: dict[str, float] = {
        "Revenue Growth (last)": _growth_from_two_rows(
            income_sorted, ["revenue"]
        ),
        "EPS Growth (last)": _growth_from_two_rows(
            income_sorted,
            ["basic_earnings_per_share", "eps", "eps_diluted", "diluted_earnings_per_share"],
        ),
        "FCF Growth (last)": _growth_from_two_rows(
            cash_sorted, ["free_cash_flow"]
        ),
        "Gross Margin (last)": latest_col_value(
            ratios_df, ["gross_profit_margin", "gross_margin"]
        ),
        "Operating Margin (last)": latest_col_value(
            ratios_df, ["operating_profit_margin", "operating_margin"]
        ),
        "Net Margin (last)": latest_col_value(
            ratios_df, ["net_profit_margin", "net_margin"]
        ),
        "ROIC (last)": latest_col_value(
            ratios_df, ["return_on_invested_capital", "roic"]
        ),
        "Current Ratio (last)": latest_col_value(ratios_df, ["current_ratio"]),
        "Debt/Equity (last)": latest_col_value(
            ratios_df, ["debt_to_equity", "debt_to_equity_ratio"]
        ),
    }

    # Fallback margins from statements when ratio endpoint missing values
    if not income_sorted.empty:
        row0 = income_sorted.iloc[[0]]
        revenue_now = latest_col_value(row0, ["revenue"])
        gross_now = latest_col_value(row0, ["gross_profit"])
        operating_now = latest_col_value(row0, ["operating_income"])
        net_now = latest_col_value(
            row0, ["net_income", "net_income_deductions"]
        )

        if (
            np.isnan(kpis["Gross Margin (last)"])
            and pd.notna(gross_now)
            and pd.notna(revenue_now)
            and revenue_now != 0
        ):
            kpis["Gross Margin (last)"] = gross_now / revenue_now

        if (
            np.isnan(kpis["Operating Margin (last)"])
            and pd.notna(operating_now)
            and pd.notna(revenue_now)
            and revenue_now != 0
        ):
            kpis["Operating Margin (last)"] = operating_now / revenue_now

        if (
            np.isnan(kpis["Net Margin (last)"])
            and pd.notna(net_now)
            and pd.notna(revenue_now)
            and revenue_now != 0
        ):
            kpis["Net Margin (last)"] = net_now / revenue_now

    # Fallback D/E from balance sheet
    if not balance_sorted.empty:
        row0_b = balance_sorted.iloc[[0]]
        debt_now = latest_col_value(row0_b, ["total_debt"])
        equity_now = latest_col_value(
            row0_b, ["total_equity", "total_common_equity"]
        )
        if (
            np.isnan(kpis["Debt/Equity (last)"])
            and pd.notna(debt_now)
            and pd.notna(equity_now)
            and equity_now != 0
        ):
            kpis["Debt/Equity (last)"] = debt_now / equity_now

    # Convert any remaining np.nan floats consistently
    return _sanitise_dict({k: (float(v) if pd.notna(v) else None) for k, v in kpis.items()})


# --------------------------------------------------------------------------- #
#  Phase 3 — Technical Indicators
# --------------------------------------------------------------------------- #

def compute_technical_kpis(price_df: pd.DataFrame) -> dict:
    """
    Compute RSI, ADX, ATR, OBV, MACD signal, and Bollinger % from daily OHLCV data.

    price_df must have columns: date, close (required), high, low, volume (optional).
    Returns a flat dict of indicator values.
    """
    if price_df is None or price_df.empty:
        return {
            "RSI(14)": None,
            "ADX(14)": None,
            "ATR(14)": None,
            "OBV": None,
            "MACD_Signal": None,
            "BB_Pct": None,
        }

    tmp = price_df.copy()

    # Normalise date index
    if "date" in tmp.columns:
        tmp["date"] = pd.to_datetime(tmp["date"], errors="coerce")
        tmp = tmp.sort_values("date").set_index("date")

    close = pd.to_numeric(tmp.get("close", pd.Series(dtype=float)), errors="coerce").dropna()
    high = pd.to_numeric(tmp.get("high", pd.Series(index=close.index, dtype=float)), errors="coerce").reindex(close.index)
    low = pd.to_numeric(tmp.get("low", pd.Series(index=close.index, dtype=float)), errors="coerce").reindex(close.index)
    volume = pd.to_numeric(tmp.get("volume", pd.Series(index=close.index, dtype=float)), errors="coerce").reindex(close.index)

    if close.empty:
        return {
            "RSI(14)": None,
            "ADX(14)": None,
            "ATR(14)": None,
            "OBV": None,
            "MACD_Signal": None,
            "BB_Pct": None,
        }

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    macd_signal_series = macd_line.ewm(span=9, adjust=False).mean()

    # ATR(14)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_series = tr.rolling(14).mean()

    # OBV
    direction = np.sign(close.diff()).fillna(0)
    obv_series = (direction * volume.fillna(0)).cumsum()

    # ADX(14)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_sum = tr.rolling(14).sum().replace(0, np.nan)
    plus_di = 100 * pd.Series(plus_dm, index=close.index).rolling(14).sum() / tr_sum
    minus_di = 100 * pd.Series(minus_dm, index=close.index).rolling(14).sum() / tr_sum
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx_series = dx.rolling(14).mean()

    # Bollinger Bands %B
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_mid + (2 * bb_std)
    bb_lower = bb_mid - (2 * bb_std)
    bb_width = (bb_upper - bb_lower).replace(0, np.nan)
    bb_pct_series = (close - bb_lower) / bb_width  # 0=at lower, 0.5=mid, 1=upper

    def _last(s: pd.Series):
        v = pd.to_numeric(s, errors="coerce").dropna()
        return _sanitise(float(v.iloc[-1])) if len(v) else None

    return {
        "RSI(14)": _last(rsi_series),
        "ADX(14)": _last(adx_series),
        "ATR(14)": _last(atr_series),
        "OBV": _last(obv_series),
        "MACD_Signal": _last(macd_signal_series),
        "BB_Pct": _last(bb_pct_series),
    }


# --------------------------------------------------------------------------- #
#  Phase 4 — Valuation
# --------------------------------------------------------------------------- #

def compute_valuation_kpis(
    ratios_df: pd.DataFrame,
    quote_df: pd.DataFrame,
    income_df: pd.DataFrame,
) -> dict:
    """
    Build a valuation snapshot from ratios, quote, and income data.

    Prefers ratios endpoint; falls back to manual calculation where possible.
    """
    def _r(candidates: list[str]) -> float | None:
        v = latest_col_value(ratios_df, candidates)
        return float(v) if pd.notna(v) else None

    price_now = latest_col_value(quote_df, ["last_price", "price", "close"])
    eps_now = latest_col_value(
        income_df,
        ["basic_earnings_per_share", "eps", "eps_diluted", "diluted_earnings_per_share"],
    )

    pe = _r(["price_earnings_ratio", "pe_ratio", "pe"])
    if pe is None and pd.notna(price_now) and pd.notna(eps_now) and eps_now != 0:
        pe = float(price_now / eps_now)

    earnings_yield = _r(["earnings_yield"])
    if earnings_yield is None and pe is not None and pe != 0:
        earnings_yield = float(1.0 / pe)

    return _sanitise_dict({
        "Price (last)": float(price_now) if pd.notna(price_now) else None,
        "EPS (last)": float(eps_now) if pd.notna(eps_now) else None,
        "P/E (last)": pe,
        "EV/EBITDA (last)": _r(["enterprise_value_multiple", "ev_to_ebitda"]),
        "P/FCF (last)": _r(
            ["price_to_free_cash_flow", "price_to_free_cash_flow_ratio", "p_fcf"]
        ),
        "P/S (last)": _r(["price_to_sales", "price_to_sales_ratio", "ps_ratio"]),
        "Earnings Yield (last)": earnings_yield,
        "WACC (last)": _r(["weighted_average_cost_of_capital", "wacc"]),
        "Piotroski (last)": _r(["piotroski_score"]),
        "Altman Z (last)": _r(["altman_z_score", "altman_z"]),
    })


# --------------------------------------------------------------------------- #
#  Phase 5 — Risk Metrics
# --------------------------------------------------------------------------- #

def compute_risk_kpis(
    asset_returns: pd.Series,
    bench_returns: pd.Series,
    risk_free_rate: float = 0.02,
) -> dict:
    """
    Compute Sharpe, Sortino, Beta, Jensen Alpha, VaR, CVaR, Max Drawdown, Ulcer.

    asset_returns / bench_returns: daily return Series (pct_change already applied).
    """
    _empty = {
        "Sharpe": None,
        "Sortino": None,
        "Jensen Alpha": None,
        "Beta": None,
        "VaR 95%": None,
        "CVaR 95%": None,
        "Max Drawdown": None,
        "Ulcer Index": None,
    }

    if asset_returns is None or asset_returns.empty or bench_returns is None or bench_returns.empty:
        return _empty

    # Align on common dates
    combined = pd.concat(
        [asset_returns.rename("asset"), bench_returns.rename("bench")], axis=1
    ).dropna()
    if combined.empty:
        return _empty

    asset = combined["asset"]
    bench = combined["bench"]

    annual_ret = float(asset.mean() * 252)
    annual_vol = float(asset.std() * np.sqrt(252))
    bench_annual_ret = float(bench.mean() * 252)

    downside = asset[asset < 0]
    downside_vol = float(downside.std() * np.sqrt(252)) if not downside.empty else np.nan

    sharpe = (annual_ret - risk_free_rate) / annual_vol if annual_vol > 0 else np.nan
    sortino = (
        (annual_ret - risk_free_rate) / downside_vol
        if pd.notna(downside_vol) and downside_vol > 0
        else np.nan
    )

    cov = float(asset.cov(bench))
    var_bench = float(bench.var())
    beta = cov / var_bench if var_bench > 0 else np.nan
    jensen_alpha = (
        annual_ret - (risk_free_rate + beta * (bench_annual_ret - risk_free_rate))
        if pd.notna(beta)
        else np.nan
    )

    var_95 = float(asset.quantile(0.05))
    cvar_95 = float(asset[asset <= var_95].mean()) if (asset <= var_95).any() else np.nan

    equity_curve = (1 + asset).cumprod()
    drawdown = equity_curve / equity_curve.cummax() - 1
    max_drawdown = float(drawdown.min())
    ulcer_index = float(np.sqrt((drawdown.pow(2)).mean()))

    def _n(v):
        return _sanitise(float(v)) if pd.notna(v) else None

    return _sanitise_dict({
        "Sharpe": _n(sharpe),
        "Sortino": _n(sortino),
        "Jensen Alpha": _n(jensen_alpha),
        "Beta": _n(beta),
        "VaR 95%": _n(var_95),
        "CVaR 95%": _n(cvar_95),
        "Max Drawdown": _n(max_drawdown),
        "Ulcer Index": _n(ulcer_index),
    })


# --------------------------------------------------------------------------- #
#  Phase 6 — Peer-Relative Table
# --------------------------------------------------------------------------- #

def compute_relative_table(
    close_matrix_df: pd.DataFrame,
    risk_free_rate: float = 0.02,
) -> pd.DataFrame:
    """
    Build a peer-relative metrics table from a wide close-price matrix.

    close_matrix_df: DatetimeIndex × symbol columns, values = adjusted close prices.
    Returns a DataFrame indexed by symbol with columns:
        Annual Return, Volatility, Sharpe, VaR 95%, CVaR 95%, Max Drawdown
    sorted descending by Sharpe.
    """
    if close_matrix_df is None or close_matrix_df.empty:
        return pd.DataFrame(
            columns=["Annual Return", "Volatility", "Sharpe", "VaR 95%", "CVaR 95%", "Max Drawdown"]
        )

    close = close_matrix_df.copy()
    close = close.dropna(axis=1, how="all").dropna(how="all")
    if close.empty or close.shape[1] == 0:
        return pd.DataFrame(
            columns=["Annual Return", "Volatility", "Sharpe", "VaR 95%", "CVaR 95%", "Max Drawdown"]
        )

    returns = close.pct_change().dropna(how="all")

    annual_ret = returns.mean() * 252
    annual_vol = returns.std() * np.sqrt(252)
    sharpe = (annual_ret - risk_free_rate) / annual_vol.replace(0, np.nan)
    var_95 = returns.quantile(0.05)
    cvar_95 = returns.where(returns.le(var_95), np.nan).mean()

    drawdown = (1 + returns).cumprod() / (1 + returns).cumprod().cummax() - 1
    max_drawdown = drawdown.min()

    table = pd.DataFrame(
        {
            "Annual Return": annual_ret,
            "Volatility": annual_vol,
            "Sharpe": sharpe,
            "VaR 95%": var_95,
            "CVaR 95%": cvar_95,
            "Max Drawdown": max_drawdown,
        }
    ).sort_values("Sharpe", ascending=False)

    return table


def build_close_matrix(hist_df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert a long-format historical DataFrame (date, symbol, close) into a
    wide close-price matrix (DatetimeIndex × symbol columns).
    """
    if hist_df is None or hist_df.empty:
        return pd.DataFrame()

    temp = hist_df.copy()

    # Normalise date column
    if "date" not in temp.columns:
        idx_name = str(temp.index.name).lower()
        if idx_name == "date" or isinstance(temp.index, pd.DatetimeIndex):
            temp = temp.reset_index().rename(columns={temp.reset_index().columns[0]: "date"})

    if {"date", "symbol", "close"}.issubset(set(temp.columns)):
        temp["date"] = pd.to_datetime(temp["date"], errors="coerce")
        temp["close"] = pd.to_numeric(temp["close"], errors="coerce")
        temp["symbol"] = temp["symbol"].astype(str).str.upper()
        close = (
            temp.dropna(subset=["date", "symbol", "close"])
            .pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
            .sort_index()
        )
    else:
        close = temp.copy()
        if "date" in close.columns:
            close["date"] = pd.to_datetime(close["date"], errors="coerce")
            close = close.set_index("date").sort_index()
        if "close" in close.columns:
            close = close[["close"]]
        else:
            close = close.apply(pd.to_numeric, errors="coerce")

    return close.dropna(axis=1, how="all").dropna(how="all")


def build_peer_universe(
    symbol: str,
    sector: str,
    peers_df: pd.DataFrame,
    benchmark: str = "SPY",
    max_peers: int = 10,
) -> list[str]:
    """Assemble the full comparison universe: stock + peers + sector ETFs + benchmark."""
    peer_candidates: list[str] = []
    if peers_df is not None and not peers_df.empty:
        peer_cols = [c for c in peers_df.columns if c.lower() in ["symbol", "peer", "ticker"]]
        if peer_cols:
            peer_candidates = peers_df[peer_cols[0]].dropna().astype(str).tolist()

    peer_candidates = [p for p in peer_candidates if p.upper() != symbol.upper()]
    peer_candidates = list(dict.fromkeys(peer_candidates))[:max_peers]

    sector_etfs = SECTOR_ETF_MAP.get(str(sector), ["SPY"])
    universe = list(dict.fromkeys([symbol] + peer_candidates + sector_etfs + [benchmark]))
    return universe


# --------------------------------------------------------------------------- #
#  Phase 7 — Decision Scoring
# --------------------------------------------------------------------------- #

def _score_band(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "Unknown"
    if value >= 4.2:
        return "Strong"
    if value >= 3.6:
        return "Good"
    if value >= 2.8:
        return "Mixed"
    return "Weak"


def _decision_label(score) -> str:
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return "Pending"
    if score >= 4.2:
        return "Strong Buy"
    if score >= 3.6:
        return "Buy"
    if score >= 2.8:
        return "Hold/Watch"
    return "Avoid/Sell"


def compute_decision_scores(
    fundamental_kpis: dict,
    technical_kpis: dict,
    valuation_kpis: dict,
    risk_kpis: dict,
    relative_table: pd.DataFrame,
    phase1_summary: dict,
    symbol: str,
) -> dict:
    """
    Produce the 6-dimension composite score and a decision label.

    All input dicts use the exact keys produced by the compute_* functions above.
    Returns a dict with keys: business_quality, fundamentals, technicals,
    valuation, risk_fit, relative_peer_score, total_score, decision.
    """
    def _g(d: dict | None, key: str) -> float:
        if d is None:
            return np.nan
        v = d.get(key)
        return _safe_float(v) if v is not None else np.nan

    # ── 1  Business quality (0-5) ─────────────────────────────────────────── #
    market_cap = _safe_float(phase1_summary.get("market_cap")) if phase1_summary else np.nan
    peer_count = _safe_float(phase1_summary.get("peer_count")) if phase1_summary else np.nan
    net_margin = _g(fundamental_kpis, "Net Margin (last)")
    roic = _g(fundamental_kpis, "ROIC (last)")

    size_score = 0.5
    if pd.notna(market_cap):
        if market_cap >= 200e9:
            size_score = 2.0
        elif market_cap >= 50e9:
            size_score = 1.6
        elif market_cap >= 10e9:
            size_score = 1.2
        elif market_cap >= 2e9:
            size_score = 0.8

    peer_score = 0.5
    if pd.notna(peer_count):
        if peer_count >= 8:
            peer_score = 1.0
        elif peer_count >= 4:
            peer_score = 0.8
        elif peer_count >= 1:
            peer_score = 0.6

    profitability_score = 1.0
    if pd.notna(net_margin) and pd.notna(roic):
        nm = 1.0 if net_margin >= 0.15 else (0.8 if net_margin >= 0.08 else (0.5 if net_margin >= 0.03 else 0.2))
        rc = 1.0 if roic >= 0.12 else (0.8 if roic >= 0.08 else (0.5 if roic >= 0.04 else 0.2))
        profitability_score = nm + rc
    elif pd.notna(net_margin):
        profitability_score = 1.0 if net_margin >= 0.12 else (0.7 if net_margin >= 0.05 else 0.3)
    elif pd.notna(roic):
        profitability_score = 1.0 if roic >= 0.10 else (0.7 if roic >= 0.05 else 0.3)

    business_quality = _clamp(size_score + peer_score + profitability_score)

    # ── 2  Fundamentals (0-5) ─────────────────────────────────────────────── #
    rev_g = _g(fundamental_kpis, "Revenue Growth (last)")
    eps_g = _g(fundamental_kpis, "EPS Growth (last)")
    fcf_g = _g(fundamental_kpis, "FCF Growth (last)")
    op_margin = _g(fundamental_kpis, "Operating Margin (last)")
    de_ratio = _g(fundamental_kpis, "Debt/Equity (last)")
    cur_ratio = _g(fundamental_kpis, "Current Ratio (last)")

    growth_score = 0.0
    for g in [rev_g, eps_g, fcf_g]:
        if pd.notna(g):
            growth_score += 0.7 if g >= 0.10 else (0.5 if g >= 0.03 else (0.3 if g >= 0 else 0.1))
        else:
            growth_score += 0.3
    growth_score = min(growth_score, 2.1)

    quality_score = 0.5
    if pd.notna(op_margin):
        quality_score = 1.4 if op_margin >= 0.15 else (1.0 if op_margin >= 0.08 else (0.6 if op_margin >= 0.03 else 0.2))

    balance_score = 0.5
    if pd.notna(de_ratio) and pd.notna(cur_ratio):
        de_part = 0.8 if de_ratio <= 0.8 else (0.6 if de_ratio <= 1.5 else (0.3 if de_ratio <= 2.5 else 0.1))
        cr_part = 0.7 if cur_ratio >= 1.5 else (0.5 if cur_ratio >= 1.0 else 0.2)
        balance_score = de_part + cr_part
    elif pd.notna(de_ratio):
        balance_score = 0.8 if de_ratio <= 1.2 else (0.5 if de_ratio <= 2.0 else 0.2)
    elif pd.notna(cur_ratio):
        balance_score = 0.7 if cur_ratio >= 1.3 else (0.5 if cur_ratio >= 1.0 else 0.2)

    fundamentals_score = _clamp(growth_score + quality_score + balance_score)

    # ── 3  Technicals (0-5) ───────────────────────────────────────────────── #
    rsi = _g(technical_kpis, "RSI(14)")
    adx = _g(technical_kpis, "ADX(14)")
    obv = _g(technical_kpis, "OBV")

    rsi_score = 1.0
    if pd.notna(rsi):
        rsi_score = 2.0 if 45 <= rsi <= 65 else (1.5 if 35 <= rsi <= 75 else 0.8)

    adx_score = 1.0
    if pd.notna(adx):
        adx_score = 1.5 if 20 <= adx <= 45 else (1.1 if 15 <= adx <= 60 else 0.7)

    obv_score = 0.8
    if pd.notna(obv):
        obv_score = 1.2 if obv > 0 else 0.7

    technicals_score = _clamp(rsi_score + adx_score + obv_score)

    # ── 4  Valuation (0-5) ────────────────────────────────────────────────── #
    pe = _g(valuation_kpis, "P/E (last)")
    ey = _g(valuation_kpis, "Earnings Yield (last)")
    ev_ebitda = _g(valuation_kpis, "EV/EBITDA (last)")

    pe_score = 2.0 if pd.notna(pe) and pe <= 15 else (
        1.6 if pd.notna(pe) and pe <= 22 else (
            1.1 if pd.notna(pe) and pe <= 30 else (
                0.6 if pd.notna(pe) and pe <= 40 else (
                    0.2 if pd.notna(pe) else 0.9
                )
            )
        )
    )

    ey_score = 1.5 if pd.notna(ey) and ey >= 0.07 else (
        1.1 if pd.notna(ey) and ey >= 0.045 else (
            0.7 if pd.notna(ey) and ey >= 0.025 else (
                0.3 if pd.notna(ey) else 0.7
            )
        )
    )

    ev_score = 1.5 if pd.notna(ev_ebitda) and ev_ebitda <= 10 else (
        1.1 if pd.notna(ev_ebitda) and ev_ebitda <= 16 else (
            0.7 if pd.notna(ev_ebitda) and ev_ebitda <= 24 else (
                0.3 if pd.notna(ev_ebitda) else 0.7
            )
        )
    )

    valuation_score = _clamp(pe_score + ey_score + ev_score)

    # ── 5  Risk fit (0-5) ─────────────────────────────────────────────────── #
    sharpe_v = _g(risk_kpis, "Sharpe")
    sortino_v = _g(risk_kpis, "Sortino")
    beta_v = _g(risk_kpis, "Beta")
    maxdd_v = _g(risk_kpis, "Max Drawdown")

    sharpe_score = (
        2.0 if pd.notna(sharpe_v) and sharpe_v >= 1.5 else (
            1.6 if pd.notna(sharpe_v) and sharpe_v >= 1.0 else (
                1.1 if pd.notna(sharpe_v) and sharpe_v >= 0.5 else (
                    0.6 if pd.notna(sharpe_v) and sharpe_v >= 0 else (
                        0.2 if pd.notna(sharpe_v) else 0.8
                    )
                )
            )
        )
    )

    sortino_score = (
        1.5 if pd.notna(sortino_v) and sortino_v >= 2.0 else (
            1.2 if pd.notna(sortino_v) and sortino_v >= 1.2 else (
                0.8 if pd.notna(sortino_v) and sortino_v >= 0.6 else (
                    0.3 if pd.notna(sortino_v) else 0.7
                )
            )
        )
    )

    mdd_score = (
        1.0 if pd.notna(maxdd_v) and maxdd_v >= -0.15 else (
            0.7 if pd.notna(maxdd_v) and maxdd_v >= -0.30 else (
                0.4 if pd.notna(maxdd_v) and maxdd_v >= -0.45 else (
                    0.2 if pd.notna(maxdd_v) else 0.5
                )
            )
        )
    )

    beta_score = (
        0.5 if pd.notna(beta_v) and 0.8 <= beta_v <= 1.2 else (
            0.35 if pd.notna(beta_v) and 0.6 <= beta_v <= 1.5 else (
                0.2 if pd.notna(beta_v) else 0.3
            )
        )
    )

    risk_fit_score = _clamp(sharpe_score + sortino_score + mdd_score + beta_score)

    # ── 6  Relative peer score (0-5) ──────────────────────────────────────── #
    relative_peer_score: float = np.nan
    if (
        relative_table is not None
        and isinstance(relative_table, pd.DataFrame)
        and not relative_table.empty
        and symbol.upper() in [str(s).upper() for s in relative_table.index]
    ):
        rt = relative_table.copy()
        # Normalise index to uppercase for safe lookup
        rt.index = rt.index.astype(str).str.upper()
        sym_up = symbol.upper()
        if sym_up in rt.index:
            sharpe_rank = rt["Sharpe"].rank(ascending=False, method="average")
            ret_rank = rt["Annual Return"].rank(ascending=False, method="average")
            n = len(rt)
            if n > 1:
                sharpe_pct = 1 - ((sharpe_rank.loc[sym_up] - 1) / (n - 1))
                ret_pct = 1 - ((ret_rank.loc[sym_up] - 1) / (n - 1))
                relative_peer_score = _clamp(5 * (0.7 * sharpe_pct + 0.3 * ret_pct))
            else:
                relative_peer_score = 2.5

    # ── Composite ─────────────────────────────────────────────────────────── #
    scores: dict[str, float | None] = {
        "business_quality": round(business_quality, 2),
        "fundamentals": round(fundamentals_score, 2),
        "technicals": round(technicals_score, 2),
        "valuation": round(valuation_score, 2),
        "risk_fit": round(risk_fit_score, 2),
        "relative_peer_score": (
            round(relative_peer_score, 2) if pd.notna(relative_peer_score) else None
        ),
    }

    weights = {
        "business_quality": 0.08,
        "fundamentals": 0.25,
        "technicals": 0.15,
        "valuation": 0.20,
        "risk_fit": 0.12,
        "relative_peer_score": 0.20,
    }

    all_available = all(v is not None for v in scores.values())
    total_score: float | None
    if all_available:
        total_score = round(
            sum(scores[k] * weights[k] for k in scores),  # type: ignore[operator]
            2,
        )
    else:
        # Partial score: weight only available dimensions
        available_weight = sum(weights[k] for k, v in scores.items() if v is not None)
        if available_weight > 0:
            total_score = round(
                sum(scores[k] * weights[k] for k, v in scores.items() if v is not None)  # type: ignore[operator]
                / available_weight
                * sum(weights.values()),
                2,
            )
        else:
            total_score = None

    return _sanitise_dict({
        **scores,
        "total_score": total_score,
        "decision": _decision_label(total_score),
    })
