"""Cached yield_curve model for FMP."""

from openbb_fmp.models.yield_curve import FMPYieldCurveFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP yield_curve fetcher
FMPCachedYieldCurveFetcher = create_cached_fetcher_class(
    FMPYieldCurveFetcher,
    "yield_curve"
)
