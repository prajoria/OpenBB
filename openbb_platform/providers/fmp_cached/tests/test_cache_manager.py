"""Unit tests for cache management utilities."""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from openbb_fmp_cached.utils.cache_manager import (
    CacheManager, 
    generate_cache_key,
    generate_data_hash,
    get_table_for_endpoint,
    get_ttl_for_endpoint,
    get_cache_manager
)


class TestCacheKeyGeneration:
    """Test cache key generation functions."""
    
    def test_generate_cache_key_consistency(self):
        """Test that same parameters generate same key."""
        key1 = generate_cache_key("EquityHistorical", symbol="AAPL", interval="1d")
        key2 = generate_cache_key("EquityHistorical", symbol="AAPL", interval="1d")
        assert key1 == key2
    
    def test_generate_cache_key_uniqueness(self):
        """Test that different parameters generate different keys."""
        key1 = generate_cache_key("EquityHistorical", symbol="AAPL", interval="1d")
        key2 = generate_cache_key("EquityHistorical", symbol="GOOGL", interval="1d")
        key3 = generate_cache_key("EquityHistorical", symbol="AAPL", interval="1h")
        key4 = generate_cache_key("BalanceSheet", symbol="AAPL")
        
        assert key1 != key2
        assert key1 != key3
        assert key1 != key4
    
    def test_generate_cache_key_parameter_order(self):
        """Test that parameter order doesn't affect key generation."""
        key1 = generate_cache_key("EquityHistorical", symbol="AAPL", interval="1d", start_date="2024-01-01")
        key2 = generate_cache_key("EquityHistorical", start_date="2024-01-01", interval="1d", symbol="AAPL")
        assert key1 == key2
    
    def test_generate_data_hash(self):
        """Test data hash generation."""
        data1 = [{"symbol": "AAPL", "price": 150.0}]
        data2 = [{"symbol": "AAPL", "price": 150.0}]  # Same data
        data3 = [{"symbol": "AAPL", "price": 151.0}]  # Different data
        
        hash1 = generate_data_hash(data1)
        hash2 = generate_data_hash(data2)
        hash3 = generate_data_hash(data3)
        
        assert hash1 == hash2
        assert hash1 != hash3
        assert len(hash1) == 64  # SHA256 hex length


class TestTableMapping:
    """Test endpoint to table mapping."""
    
    def test_equity_endpoints(self):
        """Test equity endpoint mappings."""
        assert get_table_for_endpoint("EquityHistorical") == "cache_equity_historical"
        assert get_table_for_endpoint("EquityQuote") == "cache_equity_quotes"
        assert get_table_for_endpoint("EquityInfo") == "cache_company_info"
    
    def test_fundamental_endpoints(self):
        """Test fundamental endpoint mappings."""
        assert get_table_for_endpoint("BalanceSheet") == "cache_equity_fundamentals"
        assert get_table_for_endpoint("IncomeStatement") == "cache_equity_fundamentals"
        assert get_table_for_endpoint("CashFlowStatement") == "cache_equity_fundamentals"
    
    def test_calendar_endpoints(self):
        """Test calendar endpoint mappings."""
        assert get_table_for_endpoint("CalendarEarnings") == "cache_calendar_events"
        assert get_table_for_endpoint("CalendarDividend") == "cache_calendar_events"
    
    def test_unknown_endpoint(self):
        """Test unknown endpoint returns default table."""
        assert get_table_for_endpoint("UnknownEndpoint") == "cache_market_data"


class TestTTLCalculation:
    """Test TTL (Time To Live) calculations."""
    
    def test_equity_historical_ttl(self):
        """Test equity historical TTL based on interval."""
        # Intraday intervals should have shorter TTL
        ttl_1m = get_ttl_for_endpoint("EquityHistorical", interval="1m")
        ttl_5m = get_ttl_for_endpoint("EquityHistorical", interval="5m")
        ttl_1h = get_ttl_for_endpoint("EquityHistorical", interval="1h")
        ttl_1d = get_ttl_for_endpoint("EquityHistorical", interval="1d")
        
        # All intraday should be same (3600s)
        assert ttl_1m == ttl_5m == ttl_1h == 3600
        
        # Daily should be longer (86400s)
        assert ttl_1d == 86400
        assert ttl_1d > ttl_1m
    
    def test_other_endpoints_ttl(self):
        """Test TTL for other endpoints."""
        ttl_quote = get_ttl_for_endpoint("EquityQuote")
        ttl_balance = get_ttl_for_endpoint("BalanceSheet")
        ttl_company = get_ttl_for_endpoint("EquityInfo")
        
        # Quotes should be shortest (60s)
        assert ttl_quote == 60
        
        # Fundamentals should be 24 hours (86400s)
        assert ttl_balance == 86400
        
        # Company info should be longest (604800s = 7 days)
        assert ttl_company == 604800
        
        # Verify order
        assert ttl_quote < ttl_balance < ttl_company
    
    def test_default_ttl(self):
        """Test default TTL for unknown endpoints."""
        ttl = get_ttl_for_endpoint("UnknownEndpoint")
        assert ttl == 3600  # Default 1 hour


class TestCacheManager:
    """Test CacheManager class."""
    
    def setup_method(self):
        """Set up test environment."""
        self.cache_manager = CacheManager()
    
    def test_cache_manager_initialization(self):
        """Test cache manager initializes correctly."""
        assert hasattr(self.cache_manager, 'stats')
        assert self.cache_manager.stats['hits'] == 0
        assert self.cache_manager.stats['misses'] == 0
    
    def test_get_stats(self):
        """Test stats calculation."""
        # Simulate some operations
        self.cache_manager.stats['hits'] = 7
        self.cache_manager.stats['misses'] = 3
        
        stats = self.cache_manager.get_stats()
        
        assert stats['total_requests'] == 10
        assert stats['cache_hits'] == 7
        assert stats['cache_misses'] == 3
        assert stats['hit_rate_percent'] == 70.0
    
    def test_get_stats_no_requests(self):
        """Test stats with no requests."""
        stats = self.cache_manager.get_stats()
        
        assert stats['total_requests'] == 0
        assert stats['hit_rate_percent'] == 0
    
    @pytest.mark.asyncio
    async def test_get_cached_data_miss(self):
        """Test cache miss scenario."""
        with patch('openbb_fmp_cached.utils.cache_manager.execute_query') as mock_query:
            mock_query.return_value = []  # No cached data
            
            result = await self.cache_manager.get_cached_data(
                "EquityHistorical", "test_key", symbol="AAPL"
            )
            
            assert result is None
            assert self.cache_manager.stats['misses'] == 1
    
    @pytest.mark.asyncio
    async def test_get_cached_data_hit(self):
        """Test cache hit scenario."""
        cached_response = [{"response_data": '{"test": "data"}'}]
        
        with patch('openbb_fmp_cached.utils.cache_manager.execute_query') as mock_query:
            mock_query.return_value = cached_response
            
            with patch.object(self.cache_manager, '_update_access_stats') as mock_update:
                result = await self.cache_manager.get_cached_data(
                    "EquityHistorical", "test_key", symbol="AAPL"
                )
                
                assert result == {"test": "data"}
                assert self.cache_manager.stats['hits'] == 1
                mock_update.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_store_cached_data_success(self):
        """Test successful cache storage."""
        test_data = [{"symbol": "AAPL", "price": 150.0}]
        
        with patch.object(self.cache_manager, '_store_equity_historical') as mock_store:
            mock_store.return_value = None  # Successful storage
            
            result = await self.cache_manager.store_cached_data(
                "EquityHistorical", "test_key", test_data, symbol="AAPL", interval="1d"
            )
            
            assert result is True
            assert self.cache_manager.stats['stores'] == 1
            mock_store.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_store_cached_data_error(self):
        """Test cache storage error handling."""
        test_data = [{"symbol": "AAPL", "price": 150.0}]
        
        with patch.object(self.cache_manager, '_store_equity_historical') as mock_store:
            mock_store.side_effect = Exception("Database error")
            
            result = await self.cache_manager.store_cached_data(
                "EquityHistorical", "test_key", test_data, symbol="AAPL", interval="1d"
            )
            
            assert result is False
            assert self.cache_manager.stats['errors'] == 1
    
    @pytest.mark.asyncio
    async def test_invalidate_cache_by_endpoint(self):
        """Test cache invalidation by endpoint."""
        with patch('openbb_fmp_cached.utils.cache_manager.execute_query') as mock_query:
            await self.cache_manager.invalidate_cache(endpoint="EquityHistorical")
            
            # Should call DELETE on the appropriate table
            mock_query.assert_called_once()
            call_args = mock_query.call_args[0]
            assert "DELETE FROM cache_equity_historical" in call_args[0]
    
    @pytest.mark.asyncio
    async def test_invalidate_cache_by_pattern(self):
        """Test cache invalidation by pattern."""
        with patch('openbb_fmp_cached.utils.cache_manager.execute_query') as mock_query:
            await self.cache_manager.invalidate_cache(pattern="AAPL")
            
            # Should call DELETE on all tables
            assert mock_query.call_count == 6  # Number of cache tables


class TestCacheManagerSingleton:
    """Test cache manager singleton pattern."""
    
    def test_singleton_behavior(self):
        """Test that get_cache_manager returns same instance."""
        manager1 = get_cache_manager()
        manager2 = get_cache_manager()
        
        assert manager1 is manager2
    
    def test_singleton_state_persistence(self):
        """Test that singleton state persists."""
        manager1 = get_cache_manager()
        manager1.stats['hits'] = 5
        
        manager2 = get_cache_manager()
        assert manager2.stats['hits'] == 5


class TestStorageMethods:
    """Test specific storage methods."""
    
    def setup_method(self):
        """Set up test environment."""
        self.cache_manager = CacheManager()
    
    @pytest.mark.asyncio
    async def test_store_equity_historical(self):
        """Test equity historical storage method."""
        with patch('openbb_fmp_cached.utils.cache_manager.execute_query') as mock_query:
            await self.cache_manager._store_equity_historical(
                "test_key", '{"test": "data"}', "hash123", 
                datetime.now() + timedelta(hours=1),
                symbol="AAPL", interval="1d", start_date="2024-01-01"
            )
            
            # Verify query was called with correct parameters
            mock_query.assert_called_once()
            call_args = mock_query.call_args[0]
            assert "INSERT INTO cache_equity_historical" in call_args[0]
    
    @pytest.mark.asyncio 
    async def test_store_equity_fundamentals(self):
        """Test equity fundamentals storage method."""
        with patch('openbb_fmp_cached.utils.cache_manager.execute_query') as mock_query:
            await self.cache_manager._store_equity_fundamentals(
                "test_key", '{"test": "data"}', "hash123",
                datetime.now() + timedelta(hours=24),
                "BalanceSheet", symbol="AAPL", period="annual"
            )
            
            mock_query.assert_called_once()
            call_args = mock_query.call_args[0]
            assert "INSERT INTO cache_equity_fundamentals" in call_args[0]
    
    @pytest.mark.asyncio
    async def test_store_equity_quotes(self):
        """Test equity quotes storage method."""
        with patch('openbb_fmp_cached.utils.cache_manager.execute_query') as mock_query:
            await self.cache_manager._store_equity_quotes(
                "test_key", '{"test": "data"}', "hash123",
                datetime.now() + timedelta(minutes=1),
                symbol="AAPL"
            )
            
            mock_query.assert_called_once()
            call_args = mock_query.call_args[0]
            assert "INSERT INTO cache_equity_quotes" in call_args[0]


if __name__ == "__main__":
    pytest.main([__file__])