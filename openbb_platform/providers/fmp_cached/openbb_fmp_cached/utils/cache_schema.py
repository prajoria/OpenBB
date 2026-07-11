"""
Complete Flattened Database Schema for FMP Cached Provider

Database tables with actual columns mapped from OpenBB model fields.
This enables proper relational queries and consistent DataFrame mapping.
Simple database-backed response persistence without TTL/caching complexity.
"""

import logging
import os
import threading
from .database import execute_query, safe_identifier

logger = logging.getLogger(__name__)


def get_table_name(base_name: str) -> str:
    """Get table name with test prefix if in test mode.

    Every ``base_name`` is validated by :func:`safe_identifier` BEFORE the
    ``test_`` prefix is applied (bd-9loj/20zx). ~60 create-table functions
    in this module f-string-interpolate the return value of this helper
    into ``CREATE TABLE`` DDL, so a structurally-enforced allowlist here
    protects the entire surface without changing any of the ~60 callers.

    Raises
    ------
    ValueError
        If ``base_name`` (or the ``test_``-prefixed composed name) fails
        the MySQL identifier allowlist.
    """
    # Validate the base BEFORE composition — a malicious base combined
    # with the ``test_`` prefix would still contain the injection payload
    # (``test_balance_sheet; DROP TABLE users; --``).
    safe_identifier(base_name)
    is_test_mode = os.getenv("FMP_CACHE_TEST_MODE", "false").lower() == "true"
    if is_test_mode:
        # Compose and re-validate — the ``test_`` prefix can only produce
        # a valid identifier if the base was already valid (which we just
        # checked), but the re-validation is defense-in-depth against a
        # future refactor that swaps in a different prefix source.
        composed = f"test_{base_name}"
        return safe_identifier(composed)
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
        -- bd-hyzu: defense-in-depth UNIQUE against duplicate rows from
        -- concurrent writers (or external tools bypassing
        -- _store_financial_ratios). The DELETE+INSERT race that
        -- motivated this bead was closed by PR #418 (bd-n3sf) via
        -- atomic replace_rows(); this UNIQUE prevents ANY future code
        -- path from silently duplicating a (symbol, date, period, currency)
        -- row.
        --
        -- PR #427 silent-failure-hunter P0: currency IS in the key even
        -- though FMP currently returns one currency per (symbol, date,
        -- period). Widens the key defensively so a dual-listed ADR or
        -- IFRS-vs-USD reporter emitting multi-currency rows doesn't
        -- silently collapse to one row on dedupe.
        UNIQUE KEY uk_symbol_date_period_currency
            (symbol, date, period, currency)

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


def ensure_financial_ratios_unique_index():
    """Migrate existing financial_ratios tables to add UNIQUE constraint (bd-hyzu).

    Idempotent migration for existing installs, guarded by a module-level
    ran-once flag (PR #427 code-reviewer P1): the migration fires at most
    ONCE per process. Fresh installs still pay one round-trip on the
    first ``_store_financial_ratios`` call (dedupe is a no-op; ALTER TABLE
    fails with 1061 which is caught) — subsequent stores are zero
    overhead.

    Steps (both wrapped in narrow error handling):
    1. NULL cleanup: DELETE rows where symbol/date/period is NULL — these
       rows are unfilterable and bypass the UNIQUE constraint (MySQL
       treats NULL as distinct in UNIQUE). Silent data loss risk if a
       downstream consumer depends on NULL-key rows, but institutional
       users shouldn't have any (FMP always populates these fields).
    2. Dedupe duplicates keeping the newest by cached_at (id tie-break).
    3. ALTER TABLE ADD UNIQUE. Idempotent — MySQL raises 1061 "Duplicate
       key name" on repeat runs / fresh installs (constraint already
       inline in CREATE TABLE). Caught at DEBUG so no log noise.

    Errno taxonomy (PR #427 code-reviewer P2):
    - 1061 "Duplicate key name": expected on fresh installs and repeats.
      Silently caught at DEBUG.
    - 1062 "Duplicate entry for key uk_...": UNEXPECTED — means dedupe
      missed a duplicate (should not happen). Logged at WARNING with the
      original error message so operators can investigate. Migration
      flag remains False so next call retries.
    - Other errors: logged at WARNING, flag stays False so a retry can
      happen.
    """
    global _FR_MIGRATION_RAN
    with _FR_MIGRATION_LOCK:
        if _FR_MIGRATION_RAN:
            return

        # Step 1 (bd-hyzu / PR #427 P1): purge NULL-key rows that would
        # bypass the UNIQUE constraint entirely. Institutional users
        # shouldn't have any (FMP always populates symbol/date/period).
        # currency is also in the key so include it in the NULL check.
        null_cleanup_sql = """
        DELETE FROM financial_ratios
        WHERE symbol IS NULL OR date IS NULL OR period IS NULL
           OR currency IS NULL
        """
        try:
            execute_query(null_cleanup_sql)
        except Exception as exc:
            logger.debug("financial_ratios NULL-cleanup skipped: %s", exc)

        # Step 2: dedupe (symbol, date, period, currency) keeping newest
        # by cached_at. PR #427 silent-failure-hunter P0: including
        # currency prevents collapsing legitimately-distinct multi-
        # currency rows for the same (symbol, date, period).
        dedupe_sql = """
        DELETE fr1 FROM financial_ratios fr1
        INNER JOIN financial_ratios fr2
          ON fr1.symbol = fr2.symbol
         AND fr1.date = fr2.date
         AND fr1.period = fr2.period
         AND fr1.currency = fr2.currency
         AND (fr1.cached_at < fr2.cached_at
              OR (fr1.cached_at = fr2.cached_at AND fr1.id < fr2.id))
        """
        try:
            execute_query(dedupe_sql)
        except Exception as exc:
            # Log but don't fail — dedupe is best-effort. If it fails, the
            # ADD UNIQUE below may also fail (that failure is handled).
            logger.debug("financial_ratios dedupe skipped: %s", exc)

        # Step 3: add UNIQUE constraint. Idempotent + errno-aware.
        add_unique_sql = """
        ALTER TABLE financial_ratios
        ADD UNIQUE KEY uk_symbol_date_period_currency
            (symbol, date, period, currency)
        """
        try:
            execute_query(add_unique_sql)
            logger.info(
                "financial_ratios: added UNIQUE(symbol, date, period, "
                "currency) constraint (bd-hyzu)"
            )
        except Exception as exc:
            msg = str(exc)
            # Errno 1061 = "Duplicate key name" — expected on fresh installs
            # and repeat migrations. Silent at DEBUG.
            if "1061" in msg or "Duplicate key name" in msg:
                logger.debug("financial_ratios UNIQUE already present: %s", exc)
            elif "1062" in msg or "Duplicate entry" in msg:
                # Errno 1062 = "Duplicate entry for key" — UNEXPECTED.
                # Dedupe missed something (NULL rows, race, or a corner
                # case). Log LOUDLY so operators can investigate + flag
                # stays False for next-call retry.
                logger.warning(
                    "financial_ratios UNIQUE constraint could not be added — "
                    "duplicates remain after dedupe (bd-hyzu): %s",
                    exc,
                )
                return  # keep flag False for retry
            else:
                # Other errors (permissions, disconnect, etc.) — log +
                # keep flag False so a retry has a chance.
                logger.warning("financial_ratios UNIQUE ADD failed: %s", exc)
                return

        # All 3 steps completed (or ADD UNIQUE hit 1061 which is expected).
        # Flag the migration as done so we skip the network round-trips on
        # subsequent calls in this process.
        _FR_MIGRATION_RAN = True


# Module-level guard for ensure_financial_ratios_unique_index. Set True
# after first successful (or expected-fail=1061) run so subsequent
# aextract_data calls skip the migration entirely (PR #427 code-reviewer
# P1: pre-review the migration fired on every fetch — 2 MySQL round-trips
# per call forever). Thread-safe via _FR_MIGRATION_LOCK.
_FR_MIGRATION_RAN = False
_FR_MIGRATION_LOCK = threading.Lock()


def _reset_fr_migration_flag_for_tests():
    """Test-only helper to reset the ran-once flag between tests."""
    global _FR_MIGRATION_RAN
    with _FR_MIGRATION_LOCK:
        _FR_MIGRATION_RAN = False


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
    "analyst_estimates": {"schema": create_analyst_estimates_table},
    "available_indices": {"schema": create_available_indices_table},
    "balance_sheet": {"schema": create_balance_sheet_table},
    "balance_sheet_growth": {"schema": create_balance_sheet_growth_table},
    "calendar_dividend": {"schema": create_calendar_dividend_table},
    "calendar_earnings": {"schema": create_calendar_earnings_table},
    "calendar_events": {"schema": create_calendar_events_table},
    "calendar_ipo": {"schema": create_calendar_ipo_table},
    "calendar_splits": {"schema": create_calendar_splits_table},
    "cash_flow": {"schema": create_cash_flow_table},
    "cash_flow_growth": {"schema": create_cash_flow_growth_table},
    "company_filings": {"schema": create_company_filings_table},
    "company_news": {"schema": create_company_news_table},
    "crypto_historical": {"schema": create_crypto_historical_table},
    "crypto_search": {"schema": create_crypto_search_table},
    "currency_historical": {"schema": create_currency_historical_table},
    "currency_pairs": {"schema": create_currency_pairs_table},
    "currency_snapshots": {"schema": create_currency_snapshots_table},
    "discovery_filings": {"schema": create_discovery_filings_table},
    "earnings_call_transcript": {"schema": create_earnings_call_transcript_table},
    "economic_calendar": {"schema": create_economic_calendar_table},
    "equity_gainers": {"schema": create_equity_gainers_table},
    "equity_historical": {"schema": create_equity_historical_table},
    "equity_losers": {"schema": create_equity_losers_table},
    "equity_most_active": {"schema": create_equity_most_active_table},
    "equity_ownership": {"schema": create_equity_ownership_table},
    "equity_peers": {"schema": create_equity_peers_table},
    "equity_profile": {"schema": create_equity_profile_table},
    "equity_quote": {"schema": create_equity_quote_table},
    "equity_screener": {"schema": create_equity_screener_table},
    "esg_score": {"schema": create_esg_score_table},
    "etf_countries": {"schema": create_etf_countries_table},
    "etf_equity_exposure": {"schema": create_etf_equity_exposure_table},
    "etf_holdings": {"schema": create_etf_holdings_table},
    "etf_info": {"schema": create_etf_info_table},
    "etf_search": {"schema": create_etf_search_table},
    "etf_sectors": {"schema": create_etf_sectors_table},
    "executive_compensation": {"schema": create_executive_compensation_table},
    "financial_ratios": {"schema": create_financial_ratios_table},
    "forward_ebitda_estimates": {"schema": create_forward_ebitda_estimates_table},
    "forward_eps_estimates": {"schema": create_forward_eps_estimates_table},
    "government_trades": {"schema": create_government_trades_table},
    "historical_dividends": {"schema": create_historical_dividends_table},
    "historical_employees": {"schema": create_historical_employees_table},
    "historical_eps": {"schema": create_historical_eps_table},
    "historical_market_cap": {"schema": create_historical_market_cap_table},
    "historical_splits": {"schema": create_historical_splits_table},
    "income_statement": {"schema": create_income_statement_table},
    "income_statement_growth": {"schema": create_income_statement_growth_table},
    "index_constituents": {"schema": create_index_constituents_table},
    "index_historical": {"schema": create_index_historical_table},
    "insider_trading": {"schema": create_insider_trading_table},
    "institutional_ownership": {"schema": create_institutional_ownership_table},
    "key_executives": {"schema": create_key_executives_table},
    "key_metrics": {"schema": create_key_metrics_table},
    "market_snapshots": {"schema": create_market_snapshots_table},
    "nport_disclosure": {"schema": create_nport_disclosure_table},
    "price_performance": {"schema": create_price_performance_table},
    "price_target": {"schema": create_price_target_table},
    "price_target_consensus": {"schema": create_price_target_consensus_table},
    "revenue_business_line": {"schema": create_revenue_business_line_table},
    "revenue_geographic": {"schema": create_revenue_geographic_table},
    "risk_premium": {"schema": create_risk_premium_table},
    "share_statistics": {"schema": create_share_statistics_table},
    "treasury_rates": {"schema": create_treasury_rates_table},
    "complementary_market_yields": {"schema": create_complementary_market_yields_table},
    "world_news": {"schema": create_world_news_table},
    "yield_curve": {"schema": create_yield_curve_table},
}


def create_all_flattened_tables():
    """Create all flattened database tables.

    Iterates the :data:`FLATTENED_TABLES` registry and invokes each
    schema-creator in turn. Returns a mapping of ``{table_name:
    schema_result}`` for successfully-created tables.

    Failure semantics (bd-jt4r)
    ---------------------------
    On the FIRST DDL failure the loop aborts and re-raises the
    underlying exception so the operator sees the failure at init time
    rather than at first cache read. Pre-fix this function swallowed
    every ``Exception`` and stashed a stringified error under the
    table name in the results dict — leaving the DB half-provisioned
    with no alarm and no downstream check for the sentinel string.

    Status is emitted via the module's :data:`logger` at ``INFO`` level
    (successes) and ``ERROR`` level with traceback (failures). The
    caller controls stdout/stderr routing via the standard logging
    handler chain; ASCII-only messages so the log line encodes cleanly
    under Windows ``cp1252`` consoles (the fork runs on Windows via
    ``.venv_win`` per CLAUDE.md).

    Returns
    -------
    dict[str, Any]
        Mapping of table name to whatever ``config['schema']()`` returns
        for that table (typically a truthy sentinel or None).

    Raises
    ------
    Exception
        Whatever the first failing ``config['schema']()`` call raises,
        propagated verbatim (callers expect the underlying DDL exception
        type, so ``raise ... from exc`` chaining is deliberately not
        used).
    """
    results = {}
    logger.info("Creating %d flattened database tables...", len(FLATTENED_TABLES))

    for table_name, config in FLATTENED_TABLES.items():
        try:
            result = config["schema"]()
        except Exception:
            # bd-jt4r: raise on first failure. Pre-fix a bare
            # ``except Exception`` swallowed every DDL error and left
            # the DB half-provisioned. logger.exception records the
            # full traceback for the operator; the raise then aborts
            # the loop so downstream tables are NOT half-created.
            logger.exception(
                "DDL failed while creating flattened table %r; aborting "
                "further table creation (bd-jt4r).",
                table_name,
            )
            raise
        results[table_name] = result
        logger.info("Created flattened table: %s", table_name)

    return results


# Public alias — shares the full docstring (including the bd-jt4r failure
# semantics + logging contract) with the underlying function. Rebound as
# a name rather than wrapped in a function so callers get the identical
# behavior + docstring without a stale duplicate.
#
# Production callers of this alias (verified via grep across the repo):
#   - openbb_fmp_cached/utils/database.py::init_database (auto-create path)
#   - openbb_fmp_cached/utils/__init__.py (re-exported public symbol)
#   - openbb_platform/providers/fmp_cached/setup_database.py
# All three previously received the pre-fix return-dict-with-stringified-
# errors and did not check for the ``"Error: "`` sentinel; the switch to
# raise-on-first-failure is a strict improvement for each — schema-init
# failure now surfaces immediately instead of degrading downstream cache
# reads.
create_all_tables = create_all_flattened_tables


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
        "symbol",
        "date",
        "period",
        "currency",
        "exchange",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "vwap",
        "change_amount",
        "change_percent",
        "company_name",
        "sector",
        "industry",
        "country",
        "market_cap",
        "price",
        "beta",
        "revenue",
        "cost_of_revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "cash_and_cash_equivalents",
        "operating_cash_flow",
        "free_cash_flow",
        "pe_ratio",
        "pb_ratio",
        "debt_to_equity",
    ]
