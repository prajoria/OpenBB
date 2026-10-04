"""Sector and industry snapshot/history route tests."""

# ruff: noqa: D103

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.routers.market_performance_router import router
from pydantic import ValidationError

MODELS = {
    "SectorPerformanceSnapshot": ("sector_performance_snapshot", "date"),
    "IndustryPerformanceSnapshot": ("industry_performance_snapshot", "date"),
    "SectorPeSnapshot": ("sector_pe_snapshot", "date"),
    "IndustryPeSnapshot": ("industry_pe_snapshot", "date"),
    "HistoricalSectorPerformance": (
        "historical_sector_performance",
        ("sector", "from", "to"),
    ),
    "HistoricalIndustryPerformance": (
        "historical_industry_performance",
        ("industry", "from", "to"),
    ),
    "HistoricalSectorPe": (
        "historical_sector_pe",
        ("sector", "from", "to"),
    ),
    "HistoricalIndustryPe": (
        "historical_industry_pe",
        ("industry", "from", "to"),
    ),
}


def _manifest() -> list[dict]:
    path = Path(__file__).parents[1] / "openbb_fmp_cached/assets/model_routes.json"
    return json.loads(path.read_text(encoding="utf-8"))["routes"]


def test_eight_market_performance_models_have_stable_routes():
    evidence = {row["model"]: row for row in _manifest() if row["model"] in MODELS}
    assert set(evidence) == set(MODELS)
    paths = {route.path for route in router.api_router.routes}
    for model, (command, argument) in MODELS.items():
        arguments = argument if isinstance(argument, tuple) else (argument,)
        assert evidence[model]["command"] == command
        assert set(evidence[model]["arguments"]) == set(arguments)
        assert f"/{command}" in paths


@pytest.mark.parametrize(
    ("model", "argument", "value"),
    [
        ("SectorPerformanceSnapshot", "date", "2025-01-02"),
        ("IndustryPerformanceSnapshot", "date", "2025-01-02"),
        ("SectorPeSnapshot", "date", "2025-01-02"),
        ("IndustryPeSnapshot", "date", "2025-01-02"),
        ("HistoricalSectorPerformance", "sector", "Technology"),
        ("HistoricalIndustryPerformance", "industry", "Software"),
        ("HistoricalSectorPe", "sector", "Technology"),
        ("HistoricalIndustryPe", "industry", "Software"),
    ],
)
def test_snapshot_and_history_queries_keep_real_filters(model, argument, value):
    fetcher = fmp_cached_provider.fetcher_dict[model]
    query = fetcher.transform_query({argument: value})
    assert getattr(query, argument) == value
    with pytest.raises(ValidationError):
        fetcher.transform_query({})


def test_empty_performance_responses_remain_empty():
    for model, (_, argument) in MODELS.items():
        primary = argument[0] if isinstance(argument, tuple) else argument
        value = "2025-01-02" if primary == "date" else "Technology"
        fetcher = fmp_cached_provider.fetcher_dict[model]
        query = fetcher.transform_query({primary: value})
        assert fetcher.transform_data(query, []) == []


def test_cached_history_rejects_unimplemented_date_filters():
    """Cached history never silently ignores fmp-only from/to filters."""
    app = FastAPI()
    app.include_router(router.api_router)
    response = TestClient(app).get(
        "/historical_sector_performance",
        params={
            "provider": "fmp_cached",
            "sector": "Technology",
            "from": "2025-01-01",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown query arguments: from"
