"""Cached market_snapshots model for FMP."""

from openbb_fmp.models.market_snapshots import FMPMarketSnapshotsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP market_snapshots fetcher
FMPCachedMarketSnapshotsFetcher = create_cached_fetcher_class(
    FMPMarketSnapshotsFetcher,
    "market_snapshots"
)
