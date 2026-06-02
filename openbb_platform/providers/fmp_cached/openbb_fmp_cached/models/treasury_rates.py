"""Cached treasury_rates model for FMP."""

from openbb_fmp.models.treasury_rates import FMPTreasuryRatesFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP treasury_rates fetcher
FMPCachedTreasuryRatesFetcher = create_cached_fetcher_class(
    FMPTreasuryRatesFetcher,
    "treasury_rates"
)
