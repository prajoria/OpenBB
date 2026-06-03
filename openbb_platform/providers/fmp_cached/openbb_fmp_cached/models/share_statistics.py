"""Cached share_statistics model for FMP."""

from openbb_fmp.models.share_statistics import FMPShareStatisticsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP share_statistics fetcher
FMPCachedShareStatisticsFetcher = create_cached_fetcher_class(
    FMPShareStatisticsFetcher,
    "share_statistics"
)
