"""Cached price_performance model for FMP."""

from openbb_fmp.models.price_performance import FMPPricePerformanceFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP price_performance fetcher
FMPCachedPricePerformanceFetcher = create_cached_fetcher_class(
    FMPPricePerformanceFetcher,
    "price_performance"
)
