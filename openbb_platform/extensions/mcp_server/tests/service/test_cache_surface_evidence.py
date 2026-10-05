"""Deterministic evidence for reviewed cache MCP surface membership."""

from fastapi.routing import APIRoute
from openbb_mcp_server.adapters.cache_admin import router as observability_router
from openbb_mcp_server.adapters.cache_jobs import router as maintenance_router
from openbb_mcp_server.service.exposure_policy import ExposurePolicy


def _tool_names(router) -> set[str]:
    """Return exact effective names declared by one cache adapter router."""
    return {
        str(
            (route.openapi_extra or {}).get("mcp_config", {}).get("name")
            or route.operation_id
        )
        for route in router.routes
        if isinstance(route, APIRoute)
    }


def test_cache_adapter_members_match_reviewed_policy():
    """Implementation routers and policy evidence own the same seven tools."""
    policy = ExposurePolicy.load()
    reviewed = policy.document.traceability.reviewed_capability_members

    assert (
        _tool_names(observability_router)
        == set(reviewed["platform-cache-observability"].members)
        == {"cache_health", "cache_coverage"}
    )
    assert (
        _tool_names(maintenance_router)
        == set(reviewed["platform-cache-maintenance"].members)
        == {
            "cache_jobs_definitions",
            "cache_jobs_health",
            "cache_jobs_run",
            "cache_jobs_trigger_position_history",
            "cache_jobs_trigger_etf_holdings",
        }
    )
