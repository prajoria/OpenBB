"""Database-backed response persistence for FMP Cached provider."""

import logging
from typing import Any, Dict, Optional, Tuple, List
import pandas as pd

from .database import execute_query, execute_many
from .cache_schema import FLATTENED_TABLES

logger = logging.getLogger(__name__)


def get_table_for_endpoint(endpoint: str) -> Optional[str]:
    """Map endpoint to appropriate database table."""
    # Import here to avoid circular imports
    from .cache_schema import table_exists
    
    # First check if endpoint is already a valid table name
    if table_exists(endpoint):
        return endpoint
    
    # Legacy endpoint mappings for backward compatibility
    table_mapping = {
        "EquityHistorical": "equity_historical",
        "EquityProfile": "equity_profile",
        "FinancialRatios": "financial_ratios",
        "BalanceSheet": "balance_sheet", 
        "IncomeStatement": "income_statement",
        "CashFlowStatement": "cash_flow",
        "CashFlow": "cash_flow",
    }
    
    mapped_table = table_mapping.get(endpoint)
    if mapped_table and table_exists(mapped_table):
        return mapped_table
    
    # If no mapping found, return None
    return None


class DatabaseManager:
    """Manages database-backed response persistence for FMP data."""
    
    def __init__(self):
        """Initialize database manager."""
        self.stats = {
            "hits": 0,
            "misses": 0,
            "stores": 0,
            "errors": 0
        }
    
    def get_stored_data(
        self, 
        endpoint: str, 
        **params
    ) -> Optional[List[Dict[str, Any]]]:
        """Retrieve data from database if available."""
        table_name = get_table_for_endpoint(endpoint)
        if not table_name:
            logger.warning(f"No database table for endpoint: {endpoint}")
            return None
        
        try:
            # Build query based on endpoint and parameters
            where_clause, query_params = self._build_where_clause(endpoint, **params)
            
            query = f"""
            SELECT * FROM {table_name}
            WHERE {where_clause} AND is_valid = TRUE
            ORDER BY date DESC
            """
            
            result = execute_query(query, query_params)
            
            if result:
                self.stats["hits"] += 1
                logger.info(f"Database HIT for {endpoint}: {len(result)} rows")
                return [dict(row) for row in result]
            else:
                self.stats["misses"] += 1
                logger.info(f"Database MISS for {endpoint}")
                return None
                
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Database retrieval error for {endpoint}: {e}")
            return None
    
    async def get_stored_data_async(
        self, 
        endpoint: str, 
        **params
    ) -> Optional[List[Dict[str, Any]]]:
        """Retrieve data from database (async - no longer used, kept for compatibility)."""
        # Just call the sync version
        return self.get_stored_data(endpoint, **params)
    
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
    
    def store_data(
        self,
        endpoint: str,
        data: List[Dict[str, Any]],
        **params
    ) -> bool:
        """Store data in database."""
        table_name = get_table_for_endpoint(endpoint)
        if not table_name:
            logger.warning(f"No database table for endpoint: {endpoint}")
            return False
        
        try:
            # Store each record individually
            success_count = 0
            for record in data:
                if self._store_record(table_name, record):
                    success_count += 1
            
            if success_count > 0:
                self.stats["stores"] += success_count
                logger.info(f"Stored {success_count}/{len(data)} records for {endpoint}")
                return True
            else:
                return False
            
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Database storage error for {endpoint}: {e}")
            return False
    
    async def store_data_async(
        self,
        endpoint: str,
        data: List[Dict[str, Any]],
        **params
    ) -> bool:
        """Store data in database (async - no longer used, kept for compatibility)."""
        # Just call the sync version
        return self.store_data(endpoint, data, **params)
    
    def _store_record(
        self, 
        table_name: str, 
        record: Dict[str, Any]
    ) -> bool:
        """Store a single record with flattened column mapping."""
        try:
            # Get common field names from schema
            from .cache_schema import get_common_field_names
            common_fields = get_common_field_names()
            
            # Map record fields to database columns
            db_record = {}
            additional_fields = {}
            
            # Map known fields to columns with field name mapping
            for field_name, field_value in record.items():
                # Handle field name mapping for reserved keywords
                mapped_field_name = field_name
                if field_name == 'change':
                    mapped_field_name = 'change_amount'
                
                if mapped_field_name in common_fields:
                    db_record[mapped_field_name] = field_value
                else:
                    # Store unknown fields in additional_fields JSON
                    additional_fields[field_name] = field_value
            
            # Add additional_fields as JSON if there are unmapped fields
            if additional_fields:
                import json
                db_record['additional_fields'] = json.dumps(additional_fields)
            
            # Add metadata
            db_record['is_valid'] = True
            
            # Build dynamic INSERT query based on available fields
            insert_fields = [field for field in db_record.keys()]
            insert_fields.append('cached_at')  # Add cached_at with CURRENT_TIMESTAMP
            
            placeholders = ['%s'] * len(db_record) + ['CURRENT_TIMESTAMP']
            values = list(db_record.values())
            
            # Create UPSERT query with dynamic ON DUPLICATE KEY UPDATE
            query = f"""
            INSERT INTO {table_name} ({', '.join(insert_fields)})
            VALUES ({', '.join(placeholders)})
            ON DUPLICATE KEY UPDATE
            {', '.join([f"{field} = VALUES({field})" for field in db_record.keys()])},
            cached_at = CURRENT_TIMESTAMP
            """
            
            execute_query(query, tuple(values))
            return True
            
        except Exception as e:
            logger.error(f"Error storing record in {table_name}: {e}")
            return False
    
    async def _store_record_async(
        self, 
        table_name: str, 
        record: Dict[str, Any]
    ) -> bool:
        """Store a single record with flattened column mapping (async version)."""
        try:
            # Get common field names from schema
            from .cache_schema import get_common_field_names
            common_fields = get_common_field_names()
            
            # Map record fields to database columns
            db_record = {}
            additional_fields = {}
            
            # Map known fields to columns with field name mapping
            for field_name, field_value in record.items():
                # Handle field name mapping for reserved keywords
                mapped_field_name = field_name
                if field_name == 'change':
                    mapped_field_name = 'change_amount'
                
                if mapped_field_name in common_fields:
                    db_record[mapped_field_name] = field_value
                else:
                    # Store unknown fields in additional_fields JSON
                    additional_fields[field_name] = field_value
            
            # Add additional_fields as JSON if there are unmapped fields
            if additional_fields:
                import json
                db_record['additional_fields'] = json.dumps(additional_fields)
            
            # Add metadata
            db_record['is_valid'] = True
            
            # Build dynamic INSERT query based on available fields
            insert_fields = [field for field in db_record.keys()]
            insert_fields.append('cached_at')  # Add cached_at with CURRENT_TIMESTAMP
            
            placeholders = ['%s'] * len(db_record) + ['CURRENT_TIMESTAMP']
            values = list(db_record.values())
            
            # Create UPSERT query with dynamic ON DUPLICATE KEY UPDATE
            query = f"""
            INSERT INTO {table_name} ({', '.join(insert_fields)})
            VALUES ({', '.join(placeholders)})
            ON DUPLICATE KEY UPDATE
            {', '.join([f"{field} = VALUES({field})" for field in db_record.keys()])},
            cached_at = CURRENT_TIMESTAMP
            """
            
            execute_query(query, tuple(values))
            return True
            
        except Exception as e:
            logger.error(f"Error storing record in {table_name}: {e}")
            return False
    
    def invalidate_data(self, endpoint: str = None, symbol: str = None):
        """Mark data as invalid (soft delete)."""
        if endpoint:
            table_name = get_table_for_endpoint(endpoint)
            if table_name:
                if symbol:
                    query = f"UPDATE {table_name} SET is_valid = FALSE WHERE symbol = %s"
                    self._execute_query(query, (symbol,))
                else:
                    query = f"UPDATE {table_name} SET is_valid = FALSE"
                    self._execute_query(query)
        elif symbol:
            # Invalidate across all tables for a symbol
            for table_name in FLATTENED_TABLES.keys():
                query = f"UPDATE {table_name} SET is_valid = FALSE WHERE symbol = %s"
                self._execute_query(query, (symbol,))
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database operation statistics."""
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "total_requests": total_requests,
            "database_hits": self.stats["hits"],
            "database_misses": self.stats["misses"],
            "hit_rate_percent": round(hit_rate, 2),
            "stores": self.stats["stores"],
            "errors": self.stats["errors"]
        }
    
    def to_dataframe(self, stored_data: List[Dict[str, Any]]) -> pd.DataFrame:
        """Convert stored data to DataFrame."""
        if not stored_data:
            return pd.DataFrame()
        
        # Remove database metadata columns for clean DataFrame
        clean_data = []
        for record in stored_data:
            # Start with main columns (excluding metadata)
            clean_record = {}
            for k, v in record.items():
                if k not in ['id', 'cached_at', 'is_valid', 'additional_fields']:
                    # Map back from database field names to original field names
                    original_field_name = k
                    if k == 'change_amount':
                        original_field_name = 'change'
                    clean_record[original_field_name] = v
            
            # Add additional fields from JSON if present
            if 'additional_fields' in record and record['additional_fields']:
                try:
                    import json
                    additional_data = json.loads(record['additional_fields'])
                    clean_record.update(additional_data)
                except (json.JSONDecodeError, TypeError):
                    pass  # Skip if can't parse JSON
            
            # Remove None values to clean up DataFrame
            clean_record = {k: v for k, v in clean_record.items() if v is not None}
            clean_data.append(clean_record)
        
        return pd.DataFrame(clean_data)


# Global database manager instance
_database_manager: Optional[DatabaseManager] = None


def get_database_manager() -> DatabaseManager:
    """Get global database manager instance."""
    global _database_manager
    if _database_manager is None:
        _database_manager = DatabaseManager()
    return _database_manager


# Backward compatibility aliases
def get_cache_manager() -> DatabaseManager:
    """Get database manager (alias for backward compatibility)."""
    return get_database_manager()


def get_flattened_cache_manager() -> DatabaseManager:
    """Get database manager (alias for backward compatibility)."""
    return get_database_manager()


def generate_cache_key(endpoint: str, params: dict) -> str:
    """Generate a simple cache key from endpoint and parameters."""
    import hashlib
    import json
    
    # Create a consistent string representation of the parameters
    param_str = json.dumps(params, sort_keys=True)
    key_string = f"{endpoint}:{param_str}"
    
    # Generate a hash for the key (optional, could just return key_string)
    return hashlib.md5(key_string.encode()).hexdigest()