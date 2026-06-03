"""Cached historical_eps model for FMP."""

from openbb_fmp.models.historical_eps import FMPHistoricalEpsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP historical_eps fetcher
FMPCachedHistoricalEpsFetcher = create_cached_fetcher_class(
    FMPHistoricalEpsFetcher,
    "historical_eps"
)
