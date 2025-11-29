"""Cached key_metrics model for FMP."""

from openbb_fmp.models.key_metrics import FMPKeyMetricsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP key_metrics fetcher
FMPCachedKeyMetricsFetcher = create_cached_fetcher_class(
    FMPKeyMetricsFetcher,
    "key_metrics"
)
