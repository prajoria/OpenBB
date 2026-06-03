"""Cached historical_dividends model for FMP."""

from openbb_fmp.models.historical_dividends import FMPHistoricalDividendsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP historical_dividends fetcher
FMPCachedHistoricalDividendsFetcher = create_cached_fetcher_class(
    FMPHistoricalDividendsFetcher,
    "historical_dividends"
)
