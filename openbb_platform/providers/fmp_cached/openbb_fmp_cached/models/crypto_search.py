"""Cached crypto_search model for FMP."""

from openbb_fmp.models.crypto_search import FMPCryptoSearchFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP crypto_search fetcher
FMPCachedCryptoSearchFetcher = create_cached_fetcher_class(
    FMPCryptoSearchFetcher,
    "crypto_search"
)
