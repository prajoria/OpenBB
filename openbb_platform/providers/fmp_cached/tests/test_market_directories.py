"""Unit tests for market-directory fetchers (#1158 #1173 #1182 #1197)."""

from __future__ import annotations

import pytest


@pytest.fixture
def _commodities_rows():
    return [
        {
            "symbol": "ZMUSD",
            "name": "Soybean Meal Futures",
            "exchange": None,
            "tradeMonth": "Dec",
            "currency": "USD",
        },
        {
            "symbol": "CLUSD",
            "name": "Crude Oil Futures",
            "exchange": "NYMEX",
            "tradeMonth": "Jan",
            "currency": "USD",
        },
    ]


@pytest.fixture
def _crypto_rows():
    return [
        {
            "symbol": "BTCUSD",
            "name": "Bitcoin USD",
            "exchange": "CCC",
            "icoDate": None,
            "circulatingSupply": 19_500_000,
            "totalSupply": 21_000_000,
        },
        {
            "symbol": "MIOTAUSD",
            "name": "IOTA USD",
            "exchange": "CCC",
            "icoDate": "2017-11-09",
            "circulatingSupply": 4_232_705_124,
            "totalSupply": 4_788_606_639,
        },
    ]


@pytest.fixture
def _forex_rows():
    return [
        {
            "symbol": "EURUSD",
            "fromCurrency": "EUR",
            "toCurrency": "USD",
            "fromName": "Euro",
            "toName": "US Dollar",
        },
        {
            "symbol": "ARSMXN",
            "fromCurrency": "ARS",
            "toCurrency": "MXN",
            "fromName": "Argentine Peso",
            "toName": "Mexican Peso",
        },
    ]


@pytest.fixture
def _index_rows():
    return [
        {
            "symbol": "^GSPC",
            "name": "S&P 500",
            "exchange": "SNP",
            "currency": "USD",
        },
        {
            "symbol": "^TTIN",
            "name": "S&P/TSX Capped Industrials Index",
            "exchange": "TSX",
            "currency": "CAD",
        },
    ]


def test_commodities_list_maps_trade_month(_commodities_rows):
    """TradeMonth -> trade_month camelCase mapping."""
    from openbb_fmp_cached.models.market_directories import (
        FMPCachedCommoditiesListFetcher,
    )

    out = FMPCachedCommoditiesListFetcher.transform_data(None, _commodities_rows)
    assert out[0].symbol == "ZMUSD"
    assert out[0].trade_month == "Dec"
    assert out[0].exchange is None  # tolerate null
    assert out[1].trade_month == "Jan"
    assert out[1].exchange == "NYMEX"


def test_cryptocurrency_list_maps_all_camelcase(_crypto_rows):
    """icoDate, circulatingSupply, totalSupply all remap."""
    from openbb_fmp_cached.models.market_directories import (
        FMPCachedCryptocurrencyListFetcher,
    )

    out = FMPCachedCryptocurrencyListFetcher.transform_data(None, _crypto_rows)
    assert out[0].symbol == "BTCUSD"
    assert out[0].ico_date is None
    assert out[0].circulating_supply == 19_500_000
    assert out[0].total_supply == 21_000_000
    assert out[1].ico_date == "2017-11-09"


def test_forex_list_maps_pair_fields(_forex_rows):
    """fromCurrency/toCurrency/fromName/toName all remap."""
    from openbb_fmp_cached.models.market_directories import FMPCachedForexListFetcher

    out = FMPCachedForexListFetcher.transform_data(None, _forex_rows)
    assert out[0].symbol == "EURUSD"
    assert out[0].from_currency == "EUR"
    assert out[0].to_currency == "USD"
    assert out[0].from_name == "Euro"
    assert out[0].to_name == "US Dollar"


def test_index_list_no_aliases_needed(_index_rows):
    """index-list uses only snake-compatible field names."""
    from openbb_fmp_cached.models.market_directories import FMPCachedIndexListFetcher

    out = FMPCachedIndexListFetcher.transform_data(None, _index_rows)
    assert out[0].symbol == "^GSPC"
    assert out[0].name == "S&P 500"
    assert out[0].currency == "USD"


def test_all_four_registered_in_provider():
    """Provider registration is what makes the coverage gate see them."""
    from openbb_fmp_cached import fmp_cached_provider

    for name in ("CommoditiesList", "CryptocurrencyList", "ForexList", "IndexList"):
        assert name in fmp_cached_provider.fetcher_dict, f"{name} not registered"


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out (no exception)."""
    from openbb_fmp_cached.models.market_directories import (
        FMPCachedCommoditiesListFetcher,
    )

    assert FMPCachedCommoditiesListFetcher.transform_data(None, []) == []


def test_allowlist_and_creator_map_stay_aligned():
    """Every _ALLOWED_TABLES entry MUST have a matching _TABLE_TO_CREATOR entry.

    This is the regression guard for adding a table to the allowlist but
    forgetting to wire its DDL creator — the old prefix-guessing dispatch
    would have silently used the wrong creator; the new explicit-map
    dispatch would KeyError at runtime. This test forces the drift to
    show up at test time.
    """
    from openbb_fmp_cached.models.available_directories import (
        _ALLOWED_TABLES,
        _TABLE_TO_CREATOR,
    )

    missing_creator = _ALLOWED_TABLES - set(_TABLE_TO_CREATOR.keys())
    extra_creator = set(_TABLE_TO_CREATOR.keys()) - _ALLOWED_TABLES
    assert (
        not missing_creator
    ), f"tables in allowlist missing creator: {missing_creator}"
    assert not extra_creator, f"creators with no allowlist entry: {extra_creator}"


def test_market_directory_tables_included_in_allowlist():
    """All 4 batch-3 tables are in the allowlist."""
    from openbb_fmp_cached.models.available_directories import _ALLOWED_TABLES

    for tbl in ("commodities_list", "cryptocurrency_list", "forex_list", "index_list"):
        assert tbl in _ALLOWED_TABLES, f"{tbl} not in allowlist"
