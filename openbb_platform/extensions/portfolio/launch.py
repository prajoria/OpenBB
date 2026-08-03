r"""
OpenBB Portfolio Extension — Entry Script.

This script imports the standard OpenBB Platform FastAPI application
and includes the Portfolio extension's APIRouter, registering all
portfolio, stock-analysis, and ESPP widget endpoints alongside the
existing /api/v1/* market-data routes.

Usage:
    openbb-api --app openbb_platform/extensions/portfolio/launch.py

With HTTPS (recommended for OpenBB Workspace):
    openbb-api --app openbb_platform/extensions/portfolio/launch.py \\
      --ssl_certfile portfolio_app/cert.pem \\
      --ssl_keyfile  portfolio_app/key.pem \\
      --port 6902

What this does:
    1. Imports the OpenBB Platform FastAPI app (all /api/v1/* routes)
    2. Includes the portfolio APIRouter (all /portfolio/*, /stock/*, /espp/* routes)
    3. The openbb_platform_api launcher detects /portfolio/widgets.json and
       /portfolio/apps.json and merges them into the root /widgets.json and
       /apps.json automatically — no manual configuration required.

Result:
    One service at https://127.0.0.1:6902 serves:
      - /api/v1/*          OpenBB Platform market data
      - /portfolio/*       Portfolio widget endpoints
      - /stock/*           Single-stock analysis endpoints
      - /espp/*            ESPP tracking endpoints
      - /equity/historical Cached OHLCV history
      - /market/*          OpenBB SDK proxy endpoints
      - /widgets.json      Merged (platform + portfolio widgets)
      - /apps.json         Merged (default + Portfolio Overview app)
"""

# This is an entry/launcher script: ``load_dotenv`` must run before the platform
# app is imported (the app reads env vars at import time), so imports are
# intentionally not all at module top. The E402 noqa markers below document the
# same intent for ruff; the disable here is the pylint equivalent.
# pylint: disable=wrong-import-position,wrong-import-order

from pathlib import Path

# Load .env from project root (extension/ → extensions/ → openbb_platform/ → project root)
_project_root = Path(__file__).resolve().parents[3]
try:
    from dotenv import load_dotenv

    load_dotenv(_project_root / ".env", override=False)
except ImportError:
    pass  # python-dotenv optional if env vars set another way

# Import the standard OpenBB Platform FastAPI application
from openbb_core.api.rest_api import app  # noqa: E402

# Import and include the portfolio router
from openbb_portfolio.portfolio_router import router  # noqa: E402

app.include_router(router)

# Include the custom-copilot backend (#1794): /agents.json + /query, streaming
# answers from the local copilot-api proxy on :4141. Mounted here so it reuses
# this backend's already-trusted cert and CORS origin.
from openbb_portfolio.copilot import router as copilot_router  # noqa: E402

app.include_router(copilot_router)

# Add root endpoints for widgets.json and apps.json (for pro.openbb.co integration)
import json  # noqa: E402

from fastapi.responses import JSONResponse  # noqa: E402


@app.get("/widgets.json", include_in_schema=False)
async def root_widgets():
    """Serve portfolio widgets.json at root for pro.openbb.co integration."""
    assets_dir = Path(__file__).resolve().parent / "assets"
    widgets_file = assets_dir / "widgets.json"
    with open(widgets_file, encoding="utf-8") as f:
        return JSONResponse(content=json.load(f))


@app.get("/apps.json", include_in_schema=False)
async def root_apps():
    """Serve portfolio apps.json at root for pro.openbb.co integration."""
    assets_dir = Path(__file__).resolve().parent / "assets"
    apps_file = assets_dir / "apps.json"
    with open(apps_file, encoding="utf-8") as f:
        return JSONResponse(content=json.load(f))


# `app` is the name detected by the openbb-api launcher (default name = "app")
