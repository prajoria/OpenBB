"""Unit tests for FMP Cached provider modules.

Historical note (closed by #785 and #784):

- **#785** — checked in the 4 missing VCR cassettes for the
  ``@pytest.mark.record_http`` fetcher tests and fixed a real
  ``date``-in-URL bug in ``_fetch_from_fmp_direct``.
- **#784** — realigned this file against the current production API
  surface after several refactors:

  * ``create_cached_fetcher_class`` now returns a ``Fallback…`` class,
    not a ``Cached…`` class. The wrapper still delegates to the
    original fetcher; it just has a different name.
  * ``base_cached`` no longer exposes ``get_cache_manager`` /
    ``init_database``. Caching orchestration lives in the individual
    fetcher subclasses now (each hits ``utils.cache_manager`` or
    ``utils.database`` directly). The old ``mock_cache_manager`` /
    ``mock_database`` fixtures targeted an orchestration seam that no
    longer exists — the two flow tests they backed have been reshaped
    into contract tests against the current ``DatabaseManager`` API.
  * ``generate_cache_key(endpoint, params: dict)`` — was
    ``**kwargs``. Same idea, different call shape.
  * ``get_table_for_endpoint`` returns the bare table name
    (``"equity_historical"``) — the ``cache_`` prefix is gone.
  * ``get_ttl_for_endpoint`` was removed with the schema simplification
    (see ``cache_schema.py`` docstring: "no longer use TTL/expiry").
    ``CACHE_TTL`` was removed with it.
  * ``DatabaseManager.get_stats()`` reports ``database_hits`` /
    ``database_misses`` (was ``cache_hits`` / ``cache_misses``).
  * Provider ``.credentials`` is ``["fmp_cached_api_key"]`` (was
    ``["api_key"]``) — the credential is namespaced now.

The four ``@pytest.mark.record_http`` fetcher smoke tests below replay
cassettes under ``tests/record/http/test_fmp_cached_fetchers/``.
"""

import re
from datetime import date

import pytest
from openbb_core.app.service.user_service import UserService
from openbb_fmp.models.equity_historical import FMPEquityHistoricalFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

test_credentials = UserService().default_user_settings.credentials.model_dump(
    mode="json"
)


def response_filter(response):
    """Filter the response."""
    if "Location" in response["headers"]:
        response["headers"]["Location"] = [
            re.sub(r"apikey=[^&]+", "apikey=MOCK_API_KEY", x)
            for x in response["headers"]["Location"]
        ]
    return response


@pytest.fixture(scope="module")
def vcr_config():
    """VCR configuration."""
    return {
        "filter_headers": [("User-Agent", None)],
        "filter_query_parameters": [
            ("apikey", "MOCK_API_KEY"),
        ],
        "before_record_response": response_filter,
    }


class TestCachedFetcher:
    """Contract tests for ``create_cached_fetcher_class``."""

    def test_create_cached_fetcher_class(self):
        """The wrapper is a subclass of the original fetcher.

        The wrapper's ``__name__`` starts with ``Fallback`` — the class
        was renamed during the DB-backed rewrite. #784.
        """
        CachedFetcher = create_cached_fetcher_class(
            FMPEquityHistoricalFetcher, "EquityHistorical"
        )
        assert isinstance(CachedFetcher, type)
        assert issubclass(CachedFetcher, FMPEquityHistoricalFetcher)
        # Wrapper class-name prefix is `Fallback…` after the refactor.
        assert CachedFetcher.__name__.startswith("Fallback")


class TestCacheManager:
    """Contract tests for ``utils.cache_manager`` public API."""

    def test_generate_cache_key_deterministic(self):
        """Same (endpoint, params) → same key; different → different."""
        from openbb_fmp_cached.utils.cache_manager import generate_cache_key

        p1 = {"symbol": "AAPL", "interval": "1d"}
        key1 = generate_cache_key("EquityHistorical", p1)
        key2 = generate_cache_key("EquityHistorical", dict(p1))
        assert key1 == key2

        p2 = {"symbol": "GOOGL", "interval": "1d"}
        key3 = generate_cache_key("EquityHistorical", p2)
        assert key1 != key3

    def test_get_table_for_endpoint(self):
        """``get_table_for_endpoint`` returns the bare table name.

        Endpoints that use the row-oriented persistence path resolve to
        a table name (``equity_historical``, ``balance_sheet``,
        ``income_statement``). Endpoints that use the TTL-cache /
        per-symbol flow instead (like ``EquityQuote``) return ``None``
        by design — they don't have a fixed schema table.
        """
        from openbb_fmp_cached.utils.cache_manager import get_table_for_endpoint

        # The `cache_` prefix used by the old tests is gone — table
        # names are stored bare (openbb_fmp_cached uses its own DB, so
        # there is no collision risk).
        assert get_table_for_endpoint("EquityHistorical") == "equity_historical"
        assert get_table_for_endpoint("BalanceSheet") == "balance_sheet"
        assert get_table_for_endpoint("IncomeStatement") == "income_statement"
        # Endpoints outside the row-persistence set return None.
        assert get_table_for_endpoint("EquityQuote") is None
        assert get_table_for_endpoint("NotARealEndpoint") is None


@pytest.mark.record_http
def test_fmp_cached_equity_historical_fetcher(credentials=test_credentials):
    """Test FMP cached equity historical fetcher."""
    from openbb_fmp_cached import fmp_cached_provider

    cached_fetcher_class = fmp_cached_provider.fetcher_dict["EquityHistorical"]

    params = {
        "symbol": "AAPL",
        "start_date": date(2023, 1, 1),
        "end_date": date(2023, 1, 10),
        "interval": "1d",
    }

    fetcher = cached_fetcher_class()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_cached_balance_sheet_fetcher(credentials=test_credentials):
    """Test FMP cached balance sheet fetcher."""
    from openbb_fmp_cached import fmp_cached_provider

    cached_fetcher_class = fmp_cached_provider.fetcher_dict["BalanceSheet"]

    params = {"symbol": "AAPL", "limit": 1}

    fetcher = cached_fetcher_class()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_cached_equity_quote_fetcher(credentials=test_credentials):
    """Test FMP cached equity quote fetcher."""
    from openbb_fmp_cached import fmp_cached_provider

    cached_fetcher_class = fmp_cached_provider.fetcher_dict["EquityQuote"]

    params = {"symbol": "AAPL"}

    fetcher = cached_fetcher_class()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_cached_income_statement_fetcher(credentials=test_credentials):
    """Test FMP cached income statement fetcher."""
    from openbb_fmp_cached import fmp_cached_provider

    cached_fetcher_class = fmp_cached_provider.fetcher_dict["IncomeStatement"]

    params = {"symbol": "AAPL", "limit": 1}

    fetcher = cached_fetcher_class()
    result = fetcher.test(params, credentials)
    assert result is None


class TestDatabaseOperations:
    """Test database operations (requires actual DB connection)."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_database_schema_creation(self):
        """Test database schema creation."""
        try:
            from openbb_fmp_cached.utils.database import init_database

            await init_database()
            assert True
        except Exception as e:
            pytest.skip(f"Database not available: {e}")


class TestProviderRegistration:
    """Test provider registration and configuration."""

    def test_provider_import(self):
        """Test provider can be imported."""
        from openbb_fmp_cached import fmp_cached_provider

        assert fmp_cached_provider.name == "fmp_cached"
        assert len(fmp_cached_provider.fetcher_dict) > 0
        assert "EquityHistorical" in fmp_cached_provider.fetcher_dict

    def test_provider_credentials(self):
        """Provider exposes the namespaced credential key.

        The cached provider ships its own credential name so users can
        keep a separate cache API key from the raw FMP one. #784.
        """
        from openbb_fmp_cached import fmp_cached_provider

        assert fmp_cached_provider.credentials == ["fmp_cached_api_key"]

    def test_fetcher_classes_created(self):
        """Test all fetcher classes are properly created."""
        from openbb_fmp_cached import fmp_cached_provider

        key_fetchers = [
            "EquityHistorical",
            "BalanceSheet",
            "IncomeStatement",
            "EquityQuote",
            "CompanyNews",
        ]

        for fetcher_name in key_fetchers:
            assert fetcher_name in fmp_cached_provider.fetcher_dict
            fetcher_class = fmp_cached_provider.fetcher_dict[fetcher_name]
            assert callable(fetcher_class)


class TestPerformance:
    """Performance and efficiency tests."""

    def test_cache_performance_stats(self):
        """``DatabaseManager.get_stats`` reports the current key set.

        Keys were renamed in the DB-backed rewrite:
        ``cache_hits`` → ``database_hits``,
        ``cache_misses`` → ``database_misses``. #784.
        """
        from openbb_fmp_cached.utils.cache_manager import get_cache_manager

        cache_manager = get_cache_manager()
        stats = cache_manager.get_stats()

        expected_keys = [
            "total_requests",
            "database_hits",
            "database_misses",
            "hit_rate_percent",
        ]
        for key in expected_keys:
            assert key in stats
            assert isinstance(stats[key], (int, float))

    @pytest.mark.asyncio
    async def test_cleanup_operations(self):
        """Test cache cleanup operations."""
        try:
            from openbb_fmp_cached.utils.cache_schema import cleanup_expired_cache

            result = cleanup_expired_cache()
            # The simplified schema returns a diagnostic dict, not a
            # deletion count (#784 — TTL/expiry removed from the schema).
            assert isinstance(result, dict)
        except Exception as e:
            pytest.skip(f"Database not available: {e}")


class TestConfiguration:
    """Test configuration and setup."""

    def test_user_settings_structure(self):
        """Test user settings structure."""
        from openbb_fmp_cached.utils.database import DatabaseConfig

        config = DatabaseConfig()
        assert hasattr(config, "config")
        assert "host" in config.config
        assert "database" in config.config


if __name__ == "__main__":
    pytest.main([__file__])


@pytest.mark.record_http
def test_fmp_cached_equity_profile_fetcher(credentials=test_credentials):
    """Test FMP cached equity profile fetcher (#508)."""
    from openbb_fmp_cached import fmp_cached_provider

    cached_fetcher_class = fmp_cached_provider.fetcher_dict["EquityInfo"]

    params = {"symbol": "AAPL"}

    fetcher = cached_fetcher_class()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_cached_etf_holdings_fetcher(credentials=test_credentials):
    """Test FMP cached ETF holdings fetcher (#508)."""
    from openbb_fmp_cached import fmp_cached_provider

    cached_fetcher_class = fmp_cached_provider.fetcher_dict["EtfHoldings"]

    params = {"symbol": "SPY"}

    fetcher = cached_fetcher_class()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_cached_etf_info_fetcher(credentials=test_credentials):
    """Test FMP cached ETF info fetcher (#508)."""
    from openbb_fmp_cached import fmp_cached_provider

    cached_fetcher_class = fmp_cached_provider.fetcher_dict["EtfInfo"]

    params = {"symbol": "SPY"}

    fetcher = cached_fetcher_class()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_cached_etf_sectors_fetcher(credentials=test_credentials):
    """Test FMP cached ETF sectors fetcher (#508)."""
    from openbb_fmp_cached import fmp_cached_provider

    cached_fetcher_class = fmp_cached_provider.fetcher_dict["EtfSectors"]

    params = {"symbol": "SPY"}

    fetcher = cached_fetcher_class()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_cached_etf_countries_fetcher(credentials=test_credentials):
    """Test FMP cached ETF countries fetcher (#508)."""
    from openbb_fmp_cached import fmp_cached_provider

    cached_fetcher_class = fmp_cached_provider.fetcher_dict["EtfCountries"]

    params = {"symbol": "SPY"}

    fetcher = cached_fetcher_class()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_cached_financial_ratios_fetcher(credentials=test_credentials):
    """Test FMP cached financial ratios fetcher (#508)."""
    from openbb_fmp_cached import fmp_cached_provider

    cached_fetcher_class = fmp_cached_provider.fetcher_dict["FinancialRatios"]

    params = {"symbol": "AAPL", "limit": 1}

    fetcher = cached_fetcher_class()
    result = fetcher.test(params, credentials)
    assert result is None


# ---------------------------------------------------------------------------
# #955 drain batch 1 — 15 single-symbol endpoints
# ---------------------------------------------------------------------------


@pytest.mark.record_http
def test_fmp_cached_analyst_estimates_fetcher(credentials=test_credentials):
    """Test FMP cached analyst estimates fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["AnalystEstimates"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_balance_sheet_growth_fetcher(credentials=test_credentials):
    """Test FMP cached balance sheet growth fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["BalanceSheetGrowth"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL", "limit": 1}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_cash_flow_fetcher(credentials=test_credentials):
    """Test FMP cached cash flow statement fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CashFlowStatement"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL", "limit": 1}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_cash_flow_growth_fetcher(credentials=test_credentials):
    """Test FMP cached cash flow statement growth fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CashFlowStatementGrowth"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL", "limit": 1}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_income_statement_growth_fetcher(credentials=test_credentials):
    """Test FMP cached income statement growth fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["IncomeStatementGrowth"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL", "limit": 1}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_key_metrics_fetcher(credentials=test_credentials):
    """Test FMP cached key metrics fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["KeyMetrics"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL", "limit": 1}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_key_executives_fetcher(credentials=test_credentials):
    """Test FMP cached key executives fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["KeyExecutives"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_executive_compensation_fetcher(credentials=test_credentials):
    """Test FMP cached executive compensation fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["ExecutiveCompensation"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_historical_dividends_fetcher(credentials=test_credentials):
    """Test FMP cached historical dividends fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["HistoricalDividends"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_historical_splits_fetcher(credentials=test_credentials):
    """Test FMP cached historical splits fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["HistoricalSplits"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_historical_market_cap_fetcher(credentials=test_credentials):
    """Test FMP cached historical market cap fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["HistoricalMarketCap"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_historical_eps_fetcher(credentials=test_credentials):
    """Test FMP cached historical EPS fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["HistoricalEps"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_price_target_fetcher(credentials=test_credentials):
    """Test FMP cached price target fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["PriceTarget"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_share_statistics_fetcher(credentials=test_credentials):
    """Test FMP cached share statistics fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["ShareStatistics"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


# ---------------------------------------------------------------------------
# #955 drain batch 2 — 14 more (calendars, news, forwards, historical)
# ---------------------------------------------------------------------------


@pytest.mark.record_http
def test_fmp_cached_calendar_events_fetcher(credentials=test_credentials):
    """Test FMP cached calendar events fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CalendarEvents"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_company_news_fetcher(credentials=test_credentials):
    """Test FMP cached company news fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CompanyNews"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL", "limit": 5}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_world_news_fetcher(credentials=test_credentials):
    """Test FMP cached world news fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["WorldNews"]
    fetcher = cls()
    assert fetcher.test({"limit": 5}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_forward_ebitda_estimates_fetcher(credentials=test_credentials):
    """Test FMP cached forward EBITDA estimates fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["ForwardEbitdaEstimates"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_forward_eps_estimates_fetcher(credentials=test_credentials):
    """Test FMP cached forward EPS estimates fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["ForwardEpsEstimates"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_price_target_consensus_fetcher(credentials=test_credentials):
    """Test FMP cached price target consensus fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["PriceTargetConsensus"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_historical_employees_fetcher(credentials=test_credentials):
    """Test FMP cached historical employees fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["HistoricalEmployees"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_equity_peers_fetcher(credentials=test_credentials):
    """Test FMP cached equity peers fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["EquityPeers"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


# ---------------------------------------------------------------------------
# #955 drain batch 3 — 15 more (market discovery + historical + symbol-based)
# ---------------------------------------------------------------------------


@pytest.mark.record_http
def test_fmp_cached_available_indices_fetcher(credentials=test_credentials):
    """Test FMP cached available indices fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["AvailableIndices"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_equity_gainers_fetcher(credentials=test_credentials):
    """Test FMP cached equity gainers fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["EquityGainers"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_equity_losers_fetcher(credentials=test_credentials):
    """Test FMP cached equity losers fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["EquityLosers"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_etf_search_fetcher(credentials=test_credentials):
    """Test FMP cached ETF search fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["EtfSearch"]
    fetcher = cls()
    assert fetcher.test({"query": "vanguard"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_currency_pairs_fetcher(credentials=test_credentials):
    """Test FMP cached currency pairs fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CurrencyPairs"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_revenue_business_line_fetcher(credentials=test_credentials):
    """Test FMP cached revenue by business line fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["RevenueBusinessLine"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_revenue_geographic_fetcher(credentials=test_credentials):
    """Test FMP cached revenue by geographic segment fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["RevenueGeographic"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_company_filings_fetcher(credentials=test_credentials):
    """Test FMP cached company filings fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CompanyFilings"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL", "limit": 5}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_treasury_rates_fetcher(credentials=test_credentials):
    """Test FMP cached treasury rates fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["TreasuryRates"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


# ---------------------------------------------------------------------------
# #955 drain batch 4 — 15 more (aftermarket, insider, institutional, index)
# ---------------------------------------------------------------------------


@pytest.mark.record_http
def test_fmp_cached_aftermarket_quote_fetcher(credentials=test_credentials):
    """Test FMP cached aftermarket quote fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["AftermarketQuote"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_aftermarket_trade_fetcher(credentials=test_credentials):
    """Test FMP cached aftermarket trade fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["AftermarketTrade"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_equity_quote_batch_short_fetcher(credentials=test_credentials):
    """Test FMP cached equity quote batch short fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["EquityQuoteBatchShort"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_insider_trading_fetcher(credentials=test_credentials):
    """Test FMP cached insider trading fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["InsiderTrading"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL", "limit": 5}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_government_trades_fetcher(credentials=test_credentials):
    """Test FMP cached government trades fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["GovernmentTrades"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_discovery_filings_fetcher(credentials=test_credentials):
    """Test FMP cached discovery filings fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["DiscoveryFilings"]
    fetcher = cls()
    assert fetcher.test({"limit": 5}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_exchange_market_hours_fetcher(credentials=test_credentials):
    """Test FMP cached exchange market hours fetcher (#955)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["ExchangeMarketHours"]
    fetcher = cls()
    assert fetcher.test({"exchange": "NYSE"}, credentials) is None


# ---------------------------------------------------------------------------
# #955 drain � date-coercion-safe tests using date() objects
# ---------------------------------------------------------------------------
# Each of the following endpoints was previously on _KNOWN_UNCOVERED with
# "Fetcher.test date-coercion assertion mismatch" � the round-trip
# assertion at Fetcher.test line 157-159 fails because pydantic coerces
# string date inputs to datetime.date but the assertion compares the
# ORIGINAL string against the coerced object. Passing date() objects up-
# front avoids the mismatch entirely without needing to patch upstream.


@pytest.mark.record_http
def test_fmp_cached_calendar_dividend_fetcher(credentials=test_credentials):
    """Test FMP cached calendar dividend fetcher (#955 drain)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CalendarDividend"]
    fetcher = cls()
    assert (
        fetcher.test(
            {"start_date": date(2024, 1, 1), "end_date": date(2024, 1, 7)},
            credentials,
        )
        is None
    )


@pytest.mark.record_http
def test_fmp_cached_calendar_earnings_fetcher(credentials=test_credentials):
    """Test FMP cached calendar earnings fetcher (#955 drain)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CalendarEarnings"]
    fetcher = cls()
    assert (
        fetcher.test(
            {"start_date": date(2024, 1, 22), "end_date": date(2024, 1, 26)},
            credentials,
        )
        is None
    )


@pytest.mark.record_http
def test_fmp_cached_calendar_ipo_fetcher(credentials=test_credentials):
    """Test FMP cached calendar IPO fetcher (#955 drain)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CalendarIpo"]
    fetcher = cls()
    assert (
        fetcher.test(
            {"start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)},
            credentials,
        )
        is None
    )


@pytest.mark.record_http
def test_fmp_cached_calendar_splits_fetcher(credentials=test_credentials):
    """Test FMP cached calendar splits fetcher (#955 drain)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CalendarSplits"]
    fetcher = cls()
    assert (
        fetcher.test(
            {"start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)},
            credentials,
        )
        is None
    )


@pytest.mark.record_http
def test_fmp_cached_crypto_historical_fetcher(credentials=test_credentials):
    """Test FMP cached crypto historical fetcher (#955 drain)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CryptoHistorical"]
    fetcher = cls()
    assert (
        fetcher.test(
            {
                "symbol": "BTCUSD",
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 10),
            },
            credentials,
        )
        is None
    )


@pytest.mark.record_http
def test_fmp_cached_currency_historical_fetcher(credentials=test_credentials):
    """Test FMP cached currency historical fetcher (#955 drain)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CurrencyHistorical"]
    fetcher = cls()
    assert (
        fetcher.test(
            {
                "symbol": "EURUSD",
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 10),
            },
            credentials,
        )
        is None
    )


@pytest.mark.record_http
def test_fmp_cached_economic_calendar_fetcher(credentials=test_credentials):
    """Test FMP cached economic calendar fetcher (#955 drain)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["EconomicCalendar"]
    fetcher = cls()
    assert (
        fetcher.test(
            {"start_date": date(2024, 1, 1), "end_date": date(2024, 1, 7)},
            credentials,
        )
        is None
    )


@pytest.mark.record_http
def test_fmp_cached_equity_intraday_historical_fetcher(credentials=test_credentials):
    """Test FMP cached equity intraday historical fetcher (#955 drain).

    Uses ``datetime()`` objects (not ``date()``) because
    ``FMPCachedEquityIntradayHistoricalQueryParams`` coerces string
    dates to ``datetime`` (midnight), so passing ``date()`` would fail
    the round-trip assertion (``date != datetime``).
    """
    from datetime import datetime  # local import to keep this test self-contained

    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    fetcher = cls()
    assert (
        fetcher.test(
            {
                "symbol": "AAPL",
                "start_date": datetime(2024, 1, 22),
                "end_date": datetime(2024, 1, 23),
                "interval": "1hour",
            },
            credentials,
        )
        is None
    )


@pytest.mark.record_http
def test_fmp_cached_etf_historical_fetcher(credentials=test_credentials):
    """Test FMP cached ETF historical fetcher (#955 drain)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["EtfHistorical"]
    fetcher = cls()
    assert (
        fetcher.test(
            {
                "symbol": "SPY",
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 10),
            },
            credentials,
        )
        is None
    )


@pytest.mark.record_http
def test_fmp_cached_index_historical_fetcher(credentials=test_credentials):
    """Test FMP cached index historical fetcher (#955 drain)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["IndexHistorical"]
    fetcher = cls()
    assert (
        fetcher.test(
            {
                "symbol": "SPY",
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 10),
            },
            credentials,
        )
        is None
    )


@pytest.mark.record_http
def test_fmp_cached_technical_indicator_intraday_fetcher(credentials=test_credentials):
    """Test FMP cached technical indicator intraday fetcher (#955 drain)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["TechnicalIndicatorIntraday"]
    fetcher = cls()
    assert (
        fetcher.test(
            {
                "symbol": "AAPL",
                "start_date": date(2024, 1, 22),
                "end_date": date(2024, 1, 23),
                "interval": "1hour",
                "indicator": "SMA",
                "length": 20,
            },
            credentials,
        )
        is None
    )


@pytest.mark.record_http
def test_fmp_cached_yield_curve_fetcher(credentials=test_credentials):
    """Test FMP cached yield curve fetcher (#955 drain).

    Uses a string date because ``YieldCurveQueryParams`` stores date
    as a string; passing a ``date()`` object would fail the round-trip
    assertion.
    """
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["YieldCurve"]
    fetcher = cls()
    assert fetcher.test({"date": "2024-01-15"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_risk_premium_fetcher(credentials=test_credentials):
    """Test FMP cached risk premium fetcher (#955 drain)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["RiskPremium"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_analyst_recommendations_fetcher(credentials=test_credentials):
    """Test FMP cached analyst recommendations fetcher (#997 / #1022).

    Aggregates /stable/grades into 5-bucket rating counts. This test
    hits the raw endpoint via VCR cassette + exercises the transform
    pipeline end-to-end.
    """
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["AnalystRecommendations"]
    fetcher = cls()
    assert fetcher.test({"symbol": "AAPL"}, credentials) is None


# ---------------------------------------------------------------------------
# W4 Directory drain — available-* directory endpoints (#1052-#1055)
# ---------------------------------------------------------------------------


@pytest.mark.record_http
def test_fmp_cached_available_exchanges_fetcher(credentials=test_credentials):
    """Test FMP cached available-exchanges directory (#1052)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["AvailableExchanges"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_available_sectors_fetcher(credentials=test_credentials):
    """Test FMP cached available-sectors directory (#1053)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["AvailableSectors"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_available_industries_fetcher(credentials=test_credentials):
    """Test FMP cached available-industries directory (#1054)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["AvailableIndustries"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_available_countries_fetcher(credentials=test_credentials):
    """Test FMP cached available-countries directory (#1055)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["AvailableCountries"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_stock_list_fetcher(credentials=test_credentials):
    """Test FMP cached stock-list directory (#1045)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["StockList"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_etf_list_fetcher(credentials=test_credentials):
    """Test FMP cached etf-list directory (#1049)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["EtfList"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_actively_trading_list_fetcher(credentials=test_credentials):
    """Test FMP cached actively-trading-list directory (#1050)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["ActivelyTradingList"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_financial_statement_symbol_list_fetcher(
    credentials=test_credentials,
):
    """Test FMP cached financial-statement-symbol-list directory (#1046)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["FinancialStatementSymbolList"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_cik_list_fetcher(credentials=test_credentials):
    """Test FMP cached cik-list directory (#1047)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CikList"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_commodities_list_fetcher(credentials=test_credentials):
    """Test FMP cached commodities-list directory (#1173)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CommoditiesList"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_cryptocurrency_list_fetcher(credentials=test_credentials):
    """Test FMP cached cryptocurrency-list directory (#1182)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CryptocurrencyList"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_forex_list_fetcher(credentials=test_credentials):
    """Test FMP cached forex-list directory (#1197)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["ForexList"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_index_list_fetcher(credentials=test_credentials):
    """Test FMP cached index-list directory (#1158)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["IndexList"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_sp500_constituent_fetcher(credentials=test_credentials):
    """Test FMP cached S&P 500 constituent (#1167)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["Sp500Constituent"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_nasdaq_constituent_fetcher(credentials=test_credentials):
    """Test FMP cached NASDAQ-100 constituent (#1168)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["NasdaqConstituent"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_dowjones_constituent_fetcher(credentials=test_credentials):
    """Test FMP cached Dow Jones constituent (#1169)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["DowjonesConstituent"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_commitment_of_traders_list_fetcher(credentials=test_credentials):
    """Test FMP cached CFTC commitment-of-traders list (#1102)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["CommitmentOfTradersList"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_market_risk_premium_fetcher(credentials=test_credentials):
    """Test FMP cached market-risk-premium (#1110)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["MarketRiskPremium"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_historical_sp500_constituent_fetcher(credentials=test_credentials):
    """Test FMP cached historical S&P 500 constituent (#1170)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["HistoricalSp500Constituent"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_historical_nasdaq_constituent_fetcher(credentials=test_credentials):
    """Test FMP cached historical NASDAQ-100 constituent (#1171)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["HistoricalNasdaqConstituent"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_historical_dowjones_constituent_fetcher(
    credentials=test_credentials,
):
    """Test FMP cached historical DJIA constituent (#1172)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["HistoricalDowjonesConstituent"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_symbol_change_fetcher(credentials=test_credentials):
    """Test FMP cached symbol-change (#1048)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["SymbolChange"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_shares_float_all_fetcher(credentials=test_credentials):
    """Test FMP cached shares-float-all (#1094)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["SharesFloatAll"]
    fetcher = cls()
    assert fetcher.test({}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_search_symbol_fetcher(credentials=test_credentials):
    """Test FMP cached search-symbol (#1038)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["SearchSymbol"]
    fetcher = cls()
    assert fetcher.test({"query": "AAPL"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_search_name_fetcher(credentials=test_credentials):
    """Test FMP cached search-name (#1039)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["SearchName"]
    fetcher = cls()
    assert fetcher.test({"query": "Apple"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_search_cik_fetcher(credentials=test_credentials):
    """Test FMP cached search-cik (#1040)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["SearchCik"]
    fetcher = cls()
    assert fetcher.test({"cik": "320193"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_search_cusip_fetcher(credentials=test_credentials):
    """Test FMP cached search-cusip (#1041)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["SearchCusip"]
    fetcher = cls()
    assert fetcher.test({"query": "037833100"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_search_isin_fetcher(credentials=test_credentials):
    """Test FMP cached search-isin (#1042)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["SearchIsin"]
    fetcher = cls()
    assert fetcher.test({"query": "US0378331005"}, credentials) is None


@pytest.mark.record_http
def test_fmp_cached_search_exchange_variants_fetcher(credentials=test_credentials):
    """Test FMP cached search-exchange-variants (#1044)."""
    from openbb_fmp_cached import fmp_cached_provider

    cls = fmp_cached_provider.fetcher_dict["SearchExchangeVariants"]
    fetcher = cls()
    assert fetcher.test({"query": "AAPL"}, credentials) is None
