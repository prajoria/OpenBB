"""Tests for dedicated persistence fetchers in fmp_cached provider."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from openbb_fmp.models.equity_peers import FMPEquityPeersQueryParams
from openbb_fmp.models.equity_profile import FMPEquityProfileQueryParams
from openbb_fmp.models.equity_quote import FMPEquityQuoteQueryParams
from openbb_fmp.models.key_metrics import FMPKeyMetricsQueryParams
from openbb_fmp_cached.models.equity_peers import FMPCachedEquityPeersFetcher
from openbb_fmp_cached.models.equity_profile import FMPCachedEquityProfileFetcher
from openbb_fmp_cached.models.equity_quote import FMPCachedEquityQuoteFetcher
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
