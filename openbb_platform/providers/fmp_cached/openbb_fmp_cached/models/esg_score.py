"""Cached esg_score model for FMP."""

from openbb_fmp.models.esg_score import FMPEsgScoreFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP esg_score fetcher
FMPCachedEsgScoreFetcher = create_cached_fetcher_class(
    FMPEsgScoreFetcher,
    "esg_score"
)
