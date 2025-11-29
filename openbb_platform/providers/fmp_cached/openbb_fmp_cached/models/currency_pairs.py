"""Cached currency_pairs model for FMP."""

from openbb_fmp.models.currency_pairs import FMPCurrencyPairsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP currency_pairs fetcher
FMPCachedCurrencyPairsFetcher = create_cached_fetcher_class(
    FMPCurrencyPairsFetcher,
    "currency_pairs"
)
