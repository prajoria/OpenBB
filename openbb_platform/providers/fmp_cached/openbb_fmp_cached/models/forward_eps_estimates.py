"""Cached forward_eps_estimates model for FMP."""

from openbb_fmp.models.forward_eps_estimates import FMPForwardEpsEstimatesFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP forward_eps_estimates fetcher
FMPCachedForwardEpsEstimatesFetcher = create_cached_fetcher_class(
    FMPForwardEpsEstimatesFetcher,
    "forward_eps_estimates"
)
