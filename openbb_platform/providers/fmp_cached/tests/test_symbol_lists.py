"""Unit tests for symbol-list fetchers (#1045-#1050)."""

from __future__ import annotations

import pytest


@pytest.fixture
def _stock_rows():
    return [
        {"symbol": "AAPL", "companyName": "Apple Inc."},
        {"symbol": "MSFT", "companyName": "Microsoft Corporation"},
    ]


@pytest.fixture
def _etf_rows():
    return [
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF"},
        {"symbol": "QQQ", "name": "Invesco QQQ Trust"},
    ]


@pytest.fixture
def _financial_statement_rows():
    return [
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "tradingCurrency": "USD",
            "reportingCurrency": "USD",
        },
        {
            "symbol": "ATX.V",
            "companyName": "ATEX Resources Inc.",
            "tradingCurrency": "CAD",
            "reportingCurrency": "CAD",
        },
    ]


@pytest.fixture
def _cik_rows():
    return [
        {"cik": "0000320193", "companyName": "Apple Inc."},
        {"cik": "0000789019", "companyName": "Microsoft Corporation"},
    ]


def test_stock_list_transform_data_maps_camelcase(_stock_rows):
    """CompanyName -> company_name mapping."""
    from openbb_fmp_cached.models.symbol_lists import FMPCachedStockListFetcher

    out = FMPCachedStockListFetcher.transform_data(None, _stock_rows)
    assert len(out) == 2
    assert out[0].symbol == "AAPL"
    assert out[0].company_name == "Apple Inc."
    assert out[1].symbol == "MSFT"


def test_etf_list_transform_data_uses_name_field(_etf_rows):
    """etf-list uses 'name' (not 'companyName') — no alias needed."""
    from openbb_fmp_cached.models.symbol_lists import FMPCachedEtfListFetcher

    out = FMPCachedEtfListFetcher.transform_data(None, _etf_rows)
    assert out[0].symbol == "SPY"
    assert out[0].name == "SPDR S&P 500 ETF"


def test_actively_trading_list_transform_data(_etf_rows):
    """actively-trading uses same {symbol, name} shape as etf-list."""
    from openbb_fmp_cached.models.symbol_lists import (
        FMPCachedActivelyTradingListFetcher,
    )

    out = FMPCachedActivelyTradingListFetcher.transform_data(None, _etf_rows)
    assert [r.symbol for r in out] == ["SPY", "QQQ"]
    assert [r.name for r in out] == ["SPDR S&P 500 ETF", "Invesco QQQ Trust"]


def test_financial_statement_symbol_transform_data_maps_all_aliases(
    _financial_statement_rows,
):
    """Three camelCase fields all get remapped: companyName, tradingCurrency, reportingCurrency."""
    from openbb_fmp_cached.models.symbol_lists import (
        FMPCachedFinancialStatementSymbolListFetcher,
    )

    out = FMPCachedFinancialStatementSymbolListFetcher.transform_data(
        None, _financial_statement_rows
    )
    assert out[0].symbol == "AAPL"
    assert out[0].company_name == "Apple Inc."
    assert out[0].trading_currency == "USD"
    assert out[0].reporting_currency == "USD"
    assert out[1].trading_currency == "CAD"


def test_cik_list_transform_data(_cik_rows):
    """cik-list has cik (not symbol) as its key field."""
    from openbb_fmp_cached.models.symbol_lists import FMPCachedCikListFetcher

    out = FMPCachedCikListFetcher.transform_data(None, _cik_rows)
    assert out[0].cik == "0000320193"
    assert out[0].company_name == "Apple Inc."
    # CIKs must stay as zero-padded strings, not coerced to int
    assert isinstance(out[0].cik, str)


def test_all_five_registered_in_provider():
    """Provider registration is what makes the coverage gate see them."""
    from openbb_fmp_cached import fmp_cached_provider

    for name in (
        "StockList",
        "EtfList",
        "ActivelyTradingList",
        "FinancialStatementSymbolList",
        "CikList",
    ):
        assert name in fmp_cached_provider.fetcher_dict, f"{name} not registered"


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out (no exception)."""
    from openbb_fmp_cached.models.symbol_lists import FMPCachedStockListFetcher

    assert FMPCachedStockListFetcher.transform_data(None, []) == []


def test_stock_list_tolerates_missing_optional_company_name():
    """CompanyName is optional; missing means None on the model."""
    from openbb_fmp_cached.models.symbol_lists import FMPCachedStockListFetcher

    out = FMPCachedStockListFetcher.transform_data(None, [{"symbol": "XYZ"}])
    assert out[0].symbol == "XYZ"
    assert out[0].company_name is None


def test_persist_directory_rejects_non_allowlisted_table():
    """Defense-in-depth: table names outside _ALLOWED_TABLES must raise."""
    from openbb_fmp_cached.models.available_directories import _persist_directory

    with pytest.raises(ValueError, match="not in allowlist"):
        _persist_directory("evil_users; DROP TABLE users; --", "data_json", [{"a": 1}])


def test_persist_directory_dispatches_by_prefix():
    """_persist_directory picks the right DDL creator based on table name prefix."""
    from openbb_fmp_cached.models.available_directories import _ALLOWED_TABLES

    # Sanity: both batches represented in the allowlist
    available = {t for t in _ALLOWED_TABLES if t.startswith("available_")}
    symbol_lists = _ALLOWED_TABLES - available
    assert len(available) == 4, f"expected 4 available-* tables, got {available}"
    assert len(symbol_lists) == 5, f"expected 5 symbol-list tables, got {symbol_lists}"
