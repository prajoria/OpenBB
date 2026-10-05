"""Exposure-policy coverage for the complete FMP Cached route manifest."""

import importlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from openbb_fmp_cached.fmp_cached_router import router
from openbb_mcp_server.app.app import create_mcp_server
from openbb_mcp_server.models.settings import MCPSettings

_VALUES = {
    "symbol": "AAPL",
    "symbols": "AAPL,MSFT",
    "cik": "0000320193",
    "query": "Alpha",
    "cusip": "037833100",
    "isin": "US0378331005",
    "name": "Alpha",
    "date": "2025-01-02",
    "sector": "Technology",
    "industry": "Software",
    "year": 2025,
    "period": "FY",
    "exchange": "NASDAQ",
    "indicator": "SMA",
    "period_length": 14,
    "timeframe": "5min",
    "interval": "5min",
    "start_date": "2025-01-02",
    "end_date": "2025-01-03",
    "extended_hours": False,
    "page": 0,
    "limit": 10,
    "senate_id": "A000360",
    "from": "2025-01-01",
    "to": "2025-01-31",
    "sicCode": "3571",
}


def _manifest() -> list[dict]:
    path = (
        Path(__file__).parents[4]
        / "providers"
        / "fmp_cached"
        / "openbb_fmp_cached"
        / "assets"
        / "model_routes.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))["routes"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile",
    ["platform-standard", "portfolio-read", "portfolio-ops"],
)
async def test_every_fmp_cached_tool_is_admitted_by_reviewed_profiles(profile):
    """Exact policy membership admits all provider-owned read tools."""
    app = FastAPI()
    app.include_router(router.api_router, prefix="/api/v1/fmp_cached")
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile=profile,
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    mcp = create_mcp_server(
        settings,
        app,
        auth=("synthetic-user", "x" * 32),
    )
    names = {tool.name for tool in await mcp.list_tools()}
    expected = {f"fmp_cached_{row['command']}" for row in _manifest()}
    assert expected <= names


@pytest.mark.asyncio
async def test_unreviewed_fmp_cached_tool_remains_denied():
    """The admitted route family does not bypass exact operation membership."""
    app = FastAPI()

    @app.get(
        "/api/v1/fmp_cached/future_route",
        operation_id="fmp_cached_future_route",
    )
    async def future_route():
        return {"future": True}

    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile="portfolio-ops",
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    mcp = create_mcp_server(
        settings,
        app,
        auth=("synthetic-user", "x" * 32),
    )
    names = {tool.name for tool in await mcp.list_tools()}
    assert "fmp_cached_future_route" not in names


@pytest.mark.asyncio
async def test_every_provider_owned_tool_is_callable_through_mcp():
    """Every provider-owned operation completes MCP conversion and invocation."""
    app = FastAPI()
    app.include_router(router.api_router, prefix="/api/v1/fmp_cached")
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile="portfolio-read",
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    mcp = create_mcp_server(
        settings,
        app,
        auth=("synthetic-user", "x" * 32),
    )
    routes = {route.path.removeprefix("/"): route for route in router.api_router.routes}
    for row in _manifest():
        route = routes[row["command"]]
        module = importlib.import_module(route.endpoint.__module__)
        response = module.OBBject(
            results=[],
            provider="fmp_cached",
        )
        arguments = {
            "provider": "fmp" if "fmp" in row["providers"] else "fmp_cached",
            "user_settings": {},
            **{name: _VALUES[name] for name in row["arguments"]},
        }
        with (
            patch.object(module, "Query", return_value=object()),
            patch.object(
                module.OBBject,
                "from_query",
                new=AsyncMock(return_value=response),
            ),
        ):
            result = await mcp.call_tool(
                f"fmp_cached_{row['command']}",
                arguments,
            )
        assert result
