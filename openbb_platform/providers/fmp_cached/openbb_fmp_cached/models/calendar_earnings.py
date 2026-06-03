"""Cached calendar_earnings model for FMP."""

from openbb_fmp.models.calendar_earnings import FMPCalendarEarningsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP calendar_earnings fetcher
FMPCachedCalendarEarningsFetcher = create_cached_fetcher_class(
    FMPCalendarEarningsFetcher,
    "calendar_earnings"
)
