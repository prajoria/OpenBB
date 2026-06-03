"""Cached cash_flow_growth model for FMP."""

from openbb_fmp.models.cash_flow_growth import FMPCashFlowStatementGrowthFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP cash_flow_growth fetcher
FMPCachedCashFlowStatementGrowthFetcher = create_cached_fetcher_class(
    FMPCashFlowStatementGrowthFetcher,
    "cash_flow_growth"
)
