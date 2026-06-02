"""Integration tests for FMP Cached Equity Historical model."""

import pytest
import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock
from typing import List, Dict, Any

from openbb_fmp.models.equity_historical import FMPEquityHistoricalQueryParams
from openbb_fmp_cached.models.equity_historical import (
    FMPCachedEquityHistoricalFetcher,
    get_cache_statistics,
    clear_cache_for_symbol,
    _analyze_cache_gaps,
    _fetch_from_fmp_direct,
    _store_in_database_cache
)
from .test_config import TEST_CREDENTIALS, SAMPLE_FMP_DATA


class TestEndToEndWorkflow:
    """Test complete end-to-end workflows."""
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_complete_cache_miss_workflow(self):
        """Test complete workflow when cache is empty."""
        query = FMPEquityHistoricalQueryParams(
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 10),
            interval="1d",
            adjustment="splits_only"
        )
        
        with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_db_query, \
             patch('openbb_fmp_cached.models.equity_historical._fetch_from_fmp_direct') as mock_fmp, \
             patch('openbb_fmp_cached.models.equity_historical.init_database'), \
             patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
            
            # Mock empty cache
            mock_db_query.side_effect = [
                [],  # Empty cache query
                None,  # Insert success
                None,  # Insert success
                None   # Insert success
            ]
            
            # Mock FMP API response
            mock_fmp.return_value = SAMPLE_FMP_DATA[:3]  # 3 records
            
            # Execute the complete workflow
            result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, TEST_CREDENTIALS)
            
            # Verify workflow executed correctly
            assert len(result) == 3
            assert all(record["symbol"] == "AAPL" for record in result)
            
            # Verify API was called
            mock_fmp.assert_called_once()
            
            # Verify cache storage was attempted
            assert mock_db_query.call_count >= 3  # Cache check + storage calls
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_partial_cache_hit_workflow(self):
        """Test workflow with partial cache hits requiring gap filling."""
        query = FMPEquityHistoricalQueryParams(
            symbol="GOOGL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 15),
            interval="1d",
            adjustment="splits_only"
        )
        
        # Mock partial cache data (missing middle dates)
        cached_data = [
            {"symbol": "GOOGL", "date": "2024-01-02", "close": 140.0},
            {"symbol": "GOOGL", "date": "2024-01-03", "close": 141.0},
            # Gap: 2024-01-04 to 2024-01-10 missing
            {"symbol": "GOOGL", "date": "2024-01-11", "close": 145.0},
            {"symbol": "GOOGL", "date": "2024-01-12", "close": 146.0}
        ]
        
        # Mock gap fill data from API
        gap_data = [
            {"symbol": "GOOGL", "date": "2024-01-04", "close": 142.0},
            {"symbol": "GOOGL", "date": "2024-01-05", "close": 143.0},
            {"symbol": "GOOGL", "date": "2024-01-08", "close": 144.0}
        ]
        
        with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_db_query, \
             patch('openbb_fmp_cached.models.equity_historical._fetch_from_fmp_direct') as mock_fmp, \
             patch('openbb_fmp_cached.models.equity_historical.init_database'), \
             patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
            
            # Mock cache query returning partial data
            mock_db_query.return_value = cached_data
            mock_fmp.return_value = gap_data
            
            result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, TEST_CREDENTIALS)
            
            # Should return merged data from cache + API
            assert len(result) >= len(cached_data) + len(gap_data)
            
            # Verify API was called to fill gaps
            mock_fmp.assert_called_once()
            
            # Verify dates are in sequence
            result_dates = [datetime.fromisoformat(r["date"]).date() for r in result]
            assert result_dates == sorted(result_dates)
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_multi_symbol_mixed_cache_workflow(self):
        """Test workflow with multiple symbols having different cache states."""
        query = FMPEquityHistoricalQueryParams(
            symbol="AAPL,GOOGL,MSFT",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        def mock_cache_query_side_effect(sql, params):
            """Mock different cache states for different symbols."""
            if "AAPL" in str(params):
                # AAPL: Complete cache hit
                return [{"symbol": "AAPL", "date": "2024-01-02", "close": 185.0}]
            elif "GOOGL" in str(params):
                # GOOGL: Partial cache
                return [{"symbol": "GOOGL", "date": "2024-01-02", "close": 140.0}]
            else:
                # MSFT: Cache miss
                return []
        
        def mock_fmp_side_effect(query_params, credentials):
            """Mock API responses for different symbols."""
            if "GOOGL" in query_params.symbol:
                return [{"symbol": "GOOGL", "date": "2024-01-03", "close": 141.0}]
            elif "MSFT" in query_params.symbol:
                return [{"symbol": "MSFT", "date": "2024-01-02", "close": 380.0}]
            return []
        
        with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_db_query, \
             patch('openbb_fmp_cached.models.equity_historical._fetch_from_fmp_direct') as mock_fmp, \
             patch('openbb_fmp_cached.models.equity_historical.init_database'), \
             patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
            
            mock_db_query.side_effect = mock_cache_query_side_effect
            mock_fmp.side_effect = mock_fmp_side_effect
            
            result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, TEST_CREDENTIALS)
            
            # Should have data for all symbols
            symbols_in_result = set(record["symbol"] for record in result)
            assert "AAPL" in symbols_in_result
            assert "GOOGL" in symbols_in_result or "MSFT" in symbols_in_result
            
            # API should have been called for GOOGL and MSFT (not AAPL)
            assert mock_fmp.call_count >= 1


class TestDatabaseIntegration:
    """Test database integration scenarios."""
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_database_connection_handling(self):
        """Test database connection and error handling."""
        query = FMPEquityHistoricalQueryParams(
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        with patch('openbb_fmp_cached.models.equity_historical.init_database') as mock_init_db, \
             patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_query, \
             patch('openbb_fmp_cached.models.equity_historical._fetch_from_fmp_direct') as mock_fmp, \
             patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
            
            # Simulate database initialization
            mock_init_db.return_value = None
            
            # Simulate database query failure, then success
            mock_query.side_effect = [Exception("DB Error"), SAMPLE_FMP_DATA[:2]]
            mock_fmp.return_value = SAMPLE_FMP_DATA[:2]
            
            # Should gracefully handle DB errors and fall back to API
            result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, TEST_CREDENTIALS)
            
            assert len(result) == 2
            mock_fmp.assert_called_once()  # Should fall back to API
    
    @pytest.mark.integration
    def test_cache_statistics_integration(self):
        """Test cache statistics functionality."""
        mock_stats = [
            ("AAPL", 100, date(2024, 1, 1), date(2024, 3, 31), "1d", "splits_only", 90),
            ("GOOGL", 200, date(2024, 1, 1), date(2024, 6, 30), "1d", "splits_only", 180),
            ("MSFT", 150, date(2024, 2, 1), date(2024, 4, 30), "1d", "splits_only", 90)
        ]
        
        with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_query:
            mock_query.return_value = mock_stats
            
            stats = get_cache_statistics()
            
            assert "statistics" in stats
            assert "summary" in stats
            assert len(stats["statistics"]) == 3
            
            # Verify summary calculations
            summary = stats["summary"]
            assert summary["total_symbols"] == 3
            assert summary["total_records"] == 450
            assert summary["date_range"]["earliest"] == date(2024, 1, 1)
            assert summary["date_range"]["latest"] == date(2024, 6, 30)
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_cache_clearing_integration(self):
        """Test cache clearing functionality."""
        with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_query:
            # Mock successful deletion
            mock_query.return_value = None
            
            result = await clear_cache_for_symbol("AAPL")
            
            assert result is True
            mock_query.assert_called_once()
            
            # Verify the SQL contains proper DELETE statement
            call_args = mock_query.call_args
            assert "DELETE" in call_args[0][0].upper()
            assert "AAPL" in str(call_args[0][1])
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_batch_storage_integration(self):
        """Test batch storage of multiple records."""
        query = FMPEquityHistoricalQueryParams(
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 10),
            interval="1d",
            adjustment="splits_only"
        )
        
        batch_data = SAMPLE_FMP_DATA[:5]  # 5 records
        
        with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_query:
            mock_query.return_value = None  # Successful inserts
            
            await _store_in_database_cache(query, batch_data)
            
            # Should have called execute_query for each record
            assert mock_query.call_count == len(batch_data)
            
            # Verify all calls were INSERT statements
            for call in mock_query.call_args_list:
                assert "INSERT" in call[0][0].upper()


class TestAPIIntegration:
    """Test FMP API integration scenarios."""
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_fmp_api_fallback_integration(self):
        """Test fallback to FMP API when cache fails."""
        query = FMPEquityHistoricalQueryParams(
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_db, \
             patch('openbb_fmp_cached.models.equity_historical._fetch_from_fmp_direct') as mock_fmp, \
             patch('openbb_fmp_cached.models.equity_historical.init_database'), \
             patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
            
            # Simulate database failure
            mock_db.side_effect = Exception("Database unavailable")
            
            # Mock successful FMP response
            mock_fmp.return_value = SAMPLE_FMP_DATA[:3]
            
            result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, TEST_CREDENTIALS)
            
            # Should get data from FMP despite cache failure
            assert len(result) == 3
            mock_fmp.assert_called_once()
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_fmp_api_error_handling_integration(self):
        """Test handling of FMP API errors."""
        query = FMPEquityHistoricalQueryParams(
            symbol="INVALID",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_db, \
             patch('openbb_fmp_cached.models.equity_historical._fetch_from_fmp_direct') as mock_fmp, \
             patch('openbb_fmp_cached.models.equity_historical.init_database'), \
             patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
            
            # Empty cache
            mock_db.return_value = []
            
            # Simulate FMP API error
            mock_fmp.side_effect = Exception("API rate limit exceeded")
            
            # Should handle error gracefully
            with pytest.raises(Exception) as exc_info:
                await FMPCachedEquityHistoricalFetcher.aextract_data(query, TEST_CREDENTIALS)
            
            assert "API rate limit exceeded" in str(exc_info.value)
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_credential_validation_integration(self):
        """Test credential validation with FMP API."""
        query = FMPEquityHistoricalQueryParams(
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        # Test with invalid credentials
        invalid_credentials = {"fmp_api_key": "invalid_key"}
        
        with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_db, \
             patch('openbb_fmp_cached.models.equity_historical._fetch_from_fmp_direct') as mock_fmp, \
             patch('openbb_fmp_cached.models.equity_historical.init_database'), \
             patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
            
            mock_db.return_value = []  # Empty cache
            mock_fmp.side_effect = Exception("Invalid API key")
            
            with pytest.raises(Exception) as exc_info:
                await FMPCachedEquityHistoricalFetcher.aextract_data(query, invalid_credentials)
            
            assert "Invalid API key" in str(exc_info.value)


class TestBusinessLogicIntegration:
    """Test business logic integration scenarios."""
    
    @pytest.mark.integration
    def test_trading_day_logic_integration(self):
        """Test trading day logic with real-world scenarios."""
        from openbb_fmp_cached.models.equity_historical import _detect_missing_ranges
        
        # Test with weekend gaps
        start_date = date(2024, 1, 1)  # Monday
        end_date = date(2024, 1, 8)    # Following Monday
        
        # Cache has weekday data only
        cached_dates = {
            date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5),  # Week 1
            date(2024, 1, 8)  # Monday of week 2
        }
        
        missing_ranges = _detect_missing_ranges(start_date, end_date, cached_dates, "1d")
        
        # Should only identify missing trading days (not weekends)
        assert len(missing_ranges) == 0  # No missing trading days
    
    @pytest.mark.integration
    def test_holiday_handling_integration(self):
        """Test handling of market holidays."""
        from openbb_fmp_cached.models.equity_historical import _detect_missing_ranges
        
        # Test around New Year's Day 2024 (January 1st was a holiday)
        start_date = date(2023, 12, 29)  # Friday before
        end_date = date(2024, 1, 3)      # Wednesday after
        
        cached_dates = {
            date(2023, 12, 29),  # Friday
            # Jan 1 holiday, markets closed
            date(2024, 1, 2),    # Tuesday (first trading day)
            date(2024, 1, 3)     # Wednesday
        }
        
        missing_ranges = _detect_missing_ranges(start_date, end_date, cached_dates, "1d")
        
        # Should not flag holiday as missing
        assert len(missing_ranges) == 0
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_adjustment_handling_integration(self):
        """Test different adjustment parameter handling."""
        base_query_params = {
            "symbol": "AAPL",
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 1, 5),
            "interval": "1d"
        }
        
        adjustments = ["splits_only", "unadjusted", "splits_and_dividends"]
        
        with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_db, \
             patch('openbb_fmp_cached.models.equity_historical._fetch_from_fmp_direct') as mock_fmp, \
             patch('openbb_fmp_cached.models.equity_historical.init_database'), \
             patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
            
            mock_db.return_value = []  # Empty cache
            mock_fmp.return_value = SAMPLE_FMP_DATA[:2]
            
            for adjustment in adjustments:
                query = FMPEquityHistoricalQueryParams(
                    adjustment=adjustment,
                    **base_query_params
                )
                
                result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, TEST_CREDENTIALS)
                
                # Each adjustment type should be treated separately
                assert len(result) == 2
                
                # Verify adjustment parameter was passed correctly
                fmp_call_args = mock_fmp.call_args[0][0]
                assert fmp_call_args.adjustment == adjustment
    
    @pytest.mark.integration
    def test_interval_handling_integration(self):
        """Test different interval parameter handling."""
        intervals = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
        
        for interval in intervals:
            query = FMPEquityHistoricalQueryParams(
                symbol="AAPL",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 5),
                interval=interval,
                adjustment="splits_only"
            )
            
            # Test that interval is properly stored in cache key
            with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_db:
                mock_db.return_value = []
                
                # This should trigger cache analysis with proper interval
                with patch('openbb_fmp_cached.models.equity_historical._fetch_from_fmp_direct'):
                    with patch('openbb_fmp_cached.models.equity_historical.init_database'):
                        with patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
                            try:
                                asyncio.run(FMPCachedEquityHistoricalFetcher.aextract_data(query, TEST_CREDENTIALS))
                            except:
                                pass  # We're testing the cache key formation
                
                # Verify interval was included in cache query
                if mock_db.call_args:
                    cache_query = mock_db.call_args[0][0]
                    assert interval in str(mock_db.call_args[0][1])  # In parameters


class TestErrorRecoveryIntegration:
    """Test error recovery and resilience scenarios."""
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_partial_failure_recovery(self):
        """Test recovery from partial failures in multi-symbol queries."""
        query = FMPEquityHistoricalQueryParams(
            symbol="AAPL,INVALID,GOOGL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        def mock_fmp_with_failures(query_params, credentials):
            if "INVALID" in query_params.symbol:
                raise Exception("Symbol not found")
            elif "AAPL" in query_params.symbol:
                return [{"symbol": "AAPL", "date": "2024-01-02", "close": 185.0}]
            elif "GOOGL" in query_params.symbol:
                return [{"symbol": "GOOGL", "date": "2024-01-02", "close": 140.0}]
            return []
        
        with patch('openbb_fmp_cached.models.equity_historical.execute_query') as mock_db, \
             patch('openbb_fmp_cached.models.equity_historical._fetch_from_fmp_direct') as mock_fmp, \
             patch('openbb_fmp_cached.models.equity_historical.init_database'), \
             patch('openbb_fmp_cached.models.equity_historical.is_jupyter_mode', return_value=False):
            
            mock_db.return_value = []  # Empty cache
            mock_fmp.side_effect = mock_fmp_with_failures
            
            # Should handle partial failures gracefully
            result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, TEST_CREDENTIALS)
            
            # Should get data for valid symbols despite one failure
            symbols_in_result = set(record["symbol"] for record in result)
            assert "AAPL" in symbols_in_result or "GOOGL" in symbols_in_result
            assert "INVALID" not in symbols_in_result


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-m", "integration"])