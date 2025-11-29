"""Cached income_statement model for FMP."""

from openbb_fmp.models.income_statement import FMPIncomeStatementFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP income_statement fetcher
FMPCachedIncomeStatementFetcher = create_cached_fetcher_class(
    FMPIncomeStatementFetcher,
    "income_statement"
)
