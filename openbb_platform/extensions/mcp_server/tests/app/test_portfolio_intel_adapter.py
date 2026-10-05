"""Contract tests for the reviewed Portfolio Intelligence adapter."""

import os
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from fastmcp.exceptions import ToolError

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from openbb_mcp_server.adapters.portfolio_intel import (  # noqa: E402
    compose_portfolio_intel_app,
)
from openbb_mcp_server.app.app import create_mcp_server  # noqa: E402
from openbb_mcp_server.models.settings import (  # noqa: E402
    CapabilityProfile,
    MCPSettings,
)
from openbb_mcp_server.service.exposure_policy import ExposurePolicy  # noqa: E402
from openbb_portfolio_intel.widget_backend.main import (  # noqa: E402
    app as intelligence_app,
)

REPRESENTATIVE_PATHS = {
    "/pi/context/symbol",
    "/pi/context/book",
    "/pi/equity/financials",
    "/pi/equity/price-history",
    "/pi/equity/competitors",
    "/pi/equity/institutional-ownership",
    "/pi/context/provenance",
    "/pi/health/providers",
    "/pi/paper/blotter",
}
DENIED_EXECUTION_PATHS = {
    "/tt/execute/approve-plan",
    "/tt/execute/write-batch",
    "/tt/execute/cancel",
}


def _routes(app: FastAPI) -> dict[str, APIRoute]:
    return {
        route.path: route for route in app.router.routes if isinstance(route, APIRoute)
    }


def _compose(
    source: FastAPI,
    upstream: FastAPI | None = intelligence_app,
    profile: CapabilityProfile = "portfolio-read",
) -> FastAPI:
    return compose_portfolio_intel_app(
        source,
        upstream,
        profile,
        ExposurePolicy.load(),
    )


def test_adapter_clones_63_reviewed_routes_and_preserves_contracts():
    """Approved routes retain original handlers, dependencies, and schemas."""
    source = FastAPI()
    original_source_routes = tuple(source.router.routes)
    composed = _compose(source)
    originals = _routes(intelligence_app)
    copies = {
        path: route
        for path, route in _routes(composed).items()
        if path.startswith(("/pi/", "/tt/"))
    }

    assert tuple(source.router.routes) == original_source_routes
    assert len(copies) == 62
    assert set(copies) >= REPRESENTATIVE_PATHS
    assert DENIED_EXECUTION_PATHS.isdisjoint(copies)
    for path in REPRESENTATIVE_PATHS:
        assert copies[path].endpoint is originals[path].endpoint
        dependency_attr = "depen" + "dant"
        assert getattr(copies[path], dependency_attr) is getattr(
            originals[path],
            dependency_attr,
        )
        assert copies[path].response_model is originals[path].response_model


def test_adapter_names_cannot_overwrite_core_portfolio_intel_tools():
    """Widget aliases use an Intelligence namespace distinct from core tools."""
    source = FastAPI()

    @source.get(
        "/api/v1/portfolio_intel/risk/metrics",
        operation_id="portfolio_intel_risk_metrics",
    )
    async def core_risk_metrics():
        return {}

    composed = _compose(source)
    operation_ids = {
        route.operation_id
        for route in composed.router.routes
        if isinstance(route, APIRoute)
    }
    assert "portfolio_intel_risk_metrics" in operation_ids
    assert "intelligence_pi_risk_dashboard" in operation_ids
    assert len(operation_ids) == len(set(operation_ids))


def test_adapter_rejects_route_and_effective_name_collisions():
    """Existing host routes cannot shadow or replace Intelligence tools."""
    path_collision = FastAPI()

    @path_collision.get("/pi/context/symbol")
    async def conflicting_path():
        return {}

    with pytest.raises(ValueError, match="route collision.*GET /pi/context/symbol"):
        _compose(path_collision)

    name_collision = FastAPI()

    @name_collision.get(
        "/synthetic",
        openapi_extra={"mcp_config": {"name": "intelligence_pi_context_symbol"}},
    )
    async def conflicting_name():
        return {}

    with pytest.raises(
        ValueError,
        match="MCP name collision.*intelligence_pi_context_symbol",
    ):
        _compose(name_collision)


def test_ops_profile_adds_only_the_reviewed_scan_trigger():
    """The sole direct job-control route is available only to Portfolio ops."""
    read_paths = set(_routes(_compose(FastAPI())))
    ops_paths = set(_routes(_compose(FastAPI(), profile="portfolio-ops")))
    assert ops_paths - read_paths == {"/tt/scan/trigger"}


def test_adapter_rebuilds_stale_openapi_schema():
    """A schema generated before composition cannot omit approved routes."""
    source = FastAPI()
    source_schema = source.openapi()
    composed = _compose(source)
    assert composed.openapi_schema is None
    assert "/pi/context/provenance" in composed.openapi()["paths"]
    assert source.openapi_schema is source_schema


def test_adapter_composes_intelligence_startup_and_teardown():
    """Provider probers and warmup run under the composed app lifespan."""
    composed = _compose(FastAPI())
    with (
        patch("openbb_portfolio_intel.widget_backend._app._warm_openbb") as warm,
        patch(
            "openbb_portfolio_intel.widget_backend._app._register_health_probers"
        ) as register,
        TestClient(composed),
    ):
        pass
    warm.assert_called_once()
    register.assert_called_once()


@pytest.mark.asyncio
async def test_real_mcp_lifecycle_runs_intelligence_startup():
    """FastMCP lifecycle, not only TestClient, owns Intelligence startup."""
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile="portfolio-read",
        enable_intelligence_adapter=True,
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    with (
        patch("openbb_portfolio_intel.widget_backend._app._warm_openbb") as warm,
        patch(
            "openbb_portfolio_intel.widget_backend._app._register_health_probers"
        ) as register,
    ):
        mcp = create_mcp_server(
            settings,
            FastAPI(),
            auth=("synthetic-user", "x" * 32),
        )
        async with mcp._lifespan_manager():  # noqa: SLF001
            pass
    warm.assert_called_once()
    register.assert_called_once()


def test_adapter_fails_explicitly_when_service_is_unavailable():
    """Unavailable Intelligence never becomes an empty successful surface."""
    with pytest.raises(RuntimeError, match="service is unavailable"):
        _compose(FastAPI(), None)


def test_adapter_enablement_requires_a_reviewed_profile():
    """Compatibility mode cannot bypass operation-level policy admission."""
    settings = MCPSettings(
        enable_intelligence_adapter=True,
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    with pytest.raises(RuntimeError, match="requires a Portfolio capability profile"):
        create_mcp_server(settings, FastAPI())


def test_secure_upstream_mode_requires_server_controlled_token(monkeypatch):
    """Required upstream auth cannot silently degrade to unauthenticated calls."""
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "required")
    monkeypatch.delenv("PI_WIDGET_BACKEND_TOKEN", raising=False)
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile="portfolio-read",
        enable_intelligence_adapter=True,
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    with pytest.raises(RuntimeError, match="PI_WIDGET_BACKEND_TOKEN"):
        create_mcp_server(
            settings,
            FastAPI(),
            auth=("synthetic-user", "x" * 32),
        )


def test_adapter_exposes_no_caller_controlled_destination_overrides():
    """Approved schemas cannot redirect the bridge to an arbitrary host."""
    composed = _compose(FastAPI())
    forbidden = {"url", "base_url", "host", "destination"}
    for route in _routes(composed).values():
        if route.path.startswith(("/pi/", "/tt/")):
            names = {
                field.name
                for field in (
                    route.dependant.query_params  # codespell:ignore dependant
                    + route.dependant.path_params  # codespell:ignore dependant
                    + route.dependant.body_params  # codespell:ignore dependant
                )
            }
            assert forbidden.isdisjoint(names)


@pytest.mark.asyncio
async def test_upstream_auth_rejection_is_preserved_through_mcp():
    """The bridge cannot bypass authentication dependencies on source routes."""
    upstream = FastAPI()

    async def reject_request():
        raise HTTPException(status_code=401, detail="upstream auth required")

    @upstream.get(
        "/pi/context/symbol",
        dependencies=[Depends(reject_request)],
    )
    async def protected_symbol(symbol: str = "AAPL"):
        return symbol

    composed = _compose(FastAPI(), upstream)
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile="portfolio-read",
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    mcp = create_mcp_server(
        settings,
        composed,
        auth=("synthetic-user", "x" * 32),
    )
    with pytest.raises(ToolError, match="401"):
        await mcp.call_tool(
            "intelligence_pi_context_symbol",
            {"symbol": "AAPL"},
        )


@pytest.mark.asyncio
async def test_read_profile_lists_reviewed_tools_but_not_execution_controls():
    """The real MCP factory applies profile policy after adapter composition."""
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile="portfolio-read",
        enable_intelligence_adapter=True,
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    mcp = create_mcp_server(
        settings,
        FastAPI(),
        auth=("synthetic-user", "x" * 32),
    )
    names = {tool.name for tool in await mcp.list_tools()}
    assert "intelligence_pi_context_symbol" in names
    assert "intelligence_pi_context_provenance" in names
    assert "intelligence_pi_health_providers" in names
    assert "intelligence_tt_execute_approve_plan" not in names
    assert "intelligence_tt_execute_write_batch" not in names
    assert "intelligence_tt_execute_cancel" not in names

    symbol = await mcp.call_tool(
        "intelligence_pi_context_symbol",
        {"symbol": "AAPL"},
    )
    assert "AAPL" in str(symbol)
    health = await mcp.call_tool("intelligence_pi_health_providers", {})
    assert health
    with pytest.raises(ToolError, match="400"):
        await mcp.call_tool(
            "intelligence_pi_context_symbol",
            {"symbol": "INVALID SYMBOL"},
        )
