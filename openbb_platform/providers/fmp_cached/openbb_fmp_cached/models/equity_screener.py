"""Cached equity_screener model for FMP."""

from openbb_fmp.models.equity_screener import FMPEquityScreenerFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP equity_screener fetcher
FMPCachedEquityScreenerFetcher = create_cached_fetcher_class(
    FMPEquityScreenerFetcher,
    "equity_screener"
)
