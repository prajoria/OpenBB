"""Intelligence widget-backend composition adapter."""

import copy
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.datastructures import State
from starlette.routing import Match, Mount, Route

from openbb_mcp_server.models.settings import CapabilityProfile
from openbb_mcp_server.service.exposure_policy import ExposurePolicy
from openbb_mcp_server.utils.fastapi import get_mcp_route_identity


def _tool_name(path: str) -> str:
    return f"intelligence_{path.strip('/').replace('/', '_').replace('-', '_')}"


def _mcp_name(route: APIRoute) -> str | None:
    extra = route.openapi_extra or {}
    config = extra.get("mcp_config") or extra.get("x-mcp") or {}
    return config.get("name") if isinstance(config, dict) else None


def compose_portfolio_intel_app(
    source_app: FastAPI,
    intelligence_app: FastAPI | None,
    profile: CapabilityProfile,
    policy: ExposurePolicy,
) -> FastAPI:
    """Clone reviewed Intelligence routes into an isolated MCP application."""
    if intelligence_app is None:
        raise RuntimeError("Portfolio Intelligence service is unavailable")

    composed = copy.copy(source_app)
    composed.state = State(dict(vars(source_app.state).get("_state", {})))
    composed.state.background_tasks = set(
        getattr(composed.state, "background_tasks", set())
    )
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    existing_names = {
        route.operation_id or route.name
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
    existing_mcp_names = {
        get_mcp_route_identity(
            route.path,
            name_override=_mcp_name(route),
        ).component_name
        for route in composed.router.routes
        if isinstance(route, APIRoute)
    }

    for original in intelligence_app.router.routes:
        if not isinstance(original, APIRoute):
            continue
        if not original.path.startswith(("/pi/", "/tt/")):
            continue
        methods = sorted(original.methods)
        if not methods or not all(
            policy.is_operation_admitted(method, original.path, profile)
            for method in methods
        ):
            continue
        name = _tool_name(original.path)
        conflicting_mount = next(
            (
                prefix
                for prefix in mounted_prefixes
                if original.path == prefix or original.path.startswith(f"{prefix}/")
            ),
            None,
        )
        if conflicting_mount:
            raise ValueError(f"Intelligence route collision: MOUNT {conflicting_mount}")
        shadowing_method = next(
            (
                method
                for method in methods
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
        if shadowing_method:
            raise ValueError(
                f"Intelligence route collision: {shadowing_method} {original.path}"
            )
        if name in existing_names or name in existing_mcp_names:
            raise ValueError(f"Intelligence MCP name collision: {name}")
        route = copy.copy(original)
        route.name = name
        route.operation_id = name
        route.openapi_extra = copy.deepcopy(original.openapi_extra or {})
        config = dict(route.openapi_extra.get("mcp_config") or {})
        config["name"] = name
        route.openapi_extra["mcp_config"] = config
        composed.router.routes.append(route)
        existing_names.add(name)
        existing_mcp_names.add(name)
        existing_http_routes.append(route)

    source_lifespan = source_app.router.lifespan_context
    intelligence_lifespan = intelligence_app.router.lifespan_context

    @asynccontextmanager
    async def composed_lifespan(app: FastAPI):
        async with source_lifespan(app), intelligence_lifespan(app):
            yield

    composed.router.lifespan_context = composed_lifespan
    composed.openapi_schema = None
    return composed
