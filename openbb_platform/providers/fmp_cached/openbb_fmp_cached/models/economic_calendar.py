"""Cached economic_calendar model for FMP."""

from openbb_fmp.models.economic_calendar import FMPEconomicCalendarFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP economic_calendar fetcher
FMPCachedEconomicCalendarFetcher = create_cached_fetcher_class(
    FMPEconomicCalendarFetcher,
    "economic_calendar"
)
