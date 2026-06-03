"""Cached etf_countries model for FMP."""

from openbb_fmp.models.etf_countries import FMPEtfCountriesFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP etf_countries fetcher
FMPCachedEtfCountriesFetcher = create_cached_fetcher_class(
    FMPEtfCountriesFetcher,
    "etf_countries"
)
