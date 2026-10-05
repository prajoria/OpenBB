"""Discovery and invocation exposure-policy enforcement tests."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastmcp.server.middleware import MiddlewareContext
from openbb_mcp_server.app.app import create_mcp_server
from openbb_mcp_server.models.settings import MCPSettings
from openbb_mcp_server.service.exposure_enforcement import (
    ExposureEnforcementMiddleware,
)


def policy_app(calls: dict[str, int]) -> FastAPI:
    """Build reviewed allowed and denied operation identities."""
    app = FastAPI()

    def denied_get():
        calls["denied"] += 1
        return {"denied": False}

    def analytical_post():
        calls["allowed"] += 1
        return {"result": "ok"}

    app.add_api_route(
        "/api/v1/uscongress/bill_info",
        denied_get,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/v1/backtest/run",
        analytical_post,
        methods=["POST"],
    )
    return app


def policy_settings(**changes) -> MCPSettings:
    """Return a minimal explicit profile configuration."""
    values = {
        "api_prefix": "/api/v1",
        "capability_profile": "platform-standard",
        "default_tool_categories": ["all"],
        "default_skills_dir": None,
    }
    values.update(changes)
    return MCPSettings(**values)


@pytest.mark.asyncio
async def test_policy_filters_discovery_and_allows_analytical_post():
    """Denied GET fetches are hidden while approved POST analytics remain."""
    calls = {"denied": 0, "allowed": 0}
    app = policy_app(calls)
    original_routes = tuple(app.router.routes)
    mcp = create_mcp_server(policy_settings(), app)
    names = {tool.name for tool in await mcp.list_tools()}
    assert "backtest_run" in names
    assert "uscongress_bill_info" not in names
    result = await mcp.call_tool("backtest_run", {})
    assert result
    assert calls == {"denied": 0, "allowed": 1}
    assert tuple(app.router.routes) == original_routes


@pytest.mark.asyncio
async def test_direct_call_and_activation_cannot_elevate_denied_tool():
    """Visibility activation cannot bypass invocation middleware."""
    calls = {"denied": 0, "allowed": 0}
    mcp = create_mcp_server(
        policy_settings(enable_tool_discovery=True),
        policy_app(calls),
    )
    mcp.enable(names={"uscongress_bill_info"})
    with pytest.raises(PermissionError, match="denied"):
        await mcp.call_tool("uscongress_bill_info", {})
    assert calls["denied"] == 0


@pytest.mark.asyncio
async def test_compatibility_mode_preserves_existing_surface():
    """No selected profile retains current discovery/invocation behavior."""
    calls = {"denied": 0, "allowed": 0}
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile=None,
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    mcp = create_mcp_server(settings, policy_app(calls))
    names = {tool.name for tool in await mcp.list_tools()}
    assert {"backtest_run", "uscongress_bill_info"} <= names


@pytest.mark.asyncio
async def test_middleware_rejects_unknown_name_before_call_next():
    """Invocation denial is independent of component visibility."""
    middleware = ExposureEnforcementMiddleware(frozenset({"allowed"}))
    called = False

    async def call_next(_context):
        nonlocal called
        called = True
        return SimpleNamespace()

    context = MiddlewareContext(
        message=SimpleNamespace(name="denied"),
        method="tools/call",
    )
    with pytest.raises(PermissionError, match="denied"):
        await middleware.on_call_tool(context, call_next)
    assert called is False


@pytest.mark.asyncio
async def test_denied_route_cannot_bypass_policy_as_resource():
    """Native resource discovery and reads enforce the same operation policy."""
    calls = {"denied": 0}
    app = FastAPI()

    def denied_resource():
        calls["denied"] += 1
        return {"secret": True}

    app.add_api_route(
        "/api/v1/uscongress/bill_info",
        denied_resource,
        methods=["GET"],
        openapi_extra={"mcp_config": {"mcp_type": "resource"}},
    )
    mcp = create_mcp_server(policy_settings(), app)
    unfiltered = await mcp.list_resources(run_middleware=False)
    denied_uri = next(
        str(resource.uri) for resource in unfiltered if "bill_info" in str(resource.uri)
    )
    filtered = await mcp.list_resources()
    assert denied_uri not in {str(resource.uri) for resource in filtered}
    with pytest.raises(PermissionError, match="denied"):
        await mcp.read_resource(denied_uri)
    assert calls["denied"] == 0


@pytest.mark.asyncio
async def test_install_skill_requires_filesystem_write_profile():
    """No current profile exposes the unbounded file-writing admin helper."""
    app = FastAPI()
    standard = create_mcp_server(policy_settings(), app)
    standard_names = {tool.name for tool in await standard.list_tools()}
    assert "install_skill" not in standard_names
    ops = create_mcp_server(
        policy_settings(capability_profile="portfolio-ops"),
        FastAPI(),
        auth=("synthetic-user", "x" * 32),
    )
    ops_names = {tool.name for tool in await ops.list_tools()}
    assert "install_skill" not in ops_names
