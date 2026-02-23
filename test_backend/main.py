"""
OpenBB Workspace Custom Backend — Portfolio Dashboard

A FastAPI backend that serves portfolio data widgets for OpenBB Workspace.
Connects to the fmp_cached MySQL database and exposes portfolio positions,
equity price history, ESPP plan data, and cost basis analysis.

Usage:
    uvicorn main:app --host 127.0.0.1 --port 6900 --reload

Then in OpenBB Workspace: Settings → Apps → Connect Backend → http://127.0.0.1:6900
"""

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import logging
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# --- sys.path bootstrap ---
PROJECT_ROOT = Path(__file__).resolve().parents[1]
for sub in [
    "openbb_platform/providers/fmp_cached",
    "openbb_platform/providers/fmp",
    "openbb_platform/core",
    "openbb_platform/platform",
]:
    p = str(PROJECT_ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)
# Add all extensions
ext_root = PROJECT_ROOT / "openbb_platform" / "extensions"
if ext_root.exists():
    for ext_dir in ext_root.iterdir():
        if ext_dir.is_dir():
            p = str(ext_dir)
            if p not in sys.path:
                sys.path.insert(0, p)

os.environ["FMP_CACHE_AUTO_CREATE_DB"] = "false"
os.environ["FMP_CACHE_TEST_MODE"] = "true"

from openbb_fmp_cached.utils.database import DatabaseConfig, ConnectionPool

LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

# Global connection pool
_pool: Optional[ConnectionPool] = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        cfg = DatabaseConfig()
        _pool = ConnectionPool(cfg)
    return _pool

# --------------------------------------------------------------------------- #
#  FastAPI App — includes OBB Platform routes + custom portfolio routes
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="Portfolio Dashboard + OpenBB Platform",
    description="Combined backend: custom portfolio widgets + full OBB platform API.",
    version="0.1.0",
)

# Mount all OpenBB Platform routes (equity, ETF, economy, etc.)
try:
    from openbb_core.api.app_loader import AppLoader
    from openbb_core.api.router.commands import router as router_commands
    from openbb_core.api.router.coverage import router as router_coverage
    from openbb_core.app.service.system_service import SystemService

    _system = SystemService().system_settings
    _prefix = _system.api_settings.prefix  # typically "/api/v1"

    AppLoader.add_routers(
        app=app,
        routers=[router_commands, router_coverage],
        prefix=_prefix,
    )
    AppLoader.add_openapi_tags(app)
    AppLoader.add_exception_handlers(app)
    LOG.info("Mounted %d OBB platform routes under %s", len(router_commands.routes), _prefix)
except Exception as e:
    LOG.warning("Could not mount OBB platform routes: %s", e)
    LOG.warning("Custom portfolio endpoints will still work.")

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
        "http://127.0.0.1:6900",
        "https://127.0.0.1:6900",
        "tauri://localhost",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["X-Backend-Type"],
)

OBB_HEADERS = {"X-Backend-Type": "OpenBB Platform"}

# Detect if loaded via `openbb-api --app` (platform_api adds its own widgets.json)
import inspect as _inspect
_caller_frames = _inspect.stack()
_loaded_via_openbb_api = any(
    "openbb_platform_api" in (f.filename or "") for f in _caller_frames
)
del _caller_frames, _inspect
LOG.info("Loaded via openbb-api: %s", _loaded_via_openbb_api)

# --------------------------------------------------------------------------- #
#  Root endpoint — only in standalone mode
# --------------------------------------------------------------------------- #

if not _loaded_via_openbb_api:
    @app.get("/", include_in_schema=False)
    async def root():
        return JSONResponse(
            content={"status": "ok", "name": "Portfolio Dashboard"},
            headers=OBB_HEADERS,
        )


# --------------------------------------------------------------------------- #
#  Helper: DB query → list[dict]
# --------------------------------------------------------------------------- #

def _query(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a read query and return rows as list of dicts."""
    pool = _get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            # DictCursor returns list[dict] already; convert Decimal/date
            result = []
            for row in rows:
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


# --------------------------------------------------------------------------- #
#  Widgets / Apps JSON
#
#  When running via `openbb-api --app`, the platform_api adds its own
#  /widgets.json and /apps.json endpoints that auto-generate from OpenAPI.
#  These local loaders are only used in standalone mode (direct uvicorn).
# --------------------------------------------------------------------------- #

def _load_widgets() -> dict:
    """Load widgets.json from adjacent file."""
    p = Path(__file__).parent / "widgets.json"
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _load_apps() -> list:
    """Load apps.json from adjacent file."""
    p = Path(__file__).parent / "apps.json"
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# Only register these routes if NOT loaded via openbb-api --app
# (platform_api.main will add its own /widgets.json and /apps.json)
if not _loaded_via_openbb_api:
    @app.get("/widgets.json", include_in_schema=False)
    async def get_widgets():
        return JSONResponse(content=_load_widgets(), headers=OBB_HEADERS)

    @app.get("/apps.json", include_in_schema=False)
    async def get_apps():
        return JSONResponse(content=_load_apps(), headers=OBB_HEADERS)


# --------------------------------------------------------------------------- #
#  Helper endpoints (hidden from schema)
# --------------------------------------------------------------------------- #

@app.get("/get_symbols", include_in_schema=False)
async def get_symbols():
    """Return distinct symbols for autocomplete."""
    rows = _query(
        "SELECT DISTINCT symbol FROM Portfolio_Positions ORDER BY symbol"
    )
    return [
        {"value": r["symbol"], "label": r["symbol"]}
        for r in rows
    ]


@app.get("/get_accounts", include_in_schema=False)
async def get_accounts():
    """Return distinct account names for autocomplete."""
    rows = _query(
        "SELECT DISTINCT account_name FROM Portfolio_Positions ORDER BY account_name"
    )
    return [
        {"value": r["account_name"], "label": r["account_name"]}
        for r in rows
    ]


# --------------------------------------------------------------------------- #
#  Widget Endpoints
# --------------------------------------------------------------------------- #

# ── 1. Portfolio Positions Summary ────────────────────────────────────────── #

@app.get("/portfolio/positions")
async def portfolio_positions(
    account: Optional[str] = Query(None, description="Filter by account name"),
    snapshot_date: Optional[str] = Query(None, description="Filter by snapshot date (YYYY-MM-DD)"),
):
    """Current portfolio positions with gain/loss analysis."""
    sql = """
        SELECT
            pp.account_name,
            ao.owner,
            pp.symbol,
            pp.description,
            pp.quantity,
            pp.avg_cost_basis,
            pp.cost_basis_total,
            pp.current_value,
            pp.total_gain_loss,
            pp.pct_gain_loss,
            pp.term,
            pp.acquired,
            pp.share_source,
            pp.snapshot_date
        FROM Portfolio_Positions pp
        LEFT JOIN Account_Owner ao ON pp.account_name = ao.account_name
        WHERE 1=1
    """
    params = []
    if account:
        sql += " AND pp.account_name = %s"
        params.append(account)
    if snapshot_date:
        sql += " AND DATE(pp.snapshot_date) = %s"
        params.append(snapshot_date)
    else:
        # Default: latest snapshot
        sql += " AND pp.snapshot_date = (SELECT MAX(snapshot_date) FROM Portfolio_Positions)"
    sql += " ORDER BY pp.current_value DESC"
    return _query(sql, tuple(params))


# ── 2. Portfolio Summary by Symbol ───────────────────────────────────────── #

@app.get("/portfolio/summary")
async def portfolio_summary(
    account: Optional[str] = Query(None, description="Filter by account name"),
):
    """Aggregated portfolio summary grouped by symbol."""
    sql = """
        SELECT
            pp.symbol,
            pp.description,
            SUM(pp.quantity) AS total_quantity,
            SUM(pp.cost_basis_total) AS total_cost_basis,
            SUM(pp.current_value) AS total_current_value,
            SUM(pp.total_gain_loss) AS total_gain_loss,
            CASE
                WHEN SUM(pp.cost_basis_total) > 0
                THEN ROUND(SUM(pp.total_gain_loss) / SUM(pp.cost_basis_total) * 100, 2)
                ELSE 0
            END AS pct_return
        FROM Portfolio_Positions pp
        WHERE pp.snapshot_date = (SELECT MAX(snapshot_date) FROM Portfolio_Positions)
    """
    params = []
    if account:
        sql += " AND pp.account_name = %s"
        params.append(account)
    sql += " GROUP BY pp.symbol, pp.description ORDER BY total_current_value DESC"
    return _query(sql, tuple(params))


# ── 3. Account Allocation ────────────────────────────────────────────────── #

@app.get("/portfolio/allocation")
async def portfolio_allocation():
    """Portfolio allocation by account with owner info."""
    sql = """
        SELECT
            pp.account_name,
            ao.owner,
            COUNT(DISTINCT pp.symbol) AS num_symbols,
            SUM(pp.current_value) AS total_value,
            SUM(pp.cost_basis_total) AS total_cost_basis,
            SUM(pp.total_gain_loss) AS total_gain_loss,
            CASE
                WHEN SUM(pp.cost_basis_total) > 0
                THEN ROUND(SUM(pp.total_gain_loss) / SUM(pp.cost_basis_total) * 100, 2)
                ELSE 0
            END AS pct_return
        FROM Portfolio_Positions pp
        LEFT JOIN Account_Owner ao ON pp.account_name = ao.account_name
        WHERE pp.snapshot_date = (SELECT MAX(snapshot_date) FROM Portfolio_Positions)
        GROUP BY pp.account_name, ao.owner
        ORDER BY total_value DESC
    """
    return _query(sql)


# ── 4. Cost Basis Analysis ────────────────────────────────────────────────── #

@app.get("/portfolio/cost_basis")
async def portfolio_cost_basis(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
):
    """Per-lot cost basis detail with short/long-term classification."""
    sql = """
        SELECT
            pp.symbol,
            pp.account_name,
            pp.acquired,
            pp.term,
            pp.quantity,
            pp.avg_cost_basis,
            pp.cost_basis_total,
            pp.current_value,
            pp.total_gain_loss,
            pp.pct_gain_loss,
            pp.share_source,
            pp.grant_date,
            pp.transfer_avail_date
        FROM Portfolio_Positions pp
        WHERE pp.snapshot_date = (SELECT MAX(snapshot_date) FROM Portfolio_Positions)
    """
    params = []
    if symbol:
        sql += " AND pp.symbol = %s"
        params.append(symbol)
    sql += " ORDER BY pp.symbol, pp.acquired"
    return _query(sql, tuple(params))


# ── 5. Equity Historical Prices ──────────────────────────────────────────── #

@app.get("/equity/historical")
async def equity_historical(
    symbol: str = Query("MSFT", description="Ticker symbol"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
):
    """Historical daily equity prices from cache."""
    sql = "SELECT symbol, date, open, high, low, close, volume, change_percent FROM equity_historical WHERE symbol = %s"
    params: list = [symbol]
    if start_date:
        sql += " AND date >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND date <= %s"
        params.append(end_date)
    sql += " ORDER BY date DESC LIMIT 2000"
    return _query(sql, tuple(params))


# ── 6. ESPP Plan ─────────────────────────────────────────────────────────── #

@app.get("/espp/purchases")
async def espp_purchases():
    """ESPP purchase history with discount and tax analysis."""
    sql = """
        SELECT
            purchase_date,
            offering_period_start,
            offering_period_end,
            fmv_offering_start,
            fmv_purchase_date,
            purchase_price,
            purchase_quantity,
            purchase_value,
            discount_pct,
            bargain_element,
            qualified_disposition_date,
            purchase_deposit_to,
            symbol
        FROM ESPP_Plan
        ORDER BY purchase_date DESC
    """
    return _query(sql)


# ── 7. Short-Term vs Long-Term Gain/Loss ──────────────────────────────────── #

@app.get("/portfolio/tax_summary")
async def portfolio_tax_summary():
    """Tax summary: short-term vs long-term gains/losses by account."""
    sql = """
        SELECT
            pp.account_name,
            ao.owner,
            pp.term,
            COUNT(*) AS num_lots,
            SUM(pp.quantity) AS total_quantity,
            SUM(pp.cost_basis_total) AS total_cost_basis,
            SUM(pp.current_value) AS total_current_value,
            SUM(pp.total_gain_loss) AS total_gain_loss,
            CASE
                WHEN SUM(pp.cost_basis_total) > 0
                THEN ROUND(SUM(pp.total_gain_loss) / SUM(pp.cost_basis_total) * 100, 2)
                ELSE 0
            END AS pct_return
        FROM Portfolio_Positions pp
        LEFT JOIN Account_Owner ao ON pp.account_name = ao.account_name
        WHERE pp.snapshot_date = (SELECT MAX(snapshot_date) FROM Portfolio_Positions)
            AND pp.term != ''
        GROUP BY pp.account_name, ao.owner, pp.term
        ORDER BY pp.account_name, pp.term
    """
    return _query(sql)


# ── 8. Portfolio Performance (top gainers/losers) ─────────────────────────── #

@app.get("/portfolio/performance")
async def portfolio_performance():
    """Top gainers and losers by percent return."""
    sql = """
        SELECT
            pp.symbol,
            pp.description,
            SUM(pp.quantity) AS total_quantity,
            SUM(pp.cost_basis_total) AS total_cost_basis,
            SUM(pp.current_value) AS total_current_value,
            SUM(pp.total_gain_loss) AS total_gain_loss,
            CASE
                WHEN SUM(pp.cost_basis_total) > 0
                THEN ROUND(SUM(pp.total_gain_loss) / SUM(pp.cost_basis_total) * 100, 2)
                ELSE 0
            END AS pct_return
        FROM Portfolio_Positions pp
        WHERE pp.snapshot_date = (SELECT MAX(snapshot_date) FROM Portfolio_Positions)
        GROUP BY pp.symbol, pp.description
        HAVING SUM(pp.cost_basis_total) > 0
        ORDER BY pct_return DESC
    """
    return _query(sql)


# ── 9. Market Holidays ───────────────────────────────────────────────────── #

@app.get("/market/holidays")
async def market_holidays(
    year: Optional[int] = Query(None, description="Filter by year"),
):
    """US stock market holidays."""
    sql = "SELECT holiday_date, holiday_name, year FROM market_holidays WHERE market = 'US'"
    params = []
    if year:
        sql += " AND year = %s"
        params.append(year)
    sql += " ORDER BY holiday_date DESC"
    return _query(sql, tuple(params))


# --------------------------------------------------------------------------- #
#  Health check
# --------------------------------------------------------------------------- #

@app.get("/health", include_in_schema=False)
async def health():
    """Basic health check."""
    try:
        rows = _query("SELECT 1 AS ok")
        return {"status": "ok", "database": "openbb_fmp_cache_test"}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)},
        )
