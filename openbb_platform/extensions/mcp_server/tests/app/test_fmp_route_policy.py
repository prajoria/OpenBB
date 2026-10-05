"""Exposure-policy coverage for the complete FMP Cached route manifest."""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from openbb_fmp_cached.fmp_cached_router import router
from openbb_mcp_server.app.app import create_mcp_server
from openbb_mcp_server.models.settings import MCPSettings


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
    mcp = create_mcp_server(settings, app)
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
    mcp = create_mcp_server(settings, app)
    names = {tool.name for tool in await mcp.list_tools()}
    assert "fmp_cached_future_route" not in names
