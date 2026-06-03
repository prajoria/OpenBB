"""Cached calendar_splits model for FMP."""

from openbb_fmp.models.calendar_splits import FMPCalendarSplitsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP calendar_splits fetcher
FMPCachedCalendarSplitsFetcher = create_cached_fetcher_class(
    FMPCalendarSplitsFetcher,
    "calendar_splits"
)
