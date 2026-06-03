"""
Portfolio App — Standalone FastAPI Backend

A standalone FastAPI service that serves portfolio data widgets for
OpenBB Workspace. Connects to MySQL for portfolio positions and can
call the OpenBB Platform API for market data enrichment.

Run:
    cd portfolio_app
    python run_portfolio.py

Or from project root:
    .venv_win/Scripts/python portfolio_app/run_portfolio.py
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Load .env from project root  (src/ → portfolio_app/ → project root)
_project_root = Path(__file__).resolve().parents[2]
load_dotenv(_project_root / ".env", override=True)

from data import (  # noqa: E402
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
from db import DBConfig  # noqa: E402
from openbb_client import OpenBBClient  # noqa: E402
from stock_analysis import (  # noqa: E402
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

LOG = logging.getLogger("portfolio_app")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

# --------------------------------------------------------------------------- #
#  App
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="Portfolio App",
    description=(
        "Standalone portfolio backend for OpenBB Workspace. "
        "Serves position data from MySQL and proxies to the OpenBB API for market data."
    ),
    version="1.0.0",
)

# CORS origins are environment-driven so localhost/tauri dev entries never
# leak into a public deployment. Set PORTFOLIO_CORS_ORIGINS to a comma-
# separated list to override. The default below is a LOCAL DEV allow-list
# (desktop/Tauri + OpenBB Pro); do NOT use it for a publicly exposed service,
# especially with allow_credentials=True, which would let credentialed
# cross-origin requests come from any listed origin.
_DEFAULT_DEV_ORIGINS = [
    "https://pro.openbb.co",
    "http://pro.openbb.co",
    "http://localhost:1420",
    "https://localhost:1420",
    "http://localhost:3000",
    "https://localhost:3000",
    "http://127.0.0.1:1420",
    "https://127.0.0.1:1420",
    "http://127.0.0.1:6902",
    "https://127.0.0.1:6902",
    "http://127.0.0.1:6903",
    "https://127.0.0.1:6903",
    "tauri://localhost",
]
_cors_env = os.getenv("PORTFOLIO_CORS_ORIGINS", "").strip()
_cors_origins = (
    [o.strip() for o in _cors_env.split(",") if o.strip()]
    if _cors_env
    else _DEFAULT_DEV_ORIGINS
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)

# OpenBB API client (for calling the other service — quotes, fundamentals)
obb_client = OpenBBClient()

# --------------------------------------------------------------------------- #
#  In-process TTL cache for stock analysis data
#  Keyed by (symbol, benchmark, lookback_years) — entries expire after TTL_SEC.
#  This avoids redundant OpenBB API calls when multiple widgets load for the
#  same symbol simultaneously (profile, peers, price history all reused).
# --------------------------------------------------------------------------- #
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Tuple

_CACHE_TTL_SEC = 300  # 5 minutes — matches Workspace default staleTime

@dataclass
class _CacheEntry:
    data: Any
    ts: float = field(default_factory=time.monotonic)

    def is_fresh(self, ttl: float = _CACHE_TTL_SEC) -> bool:
        return (time.monotonic() - self.ts) < ttl

_stock_cache: dict[Tuple, _CacheEntry] = {}
_cache_lock = asyncio.Lock()


async def _cached(key: Tuple, coro_factory, ttl: float = _CACHE_TTL_SEC):
    """Return cached result for *key* or await coro_factory() and cache it."""
    async with _cache_lock:
        entry = _stock_cache.get(key)
        if entry and entry.is_fresh(ttl):
            return entry.data
    result = await coro_factory()
    async with _cache_lock:
        _stock_cache[key] = _CacheEntry(data=result)
    return result


# --------------------------------------------------------------------------- #
#  Metadata endpoints (required by OpenBB Workspace)
# --------------------------------------------------------------------------- #

@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse(content={"status": "ok", "name": "Portfolio App"})


@app.get("/widgets.json", include_in_schema=False)
async def get_widgets():
    p = Path(__file__).resolve().parent.parent / "widgets.json"
    with open(p, encoding="utf-8") as f:
        return JSONResponse(content=json.load(f))


@app.get("/apps.json", include_in_schema=False)
async def get_apps():
    p = Path(__file__).resolve().parent.parent / "apps.json"
    with open(p, encoding="utf-8") as f:
        return JSONResponse(content=json.load(f))


# --------------------------------------------------------------------------- #
#  Option-list helpers (for widget dropdowns)
# --------------------------------------------------------------------------- #

@app.get("/get_symbols", include_in_schema=False)
async def get_symbols():
    return get_distinct_symbols()


@app.get("/get_accounts", include_in_schema=False)
async def get_accounts():
    return get_distinct_accounts()


@app.get("/get_owners", include_in_schema=False)
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

# ── 1. Positions detail ──────────────────────────────────────────────────── #

@app.get("/portfolio/positions")
async def portfolio_positions(
    account: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
    owner: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
    snapshot_date: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
):
    """Blocked: raw lot-level positions cannot be served via API."""
    _raw_positions_blocked()


# ── 2. Summary by symbol ─────────────────────────────────────────────────── #

@app.get("/portfolio/summary")
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


# ── 3. Account allocation ────────────────────────────────────────────────── #

@app.get("/portfolio/allocation")
async def portfolio_allocation(
    owner: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
):
    """Blocked: account allocation requires raw position metadata."""
    _raw_positions_blocked()


# ── 4. Cost basis lots ───────────────────────────────────────────────────── #

@app.get("/portfolio/cost_basis")
async def portfolio_cost_basis(
    symbol: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
    account: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
):
    """Blocked: lot-level cost basis cannot be served via API."""
    _raw_positions_blocked()


# ── 5. Tax summary ───────────────────────────────────────────────────────── #

@app.get("/portfolio/tax_summary")
async def portfolio_tax_summary(
    owner: Optional[str] = Query(None, description="Unused; raw endpoint disabled"),
):
    """Blocked: tax summary endpoint uses raw lots and is disabled."""
    _raw_positions_blocked()


# ── 6. Performance (top gainers/losers) ───────────────────────────────────── #

@app.get("/portfolio/performance")
async def portfolio_performance(
    snapshot_date: Optional[str] = Query(None, description="Filter by snapshot date (YYYY-MM-DD)"),
):
    """Symbol performance ranking from sanitized basket data."""
    df = get_portfolio_basket_df(snapshot_date=snapshot_date)
    if df.empty:
        return []
    result = df.sort_values("pct_return", ascending=False).reset_index(drop=True)
    return df_to_records(result)


# ── 7. Snapshot history (for trendlines) ──────────────────────────────────── #

@app.get("/portfolio/snapshots")
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


# ── 8. ESPP purchases ────────────────────────────────────────────────────── #

@app.get("/espp/purchases")
async def espp_purchases():
    """ESPP purchase history with discount and tax analysis."""
    return df_to_records(get_espp_df())


# ── 9. Equity historical prices (from cache DB) ──────────────────────────── #

@app.get("/equity/historical")
async def equity_historical(
    symbol: str = Query("MSFT", description="Ticker symbol"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
):
    """Historical daily equity prices from the cache database."""
    return df_to_records(get_equity_historical_df(symbol, start_date, end_date))


# ── 10. Market data from OpenBB API (proxy) ──────────────────────────────── #

@app.get("/market/quote")
async def market_quote(
    symbol: str = Query("MSFT", description="Ticker symbol"),
    provider: Optional[str] = Query(None, description="Data provider (e.g. fmp, yfinance)"),
):
    """Get a live equity quote by proxying to the OpenBB Platform API."""
    if provider:
        data = await obb_client.get(
            "/api/v1/equity/price/quote",
            symbol=symbol,
            provider=provider,
        )
    else:
        data = await obb_client.get("/api/v1/equity/price/quote", symbol=symbol)
    if data is None:
        return JSONResponse(
            status_code=502,
            content={"error": "OpenBB API not available or no data provider configured."},
        )
    return data


@app.get("/market/historical")
async def market_historical(
    symbol: str = Query("MSFT", description="Ticker symbol"),
    start_date: Optional[str] = Query(None, description="Start date"),
    end_date: Optional[str] = Query(None, description="End date"),
    provider: Optional[str] = Query(None, description="Data provider (e.g. fmp, yfinance)"),
):
    """Get historical prices by proxying to the OpenBB Platform API."""
    request_kwargs: dict[str, str] = {"symbol": symbol}
    if start_date:
        request_kwargs["start_date"] = start_date
    if end_date:
        request_kwargs["end_date"] = end_date
    if provider:
        request_kwargs["provider"] = provider

    data = await obb_client.get("/api/v1/equity/price/historical", **request_kwargs)
    if data is None:
        return JSONResponse(
            status_code=502,
            content={"error": "OpenBB API not available or no data provider configured."},
        )
    return data


# --------------------------------------------------------------------------- #
#  Single-Stock Analysis Endpoints  (Phase 1-7)
# --------------------------------------------------------------------------- #

_PROVIDER = "fmp_cached"  # primary; OpenBB falls back automatically on cache miss

# Format-map keys → how to display each KPI value as a readable string
# "pct"   → e.g. 0.307  → "30.7%"
# "x"     → e.g. 33.95  → "33.95x"
# "num"   → e.g. 1.44   → "1.44"
# "score" → e.g. 3.17   → "3.17 / 5"
_KPI_FMT: dict[str, str] = {
    # Fundamentals
    "Revenue Growth (last)":    "pct",
    "EPS Growth (last)":        "pct",
    "FCF Growth (last)":        "pct",
    "Gross Margin (last)":      "pct",
    "Operating Margin (last)":  "pct",
    "Net Margin (last)":        "pct",
    "ROIC (last)":              "pct",
    "Current Ratio (last)":     "num",
    "Debt/Equity (last)":       "num",
    # Technicals
    "RSI(14)":                  "num",
    "ADX(14)":                  "num",
    "ATR(14)":                  "num",
    "OBV":                      "num",
    "MACD_Signal":              "num",
    "BB_Pct":                   "num",
    # Valuation
    "Price (last)":             "num",
    "EPS (last)":               "num",
    "P/E (last)":               "x",
    "EV/EBITDA (last)":         "x",
    "P/FCF (last)":             "x",
    "P/S (last)":               "x",
    "Earnings Yield (last)":    "pct",
    "WACC (last)":              "pct",
    "Piotroski (last)":         "num",
    "Altman Z (last)":          "num",
    # Risk
    "Sharpe":                   "num",
    "Sortino":                  "num",
    "Jensen Alpha":             "pct",
    "Beta":                     "num",
    "VaR 95%":                  "pct",
    "CVaR 95%":                 "pct",
    "Max Drawdown":             "pct",
    "Ulcer Index":              "pct",
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
        content={"error": "OpenBB API not available or no data returned."},
    )


# --------------------------------------------------------------------------- #
#  Cached data-fetch helpers
#  All heavy OpenBB calls go through these so that when Workspace loads 7
#  widgets simultaneously for the same symbol, the data is fetched once and
#  shared across all of them within the 5-minute TTL.
# --------------------------------------------------------------------------- #

async def _get_profile_data(symbol: str):
    """Fetch profile + quote + peers — cached per symbol."""
    key = ("profile", symbol.upper())
    async def fetch():
        profile_df, quote_df, peers_df = await _gather(
            obb_client.get_df("/api/v1/equity/profile", symbol=symbol, provider=_PROVIDER),
            obb_client.get_df("/api/v1/equity/price/quote", symbol=symbol, provider=_PROVIDER),
            obb_client.get_df("/api/v1/equity/compare/peers", symbol=symbol, provider=_PROVIDER),
        )
        return profile_df, quote_df, peers_df
    return await _cached(key, fetch)


async def _get_fundamental_data(symbol: str, limit: int):
    """Fetch 4 fundamental statement DFs — cached per (symbol, limit)."""
    key = ("fundamentals", symbol.upper(), limit)
    async def fetch():
        return await _gather(
            obb_client.get_df("/api/v1/equity/fundamental/income",  symbol=symbol, period="annual", limit=limit, provider=_PROVIDER, timeout=90.0),
            obb_client.get_df("/api/v1/equity/fundamental/balance", symbol=symbol, period="annual", limit=limit, provider=_PROVIDER, timeout=90.0),
            obb_client.get_df("/api/v1/equity/fundamental/cash",    symbol=symbol, period="annual", limit=limit, provider=_PROVIDER, timeout=90.0),
            obb_client.get_df("/api/v1/equity/fundamental/ratios",  symbol=symbol, period="annual", limit=limit, provider=_PROVIDER, timeout=90.0),
        )
    return await _cached(key, fetch)


async def _get_price_history(symbol: str, benchmark: str, start: str, end: str):
    """Fetch daily price history for symbol + benchmark — cached per key."""
    key = ("price_hist", symbol.upper(), benchmark.upper(), start, end)
    async def fetch():
        return await obb_client.get_df(
            "/api/v1/equity/price/historical",
            symbol=f"{symbol},{benchmark}", start_date=start, end_date=end,
            interval="1d", provider=_PROVIDER,
        )
    return await _cached(key, fetch)


async def _get_universe_history(universe: tuple, start: str, end: str):
    """Fetch daily price history for a peer universe — cached per key."""
    key = ("universe_hist", universe, start, end)
    async def fetch():
        return await obb_client.get_df(
            "/api/v1/equity/price/historical",
            symbol=",".join(universe), start_date=start, end_date=end,
            interval="1d", provider=_PROVIDER, timeout=120.0,
        )
    return await _cached(key, fetch)


# --------------------------------------------------------------------------- #
#  Stock analysis endpoints (Phases 0–7)
# --------------------------------------------------------------------------- #

@app.get("/stock/profile")
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


@app.get("/stock/context")
async def stock_context(
    symbol: str = Query("CLS", description="Ticker symbol"),
):
    """Phase 0 — Lightweight symbol resolver / anchor widget."""
    profile_df, quote_df, peers_df = await _get_profile_data(symbol)
    from stock_analysis import first_available_value, SECTOR_ETF_MAP
    sector = str(first_available_value(profile_df, ["sector", "sector_name"], default="Unknown"))
    peers_raw = build_peer_universe(symbol.upper(), sector, peers_df, "SPY", max_peers=5)
    sector_etfs = SECTOR_ETF_MAP.get(sector, [])
    return [{
        "symbol":      symbol.upper(),
        "sector":      sector,
        "peers":       ", ".join(p for p in peers_raw if p not in (symbol.upper(), "SPY")),
        "sector_etfs": ", ".join(sector_etfs),
        "last_price":  first_available_value(quote_df, ["last_price", "price", "close"], default=None),
    }]


@app.get("/stock/fundamentals")
async def stock_fundamentals(
    symbol: str = Query("CLS", description="Ticker symbol"),
    lookback_years: int = Query(5, description="Years of annual history"),
):
    """Phase 2 — 5-year fundamental KPIs (growth, margins, ROIC, leverage)."""
    limit = max(lookback_years, 2)
    income_df, balance_df, cash_df, ratios_df = await _get_fundamental_data(symbol, limit)
    kpis = compute_fundamental_kpis(income_df, balance_df, cash_df, ratios_df)
    return [{"metric": k, "value": _fmt_kpi(k, v)} for k, v in kpis.items()]


@app.get("/stock/technicals")
async def stock_technicals(
    symbol: str = Query("CLS", description="Ticker symbol"),
    lookback_years: int = Query(1, description="Years of daily history"),
):
    """Phase 3 — Technical indicators (RSI, ADX, ATR, OBV, MACD, Bollinger %)."""
    import pandas as pd
    today = pd.Timestamp.today().normalize()
    start = (today - pd.DateOffset(years=lookback_years)).strftime("%Y-%m-%d")
    end   = today.strftime("%Y-%m-%d")
    # Reuse cached price history (benchmark SPY always fetched alongside)
    hist_df = await _get_price_history(symbol, "SPY", start, end)
    price_df = (
        hist_df[hist_df["symbol"].astype(str).str.upper() == symbol.upper()].copy()
        if not hist_df.empty and "symbol" in hist_df.columns else hist_df.copy()
    )
    kpis = compute_technical_kpis(price_df)
    return [{"indicator": k, "value": _fmt_kpi(k, v)} for k, v in kpis.items()]


@app.get("/stock/valuation")
async def stock_valuation(
    symbol: str = Query("CLS", description="Ticker symbol"),
    lookback_years: int = Query(5, description="Years of annual history"),
):
    """Phase 4 — Valuation ratios (P/E, EV/EBITDA, P/FCF, P/S, Earnings Yield)."""
    limit = max(lookback_years, 1)
    # Reuse cached fundamentals + profile quote
    (income_df, balance_df, cash_df, ratios_df), (_, quote_df, _) = await _gather(
        _get_fundamental_data(symbol, limit),
        _get_profile_data(symbol),
    )
    kpis = compute_valuation_kpis(ratios_df, quote_df, income_df)
    return [{"metric": k, "value": _fmt_kpi(k, v)} for k, v in kpis.items()]


@app.get("/stock/risk")
async def stock_risk(
    symbol: str = Query("CLS", description="Ticker symbol"),
    benchmark: str = Query("SPY", description="Benchmark ticker"),
    lookback_years: int = Query(1, description="Years of daily history"),
    risk_free_rate: float = Query(0.02, description="Annual risk-free rate (decimal)"),
):
    """Phase 5 — Risk metrics (Sharpe, Sortino, Beta, Alpha, VaR, CVaR, Max DD, Ulcer)."""
    import pandas as pd
    today = pd.Timestamp.today().normalize()
    start = (today - pd.DateOffset(years=lookback_years)).strftime("%Y-%m-%d")
    end   = today.strftime("%Y-%m-%d")
    hist_df = await _get_price_history(symbol, benchmark, start, end)
    asset_close  = _extract_close_series(hist_df, symbol)
    bench_close  = _extract_close_series(hist_df, benchmark)
    kpis = compute_risk_kpis(asset_close.pct_change().dropna(), bench_close.pct_change().dropna(), risk_free_rate)
    return [{"metric": k, "value": _fmt_kpi(k, v)} for k, v in kpis.items()]


@app.get("/stock/relative")
async def stock_relative(
    symbol: str = Query("CLS", description="Ticker symbol"),
    benchmark: str = Query("SPY", description="Benchmark ticker"),
    lookback_years: int = Query(1, description="Years of daily history"),
    risk_free_rate: float = Query(0.02, description="Annual risk-free rate (decimal)"),
):
    """Phase 6 — Peer-relative return / risk comparison table."""
    import pandas as pd
    today = pd.Timestamp.today().normalize()
    start = (today - pd.DateOffset(years=lookback_years)).strftime("%Y-%m-%d")
    end   = today.strftime("%Y-%m-%d")

    profile_df, _, peers_df = await _get_profile_data(symbol)
    sector   = first_available_value(profile_df, ["sector", "sector_name"], default="Unknown")
    universe = tuple(build_peer_universe(symbol.upper(), str(sector), peers_df, benchmark, max_peers=5))

    hist_df     = await _get_universe_history(universe, start, end)
    close_matrix = build_close_matrix(hist_df)
    rel_table    = compute_relative_table(close_matrix, risk_free_rate=risk_free_rate)

    if rel_table.empty:
        return []
    df_out  = rel_table.reset_index()
    idx_col = df_out.columns[0]
    if idx_col != "symbol":
        df_out = df_out.rename(columns={idx_col: "symbol"})
    return df_out.to_dict(orient="records")


@app.get("/stock/decision")
async def stock_decision(
    symbol: str = Query("CLS", description="Ticker symbol"),
    benchmark: str = Query("SPY", description="Benchmark ticker"),
    lookback_years: int = Query(1, description="Years for technicals/risk"),
    lookback_years_fundamentals: int = Query(5, description="Years for fundamentals"),
    risk_free_rate: float = Query(0.02, description="Annual risk-free rate (decimal)"),
):
    """Phase 7 — Composite decision score across all 6 dimensions."""
    import pandas as pd
    today = pd.Timestamp.today().normalize()
    start_tech = (today - pd.DateOffset(years=lookback_years)).strftime("%Y-%m-%d")
    start_fund = (today - pd.DateOffset(years=lookback_years_fundamentals)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    fund_limit = max(lookback_years_fundamentals, 2)

    # ── Fetch all data in parallel via cache helpers ────────────────────────
    (profile_df, quote_df, peers_df), (income_df, balance_df, cash_df, ratios_df), price_df = await _gather(
        _get_profile_data(symbol),
        _get_fundamental_data(symbol, fund_limit),
        _get_price_history(symbol, benchmark, start_tech, end),
    )

    # ── Phase 1 summary ─────────────────────────────────────────────────────
    phase1 = build_phase1_summary(symbol.upper(), profile_df, quote_df, peers_df)

    # ── Phase 2 KPIs ────────────────────────────────────────────────────────
    fund_kpis = compute_fundamental_kpis(income_df, balance_df, cash_df, ratios_df)

    # ── Phase 3 KPIs ────────────────────────────────────────────────────────
    sym_price_df = (
        price_df[price_df["symbol"].astype(str).str.upper() == symbol.upper()].copy()
        if not price_df.empty and "symbol" in price_df.columns
        else price_df.copy()
    )
    tech_kpis = compute_technical_kpis(sym_price_df)

    # ── Phase 4 KPIs ────────────────────────────────────────────────────────
    val_kpis = compute_valuation_kpis(ratios_df, quote_df, income_df)

    # ── Phase 5 KPIs ────────────────────────────────────────────────────────
    asset_close = _extract_close_series(price_df, symbol)
    bench_close = _extract_close_series(price_df, benchmark)
    risk_kpis = compute_risk_kpis(
        asset_close.pct_change().dropna(),
        bench_close.pct_change().dropna(),
        risk_free_rate,
    )

    # ── Phase 6 relative table ──────────────────────────────────────────────
    sector = first_available_value(profile_df, ["sector", "sector_name"], default="Unknown")
    universe = tuple(build_peer_universe(symbol.upper(), str(sector), peers_df, benchmark, max_peers=5))

    hist_df = await _get_universe_history(universe, start_tech, end)
    close_matrix = build_close_matrix(hist_df)
    rel_table = compute_relative_table(close_matrix, risk_free_rate=risk_free_rate)

    # ── Phase 7 decision ────────────────────────────────────────────────────
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


async def _gather(*coros):
    """Await multiple coroutines concurrently."""
    import asyncio
    return await asyncio.gather(*coros)


# --------------------------------------------------------------------------- #
#  Health
# --------------------------------------------------------------------------- #

@app.get("/health", include_in_schema=False)
async def health():
    """Health check — reports DB connectivity and OpenBB API reachability."""
    db_ok = check_db()
    obb_ok = await obb_client.health()

    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "database_name": DBConfig().database,
        "openbb_api": obb_ok,
        "openbb_api_url": obb_client.base_url,
    }
