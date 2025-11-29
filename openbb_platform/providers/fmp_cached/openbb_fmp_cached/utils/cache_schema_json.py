"""
Complete Flexible Database Schema for FMP Cached Provider

Auto-generated database tables for all FMP model entities using JSON storage.
This approach is flexible and can handle any data structure without schema changes.
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



def create_analyst_estimates_table():
    """Create analyst_estimates table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS analyst_estimates (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_available_indices_table():
    """Create available_indices table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS available_indices (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_balance_sheet_table():
    """Create balance_sheet table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS balance_sheet (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_balance_sheet_growth_table():
    """Create balance_sheet_growth table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS balance_sheet_growth (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_calendar_dividend_table():
    """Create calendar_dividend table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS calendar_dividend (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_calendar_earnings_table():
    """Create calendar_earnings table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS calendar_earnings (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_calendar_events_table():
    """Create calendar_events table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS calendar_events (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_calendar_ipo_table():
    """Create calendar_ipo table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS calendar_ipo (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_calendar_splits_table():
    """Create calendar_splits table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS calendar_splits (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_cash_flow_table():
    """Create cash_flow table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS cash_flow (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_cash_flow_growth_table():
    """Create cash_flow_growth table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS cash_flow_growth (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_company_filings_table():
    """Create company_filings table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS company_filings (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_company_news_table():
    """Create company_news table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS company_news (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_crypto_historical_table():
    """Create crypto_historical table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS crypto_historical (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_crypto_search_table():
    """Create crypto_search table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS crypto_search (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_currency_historical_table():
    """Create currency_historical table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS currency_historical (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_currency_pairs_table():
    """Create currency_pairs table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS currency_pairs (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_currency_snapshots_table():
    """Create currency_snapshots table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS currency_snapshots (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_discovery_filings_table():
    """Create discovery_filings table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS discovery_filings (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_earnings_call_transcript_table():
    """Create earnings_call_transcript table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS earnings_call_transcript (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_economic_calendar_table():
    """Create economic_calendar table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS economic_calendar (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_equity_gainers_table():
    """Create equity_gainers table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_gainers (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_equity_historical_table():
    """Create equity_historical table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_historical (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_equity_losers_table():
    """Create equity_losers table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_losers (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_equity_most_active_table():
    """Create equity_most_active table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_most_active (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_equity_ownership_table():
    """Create equity_ownership table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_ownership (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_equity_peers_table():
    """Create equity_peers table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_peers (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_equity_profile_table():
    """Create equity_profile table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_profile (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_equity_quote_table():
    """Create equity_quote table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_quote (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_equity_screener_table():
    """Create equity_screener table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_screener (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_esg_score_table():
    """Create esg_score table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS esg_score (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_etf_countries_table():
    """Create etf_countries table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS etf_countries (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_etf_equity_exposure_table():
    """Create etf_equity_exposure table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS etf_equity_exposure (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_etf_holdings_table():
    """Create etf_holdings table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS etf_holdings (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_etf_info_table():
    """Create etf_info table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS etf_info (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_etf_search_table():
    """Create etf_search table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS etf_search (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_etf_sectors_table():
    """Create etf_sectors table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS etf_sectors (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_executive_compensation_table():
    """Create executive_compensation table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS executive_compensation (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_financial_ratios_table():
    """Create financial_ratios table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS financial_ratios (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_forward_ebitda_estimates_table():
    """Create forward_ebitda_estimates table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS forward_ebitda_estimates (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_forward_eps_estimates_table():
    """Create forward_eps_estimates table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS forward_eps_estimates (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_government_trades_table():
    """Create government_trades table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS government_trades (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_historical_dividends_table():
    """Create historical_dividends table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS historical_dividends (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_historical_employees_table():
    """Create historical_employees table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS historical_employees (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_historical_eps_table():
    """Create historical_eps table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS historical_eps (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_historical_market_cap_table():
    """Create historical_market_cap table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS historical_market_cap (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_historical_splits_table():
    """Create historical_splits table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS historical_splits (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_income_statement_table():
    """Create income_statement table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS income_statement (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_income_statement_growth_table():
    """Create income_statement_growth table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS income_statement_growth (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_index_constituents_table():
    """Create index_constituents table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS index_constituents (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_index_historical_table():
    """Create index_historical table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS index_historical (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_insider_trading_table():
    """Create insider_trading table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS insider_trading (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_institutional_ownership_table():
    """Create institutional_ownership table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS institutional_ownership (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_key_executives_table():
    """Create key_executives table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS key_executives (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_key_metrics_table():
    """Create key_metrics table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS key_metrics (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_market_snapshots_table():
    """Create market_snapshots table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS market_snapshots (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_nport_disclosure_table():
    """Create nport_disclosure table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS nport_disclosure (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_price_performance_table():
    """Create price_performance table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS price_performance (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_price_target_table():
    """Create price_target table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS price_target (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_price_target_consensus_table():
    """Create price_target_consensus table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS price_target_consensus (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_revenue_business_line_table():
    """Create revenue_business_line table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS revenue_business_line (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_revenue_geographic_table():
    """Create revenue_geographic table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS revenue_geographic (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_risk_premium_table():
    """Create risk_premium table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS risk_premium (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_share_statistics_table():
    """Create share_statistics table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS share_statistics (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_treasury_rates_table():
    """Create treasury_rates table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS treasury_rates (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_world_news_table():
    """Create world_news table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS world_news (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



def create_yield_curve_table():
    """Create yield_curve table for flexible data storage."""
    query = """
    CREATE TABLE IF NOT EXISTS yield_curve (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)



# Complete table configuration for all 67 entities
FLATTENED_TABLES = {
    "analyst_estimates": {
        "schema": create_analyst_estimates_table
    },
    "available_indices": {
        "schema": create_available_indices_table
    },
    "balance_sheet": {
        "schema": create_balance_sheet_table
    },
    "balance_sheet_growth": {
        "schema": create_balance_sheet_growth_table
    },
    "calendar_dividend": {
        "schema": create_calendar_dividend_table
    },
    "calendar_earnings": {
        "schema": create_calendar_earnings_table
    },
    "calendar_events": {
        "schema": create_calendar_events_table
    },
    "calendar_ipo": {
        "schema": create_calendar_ipo_table
    },
    "calendar_splits": {
        "schema": create_calendar_splits_table
    },
    "cash_flow": {
        "schema": create_cash_flow_table
    },
    "cash_flow_growth": {
        "schema": create_cash_flow_growth_table
    },
    "company_filings": {
        "schema": create_company_filings_table
    },
    "company_news": {
        "schema": create_company_news_table
    },
    "crypto_historical": {
        "schema": create_crypto_historical_table
    },
    "crypto_search": {
        "schema": create_crypto_search_table
    },
    "currency_historical": {
        "schema": create_currency_historical_table
    },
    "currency_pairs": {
        "schema": create_currency_pairs_table
    },
    "currency_snapshots": {
        "schema": create_currency_snapshots_table
    },
    "discovery_filings": {
        "schema": create_discovery_filings_table
    },
    "earnings_call_transcript": {
        "schema": create_earnings_call_transcript_table
    },
    "economic_calendar": {
        "schema": create_economic_calendar_table
    },
    "equity_gainers": {
        "schema": create_equity_gainers_table
    },
    "equity_historical": {
        "schema": create_equity_historical_table
    },
    "equity_losers": {
        "schema": create_equity_losers_table
    },
    "equity_most_active": {
        "schema": create_equity_most_active_table
    },
    "equity_ownership": {
        "schema": create_equity_ownership_table
    },
    "equity_peers": {
        "schema": create_equity_peers_table
    },
    "equity_profile": {
        "schema": create_equity_profile_table
    },
    "equity_quote": {
        "schema": create_equity_quote_table
    },
    "equity_screener": {
        "schema": create_equity_screener_table
    },
    "esg_score": {
        "schema": create_esg_score_table
    },
    "etf_countries": {
        "schema": create_etf_countries_table
    },
    "etf_equity_exposure": {
        "schema": create_etf_equity_exposure_table
    },
    "etf_holdings": {
        "schema": create_etf_holdings_table
    },
    "etf_info": {
        "schema": create_etf_info_table
    },
    "etf_search": {
        "schema": create_etf_search_table
    },
    "etf_sectors": {
        "schema": create_etf_sectors_table
    },
    "executive_compensation": {
        "schema": create_executive_compensation_table
    },
    "financial_ratios": {
        "schema": create_financial_ratios_table
    },
    "forward_ebitda_estimates": {
        "schema": create_forward_ebitda_estimates_table
    },
    "forward_eps_estimates": {
        "schema": create_forward_eps_estimates_table
    },
    "government_trades": {
        "schema": create_government_trades_table
    },
    "historical_dividends": {
        "schema": create_historical_dividends_table
    },
    "historical_employees": {
        "schema": create_historical_employees_table
    },
    "historical_eps": {
        "schema": create_historical_eps_table
    },
    "historical_market_cap": {
        "schema": create_historical_market_cap_table
    },
    "historical_splits": {
        "schema": create_historical_splits_table
    },
    "income_statement": {
        "schema": create_income_statement_table
    },
    "income_statement_growth": {
        "schema": create_income_statement_growth_table
    },
    "index_constituents": {
        "schema": create_index_constituents_table
    },
    "index_historical": {
        "schema": create_index_historical_table
    },
    "insider_trading": {
        "schema": create_insider_trading_table
    },
    "institutional_ownership": {
        "schema": create_institutional_ownership_table
    },
    "key_executives": {
        "schema": create_key_executives_table
    },
    "key_metrics": {
        "schema": create_key_metrics_table
    },
    "market_snapshots": {
        "schema": create_market_snapshots_table
    },
    "nport_disclosure": {
        "schema": create_nport_disclosure_table
    },
    "price_performance": {
        "schema": create_price_performance_table
    },
    "price_target": {
        "schema": create_price_target_table
    },
    "price_target_consensus": {
        "schema": create_price_target_consensus_table
    },
    "revenue_business_line": {
        "schema": create_revenue_business_line_table
    },
    "revenue_geographic": {
        "schema": create_revenue_geographic_table
    },
    "risk_premium": {
        "schema": create_risk_premium_table
    },
    "share_statistics": {
        "schema": create_share_statistics_table
    },
    "treasury_rates": {
        "schema": create_treasury_rates_table
    },
    "world_news": {
        "schema": create_world_news_table
    },
    "yield_curve": {
        "schema": create_yield_curve_table
    },
}


def create_all_flattened_tables():
    """Create all flattened database tables."""
    results = {}
    print(f"Creating {len(FLATTENED_TABLES)} database tables...")
    
    for table_name, config in FLATTENED_TABLES.items():
        try:
            result = config["schema"]()
            results[table_name] = result
            print(f"✅ Created table: {table_name}")
        except Exception as e:
            results[table_name] = f"Error: {str(e)}"
            print(f"❌ Error creating {table_name}: {e}")
    
    return results


def create_all_tables():
    """Create all database tables (alias for create_all_flattened_tables)."""
    return create_all_flattened_tables()


def cleanup_expired_cache():
    """Cleanup function - no longer needed as we don't use TTL/expiry."""
    # Since we simplified to remove TTL/expiry, this function is a no-op
    return {"message": "No cleanup needed - TTL/expiry removed from simplified schema"}


def get_table_names():
    """Get all table names for the cached provider."""
    return list(FLATTENED_TABLES.keys())


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the schema."""
    return table_name in FLATTENED_TABLES
