"""Cached cash_flow model for FMP."""

from openbb_fmp.models.cash_flow import FMPCashFlowStatementFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP cash_flow fetcher
FMPCachedCashFlowStatementFetcher = create_cached_fetcher_class(
    FMPCashFlowStatementFetcher,
    "cash_flow"
)
