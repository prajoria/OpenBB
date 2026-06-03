"""Cached discovery_filings model for FMP."""

from openbb_fmp.models.discovery_filings import FMPDiscoveryFilingsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP discovery_filings fetcher
FMPCachedDiscoveryFilingsFetcher = create_cached_fetcher_class(
    FMPDiscoveryFilingsFetcher,
    "discovery_filings"
)
