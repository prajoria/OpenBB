"""Cached crypto_historical model for FMP."""

from openbb_fmp.models.crypto_historical import FMPCryptoHistoricalFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP crypto_historical fetcher
FMPCachedCryptoHistoricalFetcher = create_cached_fetcher_class(
    FMPCryptoHistoricalFetcher,
    "crypto_historical"
)
