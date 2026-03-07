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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
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
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)

# OpenBB API client (for calling the other service — quotes, fundamentals)
obb_client = OpenBBClient()


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
