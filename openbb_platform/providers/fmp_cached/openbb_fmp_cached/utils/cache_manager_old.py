"""Cache management utilities for FMP Cached provider."""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple, List

from .database import execute_query, execute_query_async, is_jupyter_mode, run_async_in_thread
from .cache_schema import CACHE_TTL

logger = logging.getLogger(__name__)


def generate_cache_key(endpoint: str, **params) -> str:
    """Generate a unique cache key from endpoint and parameters."""
    # Sort parameters for consistent key generation
    sorted_params = sorted(params.items())
    key_data = f"{endpoint}:{json.dumps(sorted_params, sort_keys=True)}"
    return hashlib.sha256(key_data.encode()).hexdigest()


def generate_data_hash(data: Any) -> str:
    """Generate hash of response data for integrity checking."""
    data_str = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(data_str.encode()).hexdigest()


def get_table_for_endpoint(endpoint: str) -> str:
    """Map endpoint to appropriate cache table."""
    table_mapping = {
        "EquityHistorical": "cache_equity_historical",
        "BalanceSheet": "cache_equity_fundamentals",
        "IncomeStatement": "cache_equity_fundamentals", 
        "CashFlowStatement": "cache_equity_fundamentals",
        "EquityQuote": "cache_equity_quotes",
        "EquityInfo": "cache_company_info",
        "EquityProfile": "cache_company_info",
        "AnalystEstimates": "cache_company_info",
        "CalendarEarnings": "cache_calendar_events",
        "CalendarDividend": "cache_calendar_events",
        "CalendarIpo": "cache_calendar_events",
        "EquityScreener": "cache_market_data",
        "MarketSnapshots": "cache_market_data",
        "AvailableIndices": "cache_market_data"
    }
    return table_mapping.get(endpoint, "cache_market_data")


def get_ttl_for_endpoint(endpoint: str, **params) -> int:
    """Get TTL (time to live) for specific endpoint and parameters."""
    # Historical data TTL depends on interval
    if endpoint == "EquityHistorical":
        interval = params.get("interval", "1d")
        if interval in ["1m", "5m", "15m", "30m", "1h"]:
            return CACHE_TTL["equity_historical_intraday"]
        else:
            return CACHE_TTL["equity_historical_daily"]
    
    # Map endpoint to TTL
    ttl_mapping = {
        "EquityQuote": CACHE_TTL["equity_quote"],
        "BalanceSheet": CACHE_TTL["balance_sheet"],
        "IncomeStatement": CACHE_TTL["income_statement"],
        "CashFlowStatement": CACHE_TTL["cash_flow"],
        "EquityInfo": CACHE_TTL["company_info"],
        "EquityProfile": CACHE_TTL["company_info"],
        "AnalystEstimates": CACHE_TTL["analyst_estimates"],
        "CalendarEarnings": CACHE_TTL["calendar_events"],
        "CalendarDividend": CACHE_TTL["calendar_events"],
        "EquityScreener": CACHE_TTL["market_data"]
    }
    
    return ttl_mapping.get(endpoint, CACHE_TTL["default"])


class CacheManager:
    """Manages cache operations for FMP data."""
    
    def __init__(self):
        """Initialize cache manager."""
        self.stats = {
            "hits": 0,
            "misses": 0,
            "stores": 0,
            "errors": 0
        }
    
    def _execute_query(self, query: str, params: tuple = ()):
        """Execute query using appropriate method based on environment."""
        if is_jupyter_mode():
            # Use synchronous version in Jupyter
            return execute_query(query, params)
        else:
            # Use async version in regular environments - needs to be wrapped
            return run_async_in_thread(execute_query_async(query, params))
    
    async def _execute_query_async(self, query: str, params: tuple = ()):
        """Execute query asynchronously for proper async contexts."""
        return await execute_query_async(query, params)
    
    def get_cached_data(
        self, 
        endpoint: str, 
        cache_key: str,
        **params
    ) -> Optional[Dict[str, Any]]:
        """Retrieve data from cache if available and not expired (sync version)."""
        if not is_jupyter_mode():
            # In async environments, use the async version via thread wrapper
            return run_async_in_thread(self.get_cached_data_async(endpoint, cache_key, **params))
        
        # Jupyter/sync environment implementation
        table_name = get_table_for_endpoint(endpoint)
        
        try:
            query = f"""
            SELECT response_data, created_at, expires_at, access_count
            FROM {table_name}
            WHERE cache_key = %s AND expires_at > NOW()
            """
            
            result = execute_query(query, (cache_key,))
            
            if result:
                # Update access statistics
                self._update_access_stats(table_name, cache_key)
                self.stats["hits"] += 1
                
                data = json.loads(result[0]["response_data"])
                logger.info(f"Cache HIT for {endpoint}: {cache_key[:16]}...")
                return data
            else:
                self.stats["misses"] += 1
                logger.info(f"Cache MISS for {endpoint}: {cache_key[:16]}...")
                return None
                
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Cache retrieval error for {endpoint}: {e}")
            return None
    
    async def get_cached_data_async(
        self, 
        endpoint: str, 
        cache_key: str,
        **params
    ) -> Optional[Dict[str, Any]]:
        """Retrieve data from cache if available and not expired (async version)."""
        table_name = get_table_for_endpoint(endpoint)
        
        try:
            query = f"""
            SELECT response_data, created_at, expires_at, access_count
            FROM {table_name}
            WHERE cache_key = %s AND expires_at > NOW()
            """
            
            result = await self._execute_query_async(query, (cache_key,))
            
            if result:
                # Update access statistics
                await self._update_access_stats_async(table_name, cache_key)
                self.stats["hits"] += 1
                
                data = json.loads(result[0]["response_data"])
                logger.info(f"Cache HIT for {endpoint}: {cache_key[:16]}...")
                return data
            else:
                self.stats["misses"] += 1
                logger.info(f"Cache MISS for {endpoint}: {cache_key[:16]}...")
                return None
                
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Cache retrieval error for {endpoint}: {e}")
            return None
    
    def store_cached_data(
        self,
        endpoint: str,
        cache_key: str,
        data: Any,
        **params
    ) -> bool:
        """Store data in cache with appropriate TTL (sync version)."""
        if not is_jupyter_mode():
            # In async environments, use the async version via thread wrapper
            return run_async_in_thread(self.store_cached_data_async(endpoint, cache_key, data, **params))
        
        # Jupyter/sync environment implementation
        table_name = get_table_for_endpoint(endpoint)
        ttl_seconds = get_ttl_for_endpoint(endpoint, **params)
        
        try:
            response_data = json.dumps(data, default=str)
            data_hash = generate_data_hash(data)
            expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
            
            # Different insert logic based on table structure
            if table_name == "cache_equity_historical":
                self._store_equity_historical(
                    cache_key, response_data, data_hash, expires_at, **params
                )
            elif table_name == "cache_equity_fundamentals":
                self._store_equity_fundamentals(
                    cache_key, response_data, data_hash, expires_at, endpoint, **params
                )
            elif table_name == "cache_equity_quotes":
                self._store_equity_quotes(
                    cache_key, response_data, data_hash, expires_at, **params
                )
            elif table_name == "cache_company_info":
                self._store_company_info(
                    cache_key, response_data, data_hash, expires_at, endpoint, **params
                )
            elif table_name == "cache_calendar_events":
                self._store_calendar_events(
                    cache_key, response_data, data_hash, expires_at, endpoint, **params
                )
            else:
                self._store_market_data(
                    cache_key, response_data, data_hash, expires_at, endpoint, **params
                )
            
            self.stats["stores"] += 1
            logger.info(f"Cached data for {endpoint}: {cache_key[:16]}... (TTL: {ttl_seconds}s)")
            return True
            
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Cache storage error for {endpoint}: {e}")
            return False
    
    async def store_cached_data_async(
        self,
        endpoint: str,
        cache_key: str,
        data: Any,
        **params
    ) -> bool:
        """Store data in cache with appropriate TTL (async version)."""
        table_name = get_table_for_endpoint(endpoint)
        ttl_seconds = get_ttl_for_endpoint(endpoint, **params)
        
        try:
            response_data = json.dumps(data, default=str)
            data_hash = generate_data_hash(data)
            expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
            
            # Different insert logic based on table structure
            if table_name == "cache_equity_historical":
                await self._store_equity_historical_async(
                    cache_key, response_data, data_hash, expires_at, **params
                )
            elif table_name == "cache_equity_fundamentals":
                await self._store_equity_fundamentals_async(
                    cache_key, response_data, data_hash, expires_at, endpoint, **params
                )
            elif table_name == "cache_equity_quotes":
                await self._store_equity_quotes_async(
                    cache_key, response_data, data_hash, expires_at, **params
                )
            elif table_name == "cache_company_info":
                await self._store_company_info_async(
                    cache_key, response_data, data_hash, expires_at, endpoint, **params
                )
            elif table_name == "cache_calendar_events":
                await self._store_calendar_events_async(
                    cache_key, response_data, data_hash, expires_at, endpoint, **params
                )
            else:
                await self._store_market_data_async(
                    cache_key, response_data, data_hash, expires_at, endpoint, **params
                )
            
            self.stats["stores"] += 1
            logger.info(f"Cached data for {endpoint}: {cache_key[:16]}... (TTL: {ttl_seconds}s)")
            return True
            
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Cache storage error for {endpoint}: {e}")
            return False
    
    def _store_equity_historical(
        self, cache_key: str, response_data: str, data_hash: str, 
        expires_at: datetime, **params
    ):
        """Store equity historical data (sync version)."""
        query = """
        INSERT INTO cache_equity_historical 
        (cache_key, symbol, interval_type, start_date, end_date, adjustment, 
         data_hash, response_data, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            data_hash = VALUES(data_hash),
            response_data = VALUES(response_data),
            expires_at = VALUES(expires_at),
            access_count = 1,
            last_accessed = CURRENT_TIMESTAMP
        """
        
        execute_query(query, (
            cache_key,
            params.get("symbol", ""),
            params.get("interval", "1d"),
            params.get("start_date"),
            params.get("end_date"),
            params.get("adjustment", ""),
            data_hash,
            response_data,
            expires_at
        ))
    
    async def _store_equity_historical_async(
        self, cache_key: str, response_data: str, data_hash: str, 
        expires_at: datetime, **params
    ):
        """Store equity historical data (async version)."""
        query = """
        INSERT INTO cache_equity_historical 
        (cache_key, symbol, interval_type, start_date, end_date, adjustment, 
         data_hash, response_data, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            data_hash = VALUES(data_hash),
            response_data = VALUES(response_data),
            expires_at = VALUES(expires_at),
            access_count = 1,
            last_accessed = CURRENT_TIMESTAMP
        """
        
        await self._execute_query_async(query, (
            cache_key,
            params.get("symbol", ""),
            params.get("interval", "1d"),
            params.get("start_date"),
            params.get("end_date"),
            params.get("adjustment", ""),
            data_hash,
            response_data,
            expires_at
        ))
    
    # Add placeholder async versions for other storage methods
    async def _store_equity_fundamentals_async(self, cache_key: str, response_data: str, data_hash: str, expires_at: datetime, endpoint: str, **params):
        """Async version - placeholder for now.""" 
        pass
    
    async def _store_equity_quotes_async(self, cache_key: str, response_data: str, data_hash: str, expires_at: datetime, **params):
        """Async version - placeholder for now."""
        pass
    
    async def _store_company_info_async(self, cache_key: str, response_data: str, data_hash: str, expires_at: datetime, endpoint: str, **params):
        """Async version - placeholder for now."""
        pass
    
    async def _store_calendar_events_async(self, cache_key: str, response_data: str, data_hash: str, expires_at: datetime, endpoint: str, **params):
        """Async version - placeholder for now."""
        pass
    
    async def _store_market_data_async(self, cache_key: str, response_data: str, data_hash: str, expires_at: datetime, endpoint: str, **params):
        """Async version - placeholder for now."""
        pass
    
    async def _store_equity_fundamentals(
        self, cache_key: str, response_data: str, data_hash: str,
        expires_at: datetime, endpoint: str, **params
    ):
        """Store equity fundamentals data."""
        query = """
        INSERT INTO cache_equity_fundamentals
        (cache_key, symbol, statement_type, period, fiscal_year, fiscal_period,
         data_hash, response_data, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            data_hash = VALUES(data_hash),
            response_data = VALUES(response_data),
            expires_at = VALUES(expires_at),
            access_count = 1,
            last_accessed = CURRENT_TIMESTAMP
        """
        
        await execute_query(query, (
            cache_key,
            params.get("symbol", ""),
            endpoint.lower().replace("statement", ""),
            params.get("period", "annual"),
            params.get("fiscal_year"),
            params.get("fiscal_period"),
            data_hash,
            response_data,
            expires_at
        ))
    
    async def _store_equity_quotes(
        self, cache_key: str, response_data: str, data_hash: str,
        expires_at: datetime, **params
    ):
        """Store equity quotes data."""
        query = """
        INSERT INTO cache_equity_quotes
        (cache_key, symbol, data_hash, response_data, expires_at)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            data_hash = VALUES(data_hash),
            response_data = VALUES(response_data),
            expires_at = VALUES(expires_at),
            access_count = 1,
            last_accessed = CURRENT_TIMESTAMP
        """
        
        await execute_query(query, (
            cache_key,
            params.get("symbol", ""),
            data_hash,
            response_data,
            expires_at
        ))
    
    async def _store_company_info(
        self, cache_key: str, response_data: str, data_hash: str,
        expires_at: datetime, endpoint: str, **params
    ):
        """Store company information data."""
        query = """
        INSERT INTO cache_company_info
        (cache_key, symbol, info_type, data_hash, response_data, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            data_hash = VALUES(data_hash),
            response_data = VALUES(response_data),
            expires_at = VALUES(expires_at),
            access_count = 1,
            last_accessed = CURRENT_TIMESTAMP
        """
        
        await execute_query(query, (
            cache_key,
            params.get("symbol", ""),
            endpoint,
            data_hash,
            response_data,
            expires_at
        ))
    
    async def _store_calendar_events(
        self, cache_key: str, response_data: str, data_hash: str,
        expires_at: datetime, endpoint: str, **params
    ):
        """Store calendar events data."""
        query = """
        INSERT INTO cache_calendar_events
        (cache_key, event_type, start_date, end_date, data_hash, response_data, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            data_hash = VALUES(data_hash),
            response_data = VALUES(response_data),
            expires_at = VALUES(expires_at),
            access_count = 1,
            last_accessed = CURRENT_TIMESTAMP
        """
        
        await execute_query(query, (
            cache_key,
            endpoint,
            params.get("start_date"),
            params.get("end_date"),
            data_hash,
            response_data,
            expires_at
        ))
    
    async def _store_market_data(
        self, cache_key: str, response_data: str, data_hash: str,
        expires_at: datetime, endpoint: str, **params
    ):
        """Store market data."""
        parameters_hash = generate_data_hash(params)
        
        query = """
        INSERT INTO cache_market_data
        (cache_key, data_type, parameters_hash, data_hash, response_data, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            data_hash = VALUES(data_hash),
            response_data = VALUES(response_data),
            expires_at = VALUES(expires_at),
            access_count = 1,
            last_accessed = CURRENT_TIMESTAMP
        """
        
        await execute_query(query, (
            cache_key,
            endpoint,
            parameters_hash,
            data_hash,
            response_data,
            expires_at
        ))
    
    def _update_access_stats(self, table_name: str, cache_key: str):
        """Update access statistics for cache entry (sync version)."""
        query = f"""
        UPDATE {table_name} 
        SET access_count = access_count + 1, 
            last_accessed = CURRENT_TIMESTAMP
        WHERE cache_key = %s
        """
        execute_query(query, (cache_key,))
    
    async def _update_access_stats_async(self, table_name: str, cache_key: str):
        """Update access statistics for cache entry (async version)."""
        query = f"""
        UPDATE {table_name} 
        SET access_count = access_count + 1, 
            last_accessed = CURRENT_TIMESTAMP
        WHERE cache_key = %s
        """
        await self._execute_query_async(query, (cache_key,))
    
    async def invalidate_cache(self, pattern: str = None, endpoint: str = None):
        """Invalidate cache entries matching pattern or endpoint."""
        if endpoint:
            table_name = get_table_for_endpoint(endpoint)
            query = f"DELETE FROM {table_name} WHERE cache_key LIKE %s"
            await execute_query(query, (f"%{endpoint}%",))
        elif pattern:
            # Invalidate across all tables
            tables = [
                "cache_equity_historical",
                "cache_equity_fundamentals",
                "cache_equity_quotes", 
                "cache_company_info",
                "cache_calendar_events",
                "cache_market_data"
            ]
            for table in tables:
                query = f"DELETE FROM {table} WHERE cache_key LIKE %s"
                await execute_query(query, (f"%{pattern}%",))
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "total_requests": total_requests,
            "cache_hits": self.stats["hits"],
            "cache_misses": self.stats["misses"],
            "hit_rate_percent": round(hit_rate, 2),
            "stores": self.stats["stores"],
            "errors": self.stats["errors"]
        }


# Global cache manager instance
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    """Get global cache manager instance."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager