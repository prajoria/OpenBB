"""Cached index_constituents model for FMP."""

from openbb_fmp.models.index_constituents import FMPIndexConstituentsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP index_constituents fetcher
FMPCachedIndexConstituentsFetcher = create_cached_fetcher_class(
    FMPIndexConstituentsFetcher,
    "index_constituents"
)
