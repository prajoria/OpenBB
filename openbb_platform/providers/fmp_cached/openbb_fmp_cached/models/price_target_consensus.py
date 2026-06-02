"""Cached price_target_consensus model for FMP."""

from openbb_fmp.models.price_target_consensus import FMPPriceTargetConsensusFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP price_target_consensus fetcher
FMPCachedPriceTargetConsensusFetcher = create_cached_fetcher_class(
    FMPPriceTargetConsensusFetcher,
    "price_target_consensus"
)
