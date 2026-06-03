"""Cached etf_holdings model for FMP."""

from openbb_fmp.models.etf_holdings import FMPEtfHoldingsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP etf_holdings fetcher
FMPCachedEtfHoldingsFetcher = create_cached_fetcher_class(
    FMPEtfHoldingsFetcher,
    "etf_holdings"
)
