"""Cached equity_peers model for FMP."""

from openbb_fmp.models.equity_peers import FMPEquityPeersFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP equity_peers fetcher
FMPCachedEquityPeersFetcher = create_cached_fetcher_class(
    FMPEquityPeersFetcher,
    "equity_peers"
)
