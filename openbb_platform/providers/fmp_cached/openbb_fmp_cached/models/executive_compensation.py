"""Cached executive_compensation model for FMP."""

from openbb_fmp.models.executive_compensation import FMPExecutiveCompensationFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP executive_compensation fetcher
FMPCachedExecutiveCompensationFetcher = create_cached_fetcher_class(
    FMPExecutiveCompensationFetcher,
    "executive_compensation"
)
