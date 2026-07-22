"""Unit tests for W7 analyst-rating fetchers (#1057 #1058 #1059 #1061 #1062 #1063)."""

from __future__ import annotations


def test_ratings_snapshot_maps_overall_score():
    """OverallScore -> overall_score; extra=allow preserves other score fields."""
    from openbb_fmp_cached.models.analyst_ratings import (
        FMPCachedRatingsSnapshotFetcher,
    )

    rows = [
        {
            "symbol": "AAPL",
            "rating": "B",
            "overallScore": 3,
            "discountedCashFlowScore": 3,
        }
    ]
    out = FMPCachedRatingsSnapshotFetcher.transform_data(None, rows)
    assert out[0].symbol == "AAPL"
    assert out[0].overall_score == 3
    # extra=allow preserves un-modeled fields
    assert out[0].discountedCashFlowScore == 3


def test_ratings_historical_carries_date():
    """ratings-historical rows include a date field."""
    from openbb_fmp_cached.models.analyst_ratings import (
        FMPCachedRatingsHistoricalFetcher,
    )

    rows = [{"symbol": "AAPL", "date": "2026-07-21", "rating": "B", "overallScore": 3}]
    out = FMPCachedRatingsHistoricalFetcher.transform_data(None, rows)
    assert out[0].date == "2026-07-21"
    assert out[0].rating == "B"


def test_price_target_summary_uses_extra_allow():
    """price-target-summary has ~8 fields (lastMonth*, lastQuarter*, etc.) — keep loose."""
    from openbb_fmp_cached.models.analyst_ratings import (
        FMPCachedPriceTargetSummaryFetcher,
    )

    rows = [
        {
            "symbol": "AAPL",
            "lastMonthCount": 6,
            "lastMonthAvgPriceTarget": 340.17,
            "lastQuarterCount": 18,
        }
    ]
    out = FMPCachedPriceTargetSummaryFetcher.transform_data(None, rows)
    assert out[0].symbol == "AAPL"
    assert out[0].lastMonthCount == 6
    assert out[0].lastQuarterCount == 18


def test_grades_maps_grading_company_and_grades():
    """GradingCompany + previousGrade + newGrade all remap."""
    from openbb_fmp_cached.models.analyst_ratings import FMPCachedGradesFetcher

    rows = [
        {
            "symbol": "AAPL",
            "date": "2026-07-17",
            "gradingCompany": "HSBC",
            "previousGrade": "Hold",
            "newGrade": "Buy",
            "action": "upgrade",
        }
    ]
    out = FMPCachedGradesFetcher.transform_data(None, rows)
    assert out[0].grading_company == "HSBC"
    assert out[0].previous_grade == "Hold"
    assert out[0].new_grade == "Buy"
    assert out[0].action == "upgrade"


def test_grades_consensus_maps_strong_buy_sell():
    """StrongBuy / strongSell alias mapping."""
    from openbb_fmp_cached.models.analyst_ratings import (
        FMPCachedGradesConsensusFetcher,
    )

    rows = [
        {
            "symbol": "AAPL",
            "strongBuy": 1,
            "buy": 70,
            "hold": 32,
            "sell": 8,
            "strongSell": 0,
            "consensus": "Buy",
        }
    ]
    out = FMPCachedGradesConsensusFetcher.transform_data(None, rows)
    assert out[0].strong_buy == 1
    assert out[0].buy == 70
    assert out[0].strong_sell == 0
    assert out[0].consensus == "Buy"


def test_all_six_registered_in_provider():
    """Provider registration is what makes the coverage gate see them."""
    from openbb_fmp_cached import fmp_cached_provider

    for name in (
        "RatingsSnapshot",
        "RatingsHistorical",
        "PriceTargetSummary",
        "Grades",
        "GradesHistorical",
        "GradesConsensus",
    ):
        assert name in fmp_cached_provider.fetcher_dict, f"{name} not registered"


def test_all_six_use_symbol_query_field():
    """Regression: every W7 Analyst fetcher must send `symbol=`, not `query=`."""
    from openbb_fmp_cached.models.analyst_ratings import (
        FMPCachedGradesConsensusFetcher,
        FMPCachedGradesFetcher,
        FMPCachedGradesHistoricalFetcher,
        FMPCachedPriceTargetSummaryFetcher,
        FMPCachedRatingsHistoricalFetcher,
        FMPCachedRatingsSnapshotFetcher,
    )

    for f in (
        FMPCachedRatingsSnapshotFetcher,
        FMPCachedRatingsHistoricalFetcher,
        FMPCachedPriceTargetSummaryFetcher,
        FMPCachedGradesFetcher,
        FMPCachedGradesHistoricalFetcher,
        FMPCachedGradesConsensusFetcher,
    ):
        assert f._query_field == "symbol", f"{f.__name__} sends wrong param"


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out (no exception)."""
    from openbb_fmp_cached.models.analyst_ratings import FMPCachedGradesFetcher

    assert FMPCachedGradesFetcher.transform_data(None, []) == []
