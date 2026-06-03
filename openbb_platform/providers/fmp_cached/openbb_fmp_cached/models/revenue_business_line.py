"""Cached revenue_business_line model for FMP."""

from openbb_fmp.models.revenue_business_line import FMPRevenueBusinessLineFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP revenue_business_line fetcher
FMPCachedRevenueBusinessLineFetcher = create_cached_fetcher_class(
    FMPRevenueBusinessLineFetcher,
    "revenue_business_line"
)
