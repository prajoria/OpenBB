"""Cached revenue_geographic model for FMP."""

from openbb_fmp.models.revenue_geographic import FMPRevenueGeographicFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP revenue_geographic fetcher
FMPCachedRevenueGeographicFetcher = create_cached_fetcher_class(
    FMPRevenueGeographicFetcher,
    "revenue_geographic"
)
