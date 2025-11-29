"""
Simplified Database Schema for FMP Cached Provider

Simple database-backed response persistence without TTL/caching complexity.
Each table maps directly to OpenBB model fields for efficient DataFrame conversion.
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


def create_equity_historical_table():
    """Create equity historical table for immutable historical data."""
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
        
        -- Simple metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        UNIQUE KEY unique_symbol_date (symbol, date),
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)


def create_equity_profile_table():
    """Create equity profile table for company information."""
    query = """
    CREATE TABLE IF NOT EXISTS equity_profile (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL UNIQUE,
        company_name VARCHAR(255),
        sector VARCHAR(100),
        industry VARCHAR(100),
        country VARCHAR(100),
        market_cap BIGINT,
        price DECIMAL(15,4),
        beta DECIMAL(8,6),
        vol_avg BIGINT,
        mkt_cap BIGINT,
        last_div DECIMAL(8,4),
        range_price VARCHAR(50),
        changes DECIMAL(15,4),
        description TEXT,
        ceo VARCHAR(255),
        employees INT,
        website VARCHAR(255),
        exchange VARCHAR(50),
        exchange_short_name VARCHAR(20),
        currency VARCHAR(10),
        is_etf BOOLEAN DEFAULT FALSE,
        is_fund BOOLEAN DEFAULT FALSE,
        is_actively_trading BOOLEAN DEFAULT TRUE,
        
        -- Simple metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        INDEX idx_symbol (symbol),
        INDEX idx_sector (sector),
        INDEX idx_industry (industry),
        INDEX idx_is_valid (is_valid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    return _execute_query_env_aware(query)


def create_financial_ratios_table():
    """Create financial ratios table for ratio analysis."""
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
        days_sales_outstanding DECIMAL(15,6),
        days_inventory_outstanding DECIMAL(15,6),
        operating_cycle DECIMAL(15,6),
        days_payables_outstanding DECIMAL(15,6),
        cash_conversion_cycle DECIMAL(15,6),
        
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
        cash_coverage DECIMAL(15,6),
        
        -- Efficiency ratios
        company_equity_multiplier DECIMAL(15,6),
        receivables_turnover DECIMAL(15,6),
        payables_turnover DECIMAL(15,6),
        inventory_turnover DECIMAL(15,6),
        fixed_asset_turnover DECIMAL(15,6),
        asset_turnover DECIMAL(15,6),
        
        -- Market ratios
        price_earnings_ratio DECIMAL(15,6),
        price_to_book_ratio DECIMAL(15,6),
        price_to_sales_ratio DECIMAL(15,6),
        price_earnings_to_growth_ratio DECIMAL(15,6),
        price_to_free_cash_flows_ratio DECIMAL(15,6),
        price_to_operating_cash_flows_ratio DECIMAL(15,6),
        price_cash_flow_ratio DECIMAL(15,6),
        price_book_value_ratio DECIMAL(15,6),
        price_to_sales_ratio_ttm DECIMAL(15,6),
        price_fair_value DECIMAL(15,6),
        dividend_yield DECIMAL(15,6),
        
        -- Enterprise value ratios  
        enterprise_value_multiple DECIMAL(15,6),
        price_sales_ratio DECIMAL(15,6),
        ptb_ratio DECIMAL(15,6),
        ev_to_sales DECIMAL(15,6),
        enterprise_value_over_ebitda DECIMAL(15,6),
        ev_to_operating_cash_flow DECIMAL(15,6),
        ev_to_free_cash_flow DECIMAL(15,6),
        earnings_yield DECIMAL(15,6),
        free_cash_flow_yield DECIMAL(15,6),
        debt_to_equity DECIMAL(15,6),
        debt_to_assets DECIMAL(15,6),
        net_debt_to_ebitda DECIMAL(15,6),
        current_ratio_ttm DECIMAL(15,6),
        operating_cash_flow_per_share DECIMAL(15,6),
        free_cash_flow_per_share DECIMAL(15,6),
        cash_per_share DECIMAL(15,6),
        book_value_per_share DECIMAL(15,6),
        operating_cash_flow_sales_ratio DECIMAL(15,6),
        free_cash_flow_operating_cash_flow_ratio DECIMAL(15,6),
        
        -- Simple metadata
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


def create_balance_sheet_table():
    """Create balance sheet table for financial statements."""
    query = """
    CREATE TABLE IF NOT EXISTS balance_sheet (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        period VARCHAR(10),
        reported_currency VARCHAR(10),
        cik VARCHAR(20),
        filling_date DATE,
        accepted_date DATETIME,
        calendar_year INT,
        
        -- Assets
        cash_and_cash_equivalents BIGINT,
        short_term_investments BIGINT,
        cash_and_short_term_investments BIGINT,
        net_receivables BIGINT,
        inventory BIGINT,
        other_current_assets BIGINT,
        total_current_assets BIGINT,
        property_plant_equipment_net BIGINT,
        goodwill BIGINT,
        intangible_assets BIGINT,
        goodwill_and_intangible_assets BIGINT,
        long_term_investments BIGINT,
        tax_assets BIGINT,
        other_non_current_assets BIGINT,
        total_non_current_assets BIGINT,
        other_assets BIGINT,
        total_assets BIGINT,
        
        -- Liabilities
        account_payables BIGINT,
        short_term_debt BIGINT,
        tax_payables BIGINT,
        deferred_revenue BIGINT,
        other_current_liabilities BIGINT,
        total_current_liabilities BIGINT,
        long_term_debt BIGINT,
        deferred_revenue_non_current BIGINT,
        deferred_tax_liabilities_non_current BIGINT,
        other_non_current_liabilities BIGINT,
        total_non_current_liabilities BIGINT,
        other_liabilities BIGINT,
        capital_lease_obligations BIGINT,
        total_liabilities BIGINT,
        
        -- Equity
        preferred_stock BIGINT,
        common_stock BIGINT,
        retained_earnings BIGINT,
        accumulated_other_comprehensive_income_loss BIGINT,
        othertotal_stockholders_equity BIGINT,
        total_stockholders_equity BIGINT,
        total_equity BIGINT,
        total_liabilities_and_stockholders_equity BIGINT,
        minority_interest BIGINT,
        total_liabilities_and_total_equity BIGINT,
        total_investments BIGINT,
        total_debt BIGINT,
        net_debt BIGINT,
        
        -- Simple metadata
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


def create_income_statement_table():
    """Create income statement table for financial statements."""
    query = """
    CREATE TABLE IF NOT EXISTS income_statement (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        period VARCHAR(10),
        reported_currency VARCHAR(10),
        cik VARCHAR(20),
        filling_date DATE,
        accepted_date DATETIME,
        calendar_year INT,
        
        -- Revenue and costs
        revenue BIGINT,
        cost_of_revenue BIGINT,
        gross_profit BIGINT,
        gross_profit_ratio DECIMAL(15,6),
        
        -- Operating expenses
        research_and_development_expenses BIGINT,
        general_and_administrative_expenses BIGINT,
        selling_and_marketing_expenses BIGINT,
        selling_general_and_administrative_expenses BIGINT,
        other_expenses BIGINT,
        operating_expenses BIGINT,
        cost_and_expenses BIGINT,
        
        -- Operating income
        interest_income BIGINT,
        interest_expense BIGINT,
        depreciation_and_amortization BIGINT,
        ebitda BIGINT,
        ebitdaratio DECIMAL(15,6),
        operating_income BIGINT,
        operating_income_ratio DECIMAL(15,6),
        total_other_income_expenses_net BIGINT,
        
        -- Pre-tax and taxes
        income_before_tax BIGINT,
        income_before_tax_ratio DECIMAL(15,6),
        income_tax_expense BIGINT,
        
        -- Net income
        net_income BIGINT,
        net_income_ratio DECIMAL(15,6),
        
        -- Per share data
        eps DECIMAL(15,6),
        epsdiluted DECIMAL(15,6),
        weighted_average_shs_out BIGINT,
        weighted_average_shs_out_dil BIGINT,
        
        -- Simple metadata
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


def create_cash_flow_table():
    """Create cash flow table for financial statements."""
    query = """
    CREATE TABLE IF NOT EXISTS cash_flow (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        period VARCHAR(10),
        reported_currency VARCHAR(10),
        cik VARCHAR(20),
        filling_date DATE,
        accepted_date DATETIME,
        calendar_year INT,
        
        -- Operating activities
        net_income BIGINT,
        depreciation_and_amortization BIGINT,
        deferred_income_tax BIGINT,
        stock_based_compensation BIGINT,
        change_in_working_capital BIGINT,
        accounts_receivables BIGINT,
        inventory BIGINT,
        accounts_payables BIGINT,
        other_working_capital BIGINT,
        other_non_cash_items BIGINT,
        net_cash_provided_by_operating_activities BIGINT,
        
        -- Investing activities
        investments_in_property_plant_and_equipment BIGINT,
        acquisitions_net BIGINT,
        purchases_of_investments BIGINT,
        sales_maturities_of_investments BIGINT,
        other_investing_activities BIGINT,
        net_cash_used_for_investing_activities BIGINT,
        
        -- Financing activities
        debt_repayment BIGINT,
        common_stock_issued BIGINT,
        common_stock_repurchased BIGINT,
        dividends_paid BIGINT,
        other_financing_activities BIGINT,
        net_cash_used_provided_by_financing_activities BIGINT,
        
        -- Summary
        effect_of_forex_changes_on_cash BIGINT,
        net_change_in_cash BIGINT,
        cash_at_end_of_period BIGINT,
        cash_at_beginning_of_period BIGINT,
        operating_cash_flow BIGINT,
        capital_expenditure BIGINT,
        free_cash_flow BIGINT,
        
        -- Simple metadata
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


# Simple table configuration - no async duplicates
FLATTENED_TABLES = {
    "equity_historical": {
        "schema": create_equity_historical_table
    },
    "equity_profile": {
        "schema": create_equity_profile_table
    },
    "financial_ratios": {
        "schema": create_financial_ratios_table
    },
    "balance_sheet": {
        "schema": create_balance_sheet_table
    },
    "income_statement": {
        "schema": create_income_statement_table
    },
    "cash_flow": {
        "schema": create_cash_flow_table
    }
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