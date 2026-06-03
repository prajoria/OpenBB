"""Cached calendar_ipo model for FMP."""

from openbb_fmp.models.calendar_ipo import FMPCalendarIpoFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP calendar_ipo fetcher
FMPCachedCalendarIpoFetcher = create_cached_fetcher_class(
    FMPCalendarIpoFetcher,
    "calendar_ipo"
)
