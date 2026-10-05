"""FinancialToolkit root-router coverage contracts."""

from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

from fastapi.routing import APIRoute
from openbb_financialtoolkit.financialtoolkit_router import about, router
from openbb_financialtoolkit.ratios.ratios_router import router as ratios_router
from openbb_financialtoolkit.technicals.technicals_router import (
    router as technicals_router,
)


def _identities(candidate) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in candidate.api_router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


def test_root_includes_every_implemented_ratios_and_technicals_route():
    """Documented implemented subrouters exactly equal registered routes."""
    root = _identities(router)
    ratios = _identities(ratios_router)
    technicals = _identities(technicals_router)
    assert len(ratios) == 19
    assert len(technicals) == 17
    assert ratios <= root
    assert technicals <= root
    assert len(root) == 67
    assert ratios.isdisjoint(technicals)


def test_toolkit_route_operation_ids_and_schemas_are_stable():
    """Prompt dependencies retain real valuation/performance tool schemas."""
    routes = {
        route.path: route
        for route in router.api_router.routes
        if isinstance(route, APIRoute)
    }
    for path in (
        "/ratios/valuation",
        "/ratios/price_to_earnings",
        "/technicals/rsi",
        "/technicals/moving_average",
        "/performance/sharpe_ratio",
    ):
        route = routes[path]
        assert route.operation_id
        assert route.dependant.query_params


def test_missing_optional_toolkit_is_reported_without_breaking_router():
    """Dependency absence remains explicit while metadata routes stay callable."""
    with patch(
        "openbb_financialtoolkit.financialtoolkit_router.version",
        side_effect=PackageNotFoundError,
    ):
        result = about()
    assert result.results.toolkit_installed is False
    assert result.results.toolkit_version is None
    assert len(_identities(router)) == 67


def test_api_key_overrides_use_redacted_header_not_query_strings():
    """Newly registered routes cannot leak provider keys through URLs or MCP."""
    for route in [
        *ratios_router.api_router.routes,
        *technicals_router.api_router.routes,
    ]:
        if route.path.endswith("/capabilities"):
            continue
        assert "api_key" not in {field.name for field in route.dependant.query_params}
        headers = {field.alias for field in route.dependant.header_params}
        assert "X-FMP-API-Key" in headers
        assert route.openapi_extra["mcp_config"]["exclude_args"] == ["X-FMP-API-Key"]
