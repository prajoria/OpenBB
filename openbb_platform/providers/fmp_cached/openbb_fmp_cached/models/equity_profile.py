"""Cached equity_profile model for FMP."""

from openbb_fmp.models.equity_profile import FMPEquityProfileFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP equity_profile fetcher
FMPCachedEquityProfileFetcher = create_cached_fetcher_class(
    FMPEquityProfileFetcher,
    "equity_profile"
)
