"""Cached nport_disclosure model for FMP."""

from openbb_fmp.models.nport_disclosure import FMPNportDisclosureFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP nport_disclosure fetcher
FMPCachedNportDisclosureFetcher = create_cached_fetcher_class(
    FMPNportDisclosureFetcher,
    "nport_disclosure"
)
