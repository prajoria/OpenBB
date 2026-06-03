"""Cached etf_equity_exposure model for FMP."""

from openbb_fmp.models.etf_equity_exposure import FMPEtfEquityExposureFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP etf_equity_exposure fetcher
FMPCachedEtfEquityExposureFetcher = create_cached_fetcher_class(
    FMPEtfEquityExposureFetcher,
    "etf_equity_exposure"
)
