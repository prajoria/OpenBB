"""Cached balance_sheet model for FMP."""

from openbb_fmp.models.balance_sheet import FMPBalanceSheetFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP balance_sheet fetcher
FMPCachedBalanceSheetFetcher = create_cached_fetcher_class(
    FMPBalanceSheetFetcher,
    "balance_sheet"
)
