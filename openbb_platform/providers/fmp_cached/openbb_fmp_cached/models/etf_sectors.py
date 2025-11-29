"""Cached etf_sectors model for FMP."""

from openbb_fmp.models.etf_sectors import FMPEtfSectorsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP etf_sectors fetcher
FMPCachedEtfSectorsFetcher = create_cached_fetcher_class(
    FMPEtfSectorsFetcher,
    "etf_sectors"
)
