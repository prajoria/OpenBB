"""Cached price_target model for FMP."""

from openbb_fmp.models.price_target import FMPPriceTargetFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP price_target fetcher
FMPCachedPriceTargetFetcher = create_cached_fetcher_class(
    FMPPriceTargetFetcher,
    "price_target"
)
