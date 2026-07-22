"""Unit tests for available-* directory fetchers (#1052-#1055)."""

from __future__ import annotations

import pytest


@pytest.fixture
def _exchange_rows():
    return [
        {
            "exchange": "NYSE",
            "name": "New York Stock Exchange",
            "countryName": "United States of America",
            "countryCode": "US",
            "symbolSuffix": "N/A",
            "delay": "Real-time",
        },
        {
            "exchange": "LSE",
            "name": "London Stock Exchange",
            "countryName": "United Kingdom",
            "countryCode": "GB",
            "symbolSuffix": ".L",
            "delay": "15 min",
        },
    ]


def test_exchanges_transform_data_maps_camelcase_to_snake(_exchange_rows):
    """FMP returns camelCase; our data model uses snake_case."""
    from openbb_fmp_cached.models.available_directories import (
        FMPCachedAvailableExchangesFetcher,
    )

    out = FMPCachedAvailableExchangesFetcher.transform_data(None, _exchange_rows)
    assert len(out) == 2
    assert out[0].exchange == "NYSE"
    assert out[0].country_name == "United States of America"
    assert out[0].country_code == "US"
    assert out[0].symbol_suffix == "N/A"
    assert out[1].exchange == "LSE"
    assert out[1].symbol_suffix == ".L"


def test_sectors_transform_data():
    """Sectors are a flat single-field list."""
    from openbb_fmp_cached.models.available_directories import (
        FMPCachedAvailableSectorsFetcher,
    )

    rows = [{"sector": "Basic Materials"}, {"sector": "Technology"}]
    out = FMPCachedAvailableSectorsFetcher.transform_data(None, rows)
    assert [r.sector for r in out] == ["Basic Materials", "Technology"]


def test_industries_transform_data():
    """Industries are a flat single-field list."""
    from openbb_fmp_cached.models.available_directories import (
        FMPCachedAvailableIndustriesFetcher,
    )

    rows = [{"industry": "Steel"}, {"industry": "Semiconductors"}]
    out = FMPCachedAvailableIndustriesFetcher.transform_data(None, rows)
    assert [r.industry for r in out] == ["Steel", "Semiconductors"]


def test_countries_transform_data():
    """Countries are ISO codes."""
    from openbb_fmp_cached.models.available_directories import (
        FMPCachedAvailableCountriesFetcher,
    )

    rows = [{"country": "US"}, {"country": "DE"}, {"country": "FK"}]
    out = FMPCachedAvailableCountriesFetcher.transform_data(None, rows)
    assert [r.country for r in out] == ["US", "DE", "FK"]


def test_all_four_registered_in_provider():
    """Provider registration is what makes the coverage gate see them."""
    from openbb_fmp_cached import fmp_cached_provider

    for name in (
        "AvailableExchanges",
        "AvailableSectors",
        "AvailableIndustries",
        "AvailableCountries",
    ):
        assert name in fmp_cached_provider.fetcher_dict, f"{name} not registered"


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out (no exception)."""
    from openbb_fmp_cached.models.available_directories import (
        FMPCachedAvailableSectorsFetcher,
    )

    assert FMPCachedAvailableSectorsFetcher.transform_data(None, []) == []


def test_exchanges_transform_data_tolerates_missing_optional_fields():
    """Symbol suffix / delay may be absent; model must accept."""
    from openbb_fmp_cached.models.available_directories import (
        FMPCachedAvailableExchangesFetcher,
    )

    rows = [{"exchange": "XYZ", "countryName": "Somewhere"}]
    out = FMPCachedAvailableExchangesFetcher.transform_data(None, rows)
    assert out[0].exchange == "XYZ"
    assert out[0].country_name == "Somewhere"
    assert out[0].symbol_suffix is None
    assert out[0].delay is None
