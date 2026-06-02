"""Cached equity_losers model for FMP."""

from openbb_fmp.models.equity_losers import FMPLosersFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP equity_losers fetcher
FMPCachedLosersFetcher = create_cached_fetcher_class(
    FMPLosersFetcher,
    "equity_losers"
)
