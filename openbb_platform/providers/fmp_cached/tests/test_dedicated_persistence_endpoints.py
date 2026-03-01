"""Tests for dedicated persistence fetchers in fmp_cached provider."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from openbb_fmp.models.equity_peers import FMPEquityPeersQueryParams
from openbb_fmp.models.equity_profile import FMPEquityProfileQueryParams
from openbb_fmp.models.equity_quote import FMPEquityQuoteQueryParams
from openbb_fmp.models.balance_sheet import FMPBalanceSheetQueryParams
from openbb_fmp.models.cash_flow import FMPCashFlowStatementQueryParams
from openbb_fmp.models.financial_ratios import FMPFinancialRatiosQueryParams
from openbb_fmp.models.income_statement import FMPIncomeStatementQueryParams
from openbb_fmp.models.key_metrics import FMPKeyMetricsQueryParams
from openbb_fmp_cached.models.balance_sheet import FMPCachedBalanceSheetFetcher
from openbb_fmp_cached.models.cash_flow import FMPCachedCashFlowStatementFetcher
from openbb_fmp_cached.models.equity_peers import FMPCachedEquityPeersFetcher
from openbb_fmp_cached.models.equity_profile import FMPCachedEquityProfileFetcher
from openbb_fmp_cached.models.equity_quote import FMPCachedEquityQuoteFetcher
from openbb_fmp_cached.models.financial_ratios import FMPCachedFinancialRatiosFetcher
from openbb_fmp_cached.models.income_statement import FMPCachedIncomeStatementFetcher
from openbb_fmp_cached.models.key_metrics import FMPCachedKeyMetricsFetcher


def test_equity_profile_cache_hit_uses_database():
    """Profile fetcher should return cached payload without FMP call."""
    query = FMPEquityProfileQueryParams(symbol="AAPL")
    cached_payload = {"symbol": "AAPL", "companyName": "Apple Inc.", "exchange": "NASDAQ"}

    with (
        patch("openbb_fmp_cached.models.equity_profile.init_database"),
        patch("openbb_fmp_cached.models.equity_profile.create_equity_profile_table"),
        patch(
            "openbb_fmp_cached.models.equity_profile.execute_query",
            return_value=[{"data_json": json.dumps(cached_payload)}],
        ),
        patch(
            "openbb_fmp_cached.models.equity_profile.FMPEquityProfileFetcher.aextract_data",
            new_callable=AsyncMock,
        ) as mock_fmp,
    ):
        result = asyncio.run(
            FMPCachedEquityProfileFetcher.aextract_data(query, {"fmp_api_key": "key"})
        )

    assert result == [cached_payload]
    mock_fmp.assert_not_awaited()


def test_equity_quote_cache_miss_fetches_and_stores():
    """Quote fetcher should call FMP and persist when cache misses."""
    query = FMPEquityQuoteQueryParams(symbol="AAPL")
    fresh_payload = [{"symbol": "AAPL", "price": 100.0, "dayHigh": 101.0, "dayLow": 99.0}]

    with (
        patch("openbb_fmp_cached.models.equity_quote.init_database"),
        patch("openbb_fmp_cached.models.equity_quote.create_equity_quote_table"),
        patch("openbb_fmp_cached.models.equity_quote.execute_query", side_effect=[[], 1]),
        patch("openbb_fmp_cached.models.equity_quote.execute_many") as mock_many,
        patch(
            "openbb_fmp_cached.models.equity_quote.FMPEquityQuoteFetcher.aextract_data",
            new_callable=AsyncMock,
            return_value=fresh_payload,
        ) as mock_fmp,
    ):
        result = asyncio.run(
            FMPCachedEquityQuoteFetcher.aextract_data(query, {"fmp_api_key": "key"})
        )

    assert result == fresh_payload
    mock_fmp.assert_awaited_once()
    mock_many.assert_called_once()


def test_key_metrics_cache_hit_filters_ttm_only():
    """Key metrics fetcher should filter cached rows based on TTM selection."""
    query = FMPKeyMetricsQueryParams(symbol="AAPL", ttm="only", period="annual", limit=5)
    cached_rows = [
        {"data_json": json.dumps({"symbol": "AAPL", "fiscal_period": "TTM", "date": "2026-01-01"})},
        {"data_json": json.dumps({"symbol": "AAPL", "fiscal_period": "Q4", "date": "2025-12-31"})},
    ]

    with (
        patch("openbb_fmp_cached.models.key_metrics.init_database"),
        patch("openbb_fmp_cached.models.key_metrics.create_key_metrics_table"),
        patch("openbb_fmp_cached.models.key_metrics.execute_query", return_value=cached_rows),
        patch(
            "openbb_fmp_cached.models.key_metrics.FMPKeyMetricsFetcher.aextract_data",
            new_callable=AsyncMock,
        ) as mock_fmp,
    ):
        result = asyncio.run(
            FMPCachedKeyMetricsFetcher.aextract_data(query, {"fmp_api_key": "key"})
        )

    assert result == [{"symbol": "AAPL", "fiscal_period": "TTM", "date": "2026-01-01"}]
    mock_fmp.assert_not_awaited()


def test_equity_peers_cache_miss_fetches_and_stores():
    """Peers fetcher should call FMP and persist when cache misses."""
    query = FMPEquityPeersQueryParams(symbol="CLS")
    fresh_payload = [{"symbol": "JBL", "companyName": "Jabil Inc.", "mktCap": 12345, "price": 200.0}]

    with (
        patch("openbb_fmp_cached.models.equity_peers.init_database"),
        patch("openbb_fmp_cached.models.equity_peers.create_equity_peers_table"),
        patch("openbb_fmp_cached.models.equity_peers.execute_query", side_effect=[[], 1]),
        patch("openbb_fmp_cached.models.equity_peers.execute_many") as mock_many,
        patch(
            "openbb_fmp_cached.models.equity_peers.FMPEquityPeersFetcher.aextract_data",
            new_callable=AsyncMock,
            return_value=fresh_payload,
        ) as mock_fmp,
    ):
        result = asyncio.run(
            FMPCachedEquityPeersFetcher.aextract_data(query, {"fmp_api_key": "key"})
        )

    assert result == fresh_payload
    mock_fmp.assert_awaited_once()
    mock_many.assert_called_once()


def test_income_statement_cache_hit_uses_database():
    """Income statement fetcher should return cached rows without FMP call."""
    query = FMPIncomeStatementQueryParams(symbol="AAPL", period="annual", limit=2)
    cached_rows = [
        {"data_json": json.dumps({"symbol": "AAPL", "period": "annual", "date": "2025-12-31", "revenue": 1000})},
        {"data_json": json.dumps({"symbol": "AAPL", "period": "annual", "date": "2024-12-31", "revenue": 900})},
    ]

    with (
        patch("openbb_fmp_cached.models.income_statement.init_database"),
        patch("openbb_fmp_cached.models.income_statement.create_income_statement_table"),
        patch("openbb_fmp_cached.models.income_statement.execute_query", return_value=cached_rows),
        patch(
            "openbb_fmp_cached.models.income_statement.FMPIncomeStatementFetcher.aextract_data",
            new_callable=AsyncMock,
        ) as mock_fmp,
    ):
        result = asyncio.run(
            FMPCachedIncomeStatementFetcher.aextract_data(query, {"fmp_api_key": "key"})
        )

    assert len(result) == 2
    assert result[0]["symbol"] == "AAPL"
    mock_fmp.assert_not_awaited()


def test_balance_sheet_cache_miss_fetches_and_stores():
    """Balance sheet fetcher should call FMP and persist when cache misses."""
    query = FMPBalanceSheetQueryParams(symbol="AAPL", period="annual", limit=1)
    fresh_payload = [{"symbol": "AAPL", "period": "annual", "date": "2025-12-31", "totalAssets": 12345}]

    with (
        patch("openbb_fmp_cached.models.balance_sheet.init_database"),
        patch("openbb_fmp_cached.models.balance_sheet.create_balance_sheet_table"),
        patch("openbb_fmp_cached.models.balance_sheet.execute_query", side_effect=[[], 1]),
        patch("openbb_fmp_cached.models.balance_sheet.execute_many") as mock_many,
        patch(
            "openbb_fmp_cached.models.balance_sheet.FMPBalanceSheetFetcher.aextract_data",
            new_callable=AsyncMock,
            return_value=fresh_payload,
        ) as mock_fmp,
    ):
        result = asyncio.run(
            FMPCachedBalanceSheetFetcher.aextract_data(query, {"fmp_api_key": "key"})
        )

    assert result == fresh_payload
    mock_fmp.assert_awaited_once()
    mock_many.assert_called_once()


def test_cash_flow_cache_miss_fetches_and_stores():
    """Cash flow fetcher should call FMP and persist when cache misses."""
    query = FMPCashFlowStatementQueryParams(symbol="AAPL", period="annual", limit=1)
    fresh_payload = [{"symbol": "AAPL", "period": "annual", "date": "2025-12-31", "freeCashFlow": 4567}]

    with (
        patch("openbb_fmp_cached.models.cash_flow.init_database"),
        patch("openbb_fmp_cached.models.cash_flow.create_cash_flow_table"),
        patch("openbb_fmp_cached.models.cash_flow.execute_query", side_effect=[[], 1]),
        patch("openbb_fmp_cached.models.cash_flow.execute_many") as mock_many,
        patch(
            "openbb_fmp_cached.models.cash_flow.FMPCashFlowStatementFetcher.aextract_data",
            new_callable=AsyncMock,
            return_value=fresh_payload,
        ) as mock_fmp,
    ):
        result = asyncio.run(
            FMPCachedCashFlowStatementFetcher.aextract_data(query, {"fmp_api_key": "key"})
        )

    assert result == fresh_payload
    mock_fmp.assert_awaited_once()
    mock_many.assert_called_once()


def test_financial_ratios_cache_hit_filters_ttm_only():
    """Financial ratios fetcher should filter cached rows based on TTM selection."""
    query = FMPFinancialRatiosQueryParams(symbol="AAPL", ttm="only", period="annual", limit=5)
    cached_rows = [
        {"data_json": json.dumps({"symbol": "AAPL", "period": "TTM", "date": "2026-01-01"})},
        {"data_json": json.dumps({"symbol": "AAPL", "period": "annual", "date": "2025-12-31"})},
    ]

    with (
        patch("openbb_fmp_cached.models.financial_ratios.init_database"),
        patch("openbb_fmp_cached.models.financial_ratios.create_financial_ratios_table"),
        patch("openbb_fmp_cached.models.financial_ratios.execute_query", return_value=cached_rows),
        patch(
            "openbb_fmp_cached.models.financial_ratios.FMPFinancialRatiosFetcher.aextract_data",
            new_callable=AsyncMock,
        ) as mock_fmp,
    ):
        result = asyncio.run(
            FMPCachedFinancialRatiosFetcher.aextract_data(query, {"fmp_api_key": "key"})
        )

    assert result == [{"symbol": "AAPL", "period": "TTM", "date": "2026-01-01"}]
    mock_fmp.assert_not_awaited()
