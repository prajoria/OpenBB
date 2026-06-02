"""Cached currency_historical model for FMP."""

from openbb_fmp.models.currency_historical import FMPCurrencyHistoricalFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP currency_historical fetcher
FMPCachedCurrencyHistoricalFetcher = create_cached_fetcher_class(
    FMPCurrencyHistoricalFetcher,
    "currency_historical"
)
