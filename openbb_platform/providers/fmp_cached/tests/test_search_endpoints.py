"""Unit tests for search-endpoint fetchers (#1038 #1039 #1040 #1041 #1042 #1044)."""

from __future__ import annotations

import pytest


@pytest.fixture
def _search_symbol_rows():
    return [
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "currency": "USD",
            "exchangeFullName": "NASDAQ Global Select",
            "exchange": "NASDAQ",
        },
        {
            "symbol": "AAPL.DE",
            "name": "Apple Inc.",
            "currency": "EUR",
            "exchangeFullName": "Deutsche Börse",
            "exchange": "XETRA",
        },
    ]


@pytest.fixture
def _cik_rows():
    return [
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "cik": "0000320193",
            "exchangeFullName": "NASDAQ Global Select",
            "exchange": "NASDAQ",
            "currency": "USD",
        }
    ]


@pytest.fixture
def _cusip_rows():
    return [
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "cusip": "037833100",
            "marketCap": 4813634055440,
        }
    ]


@pytest.fixture
def _isin_rows():
    return [
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "isin": "US0378331005",
            "marketCap": 4813634055440,
        }
    ]


def test_search_symbol_maps_exchange_full_name(_search_symbol_rows):
    """ExchangeFullName -> exchange_full_name mapping."""
    from openbb_fmp_cached.models.search_endpoints import FMPCachedSearchSymbolFetcher

    out = FMPCachedSearchSymbolFetcher.transform_data(None, _search_symbol_rows)
    assert out[0].symbol == "AAPL"
    assert out[0].exchange_full_name == "NASDAQ Global Select"
    assert out[1].currency == "EUR"


def test_search_name_uses_same_shape(_search_symbol_rows):
    """search-name shares the shared search-result Data class."""
    from openbb_fmp_cached.models.search_endpoints import FMPCachedSearchNameFetcher

    out = FMPCachedSearchNameFetcher.transform_data(None, _search_symbol_rows)
    assert out[0].name == "Apple Inc."


def test_search_cik_maps_company_name(_cik_rows):
    """CompanyName -> company_name; cik stays zero-padded string."""
    from openbb_fmp_cached.models.search_endpoints import FMPCachedSearchCikFetcher

    out = FMPCachedSearchCikFetcher.transform_data(None, _cik_rows)
    assert out[0].symbol == "AAPL"
    assert out[0].company_name == "Apple Inc."
    assert out[0].cik == "0000320193"
    assert isinstance(out[0].cik, str)


def test_search_cusip_maps_market_cap(_cusip_rows):
    """CompanyName + marketCap camelCase mapping."""
    from openbb_fmp_cached.models.search_endpoints import FMPCachedSearchCusipFetcher

    out = FMPCachedSearchCusipFetcher.transform_data(None, _cusip_rows)
    assert out[0].symbol == "AAPL"
    assert out[0].company_name == "Apple Inc."
    assert out[0].cusip == "037833100"
    assert out[0].market_cap == 4813634055440


def test_search_isin_carries_isin_field(_isin_rows):
    """search-isin returns isin + marketCap in addition to shared fields."""
    from openbb_fmp_cached.models.search_endpoints import FMPCachedSearchIsinFetcher

    out = FMPCachedSearchIsinFetcher.transform_data(None, _isin_rows)
    assert out[0].isin == "US0378331005"
    assert out[0].market_cap == 4813634055440


def test_search_exchange_variants_accepts_extra_fields():
    """search-exchange-variants returns full quote-shaped rows; extra=allow."""
    from openbb_fmp_cached.models.search_endpoints import (
        FMPCachedExchangeVariantData,
    )

    row = {
        "symbol": "AAPL",
        "price": 327.74,
        "beta": 1.097,
        "volAvg": 54959267,
        "mktCap": 4813634055440,
        "lastDiv": 1.05,
    }
    obj = FMPCachedExchangeVariantData.model_validate(row)
    assert obj.symbol == "AAPL"
    # Extra fields preserved via ConfigDict(extra=allow)
    assert obj.price == 327.74
    assert obj.mktCap == 4813634055440


def test_search_cik_uses_cik_query_field():
    """search-cik must send 'cik=' not 'query=' — regression against FMP API."""
    from openbb_fmp_cached.models.search_endpoints import FMPCachedSearchCikFetcher

    assert FMPCachedSearchCikFetcher._query_field == "cik"


def test_other_searches_use_query_field():
    """All other 5 search fetchers send 'query='."""
    from openbb_fmp_cached.models.search_endpoints import (
        FMPCachedSearchCusipFetcher,
        FMPCachedSearchExchangeVariantsFetcher,
        FMPCachedSearchIsinFetcher,
        FMPCachedSearchNameFetcher,
        FMPCachedSearchSymbolFetcher,
    )

    for fetcher in (
        FMPCachedSearchSymbolFetcher,
        FMPCachedSearchNameFetcher,
        FMPCachedSearchCusipFetcher,
        FMPCachedSearchIsinFetcher,
        FMPCachedSearchExchangeVariantsFetcher,
    ):
        assert fetcher._query_field == "query", f"{fetcher.__name__} uses wrong field"


def test_all_six_registered_in_provider():
    """Provider registration is what makes the coverage gate see them."""
    from openbb_fmp_cached import fmp_cached_provider

    for name in (
        "SearchSymbol",
        "SearchName",
        "SearchCik",
        "SearchCusip",
        "SearchIsin",
        "SearchExchangeVariants",
    ):
        assert name in fmp_cached_provider.fetcher_dict, f"{name} not registered"


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out."""
    from openbb_fmp_cached.models.search_endpoints import FMPCachedSearchSymbolFetcher

    assert FMPCachedSearchSymbolFetcher.transform_data(None, []) == []


def test_query_params_reject_missing_query():
    """_SearchQueryParams requires a query field — pydantic ValidationError otherwise."""
    from openbb_fmp_cached.models.search_endpoints import _SearchQueryParams
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _SearchQueryParams()  # missing required 'query'
