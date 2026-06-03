"""Cached equity_gainers model for FMP."""

from openbb_fmp.models.equity_gainers import FMPGainersFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP equity_gainers fetcher
FMPCachedGainersFetcher = create_cached_fetcher_class(
    FMPGainersFetcher,
    "equity_gainers"
)
