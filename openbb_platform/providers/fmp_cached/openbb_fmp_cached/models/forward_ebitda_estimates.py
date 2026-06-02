"""Cached forward_ebitda_estimates model for FMP."""

from openbb_fmp.models.forward_ebitda_estimates import FMPForwardEbitdaEstimatesFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP forward_ebitda_estimates fetcher
FMPCachedForwardEbitdaEstimatesFetcher = create_cached_fetcher_class(
    FMPForwardEbitdaEstimatesFetcher,
    "forward_ebitda_estimates"
)
