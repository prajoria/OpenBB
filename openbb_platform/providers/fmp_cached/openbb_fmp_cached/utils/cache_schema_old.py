"""Cache database schema definitions for FMP Cached provider."""

from .database import execute_query, execute_query_async, is_jupyter_mode, run_async_in_thread
import logging

logger = logging.getLogger(__name__)


def _execute_query_env_aware(query: str, params: tuple = ()):
    """Execute query using environment-appropriate method."""
    if is_jupyter_mode():
        return execute_query(query, params)
    else:
        return run_async_in_thread(execute_query_async(query, params))


async def _execute_query_async(query: str, params: tuple = ()):
    """Execute query asynchronously."""
    return await execute_query_async(query, params)


# Cache TTL settings (in seconds)
CACHE_TTL = {
    "equity_historical_intraday": 3600,    # 1 hour for intraday data
    "equity_historical_daily": 86400,      # 24 hours for daily data
    "equity_quote": 60,                    # 1 minute for real-time quotes
    "balance_sheet": 86400,                # 24 hours for fundamentals
    "income_statement": 86400,             # 24 hours for fundamentals
    "cash_flow": 86400,                    # 24 hours for fundamentals
    "company_info": 604800,                # 7 days for company profile
    "analyst_estimates": 86400,            # 24 hours for estimates
    "calendar_events": 3600,               # 1 hour for calendar data
    "market_data": 300,                    # 5 minutes for market snapshots
    "default": 3600                        # 1 hour default
}


def create_cache_metadata_table():
    """Create table for cache metadata and configuration (sync version)."""
    query = """
    CREATE TABLE IF NOT EXISTS cache_metadata (
        id INT AUTO_INCREMENT PRIMARY KEY,
        table_name VARCHAR(255) NOT NULL UNIQUE,
        description TEXT,
        ttl_seconds INT NOT NULL DEFAULT 3600,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_table_name (table_name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)


async def create_cache_metadata_table_async():
    """Create table for cache metadata and configuration (async version)."""
    query = """
    CREATE TABLE IF NOT EXISTS cache_metadata (
        id INT AUTO_INCREMENT PRIMARY KEY,
        table_name VARCHAR(255) NOT NULL UNIQUE,
        description TEXT,
        ttl_seconds INT NOT NULL DEFAULT 3600,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_table_name (table_name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return await _execute_query_async(query)


async def create_equity_historical_cache():
    """Create cache table for equity historical price data."""
    query = """
    CREATE TABLE IF NOT EXISTS cache_equity_historical (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        cache_key VARCHAR(512) NOT NULL,
        symbol VARCHAR(50) NOT NULL,
        provider VARCHAR(50) DEFAULT 'fmp',
        interval_type VARCHAR(10) NOT NULL,
        start_date DATE,
        end_date DATE,
        adjustment VARCHAR(50),
        data_hash VARCHAR(64) NOT NULL,
        response_data LONGTEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL,
        access_count INT DEFAULT 1,
        last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_cache_key (cache_key),
        INDEX idx_symbol_interval (symbol, interval_type),
        INDEX idx_expires_at (expires_at),
        INDEX idx_provider (provider),
        INDEX idx_last_accessed (last_accessed)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    await execute_query(query)


async def create_equity_fundamentals_cache():
    """Create cache table for equity fundamentals (balance sheet, income, cash flow)."""
    query = """
    CREATE TABLE IF NOT EXISTS cache_equity_fundamentals (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        cache_key VARCHAR(512) NOT NULL,
        symbol VARCHAR(50) NOT NULL,
        provider VARCHAR(50) DEFAULT 'fmp',
        statement_type VARCHAR(50) NOT NULL,
        period VARCHAR(20),
        fiscal_year INT,
        fiscal_period VARCHAR(10),
        data_hash VARCHAR(64) NOT NULL,
        response_data LONGTEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL,
        access_count INT DEFAULT 1,
        last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_cache_key (cache_key),
        INDEX idx_symbol_statement (symbol, statement_type),
        INDEX idx_expires_at (expires_at),
        INDEX idx_fiscal_year (fiscal_year),
        INDEX idx_last_accessed (last_accessed)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    await execute_query(query)


async def create_equity_quotes_cache():
    """Create cache table for equity real-time quotes."""
    query = """
    CREATE TABLE IF NOT EXISTS cache_equity_quotes (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        cache_key VARCHAR(512) NOT NULL,
        symbol VARCHAR(50) NOT NULL,
        provider VARCHAR(50) DEFAULT 'fmp',
        data_hash VARCHAR(64) NOT NULL,
        response_data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL,
        access_count INT DEFAULT 1,
        last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_cache_key (cache_key),
        INDEX idx_symbol (symbol),
        INDEX idx_expires_at (expires_at),
        INDEX idx_last_accessed (last_accessed)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    await execute_query(query)


async def create_company_info_cache():
    """Create cache table for company information and profiles."""
    query = """
    CREATE TABLE IF NOT EXISTS cache_company_info (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        cache_key VARCHAR(512) NOT NULL,
        symbol VARCHAR(50) NOT NULL,
        provider VARCHAR(50) DEFAULT 'fmp',
        info_type VARCHAR(100) NOT NULL,
        data_hash VARCHAR(64) NOT NULL,
        response_data LONGTEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL,
        access_count INT DEFAULT 1,
        last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_cache_key (cache_key),
        INDEX idx_symbol_info_type (symbol, info_type),
        INDEX idx_expires_at (expires_at),
        INDEX idx_last_accessed (last_accessed)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    await execute_query(query)


async def create_market_data_cache():
    """Create cache table for market data (screeners, indices, etc.)."""
    query = """
    CREATE TABLE IF NOT EXISTS cache_market_data (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        cache_key VARCHAR(512) NOT NULL,
        provider VARCHAR(50) DEFAULT 'fmp',
        data_type VARCHAR(100) NOT NULL,
        parameters_hash VARCHAR(64) NOT NULL,
        data_hash VARCHAR(64) NOT NULL,
        response_data LONGTEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL,
        access_count INT DEFAULT 1,
        last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_cache_key (cache_key),
        INDEX idx_data_type (data_type),
        INDEX idx_expires_at (expires_at),
        INDEX idx_parameters_hash (parameters_hash),
        INDEX idx_last_accessed (last_accessed)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    await execute_query(query)


async def create_calendar_events_cache():
    """Create cache table for calendar events (earnings, dividends, etc.)."""
    query = """
    CREATE TABLE IF NOT EXISTS cache_calendar_events (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        cache_key VARCHAR(512) NOT NULL,
        provider VARCHAR(50) DEFAULT 'fmp',
        event_type VARCHAR(100) NOT NULL,
        start_date DATE,
        end_date DATE,
        data_hash VARCHAR(64) NOT NULL,
        response_data LONGTEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL,
        access_count INT DEFAULT 1,
        last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_cache_key (cache_key),
        INDEX idx_event_type (event_type),
        INDEX idx_date_range (start_date, end_date),
        INDEX idx_expires_at (expires_at),
        INDEX idx_last_accessed (last_accessed)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    await execute_query(query)


async def create_cache_statistics_table():
    """Create table for cache performance statistics."""
    query = """
    CREATE TABLE IF NOT EXISTS cache_statistics (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        date DATE NOT NULL,
        table_name VARCHAR(255) NOT NULL,
        total_requests INT DEFAULT 0,
        cache_hits INT DEFAULT 0,
        cache_misses INT DEFAULT 0,
        api_calls_saved INT DEFAULT 0,
        total_data_size BIGINT DEFAULT 0,
        avg_response_time_ms DECIMAL(10,2) DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY unique_date_table (date, table_name),
        INDEX idx_date (date),
        INDEX idx_table_name (table_name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    await execute_query(query)


def create_all_tables_sync():
    """Create all cache tables (sync version for Jupyter)."""
    tables_to_create = [
        ("cache_metadata", create_cache_metadata_table),
        ("cache_equity_historical", lambda: _execute_query_env_aware("""
        CREATE TABLE IF NOT EXISTS cache_equity_historical (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            cache_key VARCHAR(512) NOT NULL,
            symbol VARCHAR(50) NOT NULL,
            provider VARCHAR(50) DEFAULT 'fmp',
            interval_type VARCHAR(10) NOT NULL,
            start_date DATE,
            end_date DATE,
            adjustment VARCHAR(50),
            data_hash VARCHAR(64) NOT NULL,
            response_data LONGTEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            access_count INT DEFAULT 1,
            last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_cache_key (cache_key),
            INDEX idx_symbol_interval (symbol, interval_type),
            INDEX idx_expires_at (expires_at),
            INDEX idx_provider (provider),
            INDEX idx_last_accessed (last_accessed)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)),
        # Add other tables as needed - for now just the essential ones
    ]
    
    for table_name, create_func in tables_to_create:
        try:
            create_func()
            logger.info(f"Created/verified table: {table_name}")
        except Exception as e:
            logger.error(f"Failed to create table {table_name}: {e}")
            raise
    
    # Initialize metadata
    initialize_cache_metadata_sync()


def initialize_cache_metadata_sync():
    """Initialize cache metadata with TTL settings (sync version)."""
    metadata_entries = [
        ("cache_equity_historical", "Historical equity price data cache", CACHE_TTL["equity_historical_daily"]),
    ]
    
    for table_name, description, ttl in metadata_entries:
        query = """
        INSERT INTO cache_metadata (table_name, description, ttl_seconds)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            description = VALUES(description),
            ttl_seconds = VALUES(ttl_seconds),
            updated_at = CURRENT_TIMESTAMP
        """
        _execute_query_env_aware(query, (table_name, description, ttl))


async def create_all_tables_async():
    """Create all cache tables (async version)."""
    # For async, just use the existing functions but properly awaited
    try:
        await create_cache_metadata_table_async()
        logger.info("Created/verified table: cache_metadata")
        
        # For now, just create the essential table
        query = """
        CREATE TABLE IF NOT EXISTS cache_equity_historical (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            cache_key VARCHAR(512) NOT NULL,
            symbol VARCHAR(50) NOT NULL,
            provider VARCHAR(50) DEFAULT 'fmp',
            interval_type VARCHAR(10) NOT NULL,
            start_date DATE,
            end_date DATE,
            adjustment VARCHAR(50),
            data_hash VARCHAR(64) NOT NULL,
            response_data LONGTEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            access_count INT DEFAULT 1,
            last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_cache_key (cache_key),
            INDEX idx_symbol_interval (symbol, interval_type),
            INDEX idx_expires_at (expires_at),
            INDEX idx_provider (provider),
            INDEX idx_last_accessed (last_accessed)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
        await _execute_query_async(query)
        logger.info("Created/verified table: cache_equity_historical")
        
    except Exception as e:
        logger.error(f"Failed to create tables: {e}")
        raise


async def create_all_tables():
    """Create all cache tables (backward compatibility)."""
    return await create_all_tables_async()


async def initialize_cache_metadata():
    """Initialize cache metadata with TTL settings."""
    metadata_entries = [
        ("cache_equity_historical", "Historical equity price data cache", CACHE_TTL["equity_historical_daily"]),
        ("cache_equity_fundamentals", "Equity fundamental data cache", CACHE_TTL["balance_sheet"]),
        ("cache_equity_quotes", "Real-time equity quotes cache", CACHE_TTL["equity_quote"]),
        ("cache_company_info", "Company information and profiles cache", CACHE_TTL["company_info"]),
        ("cache_market_data", "Market data and screening results cache", CACHE_TTL["market_data"]),
        ("cache_calendar_events", "Financial calendar events cache", CACHE_TTL["calendar_events"]),
    ]
    
    for table_name, description, ttl in metadata_entries:
        query = """
        INSERT INTO cache_metadata (table_name, description, ttl_seconds)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            description = VALUES(description),
            ttl_seconds = VALUES(ttl_seconds),
            updated_at = CURRENT_TIMESTAMP
        """
        await execute_query(query, (table_name, description, ttl))


async def cleanup_expired_cache():
    """Clean up expired cache entries from all tables."""
    cache_tables = [
        "cache_equity_historical",
        "cache_equity_fundamentals", 
        "cache_equity_quotes",
        "cache_company_info",
        "cache_market_data",
        "cache_calendar_events"
    ]
    
    total_deleted = 0
    for table in cache_tables:
        query = f"DELETE FROM {table} WHERE expires_at < NOW()"
        deleted_count = await execute_query(query)
        total_deleted += deleted_count
        logger.info(f"Cleaned up {deleted_count} expired entries from {table}")
    
    return total_deleted