"""Cached balance_sheet_growth model for FMP."""

from openbb_fmp.models.balance_sheet_growth import FMPBalanceSheetGrowthFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP balance_sheet_growth fetcher
FMPCachedBalanceSheetGrowthFetcher = create_cached_fetcher_class(
    FMPBalanceSheetGrowthFetcher,
    "balance_sheet_growth"
)
