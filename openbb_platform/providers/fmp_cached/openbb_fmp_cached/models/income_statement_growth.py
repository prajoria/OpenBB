"""Cached income_statement_growth model for FMP."""

from openbb_fmp.models.income_statement_growth import FMPIncomeStatementGrowthFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP income_statement_growth fetcher
FMPCachedIncomeStatementGrowthFetcher = create_cached_fetcher_class(
    FMPIncomeStatementGrowthFetcher,
    "income_statement_growth"
)
