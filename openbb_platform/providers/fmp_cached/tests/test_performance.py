"""Performance tests for FMP Cached Equity Historical model."""

import pytest
import asyncio
import time
from datetime import date, timedelta
from unittest.mock import patch, MagicMock
from concurrent.futures import ThreadPoolExecutor

from openbb_fmp.models.equity_historical import FMPEquityHistoricalQueryParams
from openbb_fmp_cached.models.equity_historical import (
    FMPCachedEquityHistoricalFetcher,
    _analyze_cache_gaps,
    _detect_missing_ranges,
    get_cache_statistics
)
from .test_config import PERFORMANCE_THRESHOLDS, TEST_CREDENTIALS


class TestCachePerformance:
    """Performance tests for caching operations."""
    
    @pytest.mark.asyncio
    async def test_cache_hit_performance(self):
        """Test cache hit response time is under threshold."""
        query = FMPEquityHistoricalQueryParams(
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 10),
            interval="1d",
            adjustment="splits_only"
        )
        
        # Mock complete cache hit
        cached_data = [
            {"symbol": "AAPL", "date": "2024-01-02", "close": 185.0} for i in range(10)
        ]
        
        with patch('openbb_fmp_cached.models.equity_historical._analyze_cache_gaps') as mock_gaps, \
             patch('openbb_fmp_cached.models.equity_historical.init_database'), \
             patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
            
            mock_gaps.return_value = (cached_data, [])  # Complete cache hit
            
            start_time = time.perf_counter()
            result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, TEST_CREDENTIALS)
            end_time = time.perf_counter()
            
            response_time_ms = (end_time - start_time) * 1000
            
            assert response_time_ms < PERFORMANCE_THRESHOLDS["cache_hit_response_time_ms"]
            assert len(result) == 10
    
    @pytest.mark.asyncio
    async def test_gap_detection_performance(self):
        """Test gap detection performance with large date ranges."""
        start_date = date(2023, 1, 1)
        end_date = date(2024, 12, 31)  # 2 years of data
        
        # Create sparse cached data (many gaps)
        cached_dates = set()
        for i in range(0, 730, 10):  # Every 10th day
            cached_dates.add(start_date + timedelta(days=i))
        
        start_time = time.perf_counter()
        missing_ranges = _detect_missing_ranges(start_date, end_date, cached_dates, "1d")
        end_time = time.perf_counter()
        
        detection_time_ms = (end_time - start_time) * 1000
        
        assert detection_time_ms < PERFORMANCE_THRESHOLDS["gap_detection_time_ms"]
        assert len(missing_ranges) > 0  # Should detect many gaps
    
    @pytest.mark.asyncio
    async def test_multi_symbol_performance(self):
        """Test performance with multiple symbols."""
        symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "META", "NFLX", "NVDA", "ORCL", "CRM"]
        query = FMPEquityHistoricalQueryParams(
            symbol=",".join(symbols),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 10),
            interval="1d",
            adjustment="splits_only"
        )
        
        with patch('openbb_fmp_cached.models.equity_historical._analyze_cache_gaps') as mock_gaps, \
             patch('openbb_fmp_cached.models.equity_historical._fetch_from_fmp_direct') as mock_fetch, \
             patch('openbb_fmp_cached.models.equity_historical._store_in_database_cache'), \
             patch('openbb_fmp_cached.models.equity_historical.init_database'), \
             patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
            
            # Mock cache misses for all symbols
            mock_gaps.return_value = ([], [(date(2024, 1, 1), date(2024, 1, 10))])
            mock_fetch.return_value = [{"symbol": "TEST", "date": "2024-01-02"}]
            
            start_time = time.perf_counter()
            result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, TEST_CREDENTIALS)
            end_time = time.perf_counter()
            
            total_time_s = end_time - start_time
            
            # Should process all symbols efficiently
            assert total_time_s < PERFORMANCE_THRESHOLDS["api_call_timeout_s"]
            assert len(result) == len(symbols)  # One result per symbol
    
    @pytest.mark.asyncio
    async def test_concurrent_requests_performance(self):
        """Test performance under concurrent load."""
        queries = []
        symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"]
        
        for symbol in symbols:
            query = FMPEquityHistoricalQueryParams(
                symbol=symbol,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 5),
                interval="1d",
                adjustment="splits_only"
            )
            queries.append(query)
        
        with patch('openbb_fmp_cached.models.equity_historical._analyze_cache_gaps') as mock_gaps, \
             patch('openbb_fmp_cached.models.equity_historical.init_database'), \
             patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
            
            # Mock cache hits to avoid actual API calls
            mock_gaps.return_value = ([{"symbol": "TEST", "date": "2024-01-02"}], [])
            
            async def process_query(query):
                return await FMPCachedEquityHistoricalFetcher.aextract_data(query, TEST_CREDENTIALS)
            
            start_time = time.perf_counter()
            results = await asyncio.gather(*[process_query(q) for q in queries])
            end_time = time.perf_counter()
            
            total_time_s = end_time - start_time
            avg_time_per_request_ms = (total_time_s / len(queries)) * 1000
            
            # Concurrent processing should be efficient
            assert avg_time_per_request_ms < PERFORMANCE_THRESHOLDS["cache_hit_response_time_ms"] * 2
            assert len(results) == len(queries)


class TestMemoryUsage:
    """Test memory usage and efficiency."""
    
    @pytest.mark.asyncio
    async def test_large_dataset_memory_usage(self):
        """Test memory usage with large datasets."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory_mb = process.memory_info().rss / 1024 / 1024
        
        # Simulate large dataset processing
        large_data = []
        for i in range(10000):  # 10k records
            large_data.append({
                "symbol": "AAPL",
                "date": f"2024-01-{(i % 30) + 1:02d}",
                "open": 180.0 + i * 0.01,
                "high": 185.0 + i * 0.01,
                "low": 179.0 + i * 0.01,
                "close": 184.0 + i * 0.01,
                "volume": 1000000 + i * 1000,
                "change": 1.0,
                "changePercent": 0.5,
                "vwap": 182.0 + i * 0.01
            })
        
        query = FMPEquityHistoricalQueryParams(
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            interval="1d",
            adjustment="splits_only"
        )
        
        with patch('openbb_fmp_cached.models.equity_historical._store_in_database_cache'):
            await _store_in_database_cache(query, large_data)
        
        peak_memory_mb = process.memory_info().rss / 1024 / 1024
        memory_increase_mb = peak_memory_mb - initial_memory_mb
        
        # Memory usage should be reasonable
        assert memory_increase_mb < PERFORMANCE_THRESHOLDS["max_cache_size_mb"]
    
    def test_gap_detection_memory_efficiency(self):
        """Test memory efficiency of gap detection with large date sets."""
        import sys
        
        # Large date range with sparse data
        start_date = date(2020, 1, 1)
        end_date = date(2024, 12, 31)  # 5 years
        
        # Create large sparse cache set
        cached_dates = set()
        for i in range(0, 1825, 7):  # Weekly data over 5 years
            cached_dates.add(start_date + timedelta(days=i))
        
        initial_size = sys.getsizeof(cached_dates)
        
        # Run gap detection
        missing_ranges = _detect_missing_ranges(start_date, end_date, cached_dates, "1d")
        
        final_size = sys.getsizeof(missing_ranges) + initial_size
        
        # Should not create excessive memory overhead
        assert final_size < initial_size * 2  # Less than 2x original size
        assert len(missing_ranges) > 0


class TestDatabasePerformance:
    """Test database operation performance."""
    
    def test_cache_statistics_query_performance(self):
        """Test cache statistics query performance."""
        with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_query:
            # Mock large statistics result
            mock_query.return_value = [
                (f"SYMBOL_{i}", 1000, date(2024, 1, 1), date(2024, 12, 31), "1d", "splits_only", 365)
                for i in range(1000)  # 1000 symbols
            ]
            
            start_time = time.perf_counter()
            stats = get_cache_statistics()
            end_time = time.perf_counter()
            
            query_time_ms = (end_time - start_time) * 1000
            
            # Query should be fast even with many symbols
            assert query_time_ms < 100  # Less than 100ms
            assert "statistics" in stats
            assert len(stats["statistics"]) == 1000
    
    @pytest.mark.asyncio
    async def test_batch_storage_performance(self):
        """Test batch storage performance."""
        # Create large batch of data
        batch_data = []
        for i in range(1000):  # 1000 records
            batch_data.append({
                "symbol": f"SYM{i % 100}",
                "date": f"2024-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
                "open": 100.0 + i,
                "high": 105.0 + i,
                "low": 95.0 + i,
                "close": 102.0 + i,
                "volume": 1000000 + i * 1000,
                "change": 1.0,
                "changePercent": 1.0,
                "vwap": 101.0 + i
            })
        
        query = FMPEquityHistoricalQueryParams(
            symbol="TEST",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            interval="1d",
            adjustment="splits_only"
        )
        
        with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_query:
            mock_query.return_value = None
            
            start_time = time.perf_counter()
            await _store_in_database_cache(query, batch_data)
            end_time = time.perf_counter()
            
            storage_time_ms = (end_time - start_time) * 1000
            
            # Should process 1000 records efficiently
            assert storage_time_ms < 1000  # Less than 1 second
            assert mock_query.call_count == 1000  # One call per record


class TestScalabilityLimits:
    """Test system behavior at scale limits."""
    
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_extreme_date_range(self):
        """Test behavior with extremely large date ranges."""
        start_date = date(1990, 1, 1)  # 34+ years of data
        end_date = date(2024, 12, 31)
        
        cached_dates = set()  # Empty cache
        
        start_time = time.perf_counter()
        missing_ranges = _detect_missing_ranges(start_date, end_date, cached_dates, "1d")
        end_time = time.perf_counter()
        
        processing_time_ms = (end_time - start_time) * 1000
        
        # Should handle extreme ranges without timeout
        assert processing_time_ms < 1000  # Less than 1 second
        assert len(missing_ranges) == 1  # Should be one big range
        assert missing_ranges[0] == (start_date, end_date)
    
    @pytest.mark.slow
    def test_massive_symbol_list(self):
        """Test behavior with very large symbol lists."""
        # Simulate 1000 symbols
        symbols = [f"SYM{i:04d}" for i in range(1000)]
        symbol_string = ",".join(symbols)
        
        query = FMPEquityHistoricalQueryParams(
            symbol=symbol_string,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        # Test symbol parsing doesn't cause performance issues
        start_time = time.perf_counter()
        parsed_symbols = query.symbol.split(",")
        end_time = time.perf_counter()
        
        parsing_time_ms = (end_time - start_time) * 1000
        
        assert parsing_time_ms < 10  # Should be very fast
        assert len(parsed_symbols) == 1000
    
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_memory_stability_under_load(self):
        """Test memory stability under sustained load."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory_mb = process.memory_info().rss / 1024 / 1024
        max_memory_mb = initial_memory_mb
        
        # Simulate 100 consecutive requests
        with patch('openbb_fmp_cached.models.equity_historical._analyze_cache_gaps') as mock_gaps, \
             patch('openbb_fmp_cached.models.equity_historical.init_database'), \
             patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
            
            mock_gaps.return_value = ([{"symbol": "TEST", "date": "2024-01-02"}], [])
            
            for i in range(100):
                query = FMPEquityHistoricalQueryParams(
                    symbol=f"SYM{i % 10}",
                    start_date=date(2024, 1, 1),
                    end_date=date(2024, 1, 5),
                    interval="1d",
                    adjustment="splits_only"
                )
                
                await FMPCachedEquityHistoricalFetcher.aextract_data(query, TEST_CREDENTIALS)
                
                # Check memory every 10 requests
                if i % 10 == 0:
                    current_memory_mb = process.memory_info().rss / 1024 / 1024
                    max_memory_mb = max(max_memory_mb, current_memory_mb)
        
        memory_growth_mb = max_memory_mb - initial_memory_mb
        
        # Memory growth should be bounded
        assert memory_growth_mb < 100  # Less than 100MB growth


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-m", "not slow"])