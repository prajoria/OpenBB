"""Typed identifier and text-search route tests."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.routers import search_router
from openbb_fmp_cached.routers.search_router import router
from openbb_fmp_cached.utils.security import raise_for_status_redacted
from pydantic import ValidationError

SEARCH_MODELS = {
    "SearchCik": ("search_cik", ("cik",)),
    "SearchCusip": ("search_cusip", ("cusip", "query")),
    "SearchIsin": ("search_isin", ("isin", "query")),
    "SearchName": ("search_name", ("query",)),
    "SearchSymbol": ("search_symbol", ("query",)),
    "SearchExchangeVariants": (
        "search_exchange_variants",
        ("symbol", "query"),
    ),
}


def _manifest() -> list[dict]:
    path = (
        Path(__file__).parents[1] / "openbb_fmp_cached" / "assets" / "model_routes.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))["routes"]


def test_six_search_models_have_explicit_routes_and_arguments():
    """Every search registration has one stable route and text argument."""
    evidence = {
        row["model"]: row for row in _manifest() if row["model"] in SEARCH_MODELS
    }
    assert set(evidence) == set(SEARCH_MODELS)
    paths = {route.path for route in router.api_router.routes}
    for model, (command, arguments) in SEARCH_MODELS.items():
        assert evidence[model]["command"] == command
        assert set(evidence[model]["arguments"]) == set(arguments)
        assert f"/{command}" in paths


@pytest.mark.parametrize(
    ("model", "argument", "value"),
    [
        ("SearchCik", "cik", "0000320193"),
        ("SearchCusip", "query", "037833100"),
        ("SearchIsin", "query", "US0378331005"),
        ("SearchName", "query", "Alpha Holdings"),
        ("SearchSymbol", "query", "BRK.B"),
        ("SearchExchangeVariants", "query", "SHOP"),
    ],
)
def test_search_identifiers_remain_exact_strings(model, argument, value):
    """Identifiers retain leading zeros and punctuation without coercion."""
    fetcher = fmp_cached_provider.fetcher_dict[model]
    query = fetcher.transform_query({argument: value})
    assert getattr(query, argument) == value
    assert isinstance(getattr(query, argument), str)


@pytest.mark.parametrize("model", SEARCH_MODELS)
def test_search_text_is_required(model):
    """Missing search text fails typed query validation."""
    fetcher = fmp_cached_provider.fetcher_dict[model]
    with pytest.raises(ValidationError):
        fetcher.transform_query({})


def test_unknown_search_arguments_are_rejected():
    """Search routes reject undocumented query transformations."""
    app = FastAPI()
    app.include_router(router.api_router)
    response = TestClient(app).get(
        "/search_cik",
        params={"provider": "fmp_cached", "cik": "0000320193", "extra": "x"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown query arguments: extra"


def test_provider_specific_search_arguments_are_enforced():
    """Provider-only identifier names cannot be ignored by cached fetchers."""
    app = FastAPI()
    app.include_router(router.api_router)
    response = TestClient(app).get(
        "/search_cusip",
        params={"provider": "fmp_cached", "cusip": "037833100"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown query arguments: cusip"

    with patch.object(
        search_router.OBBject,
        "from_query",
        new=AsyncMock(return_value=search_router.OBBject(results=[])),
    ):
        accepted = TestClient(app).request(
            "GET",
            "/search_cusip",
            params={"provider": "fmp", "cusip": "037833100"},
            json={"cusip": "037833100"},
        )
    assert accepted.status_code == 200


def test_provider_errors_retain_context_without_secret_urls():
    """API/MCP conversion receives an actionable but credential-free error."""
    response = requests.Response()
    response.status_code = 401
    response.url = (
        "https://financialmodelingprep.com/stable/search?"
        "query=AAA&apikey=super-secret"
    )
    response.request = requests.Request("GET", response.url).prepare()
    with pytest.raises(requests.HTTPError) as error:
        raise_for_status_redacted(response)
    assert "super-secret" not in str(error.value)
    assert "apikey=__redacted__" in str(error.value)


def test_httpx_provider_errors_are_redacted_without_losing_context():
    """HTTPX errors preserve status/endpoint context without credentials."""
    response = httpx.Response(
        429,
        request=httpx.Request(
            "GET",
            "https://financialmodelingprep.com/stable/search?"
            "query=AAA&apikey=super-secret",
        ),
    )
    with pytest.raises(httpx.HTTPStatusError) as error:
        raise_for_status_redacted(response)
    assert error.value.response.status_code == 429
    assert "super-secret" not in str(error.value)
    assert "super-secret" not in str(error.value.response.url)
    assert "apikey=__redacted__" in str(error.value.response.url)
