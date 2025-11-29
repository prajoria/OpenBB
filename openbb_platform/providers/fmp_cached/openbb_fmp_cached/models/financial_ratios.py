"""Cached financial_ratios model for FMP."""

from openbb_fmp.models.financial_ratios import FMPFinancialRatiosFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP financial_ratios fetcher
FMPCachedFinancialRatiosFetcher = create_cached_fetcher_class(
    FMPFinancialRatiosFetcher,
    "financial_ratios"
)
