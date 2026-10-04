"""Analyst ratings and recommendations route tests."""

# ruff: noqa: D103

import json
from pathlib import Path

import pytest
from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.routers.analyst_router import router
from pydantic import ValidationError

MODELS = {
    "AnalystRecommendations": "analyst_recommendations",
    "RatingsSnapshot": "ratings_snapshot",
    "RatingsHistorical": "ratings_historical",
    "PriceTargetSummary": "price_target_summary",
    "Grades": "grades",
    "GradesHistorical": "grades_historical",
    "GradesConsensus": "grades_consensus",
}


def _manifest() -> list[dict]:
    path = Path(__file__).parents[1] / "openbb_fmp_cached/assets/model_routes.json"
    return json.loads(path.read_text(encoding="utf-8"))["routes"]


def test_seven_analyst_models_have_stable_routes():
    evidence = {row["model"]: row for row in _manifest() if row["model"] in MODELS}
    assert set(evidence) == set(MODELS)
    paths = {route.path for route in router.api_router.routes}
    for model, command in MODELS.items():
        assert evidence[model]["command"] == command
        assert evidence[model]["arguments"] == ["symbol"]
        assert f"/{command}" in paths


@pytest.mark.parametrize("model", MODELS)
def test_analyst_symbol_is_required_and_exact(model):
    fetcher = fmp_cached_provider.fetcher_dict[model]
    query = fetcher.transform_query({"symbol": "BRK.B"})
    assert query.symbol == "BRK.B"
    with pytest.raises(ValidationError):
        fetcher.transform_query({})


def test_snapshot_history_nullable_rows_remain_distinct():
    snapshot = fmp_cached_provider.fetcher_dict["RatingsSnapshot"]
    historical = fmp_cached_provider.fetcher_dict["RatingsHistorical"]
    snapshot_query = snapshot.transform_query({"symbol": "AAA"})
    historical_query = historical.transform_query({"symbol": "AAA"})
    snapshot_rows = snapshot.transform_data(
        snapshot_query,
        [{"symbol": "AAA", "rating": None, "overallScore": None}],
    )
    historical_rows = historical.transform_data(
        historical_query,
        [{"symbol": "AAA", "date": "2025-01-02", "rating": None}],
    )
    assert snapshot_rows[0].overall_score is None
    assert historical_rows[0].date == "2025-01-02"


def test_canonical_analyst_estimates_mapping_is_not_replaced():
    assert "AnalystEstimates" in fmp_cached_provider.fetcher_dict
    assert all(row["model"] != "AnalystEstimates" for row in _manifest())
