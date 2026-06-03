"""Cached world_news model for FMP."""

from openbb_fmp.models.world_news import FMPWorldNewsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP world_news fetcher
FMPCachedWorldNewsFetcher = create_cached_fetcher_class(
    FMPWorldNewsFetcher,
    "world_news"
)
