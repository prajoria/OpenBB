"""Unit tests for historical-directory fetchers (#1048 #1094 #1170 #1171 #1172)."""

from __future__ import annotations

import pytest


@pytest.fixture
def _hist_rows():
    return [
        {
            "dateAdded": "June 29, 2026",
            "addedSecurity": "Honeywell Aerospace Inc",
            "removedTicker": "CAG",
            "removedSecurity": "Conagra Brands",
            "date": "2026-06-29",
            "symbol": "HONA",
            "reason": "Market Capitalization Changes",
        },
        {
            "dateAdded": "July 7, 2026",
            "addedSecurity": "SpaceX",
            "removedTicker": None,
            "removedSecurity": None,
            "date": "2026-07-06",
            "symbol": "SPCX",
            "reason": "New IPO",
        },
    ]


@pytest.fixture
def _symbol_change_rows():
    return [
        {
            "date": "2026-07-21",
            "companyName": "Concorde International Group Ltd",
            "oldSymbol": "YOOV",
            "newSymbol": "CIGL",
        }
    ]


@pytest.fixture
def _shares_float_rows():
    return [
        {
            "symbol": "AAPL",
            "date": "2026-07-20 23:02:50",
            "freeFloat": 99.94,
            "floatShares": 14_800_000_000,
            "outstandingShares": 15_200_000_000,
        }
    ]


@pytest.mark.parametrize(
    "attr",
    [
        "FMPCachedHistoricalSp500ConstituentFetcher",
        "FMPCachedHistoricalNasdaqConstituentFetcher",
        "FMPCachedHistoricalDowjonesConstituentFetcher",
    ],
)
def test_historical_constituent_shared_shape(attr, _hist_rows):
    """All 3 historical-constituent fetchers use the same Data class + aliases."""
    import openbb_fmp_cached.models.historical_directories as m

    out = getattr(m, attr).transform_data(None, _hist_rows)
    assert out[0].symbol == "HONA"
    assert out[0].date_added == "June 29, 2026"
    assert out[0].added_security == "Honeywell Aerospace Inc"
    assert out[0].removed_ticker == "CAG"
    assert out[0].removed_security == "Conagra Brands"
    assert out[1].removed_ticker is None
    assert out[1].removed_security is None


def test_symbol_change_maps_camelcase(_symbol_change_rows):
    """companyName/oldSymbol/newSymbol all remap."""
    from openbb_fmp_cached.models.historical_directories import (
        FMPCachedSymbolChangeFetcher,
    )

    out = FMPCachedSymbolChangeFetcher.transform_data(None, _symbol_change_rows)
    assert out[0].date == "2026-07-21"
    assert out[0].company_name == "Concorde International Group Ltd"
    assert out[0].old_symbol == "YOOV"
    assert out[0].new_symbol == "CIGL"


def test_shares_float_all_maps_camelcase(_shares_float_rows):
    """freeFloat/floatShares/outstandingShares all remap."""
    from openbb_fmp_cached.models.historical_directories import (
        FMPCachedSharesFloatAllFetcher,
    )

    out = FMPCachedSharesFloatAllFetcher.transform_data(None, _shares_float_rows)
    assert out[0].symbol == "AAPL"
    assert out[0].free_float == pytest.approx(99.94)
    assert out[0].float_shares == 14_800_000_000
    assert out[0].outstanding_shares == 15_200_000_000


def test_all_five_registered_in_provider():
    """Provider registration is what makes the coverage gate see them."""
    from openbb_fmp_cached import fmp_cached_provider

    for name in (
        "HistoricalSp500Constituent",
        "HistoricalNasdaqConstituent",
        "HistoricalDowjonesConstituent",
        "SymbolChange",
        "SharesFloatAll",
    ):
        assert name in fmp_cached_provider.fetcher_dict, f"{name} not registered"


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out (no exception)."""
    from openbb_fmp_cached.models.historical_directories import (
        FMPCachedSymbolChangeFetcher,
    )

    assert FMPCachedSymbolChangeFetcher.transform_data(None, []) == []


def test_batch5_tables_in_allowlist_and_creator_map():
    """All 5 batch-5 tables MUST be in _ALLOWED_TABLES and _TABLE_TO_CREATOR."""
    from openbb_fmp_cached.models.available_directories import (
        _ALLOWED_TABLES,
        _TABLE_TO_CREATOR,
    )

    for tbl in (
        "historical_sp500_constituent",
        "historical_nasdaq_constituent",
        "historical_dowjones_constituent",
        "symbol_change",
        "shares_float_all",
    ):
        assert tbl in _ALLOWED_TABLES, f"{tbl} not in allowlist"
        assert tbl in _TABLE_TO_CREATOR, f"{tbl} has no creator wired"


def test_earnings_transcript_list_in_plan_limited():
    """#1051 earnings-transcript-list is Premium-tier — must be registered."""
    from openbb_fmp_cached.utils.plan_limited import get_plan_limit, is_plan_limited

    assert is_plan_limited("EarningsTranscriptList") is True
    entry = get_plan_limit("EarningsTranscriptList")
    assert entry is not None
    assert entry["tier"] == "Premium"
    assert "1051" in entry["notes"]
