"""Cached etf_info model for FMP."""

from openbb_fmp.models.etf_info import FMPEtfInfoFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP etf_info fetcher
FMPCachedEtfInfoFetcher = create_cached_fetcher_class(
    FMPEtfInfoFetcher,
    "etf_info"
)
