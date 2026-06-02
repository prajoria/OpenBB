"""Cached available_indices model for FMP."""

from openbb_fmp.models.available_indices import FMPAvailableIndicesFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP available_indices fetcher
FMPCachedAvailableIndicesFetcher = create_cached_fetcher_class(
    FMPAvailableIndicesFetcher,
    "available_indices"
)
