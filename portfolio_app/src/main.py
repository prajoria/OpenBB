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
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Load .env from project root  (src/ → portfolio_app/ → project root)
_project_root = Path(__file__).resolve().parents[2]
load_dotenv(_project_root / ".env", override=True)

from data import (  # noqa: E402
    check_db,
    df_to_records,
    get_all_snapshots_df,
    get_distinct_accounts,
    get_distinct_owners,
    get_distinct_symbols,
    get_equity_historical_df,
    get_espp_df,
    get_latest_prices_df,
    get_positions_df,
)
from openbb_client import OpenBBClient  # noqa: E402
import service  # noqa: E402

import pandas as pd  # noqa: E402

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


def _fetch_latest_prices(symbols: list[str]) -> pd.DataFrame:
    """Fetch latest market prices from the fmp_cached equity_historical table.

    Uses ``get_latest_prices_df()`` which reads the equity_historical cache
    maintained by the ``openbb_fmp_cached`` provider — a direct DB read,
    no HTTP round-trip needed.

    Returns a DataFrame with columns: symbol, close, price_date.
    Returns an empty DataFrame when no data is available, which causes
    ``refresh_market_values`` to keep the original snapshot values.
    """
    if not symbols:
        return pd.DataFrame(columns=["symbol", "close", "price_date"])
    return get_latest_prices_df(symbols)


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

# ── 1. Positions detail ──────────────────────────────────────────────────── #

@app.get("/portfolio/positions")
async def portfolio_positions(
    account: Optional[str] = Query(None, description="Filter by account name"),
    owner: Optional[str] = Query(None, description="Filter by owner"),
    snapshot_date: Optional[str] = Query(None, description="Filter by snapshot date (YYYY-MM-DD)"),
):
    """Current portfolio positions with gain/loss analysis."""
    df = get_positions_df(snapshot_date=snapshot_date)
    symbols = df["symbol"].unique().tolist() if not df.empty else []
    prices = _fetch_latest_prices(symbols)
    df = service.refresh_market_values(df, prices)
    result = service.positions_detail(df, account=account, owner=owner)
    return df_to_records(result)


# ── 2. Summary by symbol ─────────────────────────────────────────────────── #

@app.get("/portfolio/summary")
async def portfolio_summary(
    account: Optional[str] = Query(None, description="Filter by account name"),
    owner: Optional[str] = Query(None, description="Filter by owner"),
):
    """Aggregated portfolio summary grouped by symbol."""
    df = get_positions_df()
    symbols = df["symbol"].unique().tolist() if not df.empty else []
    prices = _fetch_latest_prices(symbols)
    df = service.refresh_market_values(df, prices)
    result = service.summary_by_symbol(df, account=account, owner=owner)
    return df_to_records(result)


# ── 3. Account allocation ────────────────────────────────────────────────── #

@app.get("/portfolio/allocation")
async def portfolio_allocation(
    owner: Optional[str] = Query(None, description="Filter by owner"),
):
    """Portfolio allocation by account with owner info."""
    df = get_positions_df()
    symbols = df["symbol"].unique().tolist() if not df.empty else []
    prices = _fetch_latest_prices(symbols)
    df = service.refresh_market_values(df, prices)
    result = service.allocation_by_account(df, owner=owner)
    return df_to_records(result)


# ── 4. Cost basis lots ───────────────────────────────────────────────────── #

@app.get("/portfolio/cost_basis")
async def portfolio_cost_basis(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    account: Optional[str] = Query(None, description="Filter by account"),
):
    """Per-lot cost basis detail with short/long-term classification."""
    df = get_positions_df()
    symbols = df["symbol"].unique().tolist() if not df.empty else []
    prices = _fetch_latest_prices(symbols)
    df = service.refresh_market_values(df, prices)
    result = service.cost_basis_lots(df, symbol=symbol, account=account)
    return df_to_records(result)


# ── 5. Tax summary ───────────────────────────────────────────────────────── #

@app.get("/portfolio/tax_summary")
async def portfolio_tax_summary(
    owner: Optional[str] = Query(None, description="Filter by owner"),
):
    """Tax summary: short-term vs long-term gains/losses by account."""
    df = get_positions_df()
    symbols = df["symbol"].unique().tolist() if not df.empty else []
    prices = _fetch_latest_prices(symbols)
    df = service.refresh_market_values(df, prices)
    result = service.tax_summary(df, owner=owner)
    return df_to_records(result)


# ── 6. Performance (top gainers/losers) ───────────────────────────────────── #

@app.get("/portfolio/performance")
async def portfolio_performance(
    owner: Optional[str] = Query(None, description="Filter by owner"),
):
    """Top gainers and losers by percent return."""
    df = get_positions_df()
    symbols = df["symbol"].unique().tolist() if not df.empty else []
    prices = _fetch_latest_prices(symbols)
    df = service.refresh_market_values(df, prices)
    result = service.performance_ranking(df, owner=owner)
    return df_to_records(result)


# ── 7. Snapshot history (for trendlines) ──────────────────────────────────── #

@app.get("/portfolio/snapshots")
async def portfolio_snapshots():
    """All available snapshot dates with totals — for building trendlines."""
    df = get_all_snapshots_df()
    result = service.snapshot_totals(df)
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
    params = {"symbol": symbol}
    if provider:
        params["provider"] = provider
    data = await obb_client.get("/api/v1/equity/price/quote", **params)
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
    params = {"symbol": symbol}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if provider:
        params["provider"] = provider
    data = await obb_client.get("/api/v1/equity/price/historical", **params)
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
        "openbb_api": obb_ok,
        "openbb_api_url": obb_client.base_url,
    }
