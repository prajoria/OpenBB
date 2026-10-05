"""Tests for the profile-gated Portfolio route composition seam."""

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from openbb_mcp_server.adapters.portfolio import compose_portfolio_app
from openbb_mcp_server.app import app as app_module
from openbb_mcp_server.models.settings import MCPSettings
from openbb_portfolio.portfolio_router import router as portfolio_router

APPROVED_PATHS = {
    "/portfolio/positions",
    "/portfolio/summary",
    "/portfolio/allocation",
    "/portfolio/cost_basis",
    "/portfolio/tax_summary",
    "/portfolio/performance",
    "/portfolio/snapshots",
    "/espp/purchases",
    "/equity/historical",
    "/market/quote",
    "/market/historical",
    "/stock/context",
    "/stock/profile",
    "/stock/fundamentals",
    "/stock/technicals",
    "/stock/valuation",
    "/stock/risk",
    "/stock/relative",
    "/stock/decision",
}

EXCLUDED_PATHS = {
    "/portfolio/widgets.json",
    "/portfolio/apps.json",
    "/portfolio/get_symbols",
    "/portfolio/get_accounts",
    "/portfolio/get_owners",
    "/portfolio/health",
    "/widgets.json",
    "/apps.json",
    "/agents.json",
    "/query",
    "/viewer",
}


def _api_routes(app: FastAPI) -> list[APIRoute]:
    return [route for route in app.router.routes if isinstance(route, APIRoute)]


def test_composition_adds_only_approved_business_routes_without_mutating_source():
    """Composition is isolated and excludes UI, manifests, and private helpers."""
    app = FastAPI()

    @app.get("/api/v1/equity/quote", operation_id="equity_quote")
    async def equity_quote():
        return {"symbol": "SYNTH"}

    app.include_router(portfolio_router)

    @app.get("/widgets.json")
    async def widgets_manifest():
        return {}

    @app.post("/query")
    async def copilot_query():
        return {}

    @app.get("/viewer/assets/app.js")
    async def viewer_asset():
        return {}

    original_routes = tuple(app.router.routes)
    composed = compose_portfolio_app(app)

    assert tuple(app.router.routes) == original_routes
    assert composed is not app
    composed_paths = {route.path for route in _api_routes(composed)}
    assert composed_paths >= APPROVED_PATHS
    assert EXCLUDED_PATHS.isdisjoint(composed_paths)
    assert "/api/v1/equity/quote" in composed_paths


def test_composition_preserves_fastapi_route_contracts_and_namespaces_tools():
    """Copied routes retain DI/response behavior while receiving stable MCP IDs."""
    app = FastAPI()
    composed = compose_portfolio_app(app)
    originals = {
        route.path: route
        for route in portfolio_router.routes
        if isinstance(route, APIRoute) and route.path in APPROVED_PATHS
    }
    copies = {
        route.path: route
        for route in _api_routes(composed)
        if route.path in APPROVED_PATHS
    }

    assert set(copies) == APPROVED_PATHS
    for path, route in copies.items():
        original = originals[path]
        assert route is not original
        assert route.endpoint is original.endpoint
        assert route.dependant is original.dependant  # codespell:ignore dependant
        assert route.response_model is original.response_model
        assert route.responses == original.responses
        assert route.operation_id == f"portfolio_{path.strip('/').replace('/', '_')}"
        assert route.name == route.operation_id
        assert route.openapi_extra is not original.openapi_extra
        assert route.openapi_extra["mcp_config"]["name"] == route.operation_id
        assert "name" not in original.openapi_extra["mcp_config"]


def test_composition_rejects_path_method_collisions():
    """A core route cannot be silently shadowed by a Portfolio business route."""
    app = FastAPI()

    @app.get("/stock/context")
    async def conflicting_path():
        return {}

    with pytest.raises(ValueError, match="route collision.*GET /stock/context"):
        compose_portfolio_app(app)


def test_composition_rejects_starlette_route_collisions():
    """A lower-level Starlette route cannot shadow a Portfolio operation."""
    app = FastAPI()

    async def conflicting_route(_request):
        return {}

    app.add_route("/stock/context", conflicting_route, methods=["GET"])

    with pytest.raises(ValueError, match="route collision.*GET /stock/context"):
        compose_portfolio_app(app)


def test_composition_rejects_mount_prefix_collisions():
    """A mounted application cannot intercept a Portfolio route prefix."""
    app = FastAPI()
    app.mount("/stock", FastAPI())

    with pytest.raises(ValueError, match="route collision.*MOUNT /stock"):
        compose_portfolio_app(app)


def test_composition_rejects_parameterized_route_collisions():
    """An earlier parameterized route cannot intercept a concrete Portfolio path."""
    app = FastAPI()

    @app.get("/stock/{slug}")
    async def conflicting_parameterized_path(slug: str):
        return {"slug": slug}

    with pytest.raises(ValueError, match="route collision.*GET /stock/context"):
        compose_portfolio_app(app)


def test_composition_rejects_route_name_collisions():
    """Generated stable tool identities cannot replace an existing route name."""
    app = FastAPI()

    @app.get("/synthetic", name="portfolio_stock_context")
    async def conflicting_name():
        return {}

    with pytest.raises(
        ValueError, match="route name collision.*portfolio_stock_context"
    ):
        compose_portfolio_app(app)


def test_composition_rebuilds_openapi_without_reusing_source_cache():
    """Pre-generated REST schemas cannot hide composed or retain excluded routes."""
    app = FastAPI()
    app.include_router(portfolio_router)
    source_schema = app.openapi()

    composed = compose_portfolio_app(app)
    composed_paths = set(composed.openapi()["paths"])

    assert composed_paths >= APPROVED_PATHS
    assert EXCLUDED_PATHS.isdisjoint(composed_paths)
    assert app.openapi_schema is source_schema
    assert composed.openapi_schema is not source_schema


def test_composition_rebuilds_middleware_around_the_isolated_router():
    """A previously served source app cannot retain its unfiltered router stack."""
    app = FastAPI()
    app.include_router(portfolio_router)

    @app.post("/query")
    async def copilot_query():
        return {"excluded": True}

    assert TestClient(app).post("/query").status_code == 200

    composed = compose_portfolio_app(app)

    assert TestClient(composed).post("/query").status_code == 404
    assert TestClient(composed).get("/portfolio/positions").status_code == 403


@pytest.mark.parametrize(
    ("path", "openapi_extra"),
    [
        (
            "/synthetic",
            {"mcp_config": {"name": "portfolio_stock_context"}},
        ),
        (
            "/synthetic",
            {"x-mcp": {"name": "portfolio_stock_context"}},
        ),
        ("/portfolio/stock/context", {"mcp_config": {}}),
    ],
)
def test_composition_rejects_effective_mcp_name_collisions(path, openapi_extra):
    """Existing effective MCP identities cannot hide a composed Portfolio tool."""
    app = FastAPI()

    @app.get(path, openapi_extra=openapi_extra)
    async def conflicting_mcp_name():
        return {}

    with pytest.raises(ValueError, match="MCP name collision.*portfolio_stock_context"):
        compose_portfolio_app(app)


@pytest.mark.parametrize(
    ("profile", "expected_calls"),
    [
        ("platform-standard", 0),
        ("portfolio-read", 1),
        ("portfolio-ops", 1),
    ],
)
def test_mcp_server_gates_composition_by_profile(monkeypatch, profile, expected_calls):
    """Only explicit Portfolio profiles cross the custom composition seam."""
    calls = []

    def fake_compose(app, _settings):
        calls.append(app)
        return app

    monkeypatch.setattr(app_module, "compose_portfolio_app", fake_compose)
    app = FastAPI()
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile=profile,
        default_tool_categories=["all"],
        default_skills_dir=None,
    )

    app_module.create_mcp_server(settings, app)

    assert calls == [app] * expected_calls
