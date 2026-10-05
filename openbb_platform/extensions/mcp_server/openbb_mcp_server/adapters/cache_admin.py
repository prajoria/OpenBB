"""Sanitized read-only FMP cache observability."""

import copy
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from typing import Any, Literal

import pymysql
from fastapi import APIRouter, FastAPI
from openbb_core.app.router import RouterLoader
from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.utils.database import execute_query
from pydantic import BaseModel

_ASSETS = files("openbb_fmp_cached").joinpath("assets")
_HEALTH_QUERY = """
SELECT
    COUNT(*) AS table_count,
    COALESCE(SUM(TABLE_ROWS), 0) AS estimated_row_count,
    MAX(UPDATE_TIME) AS freshest_at,
    MIN(UPDATE_TIME) AS stalest_at
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
"""


class CacheHealth(BaseModel):
    """Bounded aggregate cache-health response."""

    availability: Literal[
        "available",
        "empty",
        "stale",
        "unavailable",
        "permission_denied",
    ]
    implementation_type: str
    table_count: int | None
    estimated_row_count: int | None
    freshest_at: datetime | None
    stalest_at: datetime | None
    stale: bool | None
    detail: str | None = None


class CacheCoverage(BaseModel):
    """Provider registration and persistence coverage."""

    availability: Literal["available"]
    implementation_type: str
    registered_models: int
    routed_models: int
    persistent_models: int
    non_persistent_models: int


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def build_cache_health(
    *,
    query_fn: Callable[..., Any] = execute_query,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(days=2),
) -> CacheHealth:
    """Read aggregate metadata without creating, refreshing, or mutating tables."""
    current_value = now or datetime.now(timezone.utc)
    current = (
        current_value.replace(tzinfo=timezone.utc)
        if current_value.tzinfo is None
        else current_value.astimezone(timezone.utc)
    )
    try:
        rows = query_fn(_HEALTH_QUERY)
    except ValueError:
        return CacheHealth(
            availability="unavailable",
            implementation_type="mysql_read_only_aggregate",
            table_count=None,
            estimated_row_count=None,
            freshest_at=None,
            stalest_at=None,
            stale=None,
            detail="Database configuration is unavailable.",
        )
    except pymysql.MySQLError as exc:
        code = exc.args[0] if exc.args else None
        permission_denied = code in {1044, 1045, 1142}
        return CacheHealth(
            availability=("permission_denied" if permission_denied else "unavailable"),
            implementation_type="mysql_read_only_aggregate",
            table_count=None,
            estimated_row_count=None,
            freshest_at=None,
            stalest_at=None,
            stale=None,
            detail=(
                "Database permission denied."
                if permission_denied
                else "Database is unavailable."
            ),
        )

    row = dict(rows[0]) if rows else {}
    table_count = int(row.get("table_count") or 0)
    row_count = int(row.get("estimated_row_count") or 0)
    freshest_at = _as_utc(row.get("freshest_at"))
    stalest_at = _as_utc(row.get("stalest_at"))
    if table_count == 0 or row_count == 0:
        availability = "empty"
        stale = None
    else:
        stale = stalest_at is None or current - stalest_at > stale_after
        availability = "stale" if stale else "available"
    return CacheHealth(
        availability=availability,
        implementation_type="mysql_read_only_aggregate",
        table_count=table_count,
        estimated_row_count=row_count,
        freshest_at=freshest_at,
        stalest_at=stalest_at,
        stale=stale,
    )


def build_cache_coverage() -> CacheCoverage:
    """Return exact registration, routing, and persistence metadata."""
    registered = set(fmp_cached_provider.fetcher_dict)
    manifest = json.loads((_ASSETS / "model_routes.json").read_text(encoding="utf-8"))
    provider_owned = {row["model"] for row in manifest["routes"]}
    legacy = {
        route.openapi_extra["model"]
        for route in RouterLoader.from_extensions().api_router.routes
        if route.openapi_extra
        and route.openapi_extra.get("model") in registered
        and not route.path.startswith("/fmp_cached/")
    }
    descriptor = json.loads(
        (_ASSETS / "persistence_descriptors.json").read_text(encoding="utf-8")
    )
    non_persistent = set(descriptor["non_persistent_fallbacks"])
    return CacheCoverage(
        availability="available",
        implementation_type="provider_registration_metadata",
        registered_models=len(registered),
        routed_models=len(legacy | provider_owned),
        persistent_models=len(registered - non_persistent),
        non_persistent_models=len(non_persistent),
    )


router = APIRouter(prefix="/api/v1/cache", tags=["cache"])


@router.get("/health", operation_id="cache_health")
def cache_health() -> CacheHealth:
    """Return sanitized aggregate database health."""
    return build_cache_health()


@router.get("/coverage", operation_id="cache_coverage")
def cache_coverage() -> CacheCoverage:
    """Return provider routing and persistence coverage."""
    return build_cache_coverage()


def compose_cache_observability_app(source_app: FastAPI) -> FastAPI:
    """Add observability routes to an isolated FastAPI application."""
    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    composed.include_router(router)
    composed.openapi_schema = None
    return composed
