"""Cached government_trades model for FMP."""

from openbb_fmp.models.government_trades import FMPGovernmentTradesFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP government_trades fetcher
FMPCachedGovernmentTradesFetcher = create_cached_fetcher_class(
    FMPGovernmentTradesFetcher,
    "government_trades"
)
