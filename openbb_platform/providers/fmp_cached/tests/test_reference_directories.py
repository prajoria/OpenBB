"""Unit tests for reference-directory fetchers (#1102 #1110 #1167 #1168 #1169)."""

from __future__ import annotations

import pytest


@pytest.fixture
def _index_rows():
    return [
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "sector": "Technology",
            "subSector": "Consumer Electronics",
            "headQuarter": "Cupertino, CA",
            "dateFirstAdded": "1982-11-30",
            "cik": "0000320193",
            "founded": "1976-04-01",
        },
        {
            "symbol": "GOOGL",
            "name": "Alphabet Inc.",
            "sector": "Communication Services",
            "subSector": "Internet Content & Information",
            "headQuarter": "Mountain View, CA",
            "dateFirstAdded": None,
            "cik": "0001652044",
            "founded": "1998-09-04",
        },
    ]


@pytest.fixture
def _cot_rows():
    return [
        {"symbol": "NG", "name": "Natural Gas (NG)"},
        {"symbol": "GC", "name": "Gold (GC)"},
    ]


@pytest.fixture
def _mrp_rows():
    return [
        {
            "country": "Zimbabwe",
            "continent": "Africa",
            "countryRiskPremium": 11.66,
            "totalEquityRiskPremium": 15.89,
        },
        {
            "country": "United States",
            "continent": "North America",
            "countryRiskPremium": 0.0,
            "totalEquityRiskPremium": 4.23,
        },
    ]


@pytest.mark.parametrize(
    "fetcher_module_attr",
    [
        "FMPCachedSp500ConstituentFetcher",
        "FMPCachedNasdaqConstituentFetcher",
        "FMPCachedDowjonesConstituentFetcher",
    ],
)
def test_index_constituent_shared_shape(fetcher_module_attr, _index_rows):
    """All 3 index-constituent fetchers use the same Data class and alias map."""
    import openbb_fmp_cached.models.reference_directories as m

    fetcher = getattr(m, fetcher_module_attr)
    out = fetcher.transform_data(None, _index_rows)
    assert len(out) == 2
    assert out[0].symbol == "AAPL"
    assert out[0].sub_sector == "Consumer Electronics"
    assert out[0].head_quarter == "Cupertino, CA"
    assert out[0].date_first_added == "1982-11-30"
    assert out[0].cik == "0000320193"
    assert out[1].date_first_added is None  # tolerate null


def test_cot_list_flat_shape(_cot_rows):
    """CFTC COT list is flat {symbol, name}."""
    from openbb_fmp_cached.models.reference_directories import FMPCachedCotListFetcher

    out = FMPCachedCotListFetcher.transform_data(None, _cot_rows)
    assert [r.symbol for r in out] == ["NG", "GC"]
    assert out[0].name == "Natural Gas (NG)"


def test_market_risk_premium_maps_camelcase(_mrp_rows):
    """countryRiskPremium/totalEquityRiskPremium both remap."""
    from openbb_fmp_cached.models.reference_directories import (
        FMPCachedMarketRiskPremiumFetcher,
    )

    out = FMPCachedMarketRiskPremiumFetcher.transform_data(None, _mrp_rows)
    assert out[0].country == "Zimbabwe"
    assert out[0].country_risk_premium == pytest.approx(11.66)
    assert out[0].total_equity_risk_premium == pytest.approx(15.89)
    assert out[1].country_risk_premium == 0.0  # zero is not None


def test_all_five_registered_in_provider():
    """Provider registration is what makes the coverage gate see them."""
    from openbb_fmp_cached import fmp_cached_provider

    for name in (
        "Sp500Constituent",
        "NasdaqConstituent",
        "DowjonesConstituent",
        "CommitmentOfTradersList",
        "MarketRiskPremium",
    ):
        assert name in fmp_cached_provider.fetcher_dict, f"{name} not registered"


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out (no exception)."""
    from openbb_fmp_cached.models.reference_directories import (
        FMPCachedSp500ConstituentFetcher,
    )

    assert FMPCachedSp500ConstituentFetcher.transform_data(None, []) == []


def test_batch4_tables_in_allowlist_and_creator_map():
    """All 5 batch-4 tables MUST be in both _ALLOWED_TABLES and _TABLE_TO_CREATOR.

    Guards the specific failure mode we designed the map-based dispatch to
    catch: forgetting to wire a creator when adding a new allowlist entry.
    """
    from openbb_fmp_cached.models.available_directories import (
        _ALLOWED_TABLES,
        _TABLE_TO_CREATOR,
    )

    for tbl in (
        "sp500_constituent",
        "nasdaq_constituent",
        "dowjones_constituent",
        "commitment_of_traders_list",
        "market_risk_premium",
    ):
        assert tbl in _ALLOWED_TABLES, f"{tbl} not in allowlist"
        assert tbl in _TABLE_TO_CREATOR, f"{tbl} has no creator wired"
