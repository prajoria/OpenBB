"""
Complete Database Schema for FMP Cached Provider

Auto-generated database tables for all FMP model entities.
Simple database-backed response persistence without TTL/caching complexity.
"""

from .database import execute_query, is_jupyter_mode, run_async_in_thread, execute_query_async


def _execute_query_env_aware(query: str, params: tuple = ()):
    """Execute query with environment detection."""
    if is_jupyter_mode():
        # In Jupyter, use sync version
        return execute_query(query, params)
    else:
        # In async environment, use async version
        return run_async_in_thread(execute_query_async(query, params))



# Complete table configuration for all 0 entities
FLATTENED_TABLES = {
}


def create_all_flattened_tables():
    """Create all flattened database tables."""
    results = {}
    for table_name, config in FLATTENED_TABLES.items():
        try:
            result = config["schema"]()
            results[table_name] = result
        except Exception as e:
            results[table_name] = f"Error: {str(e)}"
    return results


def create_all_tables():
    """Create all database tables (alias for create_all_flattened_tables)."""
    return create_all_flattened_tables()


def cleanup_expired_cache():
    """Cleanup function - no longer needed as we don't use TTL/expiry."""
    # Since we simplified to remove TTL/expiry, this function is a no-op
    return {"message": "No cleanup needed - TTL/expiry removed from simplified schema"}
