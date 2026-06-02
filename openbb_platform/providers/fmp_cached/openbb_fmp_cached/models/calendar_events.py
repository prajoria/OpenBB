"""Cached calendar_events model for FMP."""

from openbb_fmp.models.calendar_events import FMPCalendarEventsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP calendar_events fetcher
FMPCachedCalendarEventsFetcher = create_cached_fetcher_class(
    FMPCalendarEventsFetcher,
    "calendar_events"
)
