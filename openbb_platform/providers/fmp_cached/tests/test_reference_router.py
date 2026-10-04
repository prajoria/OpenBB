"""Coverage for the first provider-owned FMP reference route batch."""

import inspect
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_core.app.router import CommandMap
from openbb_fmp import fmp_provider
from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.fmp_cached_router import router as exported_router
from openbb_fmp_cached.routers import reference_router

EXPECTED_MODELS = {
    "ActivelyTradingList",
    "AvailableCountries",
    "AvailableExchanges",
    "AvailableIndustries",
    "AvailableSectors",
    "CommoditiesList",
    "CryptocurrencyList",
    "DowjonesConstituent",
    "EtfList",
    "ForexList",
    "IndexList",
    "MarketRiskPremium",
    "NasdaqConstituent",
    "RiskPremium",
    "Sp500Constituent",
    "StockList",
}


def _manifest_routes() -> list[dict]:
    path = (
        Path(__file__).parents[1] / "openbb_fmp_cached" / "assets" / "model_routes.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))["routes"]


def test_reference_batch_remains_in_the_expanded_manifest():
    """T12 reference routes remain stable as later batches are appended."""
    routes = _manifest_routes()
    assert {route["model"] for route in routes} >= EXPECTED_MODELS


def test_every_manifest_row_matches_router_and_provider_registry():
    """Route, command, provider and model evidence cannot drift."""
    api_routes = {
        route.path: route for route in reference_router.router.api_router.routes
    }
    for evidence in (
        route for route in _manifest_routes() if route["model"] in EXPECTED_MODELS
    ):
        local_path = evidence["canonical_route"].removeprefix("/fmp_cached")
        assert local_path in api_routes
        assert local_path == f"/{evidence['command']}"
        providers = {
            provider.name
            for provider in (fmp_provider, fmp_cached_provider)
            if evidence["model"] in provider.fetcher_dict
        }
        assert providers == set(evidence["providers"])


def test_every_manifest_row_appears_in_openapi_and_command_map():
    """Core route assembly exposes the full batch through both registries."""
    command_map = CommandMap(exported_router).map
    app = FastAPI()
    app.include_router(exported_router.api_router)
    openapi_paths = app.openapi()["paths"]
    for evidence in _manifest_routes():
        local_path = evidence["canonical_route"].removeprefix("/fmp_cached")
        assert local_path in command_map
        assert local_path in openapi_paths
        operation = openapi_paths[local_path]["get"]
        assert operation["operationId"] == (f"fmp_cached_{evidence['command']}")
        assert operation["description"]


def test_reference_commands_accept_only_dispatcher_parameters():
    """No route admits arbitrary model names or undocumented filters."""
    expected = (
        "cc",
        "provider_choices",
        "standard_params",
        "extra_params",
    )
    commands = {
        route["command"]
        for route in _manifest_routes()
        if route["model"] in EXPECTED_MODELS
    }
    for command in commands:
        function = getattr(reference_router, command)
        assert tuple(inspect.signature(function).parameters) == expected


def test_reference_models_have_real_empty_query_schemas():
    """This batch consists only of genuine no-parameter reference models."""
    for evidence in (
        route for route in _manifest_routes() if route["model"] in EXPECTED_MODELS
    ):
        fetcher = fmp_cached_provider.fetcher_dict[evidence["model"]]
        query = fetcher.transform_query({})
        assert query.model_dump() == {}
        assert evidence["arguments"] == []


def test_unknown_query_arguments_are_rejected():
    """Transport callers cannot smuggle undocumented filters."""
    app = FastAPI()
    app.include_router(exported_router.api_router)
    response = TestClient(app).get(
        "/stock_list",
        params={"provider": "fmp_cached", "bogus": "value"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown query arguments: bogus"


def test_empty_reference_results_remain_valid_empty_data():
    """Empty lists are not replaced with fabricated success rows."""
    for evidence in (
        route for route in _manifest_routes() if route["model"] in EXPECTED_MODELS
    ):
        fetcher = fmp_cached_provider.fetcher_dict[evidence["model"]]
        query = fetcher.transform_query({})
        assert fetcher.transform_data(query, []) == []
