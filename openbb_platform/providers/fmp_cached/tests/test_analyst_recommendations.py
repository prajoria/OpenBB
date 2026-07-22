"""Unit tests for FMPCachedAnalystRecommendationsFetcher (#997 / #1022).

Discriminators:

- **bucketize_grade** maps common grade strings to the right bucket.
  A misclassification would silently mis-count in the widget; test
  every string we've SEEN in production plus a set of expected
  synonyms.
- **transform_data** aggregates by keeping the LATEST grade per firm.
  Discriminator: a firm with 3 grades over time contributes 1 count
  (not 3) and it's the most recent one.
- **Loud empty** on no data — returns a single all-zeros row, not [].
- **Unknown grades** land in unknown_count and total = sum(known) +
  unknown so callers can trust the count arithmetic.
"""

from __future__ import annotations

from openbb_fmp_cached.models.analyst_recommendations import (
    FMPCachedAnalystRecommendationsFetcher,
    FMPCachedAnalystRecommendationsQueryParams,
    bucketize_grade,
)


def test_bucketize_grade_covers_the_5_canonical_labels() -> None:
    """The 5 exact labels used by Wall Street map to their own bucket."""
    assert bucketize_grade("Strong Buy") == "strong_buy"
    assert bucketize_grade("Buy") == "buy"
    assert bucketize_grade("Hold") == "hold"
    assert bucketize_grade("Sell") == "sell"
    assert bucketize_grade("Strong Sell") == "strong_sell"


def test_bucketize_grade_covers_common_synonyms() -> None:
    """Firm-specific labels that map to the standard 5 buckets."""
    # Overweight / Outperform → Buy
    assert bucketize_grade("Outperform") == "buy"
    assert bucketize_grade("Overweight") == "buy"
    assert bucketize_grade("Accumulate") == "buy"
    # Market Perform / Neutral → Hold
    assert bucketize_grade("Neutral") == "hold"
    assert bucketize_grade("Market Perform") == "hold"
    assert bucketize_grade("Equal-Weight") == "hold"
    assert bucketize_grade("Perform") == "hold"  # Cowen/Piper/BMO scale
    # Underperform / Underweight → Sell
    assert bucketize_grade("Underperform") == "sell"
    assert bucketize_grade("Underweight") == "sell"


def test_bucketize_grade_is_case_insensitive_and_strips() -> None:
    """Whitespace + case don't matter."""
    assert bucketize_grade("  buy  ") == "buy"
    assert bucketize_grade("BUY") == "buy"
    assert bucketize_grade("Buy") == "buy"


def test_bucketize_grade_returns_None_for_unknown() -> None:
    """Unknown returns None so transform_data can count into unknown_count."""
    assert bucketize_grade("Not A Real Grade") is None
    assert bucketize_grade(None) is None
    assert bucketize_grade("") is None


def test_transform_data_returns_all_zeros_row_on_empty() -> None:
    """Loud empty: [] input → a single all-zeros row, not []."""
    q = FMPCachedAnalystRecommendationsQueryParams(symbol="ZZZ")
    out = FMPCachedAnalystRecommendationsFetcher.transform_data(q, [])
    assert len(out) == 1
    row = out[0]
    assert row.symbol == "ZZZ"
    assert row.total == 0
    assert row.strong_buy == row.buy == row.hold == row.sell == row.strong_sell == 0


def test_transform_data_keeps_latest_grade_per_firm() -> None:
    """A firm with 3 grades contributes 1 count, using the LATEST date."""
    q = FMPCachedAnalystRecommendationsQueryParams(symbol="AAPL")
    data = [
        {"date": "2026-01-01", "gradingCompany": "Firm A", "newGrade": "Sell"},
        {"date": "2026-06-01", "gradingCompany": "Firm A", "newGrade": "Buy"},
        {"date": "2026-03-01", "gradingCompany": "Firm A", "newGrade": "Hold"},
        {"date": "2026-06-15", "gradingCompany": "Firm B", "newGrade": "Buy"},
    ]
    out = FMPCachedAnalystRecommendationsFetcher.transform_data(q, data)
    row = out[0]
    # Firm A's LATEST is 2026-06-01 Buy; Firm B is Buy. Both count as Buy.
    assert row.buy == 2
    assert row.hold == 0
    assert row.sell == 0
    assert row.total == 2
    assert row.as_of == "2026-06-15"  # max across ALL rows, not just latest per firm


def test_transform_data_counts_unknown_grades_separately() -> None:
    """Unmapped grade → unknown_count, still contributes to total."""
    q = FMPCachedAnalystRecommendationsQueryParams(symbol="AAPL")
    data = [
        {"date": "2026-06-01", "gradingCompany": "Firm A", "newGrade": "Buy"},
        {"date": "2026-06-01", "gradingCompany": "Firm X", "newGrade": "NotARealGrade"},
    ]
    out = FMPCachedAnalystRecommendationsFetcher.transform_data(q, data)
    row = out[0]
    assert row.buy == 1
    assert row.unknown_count == 1
    assert row.total == 2


def test_transform_data_ignores_rows_without_firm_name() -> None:
    """Firm-name-less rows are dropped (can't dedupe without a firm)."""
    q = FMPCachedAnalystRecommendationsQueryParams(symbol="AAPL")
    data = [
        {"date": "2026-06-01", "gradingCompany": None, "newGrade": "Buy"},
        {"date": "2026-06-01", "gradingCompany": "", "newGrade": "Buy"},
        {"date": "2026-06-01", "gradingCompany": "Firm A", "newGrade": "Buy"},
    ]
    out = FMPCachedAnalystRecommendationsFetcher.transform_data(q, data)
    assert out[0].buy == 1  # only Firm A counted
    assert out[0].total == 1


def test_transform_data_total_equals_sum_of_all_buckets() -> None:
    """Arithmetic invariant callers rely on."""
    q = FMPCachedAnalystRecommendationsQueryParams(symbol="AAPL")
    data = [
        {"date": "2026-06-01", "gradingCompany": f"Firm {i}", "newGrade": grade}
        for i, grade in enumerate(
            ["Strong Buy", "Buy", "Buy", "Hold", "Hold", "Sell", "Bogus"]
        )
    ]
    out = FMPCachedAnalystRecommendationsFetcher.transform_data(q, data)
    row = out[0]
    assert (
        row.strong_buy
        + row.buy
        + row.hold
        + row.sell
        + row.strong_sell
        + row.unknown_count
        == row.total
    )
    assert row.total == 7
