"""Flattened cache database schema definitions for FMP Cached provider."""

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


# Database table configuration - simple persistence without TTL complexity


def create_equity_historical_table():
    """Create equity historical table - permanent storage for immutable historical data."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_historical (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        open DECIMAL(15,4),
        high DECIMAL(15,4),
        low DECIMAL(15,4),
        close DECIMAL(15,4),
        volume BIGINT,
        vwap DECIMAL(15,4),
        change_amount DECIMAL(15,4),
        change_percent DECIMAL(8,6),
        
        -- Metadata for permanent storage (no expiry for historical data)
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        UNIQUE KEY unique_symbol_date (symbol, date),
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)


async def create_equity_historical_table_async():
    """Create equity historical table (async wrapper for same table)."""
    return await _execute_query_async("""
    CREATE TABLE IF NOT EXISTS equity_historical (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        open DECIMAL(15,4),
        high DECIMAL(15,4),
        low DECIMAL(15,4),
        close DECIMAL(15,4),
        volume BIGINT,
        vwap DECIMAL(15,4),
        change_amount DECIMAL(15,4),
        change_percent DECIMAL(8,6),
        
        -- Metadata for permanent storage (no expiry for historical data)
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        UNIQUE KEY unique_symbol_date (symbol, date),
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)


def create_equity_profile_table():
    """Create equity profile table - temporary storage for changing company data."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_profile (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL UNIQUE,
        company_name VARCHAR(255),
        sector VARCHAR(100),
        industry VARCHAR(200),
        country VARCHAR(100),
        exchange VARCHAR(50),
        currency VARCHAR(10),
        market_cap DECIMAL(20,2),
        beta DECIMAL(8,4),
        price DECIMAL(15,4),
        last_annual_dividend DECIMAL(8,4),
        volume_avg BIGINT,
        range_52w VARCHAR(50),
        changes DECIMAL(15,4),
        company_name_full VARCHAR(500),
        description TEXT,
        website VARCHAR(255),
        ceo VARCHAR(255),
        employees INT,
        city VARCHAR(100),
        state VARCHAR(100),
        zip_code VARCHAR(20),
        address VARCHAR(500),
        phone VARCHAR(50),
        ipo_date DATE,
        dcf_diff DECIMAL(15,4),
        dcf DECIMAL(15,4),
        image VARCHAR(255),
        is_etf BOOLEAN DEFAULT FALSE,
        is_fund BOOLEAN DEFAULT FALSE,
        is_actively_trading BOOLEAN DEFAULT TRUE,
        
        -- Simple cache metadata 
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        INDEX idx_symbol (symbol),
        INDEX idx_sector (sector),
        INDEX idx_industry (industry),
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)


async def create_equity_profile_table_async():
    """Create flattened equity profile table (async version)."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_profile (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL UNIQUE,
        company_name VARCHAR(255),
        sector VARCHAR(100),
        industry VARCHAR(200),
        country VARCHAR(100),
        exchange VARCHAR(50),
        currency VARCHAR(10),
        market_cap DECIMAL(20,2),
        beta DECIMAL(8,4),
        price DECIMAL(15,4),
        last_annual_dividend DECIMAL(8,4),
        volume_avg BIGINT,
        range_52w VARCHAR(50),
        changes DECIMAL(15,4),
        company_name_full VARCHAR(500),
        description TEXT,
        website VARCHAR(255),
        ceo VARCHAR(255),
        employees INT,
        city VARCHAR(100),
        state VARCHAR(100),
        zip_code VARCHAR(20),
        address VARCHAR(500),
        phone VARCHAR(50),
        ipo_date DATE,
        dcf_diff DECIMAL(15,4),
        dcf DECIMAL(15,4),
        image VARCHAR(255),
        is_etf BOOLEAN DEFAULT FALSE,
        is_fund BOOLEAN DEFAULT FALSE,
        is_actively_trading BOOLEAN DEFAULT TRUE,
        
        -- Simple cache metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        INDEX idx_symbol (symbol),
        INDEX idx_sector (sector),
        INDEX idx_industry (industry),
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return await _execute_query_async(query)


def create_financial_ratios_table():
    """Create flattened financial ratios table (sync version)."""
    query = """
    CREATE TABLE IF NOT EXISTS financial_ratios (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        period VARCHAR(10),
        
        -- Liquidity ratios
        current_ratio DECIMAL(15,6),
        quick_ratio DECIMAL(15,6),
        cash_ratio DECIMAL(15,6),
        
        -- Activity ratios
        days_of_sales_outstanding DECIMAL(15,6),
        days_of_inventory_outstanding DECIMAL(15,6),
        operating_cycle DECIMAL(15,6),
        days_of_payables_outstanding DECIMAL(15,6),
        cash_conversion_cycle DECIMAL(15,6),
        receivables_turnover DECIMAL(15,6),
        payables_turnover DECIMAL(15,6),
        inventory_turnover DECIMAL(15,6),
        fixed_asset_turnover DECIMAL(15,6),
        asset_turnover DECIMAL(15,6),
        
        -- Profitability ratios
        gross_profit_margin DECIMAL(15,6),
        operating_profit_margin DECIMAL(15,6),
        pretax_profit_margin DECIMAL(15,6),
        net_profit_margin DECIMAL(15,6),
        effective_tax_rate DECIMAL(15,6),
        return_on_assets DECIMAL(15,6),
        return_on_equity DECIMAL(15,6),
        return_on_capital_employed DECIMAL(15,6),
        
        -- Leverage ratios
        debt_ratio DECIMAL(15,6),
        debt_equity_ratio DECIMAL(15,6),
        long_term_debt_to_capitalization DECIMAL(15,6),
        total_debt_to_capitalization DECIMAL(15,6),
        interest_coverage DECIMAL(15,6),
        cash_flow_to_debt_ratio DECIMAL(15,6),
        company_equity_multiplier DECIMAL(15,6),
        
        -- Per share metrics
        operating_cash_flow_per_share DECIMAL(15,6),
        free_cash_flow_per_share DECIMAL(15,6),
        cash_per_share DECIMAL(15,6),
        book_value_per_share DECIMAL(15,6),
        tangible_book_value_per_share DECIMAL(15,6),
        shareholders_equity_per_share DECIMAL(15,6),
        interest_debt_per_share DECIMAL(15,6),
        
        -- Valuation ratios
        market_cap DECIMAL(20,2),
        enterprise_value DECIMAL(20,2),
        pe_ratio DECIMAL(15,6),
        price_to_sales_ratio DECIMAL(15,6),
        pocf_ratio DECIMAL(15,6),
        pfcf_ratio DECIMAL(15,6),
        pb_ratio DECIMAL(15,6),
        ptb_ratio DECIMAL(15,6),
        ev_to_sales DECIMAL(15,6),
        enterprise_value_over_ebitda DECIMAL(15,6),
        ev_to_operating_cash_flow DECIMAL(15,6),
        ev_to_free_cash_flow DECIMAL(15,6),
        earnings_yield DECIMAL(15,6),
        free_cash_flow_yield DECIMAL(15,6),
        dividend_yield DECIMAL(15,6),
        payout_ratio DECIMAL(15,6),
        
        -- Metadata for permanent storage (ratios based on filed statements)
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        UNIQUE KEY unique_symbol_date (symbol, date),
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_period (period),
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)


async def create_financial_ratios_table_async():
    """Create flattened financial ratios table (async version)."""
    query = """
    CREATE TABLE IF NOT EXISTS financial_ratios (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        period VARCHAR(10),
        
        -- Liquidity ratios
        current_ratio DECIMAL(15,6),
        quick_ratio DECIMAL(15,6),
        cash_ratio DECIMAL(15,6),
        
        -- Activity ratios
        days_of_sales_outstanding DECIMAL(15,6),
        days_of_inventory_outstanding DECIMAL(15,6),
        operating_cycle DECIMAL(15,6),
        days_of_payables_outstanding DECIMAL(15,6),
        cash_conversion_cycle DECIMAL(15,6),
        receivables_turnover DECIMAL(15,6),
        payables_turnover DECIMAL(15,6),
        inventory_turnover DECIMAL(15,6),
        fixed_asset_turnover DECIMAL(15,6),
        asset_turnover DECIMAL(15,6),
        
        -- Profitability ratios
        gross_profit_margin DECIMAL(15,6),
        operating_profit_margin DECIMAL(15,6),
        pretax_profit_margin DECIMAL(15,6),
        net_profit_margin DECIMAL(15,6),
        effective_tax_rate DECIMAL(15,6),
        return_on_assets DECIMAL(15,6),
        return_on_equity DECIMAL(15,6),
        return_on_capital_employed DECIMAL(15,6),
        
        -- Leverage ratios
        debt_ratio DECIMAL(15,6),
        debt_equity_ratio DECIMAL(15,6),
        long_term_debt_to_capitalization DECIMAL(15,6),
        total_debt_to_capitalization DECIMAL(15,6),
        interest_coverage DECIMAL(15,6),
        cash_flow_to_debt_ratio DECIMAL(15,6),
        company_equity_multiplier DECIMAL(15,6),
        
        -- Per share metrics
        operating_cash_flow_per_share DECIMAL(15,6),
        free_cash_flow_per_share DECIMAL(15,6),
        cash_per_share DECIMAL(15,6),
        book_value_per_share DECIMAL(15,6),
        tangible_book_value_per_share DECIMAL(15,6),
        shareholders_equity_per_share DECIMAL(15,6),
        interest_debt_per_share DECIMAL(15,6),
        
        -- Valuation ratios
        market_cap DECIMAL(20,2),
        enterprise_value DECIMAL(20,2),
        pe_ratio DECIMAL(15,6),
        price_to_sales_ratio DECIMAL(15,6),
        pocf_ratio DECIMAL(15,6),
        pfcf_ratio DECIMAL(15,6),
        pb_ratio DECIMAL(15,6),
        ptb_ratio DECIMAL(15,6),
        ev_to_sales DECIMAL(15,6),
        enterprise_value_over_ebitda DECIMAL(15,6),
        ev_to_operating_cash_flow DECIMAL(15,6),
        ev_to_free_cash_flow DECIMAL(15,6),
        earnings_yield DECIMAL(15,6),
        free_cash_flow_yield DECIMAL(15,6),
        dividend_yield DECIMAL(15,6),
        payout_ratio DECIMAL(15,6),
        
        -- Simple cache metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        UNIQUE KEY unique_symbol_date (symbol, date),
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_period (period),
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return await _execute_query_async(query)


def create_balance_sheet_table():
    """Create balance sheet table - permanent storage for filed financial statements."""
    query = """
    CREATE TABLE IF NOT EXISTS balance_sheet (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        period VARCHAR(10),
        calendar_year INT,
        reported_currency VARCHAR(10),
        filling_date DATE,
        accepted_date DATETIME,
        
        -- Assets
        cash_and_cash_equivalents DECIMAL(20,2),
        short_term_investments DECIMAL(20,2),
        cash_and_short_term_investments DECIMAL(20,2),
        net_receivables DECIMAL(20,2),
        inventory DECIMAL(20,2),
        other_current_assets DECIMAL(20,2),
        total_current_assets DECIMAL(20,2),
        property_plant_equipment_net DECIMAL(20,2),
        goodwill DECIMAL(20,2),
        intangible_assets DECIMAL(20,2),
        goodwill_and_intangible_assets DECIMAL(20,2),
        long_term_investments DECIMAL(20,2),
        tax_assets DECIMAL(20,2),
        other_non_current_assets DECIMAL(20,2),
        total_non_current_assets DECIMAL(20,2),
        other_assets DECIMAL(20,2),
        total_assets DECIMAL(20,2),
        
        -- Liabilities
        account_payables DECIMAL(20,2),
        short_term_debt DECIMAL(20,2),
        tax_payables DECIMAL(20,2),
        deferred_revenue DECIMAL(20,2),
        other_current_liabilities DECIMAL(20,2),
        total_current_liabilities DECIMAL(20,2),
        long_term_debt DECIMAL(20,2),
        deferred_revenue_non_current DECIMAL(20,2),
        deferred_tax_liabilities_non_current DECIMAL(20,2),
        other_non_current_liabilities DECIMAL(20,2),
        total_non_current_liabilities DECIMAL(20,2),
        other_liabilities DECIMAL(20,2),
        capital_lease_obligations DECIMAL(20,2),
        total_liabilities DECIMAL(20,2),
        
        -- Equity
        preferred_stock DECIMAL(20,2),
        common_stock DECIMAL(20,2),
        retained_earnings DECIMAL(20,2),
        accumulated_other_comprehensive_income_loss DECIMAL(20,2),
        othertotal_stockholders_equity DECIMAL(20,2),
        total_stockholders_equity DECIMAL(20,2),
        total_liabilities_and_stockholders_equity DECIMAL(20,2),
        minority_interest DECIMAL(20,2),
        total_equity DECIMAL(20,2),
        total_liabilities_and_total_equity DECIMAL(20,2),
        total_investments DECIMAL(20,2),
        total_debt DECIMAL(20,2),
        net_debt DECIMAL(20,2),
        
        -- Metadata for permanent storage (filed statements never change)
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        UNIQUE KEY unique_symbol_date (symbol, date),
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_period (period),
        INDEX idx_calendar_year (calendar_year),
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)


async def create_balance_sheet_table_async():
    """Create flattened balance sheet table (async version)."""
    query = """
    CREATE TABLE IF NOT EXISTS balance_sheet (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        period VARCHAR(10),
        calendar_year INT,
        reported_currency VARCHAR(10),
        filling_date DATE,
        accepted_date DATETIME,
        
        -- Assets
        cash_and_cash_equivalents DECIMAL(20,2),
        short_term_investments DECIMAL(20,2),
        cash_and_short_term_investments DECIMAL(20,2),
        net_receivables DECIMAL(20,2),
        inventory DECIMAL(20,2),
        other_current_assets DECIMAL(20,2),
        total_current_assets DECIMAL(20,2),
        property_plant_equipment_net DECIMAL(20,2),
        goodwill DECIMAL(20,2),
        intangible_assets DECIMAL(20,2),
        goodwill_and_intangible_assets DECIMAL(20,2),
        long_term_investments DECIMAL(20,2),
        tax_assets DECIMAL(20,2),
        other_non_current_assets DECIMAL(20,2),
        total_non_current_assets DECIMAL(20,2),
        other_assets DECIMAL(20,2),
        total_assets DECIMAL(20,2),
        
        -- Liabilities
        account_payables DECIMAL(20,2),
        short_term_debt DECIMAL(20,2),
        tax_payables DECIMAL(20,2),
        deferred_revenue DECIMAL(20,2),
        other_current_liabilities DECIMAL(20,2),
        total_current_liabilities DECIMAL(20,2),
        long_term_debt DECIMAL(20,2),
        deferred_revenue_non_current DECIMAL(20,2),
        deferred_tax_liabilities_non_current DECIMAL(20,2),
        other_non_current_liabilities DECIMAL(20,2),
        total_non_current_liabilities DECIMAL(20,2),
        other_liabilities DECIMAL(20,2),
        capital_lease_obligations DECIMAL(20,2),
        total_liabilities DECIMAL(20,2),
        
        -- Equity
        preferred_stock DECIMAL(20,2),
        common_stock DECIMAL(20,2),
        retained_earnings DECIMAL(20,2),
        accumulated_other_comprehensive_income_loss DECIMAL(20,2),
        othertotal_stockholders_equity DECIMAL(20,2),
        total_stockholders_equity DECIMAL(20,2),
        total_liabilities_and_stockholders_equity DECIMAL(20,2),
        minority_interest DECIMAL(20,2),
        total_equity DECIMAL(20,2),
        total_liabilities_and_total_equity DECIMAL(20,2),
        total_investments DECIMAL(20,2),
        total_debt DECIMAL(20,2),
        net_debt DECIMAL(20,2),
        
        -- Cache metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        is_valid BOOLEAN DEFAULT TRUE,
        
        UNIQUE KEY unique_symbol_date (symbol, date),
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_period (period),
        INDEX idx_calendar_year (calendar_year),
        
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return await _execute_query_async(query)


def create_income_statement_table():
    """Create flattened income statement table (sync version)."""
    query = """
    CREATE TABLE IF NOT EXISTS income_statement (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        period VARCHAR(10),
        calendar_year INT,
        reported_currency VARCHAR(10),
        filling_date DATE,
        accepted_date DATETIME,
        
        -- Revenue and costs
        revenue DECIMAL(20,2),
        cost_of_revenue DECIMAL(20,2),
        gross_profit DECIMAL(20,2),
        gross_profit_ratio DECIMAL(15,6),
        
        -- Operating expenses
        research_and_development_expenses DECIMAL(20,2),
        general_and_administrative_expenses DECIMAL(20,2),
        selling_and_marketing_expenses DECIMAL(20,2),
        selling_general_and_administrative_expenses DECIMAL(20,2),
        other_expenses DECIMAL(20,2),
        operating_expenses DECIMAL(20,2),
        cost_and_expenses DECIMAL(20,2),
        
        -- Other income/expenses
        interest_income DECIMAL(20,2),
        interest_expense DECIMAL(20,2),
        depreciation_and_amortization DECIMAL(20,2),
        
        -- EBITDA and operating income
        ebitda DECIMAL(20,2),
        ebitdaratio DECIMAL(15,6),
        operating_income DECIMAL(20,2),
        operating_income_ratio DECIMAL(15,6),
        total_other_income_expenses_net DECIMAL(20,2),
        
        -- Pre-tax and net income
        income_before_tax DECIMAL(20,2),
        income_before_tax_ratio DECIMAL(15,6),
        income_tax_expense DECIMAL(20,2),
        net_income DECIMAL(20,2),
        net_income_ratio DECIMAL(15,6),
        
        -- Per share data
        eps DECIMAL(15,6),
        epsdiluted DECIMAL(15,6),
        weighted_average_shs_out DECIMAL(20,2),
        weighted_average_shs_out_dil DECIMAL(20,2),
        
        -- Cache metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        is_valid BOOLEAN DEFAULT TRUE,
        
        UNIQUE KEY unique_symbol_date (symbol, date),
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_period (period),
        INDEX idx_calendar_year (calendar_year),
        
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)


async def create_income_statement_table_async():
    """Create flattened income statement table (async version)."""
    query = """
    CREATE TABLE IF NOT EXISTS income_statement (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        period VARCHAR(10),
        calendar_year INT,
        reported_currency VARCHAR(10),
        filling_date DATE,
        accepted_date DATETIME,
        
        -- Revenue and costs
        revenue DECIMAL(20,2),
        cost_of_revenue DECIMAL(20,2),
        gross_profit DECIMAL(20,2),
        gross_profit_ratio DECIMAL(15,6),
        
        -- Operating expenses
        research_and_development_expenses DECIMAL(20,2),
        general_and_administrative_expenses DECIMAL(20,2),
        selling_and_marketing_expenses DECIMAL(20,2),
        selling_general_and_administrative_expenses DECIMAL(20,2),
        other_expenses DECIMAL(20,2),
        operating_expenses DECIMAL(20,2),
        cost_and_expenses DECIMAL(20,2),
        
        -- Other income/expenses
        interest_income DECIMAL(20,2),
        interest_expense DECIMAL(20,2),
        depreciation_and_amortization DECIMAL(20,2),
        
        -- EBITDA and operating income
        ebitda DECIMAL(20,2),
        ebitdaratio DECIMAL(15,6),
        operating_income DECIMAL(20,2),
        operating_income_ratio DECIMAL(15,6),
        total_other_income_expenses_net DECIMAL(20,2),
        
        -- Pre-tax and net income
        income_before_tax DECIMAL(20,2),
        income_before_tax_ratio DECIMAL(15,6),
        income_tax_expense DECIMAL(20,2),
        net_income DECIMAL(20,2),
        net_income_ratio DECIMAL(15,6),
        
        -- Per share data
        eps DECIMAL(15,6),
        epsdiluted DECIMAL(15,6),
        weighted_average_shs_out DECIMAL(20,2),
        weighted_average_shs_out_dil DECIMAL(20,2),
        
        -- Cache metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        is_valid BOOLEAN DEFAULT TRUE,
        
        UNIQUE KEY unique_symbol_date (symbol, date),
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_period (period),
        INDEX idx_calendar_year (calendar_year),
        
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return await _execute_query_async(query)


def create_cash_flow_table():
    """Create flattened cash flow table (sync version)."""
    query = """
    CREATE TABLE IF NOT EXISTS cash_flow (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        period VARCHAR(10),
        calendar_year INT,
        reported_currency VARCHAR(10),
        filling_date DATE,
        accepted_date DATETIME,
        
        -- Operating activities
        net_income DECIMAL(20,2),
        depreciation_and_amortization DECIMAL(20,2),
        deferred_income_tax DECIMAL(20,2),
        stock_based_compensation DECIMAL(20,2),
        change_in_working_capital DECIMAL(20,2),
        accounts_receivables DECIMAL(20,2),
        inventory DECIMAL(20,2),
        accounts_payables DECIMAL(20,2),
        other_working_capital DECIMAL(20,2),
        other_non_cash_items DECIMAL(20,2),
        net_cash_provided_by_operating_activities DECIMAL(20,2),
        
        -- Investing activities
        investments_in_property_plant_and_equipment DECIMAL(20,2),
        acquisitions_net DECIMAL(20,2),
        purchases_of_investments DECIMAL(20,2),
        sales_maturities_of_investments DECIMAL(20,2),
        other_investing_activities DECIMAL(20,2),
        net_cash_used_for_investing_activities DECIMAL(20,2),
        
        -- Financing activities
        debt_repayment DECIMAL(20,2),
        common_stock_issued DECIMAL(20,2),
        common_stock_repurchased DECIMAL(20,2),
        dividends_paid DECIMAL(20,2),
        other_financing_activities DECIMAL(20,2),
        net_cash_used_provided_by_financing_activities DECIMAL(20,2),
        
        -- Cash flow summary
        effect_of_forex_changes_on_cash DECIMAL(20,2),
        net_change_in_cash DECIMAL(20,2),
        cash_at_end_of_period DECIMAL(20,2),
        cash_at_beginning_of_period DECIMAL(20,2),
        operating_cash_flow DECIMAL(20,2),
        capital_expenditure DECIMAL(20,2),
        free_cash_flow DECIMAL(20,2),
        
        -- Cache metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        is_valid BOOLEAN DEFAULT TRUE,
        
        UNIQUE KEY unique_symbol_date (symbol, date),
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_period (period),
        INDEX idx_calendar_year (calendar_year),
        
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)


async def create_cash_flow_table_async():
    """Create flattened cash flow table (async version)."""
    query = """
    CREATE TABLE IF NOT EXISTS cash_flow (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        period VARCHAR(10),
        calendar_year INT,
        reported_currency VARCHAR(10),
        filling_date DATE,
        accepted_date DATETIME,
        
        -- Operating activities
        net_income DECIMAL(20,2),
        depreciation_and_amortization DECIMAL(20,2),
        deferred_income_tax DECIMAL(20,2),
        stock_based_compensation DECIMAL(20,2),
        change_in_working_capital DECIMAL(20,2),
        accounts_receivables DECIMAL(20,2),
        inventory DECIMAL(20,2),
        accounts_payables DECIMAL(20,2),
        other_working_capital DECIMAL(20,2),
        other_non_cash_items DECIMAL(20,2),
        net_cash_provided_by_operating_activities DECIMAL(20,2),
        
        -- Investing activities
        investments_in_property_plant_and_equipment DECIMAL(20,2),
        acquisitions_net DECIMAL(20,2),
        purchases_of_investments DECIMAL(20,2),
        sales_maturities_of_investments DECIMAL(20,2),
        other_investing_activities DECIMAL(20,2),
        net_cash_used_for_investing_activities DECIMAL(20,2),
        
        -- Financing activities
        debt_repayment DECIMAL(20,2),
        common_stock_issued DECIMAL(20,2),
        common_stock_repurchased DECIMAL(20,2),
        dividends_paid DECIMAL(20,2),
        other_financing_activities DECIMAL(20,2),
        net_cash_used_provided_by_financing_activities DECIMAL(20,2),
        
        -- Cash flow summary
        effect_of_forex_changes_on_cash DECIMAL(20,2),
        net_change_in_cash DECIMAL(20,2),
        cash_at_end_of_period DECIMAL(20,2),
        cash_at_beginning_of_period DECIMAL(20,2),
        operating_cash_flow DECIMAL(20,2),
        capital_expenditure DECIMAL(20,2),
        free_cash_flow DECIMAL(20,2),
        
        -- Cache metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        is_valid BOOLEAN DEFAULT TRUE,
        
        UNIQUE KEY unique_symbol_date (symbol, date),
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_period (period),
        INDEX idx_calendar_year (calendar_year),
        
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return await _execute_query_async(query)


# Table creation functions mapping
FLATTENED_TABLES = {
    "equity_historical": {
        "sync": create_equity_historical_table,
        "async": create_equity_historical_table_async
    },
    "equity_profile": {
        "sync": create_equity_profile_table,
        "async": create_equity_profile_table_async
    },
    "financial_ratios": {
        "sync": create_financial_ratios_table,
        "async": create_financial_ratios_table_async
    },
    "balance_sheet": {
        "sync": create_balance_sheet_table,
        "async": create_balance_sheet_table_async
    },
    "income_statement": {
        "sync": create_income_statement_table,
        "async": create_income_statement_table_async
    },
    "cash_flow": {
        "sync": create_cash_flow_table,
        "async": create_cash_flow_table_async
    }
}


def create_all_flattened_tables_sync():
    """Create all flattened cache tables (sync version for Jupyter)."""
    logger.info("Creating flattened cache tables (sync mode)")
    
    for table_name, config in FLATTENED_TABLES.items():
        try:
            config["sync"]()
            logger.info(f"Created/verified flattened table: {table_name}")
        except Exception as e:
            logger.error(f"Failed to create flattened table {table_name}: {e}")
            raise


async def create_all_flattened_tables_async():
    """Create all flattened cache tables (async version)."""
    logger.info("Creating flattened cache tables (async mode)")
    
    for table_name, config in FLATTENED_TABLES.items():
        try:
            await config["async"]()
            logger.info(f"Created/verified flattened table: {table_name}")
        except Exception as e:
            logger.error(f"Failed to create flattened table {table_name}: {e}")
            raise


def create_all_tables_sync():
    """Create all cache tables (sync version for Jupyter)."""
    return create_all_flattened_tables_sync()


async def create_all_tables_async():
    """Create all cache tables (async version)."""
    return await create_all_flattened_tables_async()


async def create_all_tables():
    """Create all cache tables (backward compatibility)."""
    return await create_all_flattened_tables_async()


# Simplified database schema - no TTL or cleanup needed