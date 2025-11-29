"""Cached institutional_ownership model for FMP."""

from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP institutional_ownership fetcher
FMPCachedInstitutionalOwnershipFetcher = create_cached_fetcher_class(
    FMPInstitutionalOwnershipFetcher,
    "institutional_ownership"
)
