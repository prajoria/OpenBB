"""Cached historical_employees model for FMP."""

from openbb_fmp.models.historical_employees import FMPHistoricalEmployeesFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP historical_employees fetcher
FMPCachedHistoricalEmployeesFetcher = create_cached_fetcher_class(
    FMPHistoricalEmployeesFetcher,
    "historical_employees"
)
