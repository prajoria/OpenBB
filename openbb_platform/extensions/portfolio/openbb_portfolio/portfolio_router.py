"""
Portfolio Extension — FastAPI APIRouter.

All route handlers ported from portfolio_app/src/main.py.
Key change: OpenBBClient HTTP proxy calls replaced with direct
OpenBB Python SDK calls via openbb_portfolio._obb_data helpers.

Routes registered:
    /portfolio/widgets.json     (detected & merged by openbb_platform_api)
    /portfolio/apps.json        (detected & merged by openbb_platform_api)
    /portfolio/get_symbols      option-list helper
    /portfolio/get_accounts     option-list helper (returns [] for privacy)
    /portfolio/get_owners       option-list helper (returns [] for privacy)
    /portfolio/positions        blocked (privacy policy)
    /portfolio/summary          sanitised basket summary
    /portfolio/allocation       blocked (privacy policy)
    /portfolio/cost_basis       blocked (privacy policy)
    /portfolio/tax_summary      blocked (privacy policy)
    /portfolio/performance      performance ranking
    /portfolio/snapshots        snapshot trend history
    /espp/purchases             ESPP purchase history
    /equity/historical          cached OHLCV from DB
    /market/quote               live quote via OpenBB SDK
    /market/historical          historical prices via OpenBB SDK
    /stock/context              Phase 0 — symbol anchor
    /stock/profile              Phase 1 — company profile
    /stock/fundamentals         Phase 2 — fundamental KPIs
    /stock/technicals           Phase 3 — technical indicators
    /stock/valuation            Phase 4 — valuation ratios
    /stock/risk                 Phase 5 — risk metrics
    /stock/relative             Phase 6 — peer relative table
    /stock/decision             Phase 7 — composite decision score
    /portfolio/health           health check
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from openbb_portfolio import _obb_data as od
from openbb_portfolio._cache import cached
from openbb_portfolio.data import (
    check_db,
    df_to_records,
    filter_df,
    get_all_basket_snapshots_df,
    get_distinct_accounts,
    get_distinct_owners,
    get_distinct_symbols,
    get_equity_historical_df,
    get_espp_df,
    get_portfolio_basket_df,
)
from openbb_portfolio.db import DBConfig
from openbb_portfolio.stock_analysis import (
    SECTOR_ETF_MAP,
    build_close_matrix,
    build_peer_universe,
    build_phase1_summary,
    compute_decision_scores,
    compute_fundamental_kpis,
    compute_relative_table,
    compute_risk_kpis,
    compute_technical_kpis,
    compute_valuation_kpis,
    first_available_value,
    _extract_close_series,
)

LOG = logging.getLogger("openbb_portfolio")

router = APIRouter(tags=["Portfolio"])

# --------------------------------------------------------------------------- #
#  Assets directory (widgets.json / apps.json)
# --------------------------------------------------------------------------- #

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


# --------------------------------------------------------------------------- #
#  KPI formatting
# --------------------------------------------------------------------------- #

_KPI_FMT: dict[str, str] = {
    # Fundamentals
    "Revenue Growth (last)": "pct",
    "EPS Growth (last)": "pct",
    "FCF Growth (last)": "pct",
    "Gross Margin (last)": "pct",
    "Operating Margin (last)": "pct",
    "Net Margin (last)": "pct",
    "ROIC (last)": "pct",
    "Current Ratio (last)": "num",
    "Debt/Equity (last)": "num",
    # Technicals
    "RSI(14)": "num",
    "ADX(14)": "num",
    "ATR(14)": "num",
    "OBV": "num",
    "MACD_Signal": "num",
    "BB_Pct": "num",
    # Valuation
    "Price (last)": "num",
    "EPS (last)": "num",
    "P/E (last)": "x",
    "EV/EBITDA (last)": "x",
    "P/FCF (last)": "x",
    "P/S (last)": "x",
    "Earnings Yield (last)": "pct",
    "WACC (last)": "pct",
    "Piotroski (last)": "num",
    "Altman Z (last)": "num",
    # Risk
    "Sharpe": "num",
    "Sortino": "num",
    "Jensen Alpha": "pct",
    "Beta": "num",
    "VaR 95%": "pct",
    "CVaR 95%": "pct",
    "Max Drawdown": "pct",
    "Ulcer Index": "pct",
}


def _fmt_kpi(key: str, val) -> str:
    """Format a KPI value as a human-readable string."""
    if val is None:
        return "-"
    fmt = _KPI_FMT.get(key, "num")
    try:
        v = float(val)
    except (TypeError, ValueError):
        return str(val)
    if fmt == "pct":
        return f"{v * 100:.1f}%"
    if fmt == "x":
        return f"{v:.2f}x"
    # "num" — use sensible precision
    if abs(v) >= 1_000_000:
        return f"{v:,.0f}"
    if abs(v) >= 100:
        return f"{v:.2f}"
    return f"{v:.4f}"


def _obb_unavailable():
    return JSONResponse(
        status_code=502,
        content={"error": "OpenBB SDK not available or no data returned."},
    )


# --------------------------------------------------------------------------- #
#  Cached data-fetch helpers for stock analysis
# --------------------------------------------------------------------------- #

async def _get_profile_data(symbol: str):
    """Fetch profile + quote + peers — cached per symbol."""
    key = ("profile", symbol.upper())

    async def fetch():
        profile_df, quote_df, peers_df = await asyncio.gather(
            od.get_profile_df(symbol),
            od.get_quote_df(symbol),
            od.get_peers_df(symbol),
        )
        return profile_df, quote_df, peers_df

    return await cached(key, fetch)


async def _get_fundamental_data(symbol: str, limit: int):
    """Fetch 4 fundamental statement DFs — cached per (symbol, limit)."""
    key = ("fundamentals", symbol.upper(), limit)

    async def fetch():
        return await asyncio.gather(
            od.get_income_df(symbol, period="annual", limit=limit),
            od.get_balance_df(symbol, period="annual", limit=limit),
            od.get_cash_df(symbol, period="annual", limit=limit),
            od.get_ratios_df(symbol, period="annual", limit=limit),
        )

    return await cached(key, fetch)


async def _get_price_history(symbol: str, benchmark: str, start: str, end: str):
    """Fetch daily price history for symbol + benchmark — cached per key."""
    key = ("price_hist", symbol.upper(), benchmark.upper(), start, end)

    async def fetch():
        return await od.get_historical_df(
            f"{symbol},{benchmark}",
            start_date=start,
            end_date=end,
        )

    return await cached(key, fetch)


async def _get_universe_history(universe: tuple, start: str, end: str):
    """Fetch daily price history for a peer universe — cached per key."""
    key = ("universe_hist", universe, start, end)

    async def fetch():
        return await od.get_historical_df(
            ",".join(universe),
            start_date=start,
            end_date=end,
        )

    return await cached(key, fetch)


# --------------------------------------------------------------------------- #
#  Metadata / widget registry endpoints
# --------------------------------------------------------------------------- #

@router.get("/portfolio/widgets.json", include_in_schema=False,
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def portfolio_widgets():
    """Serve widgets.json — detected and merged by openbb_platform_api."""
    p = _ASSETS_DIR / "widgets.json"
    with open(p, encoding="utf-8") as f:
        return JSONResponse(content=json.load(f))


@router.get("/portfolio/apps.json", include_in_schema=False,
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def portfolio_apps():
    """Serve apps.json — detected and merged by openbb_platform_api."""
    p = _ASSETS_DIR / "apps.json"
    with open(p, encoding="utf-8") as f:
        return JSONResponse(content=json.load(f))


# --------------------------------------------------------------------------- #
#  Option-list helpers (for widget dropdowns)
# --------------------------------------------------------------------------- #

@router.get("/portfolio/get_symbols", include_in_schema=False,
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def get_symbols():
    return get_distinct_symbols()


@router.get("/portfolio/get_accounts", include_in_schema=False,
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def get_accounts():
    return get_distinct_accounts()


@router.get("/portfolio/get_owners", include_in_schema=False,
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def get_owners():
    return get_distinct_owners()


# --------------------------------------------------------------------------- #
#  Portfolio Endpoints
# --------------------------------------------------------------------------- #

def _raw_positions_blocked() -> None:
    """Raise an explicit policy error for raw holdings endpoints."""
    raise HTTPException(
        status_code=403,
        detail=(
            "Raw lot-level portfolio access is disabled in API. "
            "Use a local Python script for Portfolio_Positions access."
        ),
    )


@router.get("/portfolio/positions",
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def portfolio_positions(
    account: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
    owner: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
    snapshot_date: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
):
    """Blocked: raw lot-level positions cannot be served via API."""
    _raw_positions_blocked()


@router.get("/portfolio/summary",
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def portfolio_summary(
    snapshot_date: Optional[str] = Query(None, description="Filter by snapshot date (YYYY-MM-DD)"),
    symbol: Optional[str] = Query(None, description="Filter by ticker symbol"),
):
    """Sanitized symbol-level portfolio summary from portfolio_basket."""
    df = get_portfolio_basket_df(snapshot_date=snapshot_date)
    if symbol:
        df = filter_df(df, symbol=symbol)
    if not df.empty and "portfolio_weight_pct" in df.columns:
        df = df.sort_values("portfolio_weight_pct", ascending=False).reset_index(drop=True)
    return df_to_records(df)


@router.get("/portfolio/allocation",
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def portfolio_allocation(
    owner: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
):
    """Blocked: account allocation requires raw position metadata."""
    _raw_positions_blocked()


@router.get("/portfolio/cost_basis",
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def portfolio_cost_basis(
    symbol: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
    account: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
):
    """Blocked: lot-level cost basis cannot be served via API."""
    _raw_positions_blocked()


@router.get("/portfolio/tax_summary",
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def portfolio_tax_summary(
    owner: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
):
    """Blocked: tax summary endpoint uses raw lots and is disabled."""
    _raw_positions_blocked()


@router.get("/portfolio/performance",
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def portfolio_performance(
    snapshot_date: Optional[str] = Query(None, description="Filter by snapshot date (YYYY-MM-DD)"),
):
    """Symbol performance ranking from sanitized basket data."""
    df = get_portfolio_basket_df(snapshot_date=snapshot_date)
    if df.empty:
        return []
    result = df.sort_values("pct_return", ascending=False).reset_index(drop=True)
    return df_to_records(result)


@router.get("/portfolio/snapshots",
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def portfolio_snapshots():
    """All available basket snapshots with total portfolio values."""
    df = get_all_basket_snapshots_df()
    if df.empty:
        return []
    result = (
        df.groupby("snapshot_date", as_index=False)
        .agg(
            stocks=("symbol", "nunique"),
            total_cost_basis=("total_cost_basis", "sum"),
            total_current_value=("total_current_value", "sum"),
            total_gain_loss=("total_gain_loss", "sum"),
        )
        .sort_values("snapshot_date")
        .reset_index(drop=True)
    )
    return df_to_records(result)


# --------------------------------------------------------------------------- #
#  ESPP
# --------------------------------------------------------------------------- #

@router.get("/espp/purchases",
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def espp_purchases():
    """ESPP purchase history with discount and tax analysis."""
    return df_to_records(get_espp_df())


# --------------------------------------------------------------------------- #
#  Equity historical prices (from cache DB)
# --------------------------------------------------------------------------- #

@router.get("/equity/historical",
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def equity_historical(
    symbol: str = Query("MSFT", description="Ticker symbol"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
):
    """Historical daily equity prices from the cache database."""
    return df_to_records(get_equity_historical_df(symbol, start_date, end_date))


# --------------------------------------------------------------------------- #
#  Market data via OpenBB SDK (no HTTP proxy)
# --------------------------------------------------------------------------- #

@router.get("/market/quote",
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def market_quote(
    symbol: str = Query("MSFT", description="Ticker symbol"),
    provider: Optional[str] = Query(None, description="Data provider (e.g. fmp, yfinance)"),
):
    """Get a live equity quote via the OpenBB Python SDK."""
    _provider = provider or "fmp_cached"
    df = await od.get_quote_df(symbol, provider=_provider)
    if df.empty:
        return _obb_unavailable()
    return df_to_records(df)


@router.get("/market/historical",
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def market_historical(
    symbol: str = Query("MSFT", description="Ticker symbol"),
    start_date: Optional[str] = Query(None, description="Start date"),
    end_date: Optional[str] = Query(None, description="End date"),
    provider: Optional[str] = Query(None, description="Data provider"),
):
    """Get historical prices via the OpenBB Python SDK."""
    _provider = provider or "fmp_cached"
    today = pd.Timestamp.today().normalize().strftime("%Y-%m-%d")
    _start = start_date or (pd.Timestamp.today() - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    _end = end_date or today

    df = await od.get_historical_df(symbol, start_date=_start, end_date=_end, provider=_provider)
    if df.empty:
        return _obb_unavailable()
    return df_to_records(df)


# --------------------------------------------------------------------------- #
#  Single-Stock Analysis Endpoints  (Phase 0-7)
# --------------------------------------------------------------------------- #

@router.get("/stock/context",
            openapi_extra={"mcp_config": {"tags": ["portfolio", "financialtoolkit"]}})
async def stock_context(
    symbol: str = Query("CLS", description="Ticker symbol"),
):
    """Phase 0 — Lightweight symbol resolver / anchor widget."""
    profile_df, quote_df, peers_df = await _get_profile_data(symbol)
    sector = str(first_available_value(profile_df, ["sector", "sector_name"], default="Unknown"))
    peers_raw = build_peer_universe(symbol.upper(), sector, peers_df, "SPY", max_peers=5)
    sector_etfs = SECTOR_ETF_MAP.get(sector, [])
    return [{
        "symbol": symbol.upper(),
        "sector": sector,
        "peers": ", ".join(p for p in peers_raw if p not in (symbol.upper(), "SPY")),
        "sector_etfs": ", ".join(sector_etfs),
        "last_price": first_available_value(quote_df, ["last_price", "price", "close"], default=None),
    }]


@router.get("/stock/profile",
            openapi_extra={"mcp_config": {"tags": ["portfolio", "financialtoolkit"]}})
async def stock_profile(
    symbol: str = Query("CLS", description="Ticker symbol"),
    benchmark: str = Query("SPY", description="Benchmark ticker"),
):
    """Phase 1 — Company profile, quote, and peer-count summary."""
    profile_df, quote_df, peers_df = await _get_profile_data(symbol)
    summary = build_phase1_summary(
        symbol=symbol.upper(),
        profile_df=profile_df,
        quote_df=quote_df,
        peers_df=peers_df,
    )
    for list_field in ("peers", "sector_etfs"):
        if isinstance(summary.get(list_field), list):
            summary[list_field] = ", ".join(str(x) for x in summary[list_field])
    return [summary]


@router.get("/stock/fundamentals",
            openapi_extra={"mcp_config": {"tags": ["portfolio", "financialtoolkit"]}})
async def stock_fundamentals(
    symbol: str = Query("CLS", description="Ticker symbol"),
    lookback_years: int = Query(5, description="Years of annual history"),
):
    """Phase 2 — 5-year fundamental KPIs (growth, margins, ROIC, leverage)."""
    limit = max(lookback_years, 2)
    income_df, balance_df, cash_df, ratios_df = await _get_fundamental_data(symbol, limit)
    kpis = compute_fundamental_kpis(income_df, balance_df, cash_df, ratios_df)
    return [{"metric": k, "value": _fmt_kpi(k, v)} for k, v in kpis.items()]


@router.get("/stock/technicals",
            openapi_extra={"mcp_config": {"tags": ["portfolio", "financialtoolkit"]}})
async def stock_technicals(
    symbol: str = Query("CLS", description="Ticker symbol"),
    lookback_years: int = Query(1, description="Years of daily history"),
):
    """Phase 3 — Technical indicators (RSI, ADX, ATR, OBV, MACD, Bollinger %)."""
    today = pd.Timestamp.today().normalize()
    start = (today - pd.DateOffset(years=lookback_years)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    hist_df = await _get_price_history(symbol, "SPY", start, end)
    price_df = (
        hist_df[hist_df["symbol"].astype(str).str.upper() == symbol.upper()].copy()
        if not hist_df.empty and "symbol" in hist_df.columns
        else hist_df.copy()
    )
    kpis = compute_technical_kpis(price_df)
    return [{"indicator": k, "value": _fmt_kpi(k, v)} for k, v in kpis.items()]


@router.get("/stock/valuation",
            openapi_extra={"mcp_config": {"tags": ["portfolio", "financialtoolkit"]}})
async def stock_valuation(
    symbol: str = Query("CLS", description="Ticker symbol"),
    lookback_years: int = Query(5, description="Years of annual history"),
):
    """Phase 4 — Valuation ratios (P/E, EV/EBITDA, P/FCF, P/S, Earnings Yield)."""
    limit = max(lookback_years, 1)
    (income_df, balance_df, cash_df, ratios_df), (_, quote_df, _) = await asyncio.gather(
        _get_fundamental_data(symbol, limit),
        _get_profile_data(symbol),
    )
    kpis = compute_valuation_kpis(ratios_df, quote_df, income_df)
    return [{"metric": k, "value": _fmt_kpi(k, v)} for k, v in kpis.items()]


@router.get("/stock/risk",
            openapi_extra={"mcp_config": {"tags": ["portfolio", "financialtoolkit"]}})
async def stock_risk(
    symbol: str = Query("CLS", description="Ticker symbol"),
    benchmark: str = Query("SPY", description="Benchmark ticker"),
    lookback_years: int = Query(1, description="Years of daily history"),
    risk_free_rate: float = Query(0.02, description="Annual risk-free rate (decimal)"),
):
    """Phase 5 — Risk metrics (Sharpe, Sortino, Beta, Alpha, VaR, CVaR, Max DD, Ulcer)."""
    today = pd.Timestamp.today().normalize()
    start = (today - pd.DateOffset(years=lookback_years)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    hist_df = await _get_price_history(symbol, benchmark, start, end)
    asset_close = _extract_close_series(hist_df, symbol)
    bench_close = _extract_close_series(hist_df, benchmark)
    kpis = compute_risk_kpis(
        asset_close.pct_change().dropna(),
        bench_close.pct_change().dropna(),
        risk_free_rate,
    )
    return [{"metric": k, "value": _fmt_kpi(k, v)} for k, v in kpis.items()]


@router.get("/stock/relative",
            openapi_extra={"mcp_config": {"tags": ["portfolio", "financialtoolkit"]}})
async def stock_relative(
    symbol: str = Query("CLS", description="Ticker symbol"),
    benchmark: str = Query("SPY", description="Benchmark ticker"),
    lookback_years: int = Query(1, description="Years of daily history"),
    risk_free_rate: float = Query(0.02, description="Annual risk-free rate (decimal)"),
):
    """Phase 6 — Peer-relative return / risk comparison table."""
    today = pd.Timestamp.today().normalize()
    start = (today - pd.DateOffset(years=lookback_years)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    profile_df, _, peers_df = await _get_profile_data(symbol)
    sector = first_available_value(profile_df, ["sector", "sector_name"], default="Unknown")
    universe = tuple(build_peer_universe(symbol.upper(), str(sector), peers_df, benchmark, max_peers=5))

    hist_df = await _get_universe_history(universe, start, end)
    close_matrix = build_close_matrix(hist_df)
    rel_table = compute_relative_table(close_matrix, risk_free_rate=risk_free_rate)

    if rel_table.empty:
        return []
    df_out = rel_table.reset_index()
    idx_col = df_out.columns[0]
    if idx_col != "symbol":
        df_out = df_out.rename(columns={idx_col: "symbol"})
    return df_out.to_dict(orient="records")


@router.get("/stock/decision",
            openapi_extra={"mcp_config": {"tags": ["portfolio", "financialtoolkit"]}})
async def stock_decision(
    symbol: str = Query("CLS", description="Ticker symbol"),
    benchmark: str = Query("SPY", description="Benchmark ticker"),
    lookback_years: int = Query(1, description="Years for technicals/risk"),
    lookback_years_fundamentals: int = Query(5, description="Years for fundamentals"),
    risk_free_rate: float = Query(0.02, description="Annual risk-free rate (decimal)"),
):
    """Phase 7 — Composite decision score across all 6 dimensions."""
    today = pd.Timestamp.today().normalize()
    start_tech = (today - pd.DateOffset(years=lookback_years)).strftime("%Y-%m-%d")
    start_fund = (today - pd.DateOffset(years=lookback_years_fundamentals)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    fund_limit = max(lookback_years_fundamentals, 2)

    (profile_df, quote_df, peers_df), (income_df, balance_df, cash_df, ratios_df), price_df = await asyncio.gather(
        _get_profile_data(symbol),
        _get_fundamental_data(symbol, fund_limit),
        _get_price_history(symbol, benchmark, start_tech, end),
    )

    phase1 = build_phase1_summary(symbol.upper(), profile_df, quote_df, peers_df)
    fund_kpis = compute_fundamental_kpis(income_df, balance_df, cash_df, ratios_df)

    sym_price_df = (
        price_df[price_df["symbol"].astype(str).str.upper() == symbol.upper()].copy()
        if not price_df.empty and "symbol" in price_df.columns
        else price_df.copy()
    )
    tech_kpis = compute_technical_kpis(sym_price_df)
    val_kpis = compute_valuation_kpis(ratios_df, quote_df, income_df)

    asset_close = _extract_close_series(price_df, symbol)
    bench_close = _extract_close_series(price_df, benchmark)
    risk_kpis = compute_risk_kpis(
        asset_close.pct_change().dropna(),
        bench_close.pct_change().dropna(),
        risk_free_rate,
    )

    sector = first_available_value(profile_df, ["sector", "sector_name"], default="Unknown")
    universe = tuple(build_peer_universe(symbol.upper(), str(sector), peers_df, benchmark, max_peers=5))

    hist_df = await _get_universe_history(universe, start_tech, end)
    close_matrix = build_close_matrix(hist_df)
    rel_table = compute_relative_table(close_matrix, risk_free_rate=risk_free_rate)

    result = compute_decision_scores(
        fundamental_kpis=fund_kpis,
        technical_kpis=tech_kpis,
        valuation_kpis=val_kpis,
        risk_kpis=risk_kpis,
        relative_table=rel_table,
        phase1_summary=phase1,
        symbol=symbol.upper(),
    )
    result["symbol"] = symbol.upper()
    return [result]


# --------------------------------------------------------------------------- #
#  Health check
# --------------------------------------------------------------------------- #

@router.get("/portfolio/health", include_in_schema=False,
            openapi_extra={"mcp_config": {"tags": ["portfolio"]}})
async def health():
    """Health check — reports DB connectivity."""
    db_ok = check_db()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "database_name": DBConfig().database,
        "openbb_sdk": True,  # SDK is always available in-process
    }
