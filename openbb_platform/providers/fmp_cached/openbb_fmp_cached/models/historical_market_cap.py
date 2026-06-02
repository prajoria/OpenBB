"""Cached historical_market_cap model for FMP."""

from openbb_fmp.models.historical_market_cap import FmpHistoricalMarketCapFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP historical_market_cap fetcher
FMPCachedHistoricalMarketCapFetcher = create_cached_fetcher_class(
    FmpHistoricalMarketCapFetcher,
    "historical_market_cap"
)
