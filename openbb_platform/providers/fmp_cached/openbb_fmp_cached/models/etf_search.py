"""Cached etf_search model for FMP."""

from openbb_fmp.models.etf_search import FMPEtfSearchFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP etf_search fetcher
FMPCachedEtfSearchFetcher = create_cached_fetcher_class(
    FMPEtfSearchFetcher,
    "etf_search"
)
