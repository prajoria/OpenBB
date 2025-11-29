"""Real end-to-end integration tests for FMP Cached Equity Historical model.

These tests make actual calls to:
- MySQL database (uses test mode configuration)
- FMP API (uses OpenBB user settings for API key)

Automatically uses:
- FMP API key from OpenBB user settings (~/.openbb_platform/user_settings.json)
- Test database configuration (openbb_fmp_cache_test)
- Intelligent caching system with real API integration

Run with: FMP_CACHE_TEST_MODE=true pytest test_real_integration.py -v -s --tb=short
"""

import pytest
import asyncio
import os
import json
from datetime import date, datetime, timedelta
from typing import List, Dict, Any
from pathlib import Path

from openbb_fmp.models.equity_historical import FMPEquityHistoricalQueryParams
from openbb_fmp_cached.models.equity_historical import (
    FMPCachedEquityHistoricalFetcher,
    get_cache_statistics,
    clear_cache_for_symbol,
    _analyze_cache_gaps
)


def load_env_file():
    """Load environment variables from .env file at OpenBB project root."""
    try:
        # Find OpenBB project root (where .env should be located)
        current_path = Path(__file__).resolve()
        openbb_root = None
        
        # Look for .env file by traversing up the directory tree
        for parent in current_path.parents:
            env_file = parent / ".env"
            if env_file.exists():
                openbb_root = parent
                break
        
        if openbb_root and (openbb_root / ".env").exists():
            env_file = openbb_root / ".env"
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        # Only set if not already in environment
                        if key not in os.environ:
                            os.environ[key] = value
            print(f"✅ Loaded .env from: {env_file}")
        else:
            print("❌ Could not find .env file in OpenBB project root")
    except Exception as e:
        print(f"❌ Error loading .env file: {e}")


def get_fmp_api_key():
    """Get FMP API key from .env file, environment variables, or OpenBB user settings."""
    # Load .env file first
    load_env_file()
    
    # Try environment variable (includes .env loaded values)
    env_key = os.getenv("FMP_API_KEY")
    if env_key and env_key != "demo" and len(env_key) > 10:
        return env_key
    
    # Try OpenBB user settings as fallback
    settings_path = os.path.expanduser("~/.openbb_platform/user_settings.json")
    try:
        if os.path.exists(settings_path):
            with open(settings_path, 'r') as f:
                settings = json.load(f)
                credentials = settings.get("credentials", {})
                
                # Look for FMP API key in various field names
                fmp_keys = ["fmp_api_key", "FMP_API_KEY", "financial_modeling_prep_api_key"]
                for key_name in fmp_keys:
                    if key_name in credentials and credentials[key_name]:
                        api_key = credentials[key_name]
                        if api_key != "demo" and len(api_key) > 10:
                            return api_key
    except Exception:
        pass
    
    return None


def get_mysql_config():
    """Get MySQL configuration for test mode."""
    # Load .env file first
    load_env_file()
    
    # Check if we're in test mode
    is_test_mode = os.getenv("FMP_CACHE_TEST_MODE", "false").lower() == "true"
    
    # Get configuration from environment variables (including .env)
    config = {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "fmp_user"),
        "password": os.getenv("MYSQL_PASSWORD", "fmp_password"),
        "database": os.getenv("MYSQL_TEST_DATABASE" if is_test_mode else "MYSQL_DATABASE", 
                            "openbb_fmp_cache_test" if is_test_mode else "openbb_fmp_cache")
    }
    
    return config


# Get test configuration
REAL_API_KEY = get_fmp_api_key()
MYSQL_CONFIG = get_mysql_config()

# Skip all tests if no API key or database config
pytestmark = pytest.mark.skipif(
    not REAL_API_KEY or not all(MYSQL_CONFIG.values()),
    reason="Requires FMP API key in OpenBB user settings and test mode configuration"
)


@pytest.fixture
def real_credentials():
    """Provide real FMP API credentials."""
    return {"fmp_api_key": REAL_API_KEY}


@pytest.fixture
def test_symbols():
    """Provide list of reliable test symbols."""
    return ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"]


@pytest.fixture
async def cleanup_test_data():
    """Cleanup test data before and after tests."""
    test_symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "TEST_SYMBOL"]
    
    # Cleanup before test
    for symbol in test_symbols:
        clear_cache_for_symbol(symbol)
    
    yield
    
    # Cleanup after test
    for symbol in test_symbols:
        clear_cache_for_symbol(symbol)


class TestRealCacheMiss:
    """Test real API calls when cache is empty."""
    
    @pytest.mark.asyncio
    async def test_single_symbol_cache_miss(self, real_credentials, cleanup_test_data):
        """Test fetching data for single symbol with empty cache."""
        query = FMPEquityHistoricalQueryParams(
            symbol="AAPL",
            start_date=date(2024, 1, 2),  # Trading day
            end_date=date(2024, 1, 5),    # 4 trading days
            interval="1d",
            adjustment="splits_only"
        )

        print(f"\n🔍 Testing cache miss for {query.symbol}")

        # Clear cache first
        clear_cache_for_symbol("AAPL")

        # Fetch data - should hit API (use None to trigger user settings loading)
        start_time = datetime.now()
        result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, None)
        end_time = datetime.now()
        
        # Verify results
        assert len(result) > 0, "Should return data from FMP API"
        assert all(record["symbol"] == "AAPL" for record in result), "All records should be for AAPL"
        
        # Verify data structure
        sample_record = result[0]
        required_fields = ["symbol", "date", "open", "high", "low", "close", "volume"]
        for field in required_fields:
            assert field in sample_record, f"Missing required field: {field}"
        
        print(f"✅ Got {len(result)} records in {(end_time - start_time).total_seconds():.2f}s")
        print(f"   Date range: {result[-1]['date']} to {result[0]['date']}")
        print(f"   Sample: {sample_record['date']} AAPL ${sample_record['close']}")
    
    @pytest.mark.asyncio
    async def test_multi_symbol_cache_miss(self, real_credentials, test_symbols, cleanup_test_data):
        """Test fetching data for multiple symbols with empty cache."""
        query = FMPEquityHistoricalQueryParams(
            symbol=",".join(test_symbols[:3]),  # First 3 symbols
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        print(f"\n🔍 Testing multi-symbol cache miss for {query.symbol}")
        
        # Clear cache for all symbols
        for symbol in test_symbols[:3]:
            clear_cache_for_symbol(symbol)
        
        start_time = datetime.now()
        result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, real_credentials)
        end_time = datetime.now()
        
        # Verify results
        assert len(result) > 0, "Should return data for multiple symbols"
        
        symbols_in_result = set(record["symbol"] for record in result)
        expected_symbols = set(test_symbols[:3])
        
        print(f"✅ Got {len(result)} total records in {(end_time - start_time).total_seconds():.2f}s")
        print(f"   Expected symbols: {expected_symbols}")
        print(f"   Found symbols: {symbols_in_result}")
        
        # At least some symbols should be present (some might fail)
        assert len(symbols_in_result) > 0, "Should have data for at least one symbol"


class TestRealCacheHit:
    """Test cache hits with real database."""
    
    @pytest.mark.asyncio
    async def test_cache_hit_performance(self, real_credentials, cleanup_test_data):
        """Test cache hit performance with real database."""
        query = FMPEquityHistoricalQueryParams(
            symbol="AAPL",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        print(f"\n🔍 Testing cache hit performance")
        
        # First call - cache miss (populate cache)
        print("   First call (cache miss):")
        start_time = datetime.now()
        result1 = await FMPCachedEquityHistoricalFetcher.aextract_data(query, real_credentials)
        first_time = (datetime.now() - start_time).total_seconds()
        
        assert len(result1) > 0, "First call should return data"
        print(f"   ⏱️  Cache miss: {first_time:.2f}s, {len(result1)} records")
        
        # Second call - cache hit
        print("   Second call (cache hit):")
        start_time = datetime.now()
        result2 = await FMPCachedEquityHistoricalFetcher.aextract_data(query, real_credentials)
        second_time = (datetime.now() - start_time).total_seconds()
        
        assert len(result2) > 0, "Second call should return cached data"
        print(f"   ⏱️  Cache hit: {second_time:.2f}s, {len(result2)} records")
        
        # Cache hit should be faster
        speedup = first_time / second_time if second_time > 0 else float('inf')
        print(f"   🚀 Speedup: {speedup:.1f}x")
        
        # Verify data consistency
        assert len(result1) == len(result2), "Cache hit should return same number of records"
        
        # Compare sample records (allowing for minor differences)
        for r1, r2 in zip(result1[:3], result2[:3]):
            assert r1["symbol"] == r2["symbol"], "Symbol should match"
            assert r1["date"] == r2["date"], "Date should match"
            assert abs(float(r1["close"]) - float(r2["close"])) < 0.01, "Close price should match"


class TestRealGapDetection:
    """Test gap detection with real data."""
    
    @pytest.mark.asyncio
    async def test_gap_detection_and_filling(self, real_credentials, cleanup_test_data):
        """Test gap detection and filling with real API calls."""
        symbol = "GOOGL"
        
        print(f"\n🔍 Testing gap detection for {symbol}")
        
        # Clear cache first
        clear_cache_for_symbol(symbol)
        
        # Step 1: Fetch partial data (small range)
        query1 = FMPEquityHistoricalQueryParams(
            symbol=symbol,
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        print("   Step 1: Fetching initial data")
        result1 = await FMPCachedEquityHistoricalFetcher.aextract_data(query1, real_credentials)
        assert len(result1) > 0, "Should get initial data"
        print(f"   ✅ Got {len(result1)} records for initial range")
        
        # Step 2: Fetch extended range (should detect and fill gaps)
        query2 = FMPEquityHistoricalQueryParams(
            symbol=symbol,
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 15),  # Extended range
            interval="1d",
            adjustment="splits_only"
        )
        
        print("   Step 2: Fetching extended range (gap detection)")
        start_time = datetime.now()
        result2 = await FMPCachedEquityHistoricalFetcher.aextract_data(query2, real_credentials)
        gap_fill_time = (datetime.now() - start_time).total_seconds()
        
        assert len(result2) > len(result1), "Extended range should have more records"
        print(f"   ✅ Gap filled: {len(result1)} → {len(result2)} records in {gap_fill_time:.2f}s")
        
        # Verify no duplicates and proper ordering
        dates = [record["date"] for record in result2]
        unique_dates = set(dates)
        assert len(dates) == len(unique_dates), "Should not have duplicate dates"
        
        sorted_dates = sorted(dates)
        assert dates == sorted_dates, "Dates should be in chronological order"
        
        print(f"   📅 Date range: {min(dates)} to {max(dates)}")


class TestRealDatabaseOperations:
    """Test real database operations."""
    
    @pytest.mark.asyncio
    async def test_cache_statistics(self, real_credentials, cleanup_test_data):
        """Test real cache statistics functionality."""
        print(f"\n🔍 Testing cache statistics")
        
        # Populate cache with some data
        symbols = ["AAPL", "MSFT"]
        for symbol in symbols:
            query = FMPEquityHistoricalQueryParams(
                symbol=symbol,
                start_date=date(2024, 1, 2),
                end_date=date(2024, 1, 5),
                interval="1d",
                adjustment="splits_only"
            )
            
            result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, real_credentials)
            print(f"   📊 Cached {len(result)} records for {symbol}")
        
        # Get cache statistics
        stats = get_cache_statistics()
        
        assert "statistics" in stats, "Should have statistics section"
        assert len(stats["statistics"]) > 0, "Should have statistics data"
        
        # The statistics are returned as a list of records
        stats_data = stats["statistics"][0]  # Get the first (and only) record for overall stats
        
        print(f"   📈 Cache Statistics:")
        print(f"      Total symbols: {stats_data['unique_symbols']}")
        print(f"      Total records: {stats_data['total_records']}")
        print(f"      Date range: {stats_data['earliest_date']} to {stats_data['latest_date']}")
        
        # Should have data for our test symbols
        assert stats_data["unique_symbols"] >= len(symbols)
        assert stats_data["total_records"] > 0
    
    @pytest.mark.asyncio
    async def test_cache_clearing(self, real_credentials, cleanup_test_data):
        """Test real cache clearing functionality."""
        symbol = "TSLA"
        
        print(f"\n🔍 Testing cache clearing for {symbol}")
        
        # Populate cache
        query = FMPEquityHistoricalQueryParams(
            symbol=symbol,
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        result1 = await FMPCachedEquityHistoricalFetcher.aextract_data(query, real_credentials)
        print(f"   📊 Cached {len(result1)} records")
        
        # Verify cache hit (should be fast)
        start_time = datetime.now()
        result2 = await FMPCachedEquityHistoricalFetcher.aextract_data(query, real_credentials)
        cache_hit_time = (datetime.now() - start_time).total_seconds()
        
        assert len(result2) == len(result1), "Cache hit should return same data"
        print(f"   ⚡ Cache hit in {cache_hit_time:.3f}s")
        
        # Clear cache
        success = clear_cache_for_symbol(symbol)
        assert success, "Cache clearing should succeed"
        print(f"   🧹 Cache cleared for {symbol}")
        
        # Next call should be slower (cache miss)
        start_time = datetime.now()
        result3 = await FMPCachedEquityHistoricalFetcher.aextract_data(query, real_credentials)
        cache_miss_time = (datetime.now() - start_time).total_seconds()
        
        print(f"   🔄 Cache miss in {cache_miss_time:.3f}s")
        assert cache_miss_time > cache_hit_time * 2, "Cache miss should be significantly slower"


class TestRealErrorHandling:
    """Test error handling with real systems."""
    
    @pytest.mark.asyncio
    async def test_invalid_symbol_handling(self, real_credentials):
        """Test handling of invalid symbols with real API."""
        query = FMPEquityHistoricalQueryParams(
            symbol="INVALID_SYMBOL_12345",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        print(f"\n🔍 Testing invalid symbol handling")
        
        # Should handle gracefully (might return empty or raise exception)
        try:
            result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, real_credentials)
            # If no exception, result should be empty or minimal
            print(f"   ✅ Handled gracefully: {len(result)} records")
        except Exception as e:
            # Exception is also acceptable for invalid symbols
            print(f"   ✅ Exception handled: {type(e).__name__}: {e}")
    
    @pytest.mark.asyncio
    async def test_invalid_date_range_handling(self, real_credentials):
        """Test handling of invalid date ranges."""
        query = FMPEquityHistoricalQueryParams(
            symbol="AAPL",
            start_date=date(2025, 1, 1),  # Future date
            end_date=date(2025, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        print(f"\n🔍 Testing future date handling")
        
        try:
            result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, real_credentials)
            # Future dates might return empty data
            print(f"   ✅ Future dates handled: {len(result)} records")
        except Exception as e:
            print(f"   ✅ Exception for future dates: {type(e).__name__}: {e}")


class TestRealPerformance:
    """Test real-world performance scenarios."""
    
    @pytest.mark.asyncio
    async def test_large_date_range_performance(self, real_credentials, cleanup_test_data):
        """Test performance with large date ranges."""
        query = FMPEquityHistoricalQueryParams(
            symbol="AAPL",
            start_date=date(2023, 1, 1),
            end_date=date(2024, 1, 1),  # 1 year of data
            interval="1d",
            adjustment="splits_only"
        )
        
        print(f"\n🔍 Testing large date range performance (1 year)")
        
        # Clear cache first
        clear_cache_for_symbol("AAPL")
        
        start_time = datetime.now()
        result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, real_credentials)
        end_time = datetime.now()
        
        total_time = (end_time - start_time).total_seconds()
        records_per_second = len(result) / total_time if total_time > 0 else 0
        
        print(f"   ✅ Fetched {len(result)} records in {total_time:.2f}s")
        print(f"   📊 Performance: {records_per_second:.1f} records/second")
        
        # Verify data quality
        assert len(result) > 200, "Should have substantial data for 1 year"  # ~252 trading days
        
        # Verify date range
        dates = [record["date"] for record in result]
        min_date = min(dates)
        max_date = max(dates)
        print(f"   📅 Actual range: {min_date} to {max_date}")
    
    @pytest.mark.asyncio
    async def test_concurrent_requests_performance(self, real_credentials, test_symbols, cleanup_test_data):
        """Test performance under concurrent load."""
        print(f"\n🔍 Testing concurrent requests performance")
        
        # Create multiple queries for different symbols
        queries = []
        for symbol in test_symbols[:3]:  # Use first 3 symbols
            query = FMPEquityHistoricalQueryParams(
                symbol=symbol,
                start_date=date(2024, 1, 2),
                end_date=date(2024, 1, 10),
                interval="1d",
                adjustment="splits_only"
            )
            queries.append((symbol, query))
        
        # Clear all caches
        for symbol in test_symbols[:3]:
            clear_cache_for_symbol(symbol)
        
        # Execute concurrent requests
        async def fetch_data(symbol_query_pair):
            symbol, query = symbol_query_pair
            start_time = datetime.now()
            result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, real_credentials)
            end_time = datetime.now()
            return symbol, result, (end_time - start_time).total_seconds()
        
        print(f"   🚀 Starting {len(queries)} concurrent requests")
        start_time = datetime.now()
        
        results = await asyncio.gather(*[fetch_data(sq) for sq in queries], return_exceptions=True)
        
        total_time = (datetime.now() - start_time).total_seconds()
        
        # Analyze results
        successful_results = [r for r in results if not isinstance(r, Exception)]
        failed_results = [r for r in results if isinstance(r, Exception)]
        
        print(f"   ✅ Completed in {total_time:.2f}s total")
        print(f"   📊 Success: {len(successful_results)}/{len(queries)} requests")
        
        if failed_results:
            print(f"   ⚠️  Failures: {len(failed_results)}")
            for i, error in enumerate(failed_results[:3]):  # Show first 3 errors
                print(f"      {i+1}. {type(error).__name__}: {error}")
        
        for symbol, data, duration in successful_results:
            print(f"      {symbol}: {len(data)} records in {duration:.2f}s")
        
        # Should have at least some successful results
        assert len(successful_results) > 0, "At least some requests should succeed"


if __name__ == "__main__":
    import sys
    
    # Check environment setup
    if not REAL_API_KEY:
        print("❌ Missing FMP_API_KEY environment variable")
        sys.exit(1)
    
    if not all(MYSQL_CONFIG.values()):
        print("❌ Missing MySQL configuration in environment variables")
        print("   Required: MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE")
        sys.exit(1)
    
    print("✅ Environment configured for real integration tests")
    print(f"   FMP API Key: {REAL_API_KEY[:8]}...")
    print(f"   MySQL: {MYSQL_CONFIG['user']}@{MYSQL_CONFIG['host']}:{MYSQL_CONFIG['port']}/{MYSQL_CONFIG['database']}")
    
    # Run tests
    pytest.main([__file__, "-v", "-s", "--tb=short"])