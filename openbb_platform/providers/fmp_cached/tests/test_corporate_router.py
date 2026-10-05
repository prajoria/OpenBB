"""Corporate, SEC and fundraising route tests."""

# ruff: noqa: D103

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.routers import corporate_router
from openbb_fmp_cached.routers.corporate_router import router
from pydantic import ValidationError

MODELS = {
    "AcquisitionOfBeneficialOwnership": (
        "acquisition_of_beneficial_ownership",
        ("symbol",),
    ),
    "AllIndustryClassification": ("all_industry_classification", ()),
    "CrowdfundingOfferings": ("crowdfunding_offerings", ("cik",)),
    "CrowdfundingOfferingsLatest": (
        "crowdfunding_offerings_latest",
        ("page", "limit"),
    ),
    "CrowdfundingOfferingsSearch": ("crowdfunding_offerings_search", ("name",)),
    "DelistedCompanies": ("delisted_companies", ("page", "limit")),
    "Fundraising": ("fundraising", ("cik",)),
    "FundraisingLatest": ("fundraising_latest", ("page", "limit")),
    "FundraisingSearch": ("fundraising_search", ("name",)),
    "IndustryClassificationSearch": (
        "industry_classification_search",
        ("symbol", "cik", "sicCode"),
    ),
    "IposDisclosure": ("ipos_disclosure", ("page", "limit")),
    "IposProspectus": ("ipos_prospectus", ("page", "limit")),
    "MergersAcquisitionsLatest": (
        "mergers_acquisitions_latest",
        ("page", "limit"),
    ),
    "MergersAcquisitionsSearch": ("mergers_acquisitions_search", ("name",)),
    "SecFilings8K": ("sec_filings_8k", ("from", "to", "page", "limit")),
    "SecProfile": ("sec_profile", ("symbol",)),
    "StandardIndustrialClassificationList": (
        "standard_industrial_classification_list",
        (),
    ),
}


def _manifest() -> list[dict]:
    path = Path(__file__).parents[1] / "openbb_fmp_cached/assets/model_routes.json"
    return json.loads(path.read_text(encoding="utf-8"))["routes"]


def test_exact_seventeen_corporate_models_have_routes():
    evidence = {row["model"]: row for row in _manifest() if row["model"] in MODELS}
    assert set(evidence) == set(MODELS)
    paths = {route.path for route in router.api_router.routes}
    executable_models = {
        route.openapi_extra["model"]
        for route in router.api_router.routes
        if route.openapi_extra and route.openapi_extra.get("model")
    }
    assert executable_models == set(MODELS)
    for model, (command, arguments) in MODELS.items():
        assert evidence[model]["command"] == command
        assert set(evidence[model]["arguments"]) == set(arguments)
        assert f"/{command}" in paths


@pytest.mark.parametrize(
    ("model", "params"),
    [
        ("AcquisitionOfBeneficialOwnership", {"symbol": "BRK.B"}),
        ("CrowdfundingOfferings", {"cik": "0000320193"}),
        ("Fundraising", {"cik": "0000320193"}),
        ("CrowdfundingOfferingsSearch", {"name": "Alpha Holdings"}),
        ("FundraisingSearch", {"name": "Alpha Holdings"}),
        ("MergersAcquisitionsSearch", {"name": "Alpha Holdings"}),
        ("SecFilings8K", {"page": 2}),
    ],
)
def test_identifiers_search_and_paging_remain_typed(model, params):
    fetcher = fmp_cached_provider.fetcher_dict[model]
    query = fetcher.transform_query(params)
    for key, value in params.items():
        assert getattr(query, key) == value


@pytest.mark.parametrize(
    "model",
    [
        "AcquisitionOfBeneficialOwnership",
        "CrowdfundingOfferings",
        "Fundraising",
        "CrowdfundingOfferingsSearch",
        "FundraisingSearch",
        "MergersAcquisitionsSearch",
    ],
)
def test_required_identifiers_are_enforced(model):
    with pytest.raises(ValidationError):
        fmp_cached_provider.fetcher_dict[model].transform_query({})


def test_nested_corporate_documents_serialize_without_summaries():
    fetcher = fmp_cached_provider.fetcher_dict["IposDisclosure"]
    query = fetcher.transform_query({})
    rows = fetcher.transform_data(
        query,
        [{"cik": "0000320193", "nested": {"source": ["raw", None]}}],
    )
    dumped = rows[0].model_dump()
    assert dumped["nested"] == {"source": ["raw", None]}
    assert "summary" not in dumped


def test_no_route_accepts_a_user_supplied_url():
    for row in _manifest():
        if row["model"] in MODELS:
            assert "url" not in row["arguments"]
    app = FastAPI()
    app.include_router(router.api_router)
    for operation in app.openapi()["paths"].values():
        schema = operation["get"]
        parameters = {item["name"] for item in schema.get("parameters", [])}
        body = (
            schema.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema", {})
        )
        assert "url" not in parameters
        assert "url" not in json.dumps(body).lower()


def test_cached_routes_reject_unimplemented_union_filters():
    """Cached provider never silently ignores fmp-only paging/date filters."""
    app = FastAPI()
    app.include_router(router.api_router)
    response = TestClient(app).get(
        "/sec_filings_8k",
        params={"provider": "fmp_cached", "page": 1, "limit": 100},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown query arguments: limit"
    latest = TestClient(app).get(
        "/fundraising_latest",
        params={"provider": "fmp_cached", "page": 2},
    )
    assert latest.status_code == 422
    assert latest.json()["detail"] == "Unknown query arguments: page"

    response_obj = corporate_router.OBBject(results=[])
    with (
        patch.object(corporate_router, "Query", return_value=object()),
        patch.object(
            corporate_router.OBBject,
            "from_query",
            new=AsyncMock(return_value=response_obj),
        ),
    ):
        accepted = TestClient(app).request(
            "GET",
            "/sec_filings_8k",
            params={
                "provider": "fmp",
                "from": "2025-01-01",
                "to": "2025-01-31",
                "page": 1,
                "limit": 100,
            },
            json={},
        )
    assert accepted.status_code == 200


def test_missing_corporate_records_remain_empty():
    """Missing records remain typed empty data, not fabricated summaries."""
    fetcher = fmp_cached_provider.fetcher_dict["SecProfile"]
    query = fetcher.transform_query({"symbol": "MISSING"})
    assert fetcher.transform_data(query, []) == []


@pytest.mark.asyncio
async def test_entitlement_errors_propagate_without_fallback():
    """A provider 402 remains an explicit failure."""
    fetcher = fmp_cached_provider.fetcher_dict["AcquisitionOfBeneficialOwnership"]
    query = fetcher.transform_query({"symbol": "AAPL"})
    request = httpx.Request("GET", "https://financialmodelingprep.com/stable/x")
    error = httpx.HTTPStatusError(
        "Payment Required",
        request=request,
        response=httpx.Response(402, request=request),
    )
    with patch.object(
        fetcher,
        "_fetch",
        new=AsyncMock(side_effect=error),
    ), pytest.raises(httpx.HTTPStatusError):
        await fetcher.aextract_data(
            query,
            {"fmp_cached_api_key": "redacted"},
        )


def test_offline_api_round_trip_serializes_typed_rows():
    """A provider-owned route returns a structured synthetic response."""
    app = FastAPI()
    app.include_router(router.api_router)
    fetcher = fmp_cached_provider.fetcher_dict["AllIndustryClassification"]
    query = fetcher.transform_query({})
    typed_rows = fetcher.transform_data(
        query,
        [{"cik": "0000320193", "name": "Alpha"}],
    )
    response_obj = corporate_router.OBBject(
        results=typed_rows,
        provider="fmp_cached",
    )
    with (
        patch.object(corporate_router, "Query", return_value=object()),
        patch.object(
            corporate_router.OBBject,
            "from_query",
            new=AsyncMock(return_value=response_obj),
        ),
    ):
        response = TestClient(app).request(
            "GET",
            "/all_industry_classification",
            params={"provider": "fmp_cached"},
            json={},
        )
    assert response.status_code == 200
    assert response.json()["results"][0]["cik"] == "0000320193"
