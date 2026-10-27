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


def _schema_value(name: str, schema: dict):
    """Synthesize a schema-valid argument for a required tool parameter."""
    if name in _VALUES:
        return _VALUES[name]
    if "date" in name:
        return "2025-01-02"
    samples = {"string": "AAPL", "integer": 1, "number": 1.0, "boolean": False}
    for option in schema.get("anyOf") or [schema]:
        if "enum" in option:
            return option["enum"][0]
        if option.get("type") in samples:
            return samples[option["type"]]
    return "AAPL"


@pytest.mark.asyncio
async def test_every_legacy_fmp_cached_mapping_is_callable_through_mcp():
    """The 70 pre-existing Platform mappings also invoke through MCP (#2302).

    Together with the provider-owned routes above, this gives offline MCP
    invocation evidence for every registered FMP Cached model.
    """
    # pylint: disable=import-outside-toplevel
    from fastapi.routing import APIRoute
    from openbb_core.api.rest_api import app as platform_app
    from openbb_fmp_cached import fmp_cached_provider

    registered = set(fmp_cached_provider.fetcher_dict)
    legacy = {
        route.path: route
        for route in platform_app.routes
        if isinstance(route, APIRoute)
        and route.openapi_extra
        and route.openapi_extra.get("model") in registered
        and not route.path.startswith("/api/v1/fmp_cached/")
    }
    assert len(legacy) == len({r.openapi_extra["model"] for r in legacy.values()})
    assert len(legacy) == 70

    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile="portfolio-read",
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    mcp = create_mcp_server(settings, platform_app, auth=("synthetic-user", "x" * 32))
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    for path, route in sorted(legacy.items()):
        name = path.removeprefix("/api/v1/").replace("/", "_")
        assert name in tools, f"{path} is not listed as {name}"
        schema = tools[name].parameters or {}
        properties = schema.get("properties", {})
        provider = properties.get("provider", {})
        choices = {
            choice
            for option in provider.get("anyOf") or [provider]
            for choice in option.get("enum", ())
        }
        assert "fmp_cached" in choices, f"{name} does not offer fmp_cached"
        arguments = {"provider": "fmp_cached"}
        for required in schema.get("required", []):
            if required != "provider":
                arguments[required] = _schema_value(
                    required, properties.get(required, {})
                )
        module = importlib.import_module(route.endpoint.__module__)
        # results=None: an empty list cannot satisfy provider-discriminated
        # response unions (for example the earnings-call transcript model).
        response = module.OBBject(results=None, provider="fmp_cached")
        with (
            patch.object(module, "Query", return_value=object()),
            patch.object(
                module.OBBject,
                "from_query",
                new=AsyncMock(return_value=response),
            ) as from_query,
        ):
            assert await mcp.call_tool(name, arguments)
        assert from_query.await_count == 1, f"{name} did not reach its handler"
