"""Flattened cache management utilities for FMP Cached provider."""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple, List
import pandas as pd

from .database import execute_query, execute_query_async, is_jupyter_mode, run_async_in_thread
from .cache_schema import CACHE_TTL, FLATTENED_TABLES, get_ttl_for_table, is_permanent_table

logger = logging.getLogger(__name__)


def generate_cache_key(endpoint: str, **params) -> str:
    """Generate a unique cache key from endpoint and parameters."""
    # Sort parameters for consistent key generation
    sorted_params = sorted(params.items())
    key_data = f"{endpoint}:{json.dumps(sorted_params, sort_keys=True)}"
    return hashlib.sha256(key_data.encode()).hexdigest()


def get_table_for_endpoint(endpoint: str) -> str:
    """Map endpoint to appropriate flattened cache table."""
    table_mapping = {
        "EquityHistorical": "equity_historical",
        "EquityProfile": "equity_profile",
        "FinancialRatios": "financial_ratios",
        "BalanceSheet": "balance_sheet", 
        "IncomeStatement": "income_statement",
        "CashFlowStatement": "cash_flow",
        "CashFlow": "cash_flow",
        # Add more mappings as needed
    }
    return table_mapping.get(endpoint, None)


def get_ttl_for_endpoint(endpoint: str, **params) -> Optional[int]:
    """Get TTL (time to live) for specific endpoint and parameters. Returns None for permanent data."""
    table_name = get_table_for_endpoint(endpoint)
    if not table_name:
        return CACHE_TTL["default"]
    
    # Check if this is permanent storage
    if is_permanent_table(table_name):
        return None  # No TTL for permanent data
    
    # For non-permanent data, get TTL from table configuration
    ttl = get_ttl_for_table(table_name)
    
    # Special case for intraday data - shorter TTL
    if endpoint == "EquityHistorical":
        interval = params.get("interval", "1d")
        if interval in ["1m", "5m", "15m", "30m", "1h"]:
            return 3600  # 1 hour for intraday (temporary data)
    
    return ttl


class FlattenedCacheManager:
    """Manages flattened cache operations for FMP data."""
    
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
        **params
    ) -> Optional[List[Dict[str, Any]]]:
        """Retrieve data from flattened cache if available and not expired (sync version)."""
        if not is_jupyter_mode():
            # In async environments, use the async version via thread wrapper
            return run_async_in_thread(self.get_cached_data_async(endpoint, **params))
        
        table_name = get_table_for_endpoint(endpoint)
        if not table_name:
            logger.warning(f"No flattened cache table for endpoint: {endpoint}")
            return None
        
        try:
            # Build query based on endpoint and parameters
            where_clause, query_params = self._build_where_clause(endpoint, **params)
            
            # Handle permanent vs temporary storage
            if is_permanent_table(table_name):
                # Permanent tables don't have expires_at column
                query = f"""
                SELECT * FROM {table_name}
                WHERE {where_clause} AND is_valid = TRUE
                """
            else:
                # Temporary tables have expires_at column
                query = f"""
                SELECT * FROM {table_name}
                WHERE {where_clause} AND expires_at > NOW() AND is_valid = TRUE
                """
            
            result = execute_query(query, query_params)
            
            if result:
                self.stats["hits"] += 1
                logger.info(f"Flattened cache HIT for {endpoint}: {len(result)} rows")
                return [dict(row) for row in result]
            else:
                self.stats["misses"] += 1
                logger.info(f"Flattened cache MISS for {endpoint}")
                return None
                
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Flattened cache retrieval error for {endpoint}: {e}")
            return None
    
    async def get_cached_data_async(
        self, 
        endpoint: str, 
        **params
    ) -> Optional[List[Dict[str, Any]]]:
        """Retrieve data from flattened cache if available and not expired (async version)."""
        table_name = get_table_for_endpoint(endpoint)
        if not table_name:
            logger.warning(f"No flattened cache table for endpoint: {endpoint}")
            return None
        
        try:
            # Build query based on endpoint and parameters
            where_clause, query_params = self._build_where_clause(endpoint, **params)
            
            # Handle permanent vs temporary storage
            if is_permanent_table(table_name):
                # Permanent tables don't have expires_at column
                query = f"""
                SELECT * FROM {table_name}
                WHERE {where_clause} AND is_valid = TRUE
                """
            else:
                # Temporary tables have expires_at column
                query = f"""
                SELECT * FROM {table_name}
                WHERE {where_clause} AND expires_at > NOW() AND is_valid = TRUE
                """
            
            result = await self._execute_query_async(query, query_params)
            
            if result:
                self.stats["hits"] += 1
                logger.info(f"Flattened cache HIT for {endpoint}: {len(result)} rows")
                return [dict(row) for row in result]
            else:
                self.stats["misses"] += 1
                logger.info(f"Flattened cache MISS for {endpoint}")
                return None
                
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Flattened cache retrieval error for {endpoint}: {e}")
            return None
    
    def _build_where_clause(self, endpoint: str, **params) -> Tuple[str, tuple]:
        """Build WHERE clause and parameters based on endpoint and query params."""
        conditions = []
        values = []
        
        # Common symbol parameter
        if "symbol" in params and params["symbol"]:
            conditions.append("symbol = %s")
            values.append(params["symbol"])
        
        # Handle different endpoint-specific parameters
        if endpoint == "EquityHistorical":
            if "start_date" in params and params["start_date"]:
                conditions.append("date >= %s")
                values.append(params["start_date"])
            if "end_date" in params and params["end_date"]:
                conditions.append("date <= %s")
                values.append(params["end_date"])
        
        elif endpoint in ["BalanceSheet", "IncomeStatement", "CashFlow", "FinancialRatios"]:
            if "period" in params and params["period"]:
                conditions.append("period = %s")
                values.append(params["period"])
            if "fiscal_year" in params and params["fiscal_year"]:
                conditions.append("calendar_year = %s")
                values.append(params["fiscal_year"])
        
        # If no conditions, default to symbol match if available
        if not conditions and "symbol" in params:
            conditions.append("symbol = %s")
            values.append(params["symbol"])
        elif not conditions:
            # Fallback - this shouldn't happen in normal usage
            conditions.append("1 = 1")
        
        where_clause = " AND ".join(conditions)
        return where_clause, tuple(values)
    
    def store_cached_data(
        self,
        endpoint: str,
        data: List[Dict[str, Any]],
        **params
    ) -> bool:
        """Store data in flattened cache with appropriate TTL (sync version)."""
        if not is_jupyter_mode():
            # In async environments, use the async version via thread wrapper
            return run_async_in_thread(self.store_cached_data_async(endpoint, data, **params))
        
        table_name = get_table_for_endpoint(endpoint)
        if not table_name:
            logger.warning(f"No flattened cache table for endpoint: {endpoint}")
            return False
        
        ttl_seconds = get_ttl_for_endpoint(endpoint, **params)
        
        try:
            # Handle permanent vs temporary storage
            if ttl_seconds is None:
                # Permanent storage - no expiry
                expires_at = None
                storage_type = "permanent"
            else:
                # Temporary storage - set expiry
                expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
                storage_type = f"temporary (TTL: {ttl_seconds}s)"
            
            # Store each record individually in flattened format
            success_count = 0
            for record in data:
                if self._store_flattened_record(table_name, record, expires_at):
                    success_count += 1
            
            if success_count > 0:
                self.stats["stores"] += success_count
                logger.info(f"Stored {success_count}/{len(data)} records for {endpoint} ({storage_type})")
                return True
            else:
                return False
            
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Flattened cache storage error for {endpoint}: {e}")
            return False
    
    async def store_cached_data_async(
        self,
        endpoint: str,
        data: List[Dict[str, Any]],
        **params
    ) -> bool:
        """Store data in flattened cache with appropriate TTL (async version)."""
        table_name = get_table_for_endpoint(endpoint)
        if not table_name:
            logger.warning(f"No flattened cache table for endpoint: {endpoint}")
            return False
        
        ttl_seconds = get_ttl_for_endpoint(endpoint, **params)
        
        try:
            expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
            
            # Store each record individually in flattened format
            success_count = 0
            for record in data:
                if await self._store_flattened_record_async(table_name, record, expires_at):
                    success_count += 1
            
            if success_count > 0:
                self.stats["stores"] += success_count
                logger.info(f"Stored {success_count}/{len(data)} records for {endpoint} (TTL: {ttl_seconds}s)")
                return True
            else:
                return False
            
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Flattened cache storage error for {endpoint}: {e}")
            return False
    
    def _store_flattened_record(
        self, 
        table_name: str, 
        record: Dict[str, Any], 
        expires_at: datetime
    ) -> bool:
        """Store a single record in flattened format (sync version)."""
        try:
            # Prepare the record with cache metadata
            cache_record = record.copy()
            cache_record.update({
                "cached_at": datetime.now(),
                "expires_at": expires_at,
                "is_valid": True
            })
            
            # Build INSERT/UPDATE query
            columns = list(cache_record.keys())
            placeholders = ["%s"] * len(columns)
            values = [cache_record[col] for col in columns]
            
            # Create UPSERT query
            if table_name == "equity_historical":
                # Use symbol + date as unique key
                query = f"""
                INSERT INTO {table_name} ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
                ON DUPLICATE KEY UPDATE
                {', '.join([f"{col} = VALUES({col})" for col in columns if col not in ['id']])}
                """
            elif table_name == "equity_profile":
                # Use symbol as unique key
                query = f"""
                INSERT INTO {table_name} ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
                ON DUPLICATE KEY UPDATE
                {', '.join([f"{col} = VALUES({col})" for col in columns if col not in ['id']])}
                """
            else:
                # Use symbol + date as unique key for financial statements
                query = f"""
                INSERT INTO {table_name} ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
                ON DUPLICATE KEY UPDATE
                {', '.join([f"{col} = VALUES({col})" for col in columns if col not in ['id']])}
                """
            
            execute_query(query, tuple(values))
            return True
            
        except Exception as e:
            logger.error(f"Error storing flattened record in {table_name}: {e}")
            return False
    
    async def _store_flattened_record_async(
        self, 
        table_name: str, 
        record: Dict[str, Any], 
        expires_at: datetime
    ) -> bool:
        """Store a single record in flattened format (async version)."""
        try:
            # Prepare the record with cache metadata
            cache_record = record.copy()
            cache_record.update({
                "cached_at": datetime.now(),
                "expires_at": expires_at,
                "is_valid": True
            })
            
            # Build INSERT/UPDATE query
            columns = list(cache_record.keys())
            placeholders = ["%s"] * len(columns)
            values = [cache_record[col] for col in columns]
            
            # Create UPSERT query
            if table_name == "equity_historical":
                # Use symbol + date as unique key
                query = f"""
                INSERT INTO {table_name} ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
                ON DUPLICATE KEY UPDATE
                {', '.join([f"{col} = VALUES({col})" for col in columns if col not in ['id']])}
                """
            elif table_name == "equity_profile":
                # Use symbol as unique key
                query = f"""
                INSERT INTO {table_name} ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
                ON DUPLICATE KEY UPDATE
                {', '.join([f"{col} = VALUES({col})" for col in columns if col not in ['id']])}
                """
            else:
                # Use symbol + date as unique key for financial statements
                query = f"""
                INSERT INTO {table_name} ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
                ON DUPLICATE KEY UPDATE
                {', '.join([f"{col} = VALUES({col})" for col in columns if col not in ['id']])}
                """
            
            await self._execute_query_async(query, tuple(values))
            return True
            
        except Exception as e:
            logger.error(f"Error storing flattened record in {table_name}: {e}")
            return False
    
    async def invalidate_cache(self, pattern: str = None, endpoint: str = None):
        """Invalidate cache entries matching pattern or endpoint."""
        if endpoint:
            table_name = get_table_for_endpoint(endpoint)
            if table_name:
                query = f"UPDATE {table_name} SET is_valid = FALSE WHERE is_valid = TRUE"
                await self._execute_query_async(query)
        elif pattern:
            # Invalidate across all flattened tables
            for table_name in FLATTENED_TABLES.keys():
                query = f"UPDATE {table_name} SET is_valid = FALSE WHERE symbol LIKE %s"
                await self._execute_query_async(query, (f"%{pattern}%",))
    
    async def cleanup_expired_cache(self):
        """Clean up expired cache entries from all flattened tables."""
        total_deleted = 0
        
        for table_name in FLATTENED_TABLES.keys():
            try:
                query = f"DELETE FROM {table_name} WHERE expires_at < NOW()"
                result = await self._execute_query_async(query)
                deleted_count = result if isinstance(result, int) else 0
                total_deleted += deleted_count
                logger.info(f"Cleaned up {deleted_count} expired entries from {table_name}")
            except Exception as e:
                logger.error(f"Failed to cleanup table {table_name}: {e}")
        
        return total_deleted
    
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
    
    def to_dataframe(self, cached_data: List[Dict[str, Any]]) -> pd.DataFrame:
        """Convert cached data to DataFrame."""
        if not cached_data:
            return pd.DataFrame()
        
        # Remove cache metadata columns for clean DataFrame
        clean_data = []
        for record in cached_data:
            clean_record = {k: v for k, v in record.items() 
                           if k not in ['id', 'cached_at', 'expires_at', 'is_valid']}
            clean_data.append(clean_record)
        
        return pd.DataFrame(clean_data)


# Global cache manager instance
_flattened_cache_manager: Optional[FlattenedCacheManager] = None


def get_flattened_cache_manager() -> FlattenedCacheManager:
    """Get global flattened cache manager instance."""
    global _flattened_cache_manager
    if _flattened_cache_manager is None:
        _flattened_cache_manager = FlattenedCacheManager()
    return _flattened_cache_manager


# Backward compatibility - use flattened version as default
def get_cache_manager() -> FlattenedCacheManager:
    """Get cache manager (returns flattened version)."""
    return get_flattened_cache_manager()