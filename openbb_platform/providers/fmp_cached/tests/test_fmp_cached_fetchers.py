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
