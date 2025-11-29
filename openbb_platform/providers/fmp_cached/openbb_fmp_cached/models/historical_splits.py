"""Cached historical_splits model for FMP."""

from openbb_fmp.models.historical_splits import FMPHistoricalSplitsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP historical_splits fetcher
FMPCachedHistoricalSplitsFetcher = create_cached_fetcher_class(
    FMPHistoricalSplitsFetcher,
    "historical_splits"
)
