"""Cached insider_trading model for FMP."""

from openbb_fmp.models.insider_trading import FMPInsiderTradingFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP insider_trading fetcher
FMPCachedInsiderTradingFetcher = create_cached_fetcher_class(
    FMPInsiderTradingFetcher,
    "insider_trading"
)
