"""Cached currency_snapshots model for FMP."""

from openbb_fmp.models.currency_snapshots import FMPCurrencySnapshotsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP currency_snapshots fetcher
FMPCachedCurrencySnapshotsFetcher = create_cached_fetcher_class(
    FMPCurrencySnapshotsFetcher,
    "currency_snapshots"
)
