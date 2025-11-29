"""Cached equity_quote model for FMP."""

from openbb_fmp.models.equity_quote import FMPEquityQuoteFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP equity_quote fetcher
FMPCachedEquityQuoteFetcher = create_cached_fetcher_class(
    FMPEquityQuoteFetcher,
    "equity_quote"
)
