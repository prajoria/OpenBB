#!/usr/bin/env python3
"""Script to create all missing cached model files."""

import os
from pathlib import Path

# Define all FMP models that need cached versions
fmp_models = [
    "calendar_events", "calendar_ipo", "calendar_splits", "cash_flow", "cash_flow_growth",
    "company_filings", "company_news", "crypto_historical", "crypto_search", "currency_historical", 
    "currency_pairs", "currency_snapshots", "discovery_filings", "earnings_call_transcript",
    "economic_calendar", "equity_gainers", "equity_losers", "equity_most_active", "equity_ownership",
    "equity_peers", "equity_profile", "equity_screener", "esg_score", "etf_countries",
    "etf_equity_exposure", "etf_holdings", "etf_info", "etf_search", "etf_sectors",
    "executive_compensation", "financial_ratios", "forward_ebitda_estimates", "forward_eps_estimates",
    "government_trades", "historical_dividends", "historical_employees", "historical_eps",
    "historical_market_cap", "historical_splits", "income_statement", "income_statement_growth",
    "index_constituents", "index_historical", "insider_trading", "institutional_ownership",
    "key_executives", "key_metrics", "market_snapshots", "nport_disclosure", "price_performance",
    "price_target", "price_target_consensus", "revenue_business_line", "revenue_geographic",
    "risk_premium", "share_statistics", "treasury_rates", "world_news", "yield_curve"
]

def snake_to_pascal(snake_str):
    """Convert snake_case to PascalCase."""
    components = snake_str.split('_')
    return ''.join(word.capitalize() for word in components)

def create_cached_model_file(model_name):
    """Create cached model file for given FMP model."""
    class_name = snake_to_pascal(model_name)
    
    content = f'''"""Cached {model_name} model for FMP."""

from openbb_fmp.models.{model_name} import FMP{class_name}Fetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP {model_name} fetcher
FMPCached{class_name}Fetcher = create_cached_fetcher_class(
    FMP{class_name}Fetcher,
    "{class_name}"
)
'''
    
    file_path = Path(f"{model_name}.py")
    with open(file_path, 'w') as f:
        f.write(content)
    
    print(f"Created {file_path}")

if __name__ == "__main__":
    # Change to models directory
    models_dir = Path("/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/models")
    os.chdir(models_dir)
    
    # Check which files already exist
    existing_files = set(f.stem for f in models_dir.glob("*.py") if f.name != "__init__.py" and f.name != "base_cached.py")
    
    created_count = 0
    for model in fmp_models:
        if model not in existing_files:
            create_cached_model_file(model)
            created_count += 1
        else:
            print(f"Skipped {model}.py (already exists)")
    
    print(f"\nCreated {created_count} new cached model files")
    print(f"Total FMP models: {len(fmp_models)}")