"""Cached key_executives model for FMP."""

from openbb_fmp.models.key_executives import FMPKeyExecutivesFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP key_executives fetcher
FMPCachedKeyExecutivesFetcher = create_cached_fetcher_class(
    FMPKeyExecutivesFetcher,
    "key_executives"
)
