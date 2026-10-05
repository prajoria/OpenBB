"""Complete FMP Cached persistence evidence contract."""

import json
from pathlib import Path

from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.models.aftermarket_quote import _TTL_SECONDS
from openbb_fmp_cached.utils.plan_limited import _PLAN_LIMITED

_ASSETS = Path(__file__).parents[1] / "openbb_fmp_cached" / "assets"
_HIGH_DEMAND = {
    "CompanyNews",
    "EconomicCalendar",
    "EquityGainers",
    "EquityLosers",
    "EquityScreener",
    "GovernmentTrades",
    "HistoricalDividends",
    "HistoricalMarketCap",
    "HistoricalSplits",
    "InsiderTrading",
    "PriceTarget",
    "PriceTargetConsensus",
    "RevenueBusinessLine",
    "RevenueGeographic",
    "TreasuryRates",
    "WorldNews",
    "YieldCurve",
}
_ENTITLEMENT_BLOCKED = {
    "CryptoSearch",
    "CurrencySnapshots",
    "EarningsCallTranscript",
    "EquityActive",
    "EquityOwnership",
    "EsgScore",
    "EtfEquityExposure",
    "EtfPricePerformance",
    "MarketSnapshots",
}
_BACKLOG = {
    "AftermarketTrade",
    "AvailableIndices",
    "BalanceSheetGrowth",
    "CalendarDividend",
    "CalendarEarnings",
    "CalendarEvents",
    "CalendarIpo",
    "CalendarSplits",
    "CashFlowStatementGrowth",
    "CompanyFilings",
    "CryptoHistorical",
    "CurrencyHistorical",
    "CurrencyPairs",
    "DiscoveryFilings",
    "EquityQuoteBatchShort",
    "EtfCountries",
    "EtfInfo",
    "EtfSearch",
    "EtfSectors",
    "ExecutiveCompensation",
    "ForwardEbitdaEstimates",
    "ForwardEpsEstimates",
    "HistoricalEmployees",
    "HistoricalEps",
    "IncomeStatementGrowth",
    "IndexHistorical",
    "KeyExecutives",
    "NportDisclosure",
    "PricePerformance",
    "RiskPremium",
    "ShareStatistics",
    "TechnicalIndicatorIntraday",
}


def _fallbacks() -> set[str]:
    return {
        model
        for model, fetcher in fmp_cached_provider.fetcher_dict.items()
        if fetcher.__module__ == "openbb_fmp_cached.models.base_cached"
        and fetcher.__name__.startswith("Fallback")
    }


def test_every_registration_has_explicit_persistence_evidence():
    """The 181-model denominator splits exactly into dedicated and fallback."""
    registered = set(fmp_cached_provider.fetcher_dict)
    descriptor = json.loads(
        (_ASSETS / "persistence_descriptors.json").read_text(encoding="utf-8")
    )
    fallbacks = _fallbacks()
    assert len(registered) == 181
    assert len(fallbacks) == 58
    assert set(descriptor["non_persistent_fallbacks"]) == fallbacks
    assert len(registered - fallbacks) == 123


def test_conversion_priorities_cover_every_fallback_without_claiming_cache():
    """Demand and entitlement rank future work without fabricating persistence."""
    fallbacks = _fallbacks()
    assert set(_PLAN_LIMITED) >= _ENTITLEMENT_BLOCKED
    assert fallbacks == _HIGH_DEMAND | _ENTITLEMENT_BLOCKED | _BACKLOG
    assert _HIGH_DEMAND.isdisjoint(_ENTITLEMENT_BLOCKED)
    assert _HIGH_DEMAND.isdisjoint(_BACKLOG)
    assert _ENTITLEMENT_BLOCKED.isdisjoint(_BACKLOG)


def test_ttl_semantics_are_independent_from_persistence_classification():
    """A dedicated table can still enforce a short model-specific freshness TTL."""
    assert "AftermarketQuote" not in _fallbacks()
    assert _TTL_SECONDS == 60
