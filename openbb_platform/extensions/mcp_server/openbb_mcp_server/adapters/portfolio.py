"""Portfolio FastAPI composition adapter."""

import copy

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Match, Mount, Route

from openbb_mcp_server.models.settings import MCPSettings
from openbb_mcp_server.utils.fastapi import get_mcp_route_identity

PORTFOLIO_PROFILES = frozenset({"portfolio-read", "portfolio-ops"})
APPROVED_PORTFOLIO_PATHS = frozenset(
    {
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
)
_NON_BUSINESS_PATHS = frozenset(
    {"/widgets.json", "/apps.json", "/agents.json", "/query"}
)
_NON_BUSINESS_PREFIXES = ("/viewer",)


def _is_portfolio_extension_route(route) -> bool:
    endpoint = getattr(route, "endpoint", None)
    module = str(getattr(endpoint, "__module__", ""))
    path = str(getattr(route, "path", ""))
    return (
        module.startswith("openbb_portfolio.")
        or path in _NON_BUSINESS_PATHS
        or path.startswith(_NON_BUSINESS_PREFIXES)
    )


def _operation_id(path: str) -> str:
    return f"portfolio_{path.strip('/').replace('/', '_')}"


def _mcp_name_override(route: APIRoute) -> str | None:
    extra = route.openapi_extra or {}
    config = extra.get("mcp_config") or extra.get("x-mcp") or {}
    return config.get("name") if isinstance(config, dict) else None


def compose_portfolio_app(
    source_app: FastAPI,
    settings: MCPSettings | None = None,
) -> FastAPI:
    """Return an isolated MCP composition of approved Portfolio routes."""
    # Imported only for Portfolio profiles so the standard MCP stays optional.
    try:
        from openbb_portfolio.portfolio_router import (  # pylint: disable=import-outside-toplevel
            router as portfolio_router,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Portfolio MCP profiles require the openbb_portfolio extension"
        ) from exc

    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = [
        route
        for route in source_app.router.routes
        if not _is_portfolio_extension_route(route)
    ]

    existing_names = {
        route.name for route in composed.router.routes if isinstance(route, Route)
    }
    existing_mcp_names = {
        get_mcp_route_identity(
            route.path,
            settings,
            name_override=_mcp_name_override(route),
        ).component_name
        for route in composed.router.routes
        if isinstance(route, APIRoute)
    }
    existing_http_routes = [
        route for route in composed.router.routes if isinstance(route, Route)
    ]
    mounted_prefixes = [
        route.path.rstrip("/")
        for route in composed.router.routes
        if isinstance(route, Mount)
    ]
    approved_routes = [
        route
        for route in portfolio_router.routes
        if isinstance(route, APIRoute) and route.path in APPROVED_PORTFOLIO_PATHS
    ]
    if {route.path for route in approved_routes} != APPROVED_PORTFOLIO_PATHS:
        raise RuntimeError("approved Portfolio route set is incomplete")

    for original in approved_routes:
        conflicting_mount = next(
            (
                prefix
                for prefix in mounted_prefixes
                if original.path == prefix or original.path.startswith(f"{prefix}/")
            ),
            None,
        )
        if conflicting_mount is not None:
            raise ValueError(f"Portfolio route collision: MOUNT {conflicting_mount}")
        shadowing_method = next(
            (
                method
                for method in sorted(original.methods)
                if any(
                    method in route.methods
                    and route.matches(
                        {"type": "http", "path": original.path, "method": method}
                    )[0]
                    is Match.FULL
                    for route in existing_http_routes
                )
            ),
            None,
        )
        if shadowing_method is not None:
            raise ValueError(
                f"Portfolio route collision: {shadowing_method} {original.path}"
            )
        name = _operation_id(original.path)
        if name in existing_names:
            raise ValueError(f"Portfolio route name collision: {name}")
        if name in existing_mcp_names:
            raise ValueError(f"Portfolio MCP name collision: {name}")
        route = copy.copy(original)
        route.name = name
        route.operation_id = name
        route.openapi_extra = copy.deepcopy(original.openapi_extra or {})
        mcp_config = dict(route.openapi_extra.get("mcp_config") or {})
        mcp_config["name"] = name
        route.openapi_extra["mcp_config"] = mcp_config
        composed.router.routes.append(route)
        existing_http_routes.append(route)
        existing_names.add(name)
        existing_mcp_names.add(name)

    composed.openapi_schema = None
    return composed
