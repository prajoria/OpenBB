"""Cached risk_premium model for FMP."""

from openbb_fmp.models.risk_premium import FMPRiskPremiumFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP risk_premium fetcher
FMPCachedRiskPremiumFetcher = create_cached_fetcher_class(
    FMPRiskPremiumFetcher,
    "risk_premium"
)
