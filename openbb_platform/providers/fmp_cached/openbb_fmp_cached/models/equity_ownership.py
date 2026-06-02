"""Cached equity_ownership model for FMP."""

from openbb_fmp.models.equity_ownership import FMPEquityOwnershipFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP equity_ownership fetcher
FMPCachedEquityOwnershipFetcher = create_cached_fetcher_class(
    FMPEquityOwnershipFetcher,
    "equity_ownership"
)
