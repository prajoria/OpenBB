"""
Complete Flattened Database Schema for FMP Cached Provider

Database tables with actual columns mapped from OpenBB model fields.
This enables proper relational queries and consistent DataFrame mapping.
Simple database-backed response persistence without TTL/caching complexity.
"""

import os
from .database import execute_query


def get_table_name(base_name: str) -> str:
    """Get table name with test prefix if in test mode."""
    is_test_mode = os.getenv("FMP_CACHE_TEST_MODE", "false").lower() == "true"
    if is_test_mode:
        return f"test_{base_name}"
    return base_name


def should_auto_create() -> bool:
    """Check if automatic database/table creation is enabled."""
    return os.getenv("FMP_CACHE_AUTO_CREATE_DB", "true").lower() == "true"


def create_analyst_estimates_table():
    """Create analyst_estimates table with common financial data columns."""
    table_name = get_table_name("analyst_estimates")
    query = f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_available_indices_table():
    """Create available_indices table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS available_indices (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_balance_sheet_table():
    """Create balance_sheet table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS balance_sheet (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        UNIQUE KEY unique_symbol_date_period (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_balance_sheet_growth_table():
    """Create balance_sheet_growth table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS balance_sheet_growth (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_calendar_dividend_table():
    """Create calendar_dividend table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS calendar_dividend (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_calendar_earnings_table():
    """Create calendar_earnings table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS calendar_earnings (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_calendar_events_table():
    """Create calendar_events table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS calendar_events (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_calendar_ipo_table():
    """Create calendar_ipo table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS calendar_ipo (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_calendar_splits_table():
    """Create calendar_splits table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS calendar_splits (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_cash_flow_table():
    """Create cash_flow table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS cash_flow (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        UNIQUE KEY unique_symbol_date_period (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_cash_flow_growth_table():
    """Create cash_flow_growth table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS cash_flow_growth (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_company_filings_table():
    """Create company_filings table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS company_filings (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_company_news_table():
    """Create company_news table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS company_news (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_crypto_historical_table():
    """Create crypto_historical table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS crypto_historical (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        UNIQUE KEY unique_symbol_date_period (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_crypto_search_table():
    """Create crypto_search table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS crypto_search (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_currency_historical_table():
    """Create currency_historical table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS currency_historical (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        UNIQUE KEY unique_symbol_date_period (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_currency_pairs_table():
    """Create currency_pairs table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS currency_pairs (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_currency_snapshots_table():
    """Create currency_snapshots table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS currency_snapshots (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_discovery_filings_table():
    """Create discovery_filings table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS discovery_filings (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_earnings_call_transcript_table():
    """Create earnings_call_transcript table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS earnings_call_transcript (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_economic_calendar_table():
    """Create economic_calendar table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS economic_calendar (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_equity_gainers_table():
    """Create equity_gainers table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_gainers (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_equity_historical_table():
    """Create equity_historical table optimized for FMP equity historical data."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_historical (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Core identifier fields (REQUIRED)
        symbol VARCHAR(50) NOT NULL,
        date DATE NOT NULL,
        
        -- Standard OHLCV data (from EquityHistoricalData base model)
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        
        -- Dividend data (from FMP /dividends endpoint)
        dividend DECIMAL(15,6) DEFAULT NULL,
        
        -- FMP-specific additional fields (from FMPEquityHistoricalData)
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(12,6) DEFAULT NULL,
        
        -- Query context fields (for multi-interval and adjustment support)
        interval_type VARCHAR(10) DEFAULT '1d',
        adjustment_type VARCHAR(20) DEFAULT 'splits_only',
        
        -- Gap filling metadata (for holiday/weekend fills)
        is_filled BOOLEAN DEFAULT FALSE,
        fill_source_date DATE DEFAULT NULL,
        fill_type ENUM('previous_close', 'next_open') DEFAULT NULL,
        
        -- Caching metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_symbol_date_interval (symbol, date, interval_type),
        INDEX idx_interval_adjustment (interval_type, adjustment_type),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- Unique constraint to prevent duplicates
        UNIQUE KEY unique_symbol_date_interval_adjustment (symbol, date, interval_type, adjustment_type)
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_equity_losers_table():
    """Create equity_losers table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_losers (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_equity_most_active_table():
    """Create equity_most_active table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_most_active (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_equity_ownership_table():
    """Create equity_ownership table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_ownership (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_equity_peers_table():
    """Create equity_peers table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_peers (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_equity_profile_table():
    """Create equity_profile table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_profile (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        UNIQUE KEY unique_symbol (symbol)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_equity_quote_table():
    """Create equity_quote table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_quote (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_equity_screener_table():
    """Create equity_screener table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_screener (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_esg_score_table():
    """Create esg_score table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS esg_score (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_etf_countries_table():
    """Create etf_countries table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS etf_countries (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_etf_equity_exposure_table():
    """Create etf_equity_exposure table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS etf_equity_exposure (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_etf_holdings_table():
    """Create etf_holdings table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS etf_holdings (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_etf_info_table():
    """Create etf_info table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS etf_info (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_etf_search_table():
    """Create etf_search table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS etf_search (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_etf_sectors_table():
    """Create etf_sectors table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS etf_sectors (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_executive_compensation_table():
    """Create executive_compensation table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS executive_compensation (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_financial_ratios_table():
    """Create financial_ratios table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS financial_ratios (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_forward_ebitda_estimates_table():
    """Create forward_ebitda_estimates table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS forward_ebitda_estimates (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_forward_eps_estimates_table():
    """Create forward_eps_estimates table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS forward_eps_estimates (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_government_trades_table():
    """Create government_trades table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS government_trades (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_historical_dividends_table():
    """Create historical_dividends table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS historical_dividends (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_historical_employees_table():
    """Create historical_employees table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS historical_employees (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_historical_eps_table():
    """Create historical_eps table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS historical_eps (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_historical_market_cap_table():
    """Create historical_market_cap table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS historical_market_cap (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_historical_splits_table():
    """Create historical_splits table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS historical_splits (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_income_statement_table():
    """Create income_statement table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS income_statement (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        UNIQUE KEY unique_symbol_date_period (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_income_statement_growth_table():
    """Create income_statement_growth table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS income_statement_growth (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_index_constituents_table():
    """Create index_constituents table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS index_constituents (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_index_historical_table():
    """Create index_historical table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS index_historical (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        UNIQUE KEY unique_symbol_date_period (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_insider_trading_table():
    """Create insider_trading table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS insider_trading (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_institutional_ownership_table():
    """Create institutional_ownership table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS institutional_ownership (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_key_executives_table():
    """Create key_executives table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS key_executives (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_key_metrics_table():
    """Create key_metrics table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS key_metrics (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_market_snapshots_table():
    """Create market_snapshots table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS market_snapshots (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_nport_disclosure_table():
    """Create nport_disclosure table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS nport_disclosure (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_price_performance_table():
    """Create price_performance table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS price_performance (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_price_target_table():
    """Create price_target table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS price_target (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_price_target_consensus_table():
    """Create price_target_consensus table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS price_target_consensus (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_revenue_business_line_table():
    """Create revenue_business_line table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS revenue_business_line (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_revenue_geographic_table():
    """Create revenue_geographic table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS revenue_geographic (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_risk_premium_table():
    """Create risk_premium table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS risk_premium (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_share_statistics_table():
    """Create share_statistics table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS share_statistics (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_treasury_rates_table():
    """Create treasury_rates table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS treasury_rates (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_complementary_market_yields_table():
    """Create complementary_market_yields table for TNX and similar series."""
    table_name = get_table_name("complementary_market_yields")
    query = f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,

        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        UNIQUE KEY unique_symbol_date (symbol, date)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_world_news_table():
    """Create world_news table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS world_news (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)


def create_yield_curve_table():
    """Create yield_curve table with common financial data columns."""
    query = """
    CREATE TABLE IF NOT EXISTS yield_curve (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        open DECIMAL(15,6) DEFAULT NULL,
        high DECIMAL(15,6) DEFAULT NULL,
        low DECIMAL(15,6) DEFAULT NULL,
        close DECIMAL(15,6) DEFAULT NULL,
        volume BIGINT DEFAULT NULL,
        vwap DECIMAL(15,6) DEFAULT NULL,
        change_amount DECIMAL(15,6) DEFAULT NULL,
        change_percent DECIMAL(8,6) DEFAULT NULL,
        company_name VARCHAR(255) DEFAULT NULL,
        sector VARCHAR(100) DEFAULT NULL,
        industry VARCHAR(100) DEFAULT NULL,
        country VARCHAR(100) DEFAULT NULL,
        market_cap BIGINT DEFAULT NULL,
        price DECIMAL(15,6) DEFAULT NULL,
        beta DECIMAL(8,6) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        ceo VARCHAR(255) DEFAULT NULL,
        employees INT DEFAULT NULL,
        website VARCHAR(255) DEFAULT NULL,
        revenue BIGINT DEFAULT NULL,
        cost_of_revenue BIGINT DEFAULT NULL,
        gross_profit BIGINT DEFAULT NULL,
        operating_expenses BIGINT DEFAULT NULL,
        operating_income BIGINT DEFAULT NULL,
        net_income BIGINT DEFAULT NULL,
        eps DECIMAL(8,6) DEFAULT NULL,
        eps_diluted DECIMAL(8,6) DEFAULT NULL,
        total_assets BIGINT DEFAULT NULL,
        total_liabilities BIGINT DEFAULT NULL,
        total_equity BIGINT DEFAULT NULL,
        cash_and_cash_equivalents BIGINT DEFAULT NULL,
        total_debt BIGINT DEFAULT NULL,
        working_capital BIGINT DEFAULT NULL,
        operating_cash_flow BIGINT DEFAULT NULL,
        investing_cash_flow BIGINT DEFAULT NULL,
        financing_cash_flow BIGINT DEFAULT NULL,
        free_cash_flow BIGINT DEFAULT NULL,
        capital_expenditure BIGINT DEFAULT NULL,
        pe_ratio DECIMAL(15,6) DEFAULT NULL,
        pb_ratio DECIMAL(15,6) DEFAULT NULL,
        debt_to_equity DECIMAL(15,6) DEFAULT NULL,
        current_ratio DECIMAL(15,6) DEFAULT NULL,
        roe DECIMAL(15,6) DEFAULT NULL,
        roa DECIMAL(15,6) DEFAULT NULL,
        data_json JSON DEFAULT NULL,
        additional_fields JSON DEFAULT NULL,

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
        INDEX idx_composite (symbol, date, period)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return execute_query(query)



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
    "complementary_market_yields": {
        "schema": create_complementary_market_yields_table
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
    print(f"Creating {len(FLATTENED_TABLES)} flattened database tables...")
    
    for table_name, config in FLATTENED_TABLES.items():
        try:
            result = config["schema"]()
            results[table_name] = result
            print(f"✅ Created flattened table: {table_name}")
        except Exception as e:
            results[table_name] = f"Error: {str(e)}"
            print(f"❌ Error creating {table_name}: {e}")
    
    return results


def create_all_tables():
    """Create all database tables (alias for create_all_flattened_tables)."""
    return create_all_flattened_tables()


def cleanup_expired_cache():
    """Cleanup function - no longer needed as we don't use TTL/expiry."""
    return {"message": "No cleanup needed - TTL/expiry removed from simplified schema"}


def get_table_names():
    """Get all table names for the cached provider."""
    return list(FLATTENED_TABLES.keys())


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the schema."""
    return table_name in FLATTENED_TABLES


def get_common_field_names():
    """Get list of common field names used across entities."""
    return [
        'symbol', 'date', 'period', 'currency', 'exchange',
        'open', 'high', 'low', 'close', 'volume', 'vwap', 'change_amount', 'change_percent',
        'company_name', 'sector', 'industry', 'country', 'market_cap', 'price', 'beta',
        'revenue', 'cost_of_revenue', 'gross_profit', 'operating_income', 'net_income',
        'total_assets', 'total_liabilities', 'total_equity', 'cash_and_cash_equivalents',
        'operating_cash_flow', 'free_cash_flow', 'pe_ratio', 'pb_ratio', 'debt_to_equity'
    ]
