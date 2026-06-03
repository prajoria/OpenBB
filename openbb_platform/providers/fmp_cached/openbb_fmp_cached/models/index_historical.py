"""Cached index_historical model for FMP."""

from openbb_fmp.models.index_historical import FMPIndexHistoricalFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP index_historical fetcher
FMPCachedIndexHistoricalFetcher = create_cached_fetcher_class(
    FMPIndexHistoricalFetcher,
    "index_historical"
)
