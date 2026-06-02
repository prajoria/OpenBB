"""Cached equity_most_active model for FMP."""

from openbb_fmp.models.equity_most_active import FMPEquityActiveFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP equity_most_active fetcher
FMPCachedEquityActiveFetcher = create_cached_fetcher_class(
    FMPEquityActiveFetcher,
    "equity_most_active"
)
