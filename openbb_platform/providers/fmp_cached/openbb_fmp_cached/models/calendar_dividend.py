"""Cached calendar_dividend model for FMP."""

from openbb_fmp.models.calendar_dividend import FMPCalendarDividendFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP calendar_dividend fetcher
FMPCachedCalendarDividendFetcher = create_cached_fetcher_class(
    FMPCalendarDividendFetcher,
    "calendar_dividend"
)
