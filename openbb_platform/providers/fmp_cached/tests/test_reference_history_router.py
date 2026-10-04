"""Historical reference-directory route tests."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.routers import reference_history_router
from openbb_fmp_cached.routers.reference_history_router import router

HISTORY_MODELS = {
    "HistoricalDowjonesConstituent": (
        "historical_dowjones_constituent",
        (),
    ),
    "HistoricalNasdaqConstituent": (
        "historical_nasdaq_constituent",
        (),
    ),
    "HistoricalSp500Constituent": (
        "historical_sp500_constituent",
        (),
    ),
    "SymbolChange": ("symbol_change", ("from", "to")),
    "SharesFloatAll": ("shares_float_all", ("page", "limit")),
}


def _manifest() -> list[dict]:
    path = (
        Path(__file__).parents[1] / "openbb_fmp_cached" / "assets" / "model_routes.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))["routes"]


def test_five_history_models_have_stable_routes():
    """All five historical-directory registrations are explicitly mapped."""
    evidence = {
        row["model"]: row for row in _manifest() if row["model"] in HISTORY_MODELS
    }
    assert set(evidence) == set(HISTORY_MODELS)
    paths = {route.path for route in router.api_router.routes}
    for model, (command, arguments) in HISTORY_MODELS.items():
        assert evidence[model]["command"] == command
        assert set(evidence[model]["arguments"]) == set(arguments)
        assert f"/{command}" in paths


def test_history_fetchers_preserve_valid_empty_results():
    """The cached fetchers do not fabricate rows for empty results."""
    for model in HISTORY_MODELS:
        fetcher = fmp_cached_provider.fetcher_dict[model]
        query = fetcher.transform_query({})
        assert query.model_dump() == {}
        assert fetcher.transform_data(query, []) == []


def test_history_result_dates_remain_iso_strings():
    """Historical event dates are not coerced into lossy numeric values."""
    fetcher = fmp_cached_provider.fetcher_dict["SymbolChange"]
    query = fetcher.transform_query({})
    result = fetcher.transform_data(
        query,
        [
            {
                "date": "2025-01-02",
                "companyName": "Alpha",
                "oldSymbol": "OLD",
                "newSymbol": "NEW",
            }
        ],
    )
    assert result[0].date == "2025-01-02"
    assert isinstance(result[0].date, str)


def test_history_filters_are_provider_specific():
    """Cached directories reject filters they cannot apply instead of ignoring them."""
    app = FastAPI()
    app.include_router(router.api_router)
    rejected = TestClient(app).get(
        "/symbol_change",
        params={"provider": "fmp_cached", "from": "2025-01-01"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "Unknown query arguments: from"

    with patch.object(
        reference_history_router.OBBject,
        "from_query",
        new=AsyncMock(return_value=reference_history_router.OBBject(results=[])),
    ):
        accepted = TestClient(app).request(
            "GET",
            "/symbol_change",
            params={"provider": "fmp", "from": "2025-01-01"},
            json={"from": "2025-01-01"},
        )
    assert accepted.status_code == 200
