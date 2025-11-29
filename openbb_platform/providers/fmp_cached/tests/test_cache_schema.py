"""Unit tests for cache schema creation and management."""

import pytest
from unittest.mock import patch, AsyncMock

from openbb_fmp_cached.utils.cache_schema import (
    CACHE_TTL,
    create_cache_metadata_table,
    create_equity_historical_cache,
    create_equity_fundamentals_cache,
    create_equity_quotes_cache,
    create_company_info_cache,
    create_market_data_cache,
    create_calendar_events_cache,
    create_cache_statistics_table,
    create_all_tables,
    initialize_cache_metadata,
    cleanup_expired_cache
)


class TestCacheTTLConfiguration:
    """Test cache TTL configuration."""
    
    def test_ttl_constants_exist(self):
        """Test that all expected TTL constants are defined."""
        expected_keys = [
            "equity_historical_intraday",
            "equity_historical_daily", 
            "equity_quote",
            "balance_sheet",
            "income_statement",
            "cash_flow",
            "company_info",
            "analyst_estimates",
            "calendar_events",
            "market_data",
            "default"
        ]
        
        for key in expected_keys:
            assert key in CACHE_TTL
            assert isinstance(CACHE_TTL[key], int)
            assert CACHE_TTL[key] > 0
    
    def test_ttl_hierarchy(self):
        """Test TTL values are in expected hierarchy (shorter to longer)."""
        # Real-time data should be shortest
        assert CACHE_TTL["equity_quote"] < CACHE_TTL["equity_historical_intraday"]
        
        # Intraday should be shorter than daily
        assert CACHE_TTL["equity_historical_intraday"] < CACHE_TTL["equity_historical_daily"]
        
        # Fundamentals should be daily or longer
        assert CACHE_TTL["balance_sheet"] >= CACHE_TTL["equity_historical_daily"]
        
        # Company info should be longest
        assert CACHE_TTL["company_info"] > CACHE_TTL["balance_sheet"]


class TestTableCreation:
    """Test individual table creation functions."""
    
    @pytest.mark.asyncio
    async def test_create_cache_metadata_table(self):
        """Test cache metadata table creation."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            await create_cache_metadata_table()
            
            mock_query.assert_called_once()
            query = mock_query.call_args[0][0]
            
            # Verify table structure
            assert "CREATE TABLE IF NOT EXISTS cache_metadata" in query
            assert "table_name VARCHAR(255)" in query
            assert "ttl_seconds INT" in query
            assert "created_at TIMESTAMP" in query
    
    @pytest.mark.asyncio
    async def test_create_equity_historical_cache(self):
        """Test equity historical cache table creation."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            await create_equity_historical_cache()
            
            mock_query.assert_called_once()
            query = mock_query.call_args[0][0]
            
            assert "CREATE TABLE IF NOT EXISTS cache_equity_historical" in query
            assert "symbol VARCHAR(50)" in query
            assert "interval_type VARCHAR(10)" in query
            assert "start_date DATE" in query
            assert "end_date DATE" in query
            assert "response_data LONGTEXT" in query
            assert "expires_at TIMESTAMP" in query
            assert "INDEX idx_symbol_interval" in query
    
    @pytest.mark.asyncio
    async def test_create_equity_fundamentals_cache(self):
        """Test equity fundamentals cache table creation."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            await create_equity_fundamentals_cache()
            
            mock_query.assert_called_once()
            query = mock_query.call_args[0][0]
            
            assert "CREATE TABLE IF NOT EXISTS cache_equity_fundamentals" in query
            assert "statement_type VARCHAR(50)" in query
            assert "fiscal_year INT" in query
            assert "fiscal_period VARCHAR(10)" in query
    
    @pytest.mark.asyncio
    async def test_create_equity_quotes_cache(self):
        """Test equity quotes cache table creation."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            await create_equity_quotes_cache()
            
            mock_query.assert_called_once()
            query = mock_query.call_args[0][0]
            
            assert "CREATE TABLE IF NOT EXISTS cache_equity_quotes" in query
            assert "symbol VARCHAR(50)" in query
            assert "response_data TEXT" in query  # Shorter than LONGTEXT for quotes
    
    @pytest.mark.asyncio
    async def test_create_company_info_cache(self):
        """Test company info cache table creation."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            await create_company_info_cache()
            
            mock_query.assert_called_once()
            query = mock_query.call_args[0][0]
            
            assert "CREATE TABLE IF NOT EXISTS cache_company_info" in query
            assert "info_type VARCHAR(100)" in query
    
    @pytest.mark.asyncio
    async def test_create_market_data_cache(self):
        """Test market data cache table creation."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            await create_market_data_cache()
            
            mock_query.assert_called_once()
            query = mock_query.call_args[0][0]
            
            assert "CREATE TABLE IF NOT EXISTS cache_market_data" in query
            assert "data_type VARCHAR(100)" in query
            assert "parameters_hash VARCHAR(64)" in query
    
    @pytest.mark.asyncio
    async def test_create_calendar_events_cache(self):
        """Test calendar events cache table creation."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            await create_calendar_events_cache()
            
            mock_query.assert_called_once()
            query = mock_query.call_args[0][0]
            
            assert "CREATE TABLE IF NOT EXISTS cache_calendar_events" in query
            assert "event_type VARCHAR(100)" in query
            assert "start_date DATE" in query
            assert "end_date DATE" in query
    
    @pytest.mark.asyncio
    async def test_create_cache_statistics_table(self):
        """Test cache statistics table creation."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            await create_cache_statistics_table()
            
            mock_query.assert_called_once()
            query = mock_query.call_args[0][0]
            
            assert "CREATE TABLE IF NOT EXISTS cache_statistics" in query
            assert "total_requests INT" in query
            assert "cache_hits INT" in query
            assert "cache_misses INT" in query
            assert "hit_rate_percent" in query or "avg_response_time_ms" in query


class TestSchemaInitialization:
    """Test schema initialization and setup."""
    
    @pytest.mark.asyncio
    async def test_create_all_tables(self):
        """Test creating all tables."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query, \
             patch('openbb_fmp_cached.utils.cache_schema.initialize_cache_metadata') as mock_init:
            
            await create_all_tables()
            
            # Should call execute_query for each table (8 tables)
            assert mock_query.call_count == 8
            
            # Should initialize metadata
            mock_init.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_all_tables_error_handling(self):
        """Test error handling in create_all_tables."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            mock_query.side_effect = Exception("Database error")
            
            with pytest.raises(Exception, match="Database error"):
                await create_all_tables()
    
    @pytest.mark.asyncio
    async def test_initialize_cache_metadata(self):
        """Test cache metadata initialization."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            await initialize_cache_metadata()
            
            # Should insert metadata for each cache table
            expected_calls = 6  # Number of cache tables
            assert mock_query.call_count == expected_calls
            
            # Verify INSERT queries
            for call in mock_query.call_args_list:
                query = call[0][0]
                assert "INSERT INTO cache_metadata" in query
                assert "ON DUPLICATE KEY UPDATE" in query


class TestCacheCleanup:
    """Test cache cleanup operations."""
    
    @pytest.mark.asyncio
    async def test_cleanup_expired_cache(self):
        """Test cleanup of expired cache entries."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            # Mock return values for DELETE operations
            mock_query.side_effect = [1, 0, 2, 0, 1, 0]  # Simulate different delete counts
            
            total_deleted = await cleanup_expired_cache()
            
            # Should call DELETE on each cache table
            expected_calls = 6  # Number of cache tables
            assert mock_query.call_count == expected_calls
            
            # Should return total deleted count
            assert total_deleted == 4  # Sum of non-zero delete counts
            
            # Verify DELETE queries
            for call in mock_query.call_args_list:
                query = call[0][0]
                assert "DELETE FROM cache_" in query
                assert "WHERE expires_at < NOW()" in query
    
    @pytest.mark.asyncio
    async def test_cleanup_expired_cache_error_handling(self):
        """Test error handling in cleanup operation."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            mock_query.side_effect = Exception("Database error")
            
            # Should propagate the exception
            with pytest.raises(Exception, match="Database error"):
                await cleanup_expired_cache()


class TestTableStructureValidation:
    """Test that table structures meet requirements."""
    
    @pytest.mark.asyncio
    async def test_all_tables_have_cache_key(self):
        """Test that all cache tables have cache_key column."""
        table_creation_functions = [
            create_equity_historical_cache,
            create_equity_fundamentals_cache,
            create_equity_quotes_cache,
            create_company_info_cache,
            create_market_data_cache,
            create_calendar_events_cache
        ]
        
        for create_func in table_creation_functions:
            with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
                await create_func()
                
                query = mock_query.call_args[0][0]
                assert "cache_key VARCHAR(512)" in query
                assert "UNIQUE KEY unique_cache_key (cache_key)" in query
    
    @pytest.mark.asyncio
    async def test_all_tables_have_expiration(self):
        """Test that all cache tables have expiration tracking."""
        table_creation_functions = [
            create_equity_historical_cache,
            create_equity_fundamentals_cache,
            create_equity_quotes_cache,
            create_company_info_cache,
            create_market_data_cache,
            create_calendar_events_cache
        ]
        
        for create_func in table_creation_functions:
            with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
                await create_func()
                
                query = mock_query.call_args[0][0]
                assert "expires_at TIMESTAMP" in query
                assert "INDEX idx_expires_at (expires_at)" in query
    
    @pytest.mark.asyncio
    async def test_all_tables_have_access_tracking(self):
        """Test that all cache tables have access tracking."""
        table_creation_functions = [
            create_equity_historical_cache,
            create_equity_fundamentals_cache,
            create_equity_quotes_cache,
            create_company_info_cache,
            create_market_data_cache,
            create_calendar_events_cache
        ]
        
        for create_func in table_creation_functions:
            with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
                await create_func()
                
                query = mock_query.call_args[0][0]
                assert "access_count INT DEFAULT 1" in query
                assert "last_accessed TIMESTAMP" in query
    
    @pytest.mark.asyncio
    async def test_all_tables_have_utf8_charset(self):
        """Test that all tables use UTF-8 charset."""
        table_creation_functions = [
            create_cache_metadata_table,
            create_equity_historical_cache,
            create_equity_fundamentals_cache,
            create_equity_quotes_cache,
            create_company_info_cache,
            create_market_data_cache,
            create_calendar_events_cache,
            create_cache_statistics_table
        ]
        
        for create_func in table_creation_functions:
            with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
                await create_func()
                
                query = mock_query.call_args[0][0]
                assert "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4" in query


class TestIndexOptimization:
    """Test that tables have appropriate indexes for performance."""
    
    @pytest.mark.asyncio
    async def test_equity_historical_indexes(self):
        """Test equity historical table has performance indexes."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            await create_equity_historical_cache()
            
            query = mock_query.call_args[0][0]
            assert "INDEX idx_symbol_interval (symbol, interval_type)" in query
            assert "INDEX idx_expires_at (expires_at)" in query
            assert "INDEX idx_provider (provider)" in query
    
    @pytest.mark.asyncio
    async def test_fundamentals_indexes(self):
        """Test fundamentals table has performance indexes."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            await create_equity_fundamentals_cache()
            
            query = mock_query.call_args[0][0]
            assert "INDEX idx_symbol_statement (symbol, statement_type)" in query
            assert "INDEX idx_fiscal_year (fiscal_year)" in query
    
    @pytest.mark.asyncio
    async def test_calendar_events_indexes(self):
        """Test calendar events table has date range indexes."""
        with patch('openbb_fmp_cached.utils.cache_schema.execute_query') as mock_query:
            await create_calendar_events_cache()
            
            query = mock_query.call_args[0][0]
            assert "INDEX idx_date_range (start_date, end_date)" in query
            assert "INDEX idx_event_type (event_type)" in query


if __name__ == "__main__":
    pytest.main([__file__])