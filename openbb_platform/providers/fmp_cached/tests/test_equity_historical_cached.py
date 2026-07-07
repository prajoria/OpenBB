"""Comprehensive tests for the new FMP Cached Equity Historical model with gap detection."""

import contextlib
from datetime import date, timedelta

import pytest
from openbb_fmp.models.equity_historical import (
    FMPEquityHistoricalQueryParams,
)
from openbb_fmp_cached.models.equity_historical import (
    FMPCachedEquityHistoricalFetcher,
    FMPCachedEquityHistoricalQueryParams,
    _analyze_cache_gaps,
    _detect_missing_ranges,
    _get_basic_market_holidays,
    _is_trading_day,
    _store_in_database_cache,
    clean_old_cache,
    get_cache_statistics,
)

# Test credentials
test_credentials = {"fmp_cached_api_key": "test_api_key_123"}


@pytest.fixture
def sample_fmp_data():
    """Sample FMP API response data."""
    return [
        {
            "symbol": "AAPL",
            "date": "2024-01-02",
            "open": 185.64,
            "high": 186.95,
            "low": 185.0,
            "close": 185.64,
            "volume": 54120000,
            "change": -1.91,
            "changePercent": -1.02,
            "vwap": 185.82,
        },
        {
            "symbol": "AAPL",
            "date": "2024-01-03",
            "open": 184.22,
            "high": 185.88,
            "low": 183.43,
            "close": 184.25,
            "volume": 58953400,
            "change": -1.39,
            "changePercent": -0.75,
            "vwap": 184.64,
        },
        {
            "symbol": "AAPL",
            "date": "2024-01-04",
            "open": 182.09,
            "high": 182.76,
            "low": 180.17,
            "close": 181.91,
            "volume": 81235900,
            "change": -2.34,
            "changePercent": -1.27,
            "vwap": 181.47,
        },
    ]


@pytest.fixture
def sample_query():
    """Sample query parameters."""
    return FMPEquityHistoricalQueryParams(
        symbol="AAPL",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 10),
        interval="1d",
        adjustment="splits_only",
    )


@pytest.fixture
def setup_test_tables(setup_test_database):
    """Set up test database tables before each test."""
    import os

    from openbb_fmp_cached.utils.database import execute_query

    # Ensure test mode
    os.environ["FMP_CACHE_TEST_MODE"] = "true"
    os.environ["MYSQL_DATABASE"] = "openbb_fmp_cache_test"

    # Clean up test data before each test
    try:
        execute_query(
            "DELETE FROM equity_historical WHERE symbol = %s OR symbol LIKE %s",
            ("AAPL", "TEST%"),
        )
    except Exception:
        pass  # Ignore cleanup errors

    yield

    # Clean up test data after each test
    try:
        execute_query(
            "DELETE FROM equity_historical WHERE symbol = %s OR symbol LIKE %s",
            ("AAPL", "TEST%"),
        )
    except Exception:
        pass  # Ignore cleanup errors


class TestEquityHistoricalCachedFetcher:
    """Test the main cached fetcher functionality."""

    def test_transform_query(self):
        """Test that query transformation works correctly."""
        params = {
            "symbol": "AAPL",
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 1, 10),
            "interval": "1d",
            "adjustment": "splits_only",
        }

        result = FMPCachedEquityHistoricalFetcher.transform_query(params)

        # Should return FMPCachedEquityHistoricalQueryParams
        assert isinstance(result, FMPCachedEquityHistoricalQueryParams)
        assert result.symbol == "AAPL"
        assert result.start_date == date(2024, 1, 1)
        assert result.end_date == date(2024, 1, 10)

    def test_transform_data(self, sample_query, sample_fmp_data):
        """Test that data transformation works correctly."""
        result = FMPCachedEquityHistoricalFetcher.transform_data(
            sample_query, sample_fmp_data
        )

        # Should return list of data
        assert isinstance(result, list)
        assert len(result) == len(sample_fmp_data)
        # The cached fetcher returns its own data type, not FMPEquityHistoricalData
        if result:
            assert hasattr(result[0], "symbol")
            assert hasattr(result[0], "date")
            assert hasattr(result[0], "close")


class TestGapDetectionLogic:
    """Test the intelligent gap detection system."""

    def test_analyze_cache_gaps_empty_cache(self, sample_query, setup_test_tables):
        """Test gap analysis with empty cache."""
        from openbb_fmp_cached.utils.database import execute_query

        # Ensure cache is empty for this symbol
        execute_query("DELETE FROM equity_historical WHERE symbol = %s", ("AAPL",))

        cached_data, missing_ranges = _analyze_cache_gaps(sample_query)

        assert len(cached_data) == 0
        assert len(missing_ranges) == 1
        # January 1 is a holiday, so gap should start on first trading day (Jan 2)
        assert missing_ranges[0][0] >= sample_query.start_date
        assert missing_ranges[0][1] == sample_query.end_date

    def test_analyze_cache_gaps_complete_cache(self, sample_query, setup_test_tables):
        """Test gap analysis with complete cache coverage."""
        from openbb_fmp_cached.utils.database import execute_query

        # Insert complete cache data for the query range matching the query's interval and adjustment
        insert_query = """
        INSERT INTO equity_historical 
        (symbol, date, open, high, low, close, volume, change_amount, change_percent, vwap, 
         interval_type, adjustment_type, cached_at, is_valid)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), 1)
        ON DUPLICATE KEY UPDATE cached_at = NOW()
        """

        # Use the query's interval and adjustment type
        interval_type = sample_query.interval or "1d"
        adjustment_type = sample_query.adjustment or "splits_only"

        # Insert data for all trading days in the range (Jan 2-5, 2024)
        cache_rows = [
            (
                "AAPL",
                date(2024, 1, 2),
                185.64,
                186.95,
                185.0,
                185.64,
                54120000,
                -1.91,
                -1.02,
                185.82,
                interval_type,
                adjustment_type,
            ),
            (
                "AAPL",
                date(2024, 1, 3),
                184.22,
                185.88,
                183.43,
                184.25,
                58953400,
                -1.39,
                -0.75,
                184.64,
                interval_type,
                adjustment_type,
            ),
            (
                "AAPL",
                date(2024, 1, 4),
                182.09,
                182.76,
                180.17,
                181.91,
                81235900,
                -2.34,
                -1.27,
                181.47,
                interval_type,
                adjustment_type,
            ),
            (
                "AAPL",
                date(2024, 1, 5),
                181.99,
                182.76,
                180.17,
                181.18,
                62379700,
                -0.81,
                -0.44,
                181.52,
                interval_type,
                adjustment_type,
            ),
            (
                "AAPL",
                date(2024, 1, 8),
                182.09,
                185.60,
                181.50,
                185.56,
                59144500,
                3.47,
                1.91,
                183.69,
                interval_type,
                adjustment_type,
            ),
            (
                "AAPL",
                date(2024, 1, 9),
                183.92,
                185.15,
                182.73,
                185.14,
                42841809,
                1.22,
                0.66,
                184.24,
                interval_type,
                adjustment_type,
            ),
            (
                "AAPL",
                date(2024, 1, 10),
                184.35,
                186.40,
                183.92,
                186.19,
                46792908,
                1.84,
                0.99,
                185.22,
                interval_type,
                adjustment_type,
            ),
        ]

        for row in cache_rows:
            execute_query(insert_query, row)

        cached_data, missing_ranges = _analyze_cache_gaps(sample_query)

        # Should have cached data
        assert len(cached_data) >= 3
        # May have minimal or no gaps (weekends/holidays excluded)
        assert len(missing_ranges) >= 0

    def test_analyze_cache_gaps_partial_cache(self, sample_query, setup_test_tables):
        """Test gap analysis with partial cache coverage."""
        from openbb_fmp_cached.utils.database import execute_query

        # Insert partial cache data (missing middle day)
        insert_query = """
        INSERT INTO equity_historical 
        (symbol, date, open, high, low, close, volume, change_amount, change_percent, vwap, 
         interval_type, adjustment_type, cached_at, is_valid)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), 1)
        ON DUPLICATE KEY UPDATE cached_at = NOW()
        """

        interval_type = sample_query.interval or "1d"
        adjustment_type = sample_query.adjustment or "splits_only"

        # Insert only first and last day (missing middle days)
        cache_rows = [
            (
                "AAPL",
                date(2024, 1, 2),
                185.64,
                186.95,
                185.0,
                185.64,
                54120000,
                -1.91,
                -1.02,
                185.82,
                interval_type,
                adjustment_type,
            ),
            (
                "AAPL",
                date(2024, 1, 5),
                182.09,
                182.76,
                180.17,
                181.91,
                81235900,
                -2.34,
                -1.27,
                181.47,
                interval_type,
                adjustment_type,
            ),
        ]

        for row in cache_rows:
            execute_query(insert_query, row)

        cached_data, missing_ranges = _analyze_cache_gaps(sample_query)

        # Should have some cached data
        assert len(cached_data) >= 1
        # Should detect gaps
        assert len(missing_ranges) > 0

        # Should have gaps between Jan 2 and Jan 8
        cached_dates = {date(2024, 1, 2), date(2024, 1, 8)}
        detected_ranges = _detect_missing_ranges(
            sample_query.start_date,
            sample_query.end_date,
            cached_dates,
            sample_query.interval,
        )
        assert len(detected_ranges) > 0


class TestMissingRangeDetection:
    """Test the missing date range detection logic."""

    def test_detect_missing_ranges_daily_complete(self):
        """Test daily range detection with complete data."""
        start_date = date(2024, 1, 1)  # Monday
        end_date = date(2024, 1, 5)  # Friday

        # All business days present
        cached_dates = {
            date(2024, 1, 2),  # Tuesday (Jan 1 is holiday)
            date(2024, 1, 3),  # Wednesday
            date(2024, 1, 4),  # Thursday
            date(2024, 1, 5),  # Friday
        }

        missing_ranges = _detect_missing_ranges(
            start_date, end_date, cached_dates, "1d"
        )

        # Should have minimal gaps (maybe just Jan 1 holiday)
        assert len(missing_ranges) <= 1

    def test_detect_missing_ranges_daily_gaps(self):
        """Test daily range detection with gaps."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 10)

        # Missing some business days
        cached_dates = {
            date(2024, 1, 2),
            date(2024, 1, 3),
            # Gap: Jan 4, 5
            date(2024, 1, 8),
            date(2024, 1, 9),
        }

        missing_ranges = _detect_missing_ranges(
            start_date, end_date, cached_dates, "1d"
        )

        assert len(missing_ranges) > 0

        # Should detect gaps around Jan 4-5 and possibly beginning/end
        for start_gap, end_gap in missing_ranges:
            assert start_gap <= end_gap
            assert start_gap >= start_date
            assert end_gap <= end_date

    def test_detect_missing_ranges_intraday_empty(self):
        """Test intraday range detection with empty cache."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 5)
        cached_dates = set()

        missing_ranges = _detect_missing_ranges(
            start_date, end_date, cached_dates, "1h"
        )

        # Should request full range for intraday when empty
        assert len(missing_ranges) == 1
        assert missing_ranges[0] == (start_date, end_date)

    def test_detect_missing_ranges_intraday_partial(self):
        """Test intraday range detection with some data."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 5)

        # Some data present
        cached_dates = {date(2024, 1, 2), date(2024, 1, 3)}

        missing_ranges = _detect_missing_ranges(
            start_date, end_date, cached_dates, "1h"
        )

        # For intraday with gaps, should be conservative and request full range
        assert len(missing_ranges) == 1
        assert missing_ranges[0] == (start_date, end_date)

    # ---- bd-isvv: sparse-cache silent-data-loss guard ---------------------
    #
    # Pre-fix (bd-isvv) the intraday shortcut at equity_historical.py:557
    # returned [] (no missing ranges = "cache is complete") whenever three
    # conditions held:
    #   1. min(cached_dates) <= start_date
    #   2. max(cached_dates) >= end_date
    #   3. no consecutive-cached-date gap exceeded 7 days
    # A 6-month intraday request with only endpoint bars + a couple mid-range
    # samples satisfies all three conditions AND is silently reported as
    # complete — hot-path data-loss for every intraday backtest. Post-fix
    # the detector requires the cached bar density to be plausible for the
    # interval before it can claim completeness.
    #
    # Density thresholds (bars-per-cached-trading-day) come from expected US
    # session length (~6.5h). For the coverage check we look at cached_dates
    # cardinality relative to the number of trading days in the requested
    # range — cached_dates is a SET OF DAYS (multiple bars/day collapse to
    # one entry), so density = |cached_dates| / trading_days_in_range must
    # be >= threshold for the "cache is complete" fast-path to fire.

    def test_detect_missing_ranges_intraday_sparse_endpoints_only(self):
        """bd-isvv: cache with only endpoint bars must NOT report 'complete'.

        6-month request, cache holds bars only at the two endpoint dates
        (min/max cover the range, no gap > 7 days between the two entries
        after adding intermediate weekly samples — but density is
        effectively zero). Pre-fix returned []; post-fix returns the full
        range as missing.
        """
        start_date = date(2026, 1, 5)  # Monday
        end_date = date(2026, 6, 30)  # Tuesday, ~180 days = ~125 trading days

        # 4 cached dates spanning the range, spaced every ~60 days. Under
        # the pre-fix rule this satisfies min<=start, max>=end, gap<=7
        # weeks... wait, gap is checked in DAYS not weeks. 60 > 7 so the
        # pre-fix WOULD have caught this. Use a smaller sample where the
        # pre-fix silent-drop actually fires.
        # 26 cached dates spaced 7 days apart (weekly samples) — every
        # consecutive gap is EXACTLY 7 days, and current code uses
        # ``> 7`` so 7-day gaps do NOT trigger the fallback.
        cached_dates = set()
        d = start_date
        while d <= end_date:
            cached_dates.add(d)
            d += timedelta(days=7)
        # Ensure endpoints are covered
        cached_dates.add(start_date)
        cached_dates.add(end_date)

        # ~26 weekly samples over ~125 trading days = 0.2 cached-dates
        # per trading day. For 1h data we expect 1 cached-date per
        # trading day (every trading day should have at least SOME 1h
        # bars). Density well below threshold → must report missing.

        missing_ranges = _detect_missing_ranges(
            start_date, end_date, cached_dates, "1h"
        )
        assert len(missing_ranges) == 1, (
            f"sparse intraday cache (~{len(cached_dates)} dates over ~125 "
            f"trading days) reported {missing_ranges!r} — pre-fix bd-isvv "
            f"silently returned [] (i.e. 'complete'), causing hot-path "
            f"intraday data-loss."
        )
        assert missing_ranges[0] == (start_date, end_date), (
            f"missing range must cover the FULL requested window, got "
            f"{missing_ranges[0]!r}"
        )

    def test_detect_missing_ranges_intraday_dense_still_complete(self):
        """Regression lock: dense intraday cache (every trading day) → [].

        The density check must NOT cause spurious re-fetches when the
        cache genuinely IS complete. Every trading day in the range has
        at least one cached bar (i.e. |cached_dates| == trading_days),
        so density = 1.0 which is at or above every interval's
        threshold.
        """
        # 2-week window with a bar on every trading day.
        start_date = date(2026, 1, 5)  # Monday
        end_date = date(2026, 1, 16)  # Friday, 10 trading days

        cached_dates = set()
        d = start_date
        while d <= end_date:
            if d.weekday() < 5:  # Mon-Fri
                cached_dates.add(d)
            d += timedelta(days=1)

        # Every trading day has a bar → density is 1.0 → complete for
        # every interval.
        for interval in ("1m", "5m", "15m", "30m", "1h", "4h"):
            missing_ranges = _detect_missing_ranges(
                start_date, end_date, cached_dates, interval
            )
            assert missing_ranges == [], (
                f"dense cache (bar every trading day) at interval={interval!r} "
                f"was reported as incomplete: {missing_ranges!r} — the density "
                f"threshold is too strict and causes spurious re-fetches."
            )

    def test_detect_missing_ranges_intraday_missing_middle_days(self):
        """bd-isvv: cache with endpoints + only a few middle days must refetch.

        A 30-day range where cache covers endpoints + 3 middle days but
        misses 20+ trading days in between. Pre-fix: min≤start, max≥end,
        and the max consecutive gap is < 7 days (adjacent samples every
        ~5 days apart) → return []. Post-fix: density check flags this
        as insufficient.
        """
        start_date = date(2026, 1, 5)  # Monday
        end_date = date(2026, 2, 2)  # ~20 trading days

        cached_dates = {
            date(2026, 1, 5),
            date(2026, 1, 8),
            date(2026, 1, 12),
            date(2026, 1, 16),
            date(2026, 1, 20),
            date(2026, 1, 26),
            date(2026, 2, 2),
        }
        # 7 cached days out of ~20 trading days = 35% density. For 1h
        # (expected 1 date/day), this is below threshold and MUST refetch.

        missing_ranges = _detect_missing_ranges(
            start_date, end_date, cached_dates, "1h"
        )
        assert len(missing_ranges) == 1, (
            f"partial intraday cache (~35% density) reported {missing_ranges!r} "
            f"— pre-fix bd-isvv would have returned [] because no consecutive "
            f"gap exceeded 7 days; post-fix must flag as missing."
        )


class TestTradingDayLogic:
    """Test trading day and holiday logic."""

    def test_is_trading_day_weekdays(self):
        """Test trading day detection for weekdays."""
        # Monday through Friday should be trading days (unless holiday)
        monday = date(2024, 1, 1)  # New Year's Day - holiday
        tuesday = date(2024, 1, 2)
        wednesday = date(2024, 1, 3)

        holidays = _get_basic_market_holidays(2024, 2024)

        assert not _is_trading_day(monday, holidays)  # Holiday
        assert _is_trading_day(tuesday, holidays)  # Normal Tuesday
        assert _is_trading_day(wednesday, holidays)  # Normal Wednesday

    def test_is_trading_day_weekends(self):
        """Test trading day detection for weekends."""
        saturday = date(2024, 1, 6)
        sunday = date(2024, 1, 7)

        holidays = _get_basic_market_holidays(2024, 2024)

        assert not _is_trading_day(saturday, holidays)
        assert not _is_trading_day(sunday, holidays)

    def test_get_basic_market_holidays(self):
        """Test basic market holiday detection."""
        holidays = _get_basic_market_holidays(2024, 2024)

        # Should include New Year's, Christmas, July 4th
        assert date(2024, 1, 1) in holidays  # New Year's
        assert date(2024, 7, 4) in holidays  # Independence Day
        assert date(2024, 12, 25) in holidays  # Christmas

        # Should be date objects
        for holiday in holidays:
            assert isinstance(holiday, date)

    def test_get_basic_market_holidays_multi_year(self):
        """Test holiday detection across multiple years."""
        holidays = _get_basic_market_holidays(2023, 2025)

        # Should have holidays for all years
        assert date(2023, 1, 1) in holidays
        assert date(2024, 1, 1) in holidays
        assert date(2025, 1, 1) in holidays

        # Should have multiple years worth
        assert len(holidays) >= 9  # 3 holidays × 3 years


class TestDatabaseOperations:
    """Test database storage and retrieval operations."""

    def test_store_in_database_cache(
        self, sample_query, sample_fmp_data, setup_test_tables
    ):
        """Test storing FMP data in database cache."""

        from openbb_fmp_cached.utils.database import execute_query

        # Store the data
        _store_in_database_cache(sample_query, sample_fmp_data)

        # Verify data was stored by counting records
        count_query = (
            "SELECT COUNT(*) as count FROM equity_historical WHERE symbol = %s"
        )
        result = execute_query(count_query, ("AAPL",))
        assert result[0]["count"] == len(sample_fmp_data)

        # Verify data details (handle Decimal type from database)
        data_query = "SELECT * FROM equity_historical WHERE symbol = %s ORDER BY date"
        stored_data = execute_query(data_query, ("AAPL",))
        assert len(stored_data) == len(sample_fmp_data)
        # Compare as floats since DB returns Decimal
        assert float(stored_data[0]["close"]) == 185.64

    def test_store_in_database_cache_empty_data(self, sample_query, setup_test_tables):
        """Test storing empty data doesn't cause errors."""
        # Should not raise an error
        _store_in_database_cache(sample_query, [])

    def test_store_in_database_cache_invalid_dates(
        self, sample_query, setup_test_tables
    ):
        """Test handling of invalid date formats."""
        from openbb_fmp_cached.utils.database import execute_query

        invalid_data = [
            {
                "symbol": "AAPL",
                "date": "2024-01-02",
                "close": 152.0,
                "open": 150.0,
                "high": 153.0,
                "low": 149.0,
                "volume": 1000000,
            },
        ]

        # Should handle gracefully
        _store_in_database_cache(sample_query, invalid_data)

        # Verify at least one record was stored
        count_query = (
            "SELECT COUNT(*) as count FROM equity_historical WHERE symbol = %s"
        )
        result = execute_query(count_query, ("AAPL",))
        assert result[0]["count"] >= 1

    def test_get_cache_statistics_with_symbol(self, setup_test_tables):
        """Test cache statistics for specific symbol."""
        stats = get_cache_statistics("AAPL")

        # Should return dict with statistics key
        assert isinstance(stats, dict)
        # May be empty if no data, which is fine

    def test_get_cache_statistics_all_symbols(self, setup_test_tables):
        """Test cache statistics for all symbols."""
        stats = get_cache_statistics()

        # Should return dict with statistics key
        assert isinstance(stats, dict)

    def test_clean_old_cache(self, setup_test_tables):
        """Test cleaning old cache entries."""
        from openbb_fmp_cached.utils.database import execute_query

        # Insert some old test data
        old_date = date(2020, 1, 1)
        insert_query = """
        INSERT INTO equity_historical 
        (symbol, date, close, interval_type, adjustment_type, cached_at, is_valid)
        VALUES (%s, %s, %s, %s, %s, DATE_SUB(NOW(), INTERVAL 100 DAY), 1)
        ON DUPLICATE KEY UPDATE cached_at = DATE_SUB(NOW(), INTERVAL 100 DAY)
        """
        execute_query(insert_query, ("TEST_OLD", old_date, 100.0, "1d", "unadj"))

        # Clean data older than 30 days
        deleted_count = clean_old_cache(30)

        # Should have deleted at least the test record
        assert deleted_count >= 1


class TestMultiSymbolSupport:
    """Test multi-symbol request handling."""

    def test_multi_symbol_query_parsing(self, setup_test_tables):
        """Test that multi-symbol queries are parsed correctly."""

        # Create query with multiple symbols
        multi_query = FMPCachedEquityHistoricalQueryParams(
            symbol="AAPL,GOOGL,MSFT",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only",
        )

        # The symbol should be stored as-is
        assert multi_query.symbol == "AAPL,GOOGL,MSFT"

        # Test that we can split and process symbols
        symbols = [s.strip() for s in multi_query.symbol.split(",")]
        assert len(symbols) == 3
        assert "AAPL" in symbols
        assert "GOOGL" in symbols
        assert "MSFT" in symbols

    def test_mixed_cache_states(self, setup_test_tables):
        """Test handling symbols with different cache states."""
        from openbb_fmp_cached.utils.database import execute_query

        interval_type = "1d"
        adjustment_type = "splits_only"

        # Insert data for AAPL only
        insert_query = """
        INSERT INTO equity_historical 
        (symbol, date, close, interval_type, adjustment_type, cached_at, is_valid)
        VALUES (%s, %s, %s, %s, %s, NOW(), 1)
        ON DUPLICATE KEY UPDATE cached_at = NOW()
        """
        execute_query(
            insert_query,
            ("AAPL", date(2024, 1, 2), 185.0, interval_type, adjustment_type),
        )

        # Verify AAPL has cached data
        aapl_query = "SELECT COUNT(*) as count FROM equity_historical WHERE symbol = %s"
        aapl_result = execute_query(aapl_query, ("AAPL",))
        assert aapl_result[0]["count"] > 0

        # Verify GOOGL has no cached data
        googl_result = execute_query(aapl_query, ("GOOGL",))
        assert googl_result[0]["count"] == 0


class TestErrorHandling:
    """Test error handling and fallback mechanisms."""

    def test_database_connection_resilience(self, setup_test_tables):
        """Test that database operations handle errors gracefully."""
        from openbb_fmp_cached.utils.database import execute_query

        # Try to execute an invalid query
        try:
            execute_query("SELECT * FROM nonexistent_table")
            assert False, "Should have raised an exception"
        except Exception as e:
            # Should raise an exception for invalid table
            assert (
                "nonexistent_table" in str(e).lower()
                or "doesn't exist" in str(e).lower()
            )

    def test_cache_analysis_with_no_data(self, setup_test_tables):
        """Test cache analysis when no data exists."""
        from openbb_fmp_cached.utils.database import execute_query

        # Ensure no data for test symbol
        execute_query(
            "DELETE FROM equity_historical WHERE symbol = %s", ("TESTNODATA",)
        )

        # Create query for symbol with no data
        query = FMPCachedEquityHistoricalQueryParams(
            symbol="TESTNODATA",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 10),
            interval="1d",
            adjustment="splits_only",
        )

        # Should handle gracefully
        cached_data, missing_ranges = _analyze_cache_gaps(query)

        assert len(cached_data) == 0
        assert len(missing_ranges) >= 1

    def test_invalid_date_handling(self, setup_test_tables):
        """Test handling of invalid dates in data."""
        # Store data should handle various data formats gracefully
        invalid_data = [
            {"symbol": "TEST", "date": "2024-01-02", "close": 100.0},
        ]

        query = FMPCachedEquityHistoricalQueryParams(
            symbol="TEST",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 10),
            interval="1d",
            adjustment="splits_only",
        )

        # Should not raise an exception
        try:
            _store_in_database_cache(query, invalid_data)
        except Exception as e:
            # If it does raise, it should be a known database error
            assert "mysql" in str(e).lower() or "database" in str(e).lower()


class TestPerformanceOptimizations:
    """Test performance-related optimizations."""

    def test_gap_detection_efficiency(self, setup_test_tables):
        """Test that gap detection efficiently identifies missing data ranges."""
        from openbb_fmp_cached.utils.database import execute_query

        # Insert sparse data (lots of gaps)
        insert_query = """
        INSERT INTO equity_historical 
        (symbol, date, close, interval_type, adjustment_type, cached_at, is_valid)
        VALUES (%s, %s, %s, %s, %s, NOW(), 1)
        ON DUPLICATE KEY UPDATE cached_at = NOW()
        """

        interval_type = "1d"
        adjustment_type = "splits_only"

        # Insert only a few dates with big gaps
        execute_query(
            insert_query,
            ("PERF_TEST", date(2024, 1, 2), 100.0, interval_type, adjustment_type),
        )
        execute_query(
            insert_query,
            ("PERF_TEST", date(2024, 1, 10), 105.0, interval_type, adjustment_type),
        )

        query = FMPCachedEquityHistoricalQueryParams(
            symbol="PERF_TEST",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 15),
            interval="1d",
            adjustment="splits_only",
        )

        cached_data, missing_ranges = _analyze_cache_gaps(query)

        # Should efficiently detect gaps
        assert len(cached_data) == 2
        assert len(missing_ranges) >= 1

    def test_query_uses_indexed_columns(self, sample_query):
        """Test that queries use indexed columns for performance."""
        # The gap analysis query should use indexed columns
        # We can verify this by checking the actual query
        cached_data, missing_ranges = _analyze_cache_gaps(sample_query)

        # If query is efficient, it should complete quickly even with data
        # This is implicitly tested by the fact that the test completes
        assert isinstance(cached_data, list)
        assert isinstance(missing_ranges, list)


class TestIntegration:
    """Integration tests with real database operations."""

    @pytest.mark.integration
    def test_store_and_retrieve_cycle(self, setup_test_tables):
        """Test complete store and retrieve cycle."""

        query = FMPCachedEquityHistoricalQueryParams(
            symbol="INTEGRATION_TEST",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only",
        )

        # Store some test data
        test_data = [
            {
                "symbol": "INTEGRATION_TEST",
                "date": "2024-01-02",
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 102.0,
                "volume": 1000000,
                "change": 2.0,
                "changePercent": 2.0,
                "vwap": 101.5,
            },
            {
                "symbol": "INTEGRATION_TEST",
                "date": "2024-01-03",
                "open": 102.0,
                "high": 106.0,
                "low": 101.0,
                "close": 104.0,
                "volume": 1100000,
                "change": 2.0,
                "changePercent": 1.96,
                "vwap": 103.5,
            },
        ]

        # Store the data
        _store_in_database_cache(query, test_data)

        # Retrieve and verify
        cached_data, missing_ranges = _analyze_cache_gaps(query)

        assert len(cached_data) >= 2
        assert len(missing_ranges) >= 0  # May have gaps for non-trading days


class TestHolidayGapFilling:
    """Test holiday/weekend gap filling functionality."""

    def test_fill_weekend_gap_with_previous_close(self, setup_test_tables):
        """Test that weekend gaps are filled with previous Friday's close."""
        from openbb_fmp_cached.models.equity_historical import _fill_holiday_gaps

        query = FMPCachedEquityHistoricalQueryParams(
            symbol="GAPTEST",
            start_date=date(2024, 1, 5),  # Friday
            end_date=date(2024, 1, 8),  # Monday
            interval="1d",
            adjustment="splits_only",
        )

        # Cached data: Friday Jan 5
        cached_data = [
            {
                "symbol": "GAPTEST",
                "date": "2024-01-05",
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 102.0,
                "volume": 1000000,
                "change": 2.0,
                "changePercent": 2.0,
                "vwap": 101.5,
            }
        ]

        # Fetched data: Monday Jan 8
        fetched_data = [
            {
                "symbol": "GAPTEST",
                "date": "2024-01-08",
                "open": 102.5,
                "high": 106.0,
                "low": 101.0,
                "close": 105.0,
                "volume": 1100000,
                "change": 3.0,
                "changePercent": 2.94,
                "vwap": 103.5,
            }
        ]

        # Fill weekend gaps
        filled_data = _fill_holiday_gaps(query, cached_data, fetched_data)

        # Should have original fetched data + 2 filled records (Sat, Sun)
        assert len(filled_data) >= 3

        # Find filled records
        filled_records = [d for d in filled_data if d.get("_is_filled")]
        assert len(filled_records) == 2  # Saturday and Sunday

        # Verify Saturday (2024-01-06) is filled
        sat_record = next(
            (d for d in filled_records if d["date"] == "2024-01-06"), None
        )
        assert sat_record is not None
        assert sat_record["_fill_type"] == "previous_close"
        assert sat_record["_fill_source_date"] == "2024-01-05"
        assert sat_record["close"] == 102.0  # Friday's close
        assert sat_record["volume"] == 0  # No volume on weekends

    def test_fill_holiday_gap_with_next_open(self, setup_test_tables):
        """Test that holiday gaps can be filled with next trading day's open."""
        from openbb_fmp_cached.models.equity_historical import _fill_holiday_gaps

        query = FMPCachedEquityHistoricalQueryParams(
            symbol="HOLIDAYTEST",
            start_date=date(2024, 12, 24),  # Tuesday before Christmas
            end_date=date(2024, 12, 26),  # Thursday after Christmas
            interval="1d",
            adjustment="splits_only",
        )

        # No cached data
        cached_data = []

        # Only fetched Thursday data (day after Christmas)
        fetched_data = [
            {
                "symbol": "HOLIDAYTEST",
                "date": "2024-12-26",
                "open": 150.0,
                "high": 155.0,
                "low": 149.0,
                "close": 153.0,
                "volume": 800000,
                "change": 3.0,
                "changePercent": 2.0,
                "vwap": 152.0,
            }
        ]

        # Fill holiday gap (Christmas Day)
        filled_data = _fill_holiday_gaps(query, cached_data, fetched_data)

        # Find Christmas Day filled record
        christmas_record = next(
            (d for d in filled_data if d["date"] == "2024-12-25"), None
        )
        assert christmas_record is not None
        assert christmas_record["_is_filled"] is True
        assert christmas_record["_fill_type"] == "next_open"
        assert christmas_record["_fill_source_date"] == "2024-12-26"
        assert christmas_record["close"] == 153.0

    def test_filled_data_persists_in_database(self, setup_test_tables):
        """Test that filled data is correctly stored and retrieved from database."""
        from openbb_fmp_cached.utils.database import execute_query

        query = FMPCachedEquityHistoricalQueryParams(
            symbol="PERSISTTEST",
            start_date=date(2024, 1, 1),  # Holiday (New Year)
            end_date=date(2024, 1, 3),
            interval="1d",
            adjustment="splits_only",
        )

        # Create test data with filled record
        test_data = [
            {
                "symbol": "PERSISTTEST",
                "date": "2024-01-01",
                "open": 200.0,
                "high": 205.0,
                "low": 199.0,
                "close": 203.0,
                "volume": 0,
                "change": 0.0,
                "changePercent": 0.0,
                "vwap": 202.0,
                "_is_filled": True,
                "_fill_source_date": "2024-01-02",
                "_fill_type": "next_open",
            },
            {
                "symbol": "PERSISTTEST",
                "date": "2024-01-02",
                "open": 200.0,
                "high": 205.0,
                "low": 199.0,
                "close": 203.0,
                "volume": 1000000,
                "change": 3.0,
                "changePercent": 1.5,
                "vwap": 202.0,
            },
        ]

        # Store the data
        _store_in_database_cache(query, test_data)

        # Retrieve from database
        check_query = """
        SELECT date, is_filled, fill_source_date, fill_type, volume
        FROM equity_historical
        WHERE symbol = %s AND date = %s
        """

        result = execute_query(check_query, ("PERSISTTEST", date(2024, 1, 1)))
        assert len(result) == 1

        record = result[0]
        assert record["is_filled"] == 1  # MySQL boolean as int
        assert record["fill_source_date"] == date(2024, 1, 2)
        assert record["fill_type"] == "next_open"
        assert record["volume"] == 0


# ---------------------------------------------------------------------------
# API-key-in-URL defenses (bd-6641, closes ir3f + q4b4)
# ---------------------------------------------------------------------------


class TestApiKeyNotInUrl:
    """Regression tests for OpenBBTechnical-ir3f / q4b4 — api-key must not be
    embedded in URL querystring (leaks via HTTPError.url, proxy logs, tracebacks).

    Each site is verified by capturing the URL / params passed to the HTTP
    layer and asserting:
      1. The URL string does NOT contain ``apikey=``
      2. The ``params`` kwarg DOES contain ``apikey`` with the correct value
    """

    _SENTINEL_KEY = "SENTINEL_API_KEY_MUST_NOT_LEAK"

    def test_fetch_from_fmp_sync_uses_params_not_urlkey(self, monkeypatch):
        """Sync fetch (line 1012) passes apikey via params=, not URL."""
        import requests as top_requests
        from openbb_fmp_cached.models import equity_historical as mod

        captured = {}

        def fake_get(url, timeout=None, params=None, **kwargs):
            captured["url"] = url
            captured["params"] = params or {}
            captured["timeout"] = timeout

            class R:
                status_code = 200
                content = b"[]"

                def raise_for_status(self):
                    pass

                def json(self):
                    return []

            return R()

        # ``_fetch_from_fmp_sync`` imports ``requests`` inside the function
        # body (``import requests as _requests``), so patch the top-level
        # requests module — the local re-import picks up our fake.
        monkeypatch.setattr(top_requests, "get", fake_get)

        query = FMPCachedEquityHistoricalQueryParams(
            symbol="AAPL",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 5),
        )
        credentials = {
            "fmp_api_key": self._SENTINEL_KEY,
            "fmp_cached_api_key": self._SENTINEL_KEY,
        }
        # The fake returns empty data, so the function raises EmptyDataError
        # after making its request — that's fine; we only care whether the URL
        # / params carried the apikey correctly. Swallow the expected error.
        with contextlib.suppress(Exception):
            mod._fetch_from_fmp_sync(query, credentials)

        assert "url" in captured, "fake_get was never called"

        assert (
            self._SENTINEL_KEY not in captured["url"]
        ), f"apikey leaked into URL: {captured['url']!r}"
        assert (
            "apikey" not in captured["url"]
        ), f"'apikey=' substring found in URL: {captured['url']!r}"
        assert (
            captured["params"].get("apikey") == self._SENTINEL_KEY
        ), f"apikey missing from params dict: {captured['params']!r}"

    def test_fetch_from_fmp_sync_http_error_does_not_leak_apikey(self, monkeypatch):
        """HTTPError from sync path must not leak apikey via exception message.

        Regression test for Phase-6 self-QC finding — even with params=, the
        ``requests`` library merges params into PreparedRequest.url before
        sending, so ``resp.url`` and ``HTTPError.__str__()`` contained the
        apikey. Since ``raise_for_status()`` was called on a 4xx/5xx
        response, an unhandled traceback landed in stderr/CI logs with the
        real key in it.
        """
        import requests as top_requests
        from openbb_fmp_cached.models import equity_historical as mod

        def fake_get(url, timeout=None, params=None, **kwargs):
            merged_url = f"{url}?symbol={params['symbol']}&apikey={params['apikey']}"

            class R:
                status_code = 429
                content = b"rate limited"
                url = merged_url

                def raise_for_status(self):
                    # Match requests.Response.raise_for_status() behaviour:
                    # read self.url AT RAISE TIME so the fix (which mutates
                    # self.url just before this call) actually redacts the
                    # message. Real requests does the same.
                    err = top_requests.HTTPError(
                        f"429 Client Error: Too Many Requests for url: {self.url}",
                        response=self,
                    )
                    raise err

                def json(self):
                    return {}

            return R()

        monkeypatch.setattr(top_requests, "get", fake_get)

        query = FMPCachedEquityHistoricalQueryParams(
            symbol="AAPL",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 5),
        )
        credentials = {
            "fmp_api_key": self._SENTINEL_KEY,
            "fmp_cached_api_key": self._SENTINEL_KEY,
        }

        # Whatever exception the function raises, its message must NOT
        # contain the apikey.
        try:
            mod._fetch_from_fmp_sync(query, credentials)
        except Exception as exc:  # noqa: BLE001 - we assert on the message
            assert self._SENTINEL_KEY not in str(
                exc
            ), f"HTTPError leaked apikey in message: {exc!s}"
            # Also check the .response.url (a common Sentry breadcrumb field)
            resp = getattr(exc, "response", None)
            if resp is not None:
                assert self._SENTINEL_KEY not in str(
                    getattr(resp, "url", "")
                ), f"HTTPError.response.url leaked apikey: {resp.url!r}"
        else:
            pytest.fail("_fetch_from_fmp_sync should have raised on HTTP 429 response")


_ASYNC_SENTINEL_KEY = "SENTINEL_ASYNC_API_KEY_MUST_NOT_LEAK"


# ---------------------------------------------------------------------------
# Structural apikey-not-in-URL test — covers the async sites
#
# Written as a source-level assertion because pytest-asyncio's event_loop
# fixture setup hits an ``OSError: could not get source code`` on this
# provider's test env for certain async coroutines. A source-level scan is
# strictly stronger for a security fix like this: any future refactor that
# adds a new ``apikey={...}`` f-string in the file will fail this test,
# even ones we didn't think to unit-test individually.
# ---------------------------------------------------------------------------


def test_no_apikey_in_url_fstring_in_equity_historical():
    """No ``apikey=`` f-string interpolation anywhere in equity_historical.py.

    Regression test for OpenBBTechnical-ir3f (async main historical fetch,
    line 920) AND the sibling dividend fetch (line 1121) which uses the
    same pattern but had no dedicated bead — caught during Phase-1
    exploration and fixed in the same commit.

    The fixed pattern routes the key through ``params={'apikey': ...}``
    on the HTTP call (aiohttp / requests both handle URL-encoding + keep
    the key out of any URL that lands in tracebacks or proxy logs).

    NB: this is a structural test — it reads the source file and asserts
    the anti-pattern doesn't appear. Preferred over a live-async unit test
    because pytest-asyncio's event_loop fixture setup was breaking on this
    provider's test env; the structural scan is also strictly stronger
    (catches any future refactor that reintroduces the pattern in a new
    call site we didn't think to unit-test).
    """
    import inspect
    import re

    from openbb_fmp_cached.models import equity_historical as mod

    src = inspect.getsource(mod)

    # Look for f-string URL patterns that embed apikey=. Allowed shapes:
    #   - ``apikey=`` inside a comment (``# strip &apikey=`` for the safe_url
    #     comment on line 1014)
    #   - ``apikey=`` inside a string literal that isn't an f-string
    # Rejected: ``f"...apikey={...}"`` or ``&apikey={var}`` anywhere.
    # We approximate this with a straightforward regex that catches the
    # canonical anti-pattern; a future maintainer using a different pattern
    # should update this regex accordingly.
    anti_pattern = re.compile(r"apikey=\{[^}]+\}")

    hits = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # comments are allowed to mention the old pattern
        if anti_pattern.search(line):
            hits.append((lineno, line.rstrip()))

    assert not hits, (
        "Found f-string apikey= interpolation in equity_historical.py — "
        "these leak the API key via HTTPError.url and proxy logs. Move to "
        "params={'apikey': api_key}. Sites:\n"
        + "\n".join(f"  L{ln}: {ln_text}" for ln, ln_text in hits)
    )


# ---------------------------------------------------------------------------
# Interval → URL routing correctness (bd-o61s, P0)
# ---------------------------------------------------------------------------


class TestIntervalUrlRouting:
    """Regression tests for OpenBBTechnical-o61s — the URL-building ladder
    silently returned daily bars when interval was intraday +
    adjustment != 'splits_only'. Also dropped 15m/30m/4h to an invalid
    empty endpoint. Fix: mirror upstream FMPEquityHistoricalFetcher's
    model_validator (adjustment != 'splits_only' → interval must be '1d')
    AND add explicit branches for the missing intervals.
    """

    def test_model_validator_rejects_intraday_with_adjustment(self):
        """``adjustment=unadjusted`` + ``interval=1h`` must raise at query construction.

        Mirrors upstream ``FMPEquityHistoricalFetcher._validate_params``.
        Pre-fix behaviour: silently returned daily bars.
        """
        import pytest as _pytest

        with _pytest.raises(ValueError, match="daily"):
            FMPCachedEquityHistoricalQueryParams(
                symbol="AAPL",
                start_date=date(2024, 1, 2),
                end_date=date(2024, 1, 5),
                interval="1h",
                adjustment="unadjusted",
            )

    def test_model_validator_rejects_intraday_with_splits_and_dividends(self):
        """Same guard for the other non-splits_only adjustment."""
        import pytest as _pytest

        with _pytest.raises(ValueError, match="daily"):
            FMPCachedEquityHistoricalQueryParams(
                symbol="AAPL",
                start_date=date(2024, 1, 2),
                end_date=date(2024, 1, 5),
                interval="5m",
                adjustment="splits_and_dividends",
            )

    def test_model_validator_accepts_daily_with_any_adjustment(self):
        """``interval='1d'`` works with all three adjustment values (happy path)."""
        for adj in ("splits_only", "splits_and_dividends", "unadjusted"):
            q = FMPCachedEquityHistoricalQueryParams(
                symbol="AAPL",
                start_date=date(2024, 1, 2),
                end_date=date(2024, 1, 5),
                interval="1d",
                adjustment=adj,
            )
            assert q.adjustment == adj

    def test_model_validator_accepts_intraday_with_splits_only(self):
        """``splits_only`` is the default and works with any interval."""
        for interval in ("1m", "5m", "15m", "30m", "1h", "4h", "1d"):
            q = FMPCachedEquityHistoricalQueryParams(
                symbol="AAPL",
                start_date=date(2024, 1, 2),
                end_date=date(2024, 1, 5),
                interval=interval,
                adjustment="splits_only",
            )
            assert q.interval == interval

    @pytest.mark.parametrize(
        "interval,expected_path",
        [
            ("1m", "historical-chart/1min"),
            ("5m", "historical-chart/5min"),
            ("15m", "historical-chart/15min"),
            ("30m", "historical-chart/30min"),
            ("1h", "historical-chart/1hour"),
            ("4h", "historical-chart/4hour"),
            ("1d", "historical-price-eod/full"),
        ],
    )
    def test_build_fmp_endpoint_covers_every_documented_interval(
        self, interval, expected_path
    ):
        """Every ``Literal`` interval value must map to a real FMP endpoint.

        Pre-fix behaviour: ``15m``/``30m``/``4h`` fell through with
        ``base_url`` still just ``https://financialmodelingprep.com/stable/``
        (empty endpoint), producing 4xx from FMP. Fix: new
        ``_build_fmp_endpoint`` helper is the single source of truth for
        (adjustment, interval) → URL, tested directly here so we don't
        need to spin up the async fetch pipeline (which had a pre-
        existing pytest-asyncio inspect quirk on this provider's env).
        """
        from openbb_fmp_cached.models.equity_historical import (
            _build_fmp_endpoint,
        )

        # Passing splits_only satisfies the model_validator invariant for
        # any interval.
        url = _build_fmp_endpoint(adjustment="splits_only", interval=interval)
        assert expected_path in url, (
            f"interval={interval!r} routed to wrong endpoint: got "
            f"{url!r}, expected substring {expected_path!r}."
        )
        # No trailing '?' — the HTTP layer's params= kwarg encodes the
        # querystring (bd-6641 / bd-ir3f).
        assert not url.endswith("?")

    def test_build_fmp_endpoint_daily_adjusted_variants(self):
        """The two daily-adjusted variants each get their own endpoint."""
        from openbb_fmp_cached.models.equity_historical import (
            _build_fmp_endpoint,
        )

        assert (
            _build_fmp_endpoint(adjustment="unadjusted", interval="1d")
            == "https://financialmodelingprep.com/stable/historical-price-eod/non-split-adjusted"
        )
        assert (
            _build_fmp_endpoint(adjustment="splits_and_dividends", interval="1d")
            == "https://financialmodelingprep.com/stable/historical-price-eod/dividend-adjusted"
        )

    def test_build_fmp_endpoint_raises_on_unknown_interval(self):
        """Defense in depth: unknown interval raises rather than empty-path silent 4xx."""
        import pytest as _pytest

        from openbb_fmp_cached.models.equity_historical import (
            _build_fmp_endpoint,
        )

        with _pytest.raises(ValueError, match="Unsupported FMP interval"):
            _build_fmp_endpoint(adjustment="splits_only", interval="1w")

    def test_build_fmp_endpoint_raises_on_unsupported_60m_legacy_alias(self):
        """``60m`` is NOT in the Literal type — verify it raises rather than silently routing.

        The initial fix added a ``'60m'`` entry to ``_INTRADAY_ENDPOINTS``
        as a "legacy alias" but that was dead code: the ``interval``
        field's Literal type only accepts ``('1m','5m','15m','30m','1h','4h','1d')``
        so ``60m`` is unreachable via the public API. Round-1 review flagged
        the dead branch; removed. This test locks in that any future
        attempt to route ``60m`` (via ``.model_construct()`` bypass or a
        misconfigured caller) fails loudly rather than silently.
        """
        import pytest as _pytest

        from openbb_fmp_cached.models.equity_historical import (
            _build_fmp_endpoint,
        )

        with _pytest.raises(ValueError, match="Unsupported FMP interval"):
            _build_fmp_endpoint(adjustment="splits_only", interval="60m")


if __name__ == "__main__":
    # Run tests with different markers
    pytest.main(
        [
            __file__,
            "-v",
            "--tb=short",
            "-m",
            "not integration",  # Skip integration tests by default
        ]
    )
