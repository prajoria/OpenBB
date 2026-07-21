"""FMP Cached Provider for OpenBB Platform."""

# The apikey-scrub install block below MUST run before any fetcher
# import so log filters are in place before any HTTP call fires.
# That pushes the fetcher imports below module-level statements —
# suppress the wrong-import-position warning for the whole file.
# pylint: disable=wrong-import-position,ungrouped-imports

import logging as _logging

from openbb_core.provider.abstract.provider import Provider

# Install the apikey-scrub log filter as early as possible so any log
# record emitted by this package (or urllib3, requests, aiohttp, etc.)
# is scrubbed of ``apikey=<value>`` before it hits any handler.
# See openbb_fmp_cached.utils.security (#963) for details.
from openbb_fmp_cached.utils.security import (
    _wrap_root_addHandler_with_scrub,
    install_apikey_scrub_filter,
    install_apikey_scrub_filter_on_root_handlers,
)

# Per-logger installs — catch records emitted BY these loggers directly.
install_apikey_scrub_filter()
install_apikey_scrub_filter(_logging.getLogger("openbb_fmp"))
install_apikey_scrub_filter(_logging.getLogger("urllib3"))
install_apikey_scrub_filter(_logging.getLogger("requests"))
install_apikey_scrub_filter(_logging.getLogger("httpx"))
install_apikey_scrub_filter(_logging.getLogger("aiohttp"))

# Root-handler install — catches records that propagate up from any
# child logger (this is where urllib3.connectionpool DEBUG logs land
# when caplog / pytest --log-cli / logging.basicConfig is configured).
# Python filter semantics: filters on a LOGGER don't run on records
# propagated from a child; only handlers' filters do. See
# install_apikey_scrub_filter_on_root_handlers docstring for details.
install_apikey_scrub_filter_on_root_handlers()
_wrap_root_addHandler_with_scrub()

# Import original FMP fetchers
from openbb_fmp.models.aftermarket_trade import FMPAftermarketTradeFetcher
from openbb_fmp.models.available_indices import FMPAvailableIndicesFetcher
from openbb_fmp.models.balance_sheet_growth import FMPBalanceSheetGrowthFetcher
from openbb_fmp.models.calendar_dividend import FMPCalendarDividendFetcher
from openbb_fmp.models.calendar_earnings import FMPCalendarEarningsFetcher
from openbb_fmp.models.calendar_events import FMPCalendarEventsFetcher
from openbb_fmp.models.calendar_ipo import FMPCalendarIpoFetcher
from openbb_fmp.models.calendar_splits import FMPCalendarSplitsFetcher
from openbb_fmp.models.cash_flow_growth import FMPCashFlowStatementGrowthFetcher
from openbb_fmp.models.company_filings import FMPCompanyFilingsFetcher
from openbb_fmp.models.company_news import FMPCompanyNewsFetcher
from openbb_fmp.models.crypto_historical import FMPCryptoHistoricalFetcher
from openbb_fmp.models.crypto_search import FMPCryptoSearchFetcher
from openbb_fmp.models.currency_historical import FMPCurrencyHistoricalFetcher
from openbb_fmp.models.currency_pairs import FMPCurrencyPairsFetcher
from openbb_fmp.models.currency_snapshots import FMPCurrencySnapshotsFetcher
from openbb_fmp.models.discovery_filings import FMPDiscoveryFilingsFetcher
from openbb_fmp.models.earnings_call_transcript import FMPEarningsCallTranscriptFetcher
from openbb_fmp.models.economic_calendar import FMPEconomicCalendarFetcher
from openbb_fmp.models.equity_gainers import FMPGainersFetcher
from openbb_fmp.models.equity_losers import FMPLosersFetcher
from openbb_fmp.models.equity_most_active import FMPEquityActiveFetcher
from openbb_fmp.models.equity_ownership import FMPEquityOwnershipFetcher
from openbb_fmp.models.equity_quote_batch_short import (
    FMPEquityQuoteBatchShortFetcher,
)
from openbb_fmp.models.equity_screener import FMPEquityScreenerFetcher
from openbb_fmp.models.esg_score import FMPEsgScoreFetcher
from openbb_fmp.models.etf_countries import FMPEtfCountriesFetcher
from openbb_fmp.models.etf_equity_exposure import FMPEtfEquityExposureFetcher
from openbb_fmp.models.etf_holdings import FMPEtfHoldingsFetcher
from openbb_fmp.models.etf_info import FMPEtfInfoFetcher
from openbb_fmp.models.etf_search import FMPEtfSearchFetcher
from openbb_fmp.models.etf_sectors import FMPEtfSectorsFetcher
from openbb_fmp.models.executive_compensation import FMPExecutiveCompensationFetcher
from openbb_fmp.models.forward_ebitda_estimates import FMPForwardEbitdaEstimatesFetcher
from openbb_fmp.models.forward_eps_estimates import FMPForwardEpsEstimatesFetcher
from openbb_fmp.models.government_trades import FMPGovernmentTradesFetcher
from openbb_fmp.models.historical_dividends import FMPHistoricalDividendsFetcher
from openbb_fmp.models.historical_employees import FMPHistoricalEmployeesFetcher
from openbb_fmp.models.historical_eps import FMPHistoricalEpsFetcher
from openbb_fmp.models.historical_market_cap import FmpHistoricalMarketCapFetcher
from openbb_fmp.models.historical_splits import FMPHistoricalSplitsFetcher
from openbb_fmp.models.income_statement_growth import FMPIncomeStatementGrowthFetcher
from openbb_fmp.models.index_historical import FMPIndexHistoricalFetcher
from openbb_fmp.models.insider_trading import FMPInsiderTradingFetcher
from openbb_fmp.models.key_executives import FMPKeyExecutivesFetcher
from openbb_fmp.models.market_snapshots import FMPMarketSnapshotsFetcher
from openbb_fmp.models.nport_disclosure import FMPNportDisclosureFetcher
from openbb_fmp.models.price_performance import FMPPricePerformanceFetcher
from openbb_fmp.models.price_target import FMPPriceTargetFetcher
from openbb_fmp.models.price_target_consensus import FMPPriceTargetConsensusFetcher
from openbb_fmp.models.revenue_business_line import FMPRevenueBusinessLineFetcher
from openbb_fmp.models.revenue_geographic import FMPRevenueGeographicFetcher
from openbb_fmp.models.risk_premium import FMPRiskPremiumFetcher
from openbb_fmp.models.share_statistics import FMPShareStatisticsFetcher
from openbb_fmp.models.technical_indicator_intraday import (
    FMPTechnicalIndicatorIntradayFetcher,
)
from openbb_fmp.models.treasury_rates import FMPTreasuryRatesFetcher
from openbb_fmp.models.world_news import FMPWorldNewsFetcher
from openbb_fmp.models.yield_curve import FMPYieldCurveFetcher

from openbb_fmp_cached.models.aftermarket_quote import (
    FMPCachedAftermarketQuoteFetcher,
)

# Import independent cached fetchers (with database persistence)
from openbb_fmp_cached.models.analyst_estimates import FMPCachedAnalystEstimatesFetcher
from openbb_fmp_cached.models.balance_sheet import FMPCachedBalanceSheetFetcher

# Import cached wrapper utility
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class
from openbb_fmp_cached.models.cash_flow import FMPCachedCashFlowStatementFetcher
from openbb_fmp_cached.models.equity_historical import FMPCachedEquityHistoricalFetcher
from openbb_fmp_cached.models.equity_intraday_historical import (
    FMPCachedEquityIntradayHistoricalFetcher,
)
from openbb_fmp_cached.models.equity_peers import FMPCachedEquityPeersFetcher
from openbb_fmp_cached.models.equity_profile import FMPCachedEquityProfileFetcher
from openbb_fmp_cached.models.equity_quote import FMPCachedEquityQuoteFetcher
from openbb_fmp_cached.models.etf_holdings import FMPCachedEtfHoldingsFetcher
from openbb_fmp_cached.models.exchange_market_hours import (
    FMPCachedExchangeMarketHoursFetcher,
)
from openbb_fmp_cached.models.financial_ratios import FMPCachedFinancialRatiosFetcher
from openbb_fmp_cached.models.income_statement import FMPCachedIncomeStatementFetcher
from openbb_fmp_cached.models.index_constituents import (
    FMPCachedIndexConstituentsFetcher,
)
from openbb_fmp_cached.models.institutional_ownership import (
    FMPCachedInstitutionalOwnershipFetcher,
)
from openbb_fmp_cached.models.key_metrics import FMPCachedKeyMetricsFetcher


# Create cached versions of all FMP fetchers
def create_all_cached_fetchers():
    """Create cached versions of all FMP fetcher classes."""
    # Fetchers with dedicated database persistence (use directly, no wrapping)
    dedicated_fetchers = {
        "AftermarketQuote": FMPCachedAftermarketQuoteFetcher,
        "AnalystEstimates": FMPCachedAnalystEstimatesFetcher,
        "EquityHistorical": FMPCachedEquityHistoricalFetcher,
        "EquityInfo": FMPCachedEquityProfileFetcher,
        "EquityIntradayHistorical": FMPCachedEquityIntradayHistoricalFetcher,
        "EquityPeers": FMPCachedEquityPeersFetcher,
        "EquityQuote": FMPCachedEquityQuoteFetcher,
        "EtfHistorical": FMPCachedEquityHistoricalFetcher,
        "EtfHoldings": FMPCachedEtfHoldingsFetcher,
        "ExchangeMarketHours": FMPCachedExchangeMarketHoursFetcher,
        "FinancialRatios": FMPCachedFinancialRatiosFetcher,
        "IndexConstituents": FMPCachedIndexConstituentsFetcher,
        "IncomeStatement": FMPCachedIncomeStatementFetcher,
        "InstitutionalOwnership": FMPCachedInstitutionalOwnershipFetcher,
        "KeyMetrics": FMPCachedKeyMetricsFetcher,
        "BalanceSheet": FMPCachedBalanceSheetFetcher,
        "CashFlowStatement": FMPCachedCashFlowStatementFetcher,
    }

    # Fetchers that need fallback wrapping
    fetcher_mapping = [
        ("AvailableIndices", FMPAvailableIndicesFetcher),
        ("BalanceSheetGrowth", FMPBalanceSheetGrowthFetcher),
        ("CalendarDividend", FMPCalendarDividendFetcher),
        ("CalendarEarnings", FMPCalendarEarningsFetcher),
        ("CalendarEvents", FMPCalendarEventsFetcher),
        ("CalendarIpo", FMPCalendarIpoFetcher),
        ("CalendarSplits", FMPCalendarSplitsFetcher),
        ("CashFlowStatementGrowth", FMPCashFlowStatementGrowthFetcher),
        ("CompanyFilings", FMPCompanyFilingsFetcher),
        ("CompanyNews", FMPCompanyNewsFetcher),
        ("CryptoHistorical", FMPCryptoHistoricalFetcher),
        ("CryptoSearch", FMPCryptoSearchFetcher),
        ("CurrencyHistorical", FMPCurrencyHistoricalFetcher),
        ("CurrencyPairs", FMPCurrencyPairsFetcher),
        ("CurrencySnapshots", FMPCurrencySnapshotsFetcher),
        ("DiscoveryFilings", FMPDiscoveryFilingsFetcher),
        ("EarningsCallTranscript", FMPEarningsCallTranscriptFetcher),
        ("EconomicCalendar", FMPEconomicCalendarFetcher),
        ("EquityActive", FMPEquityActiveFetcher),
        ("EquityOwnership", FMPEquityOwnershipFetcher),
        ("EquityGainers", FMPGainersFetcher),
        ("EquityLosers", FMPLosersFetcher),
        ("EquityScreener", FMPEquityScreenerFetcher),
        ("EsgScore", FMPEsgScoreFetcher),
        ("EtfCountries", FMPEtfCountriesFetcher),
        ("EtfEquityExposure", FMPEtfEquityExposureFetcher),
        ("EtfInfo", FMPEtfInfoFetcher),
        ("EtfPricePerformance", FMPPricePerformanceFetcher),
        ("EtfSearch", FMPEtfSearchFetcher),
        ("EtfSectors", FMPEtfSectorsFetcher),
        ("ExecutiveCompensation", FMPExecutiveCompensationFetcher),
        ("ForwardEbitdaEstimates", FMPForwardEbitdaEstimatesFetcher),
        ("ForwardEpsEstimates", FMPForwardEpsEstimatesFetcher),
        ("HistoricalDividends", FMPHistoricalDividendsFetcher),
        ("HistoricalEmployees", FMPHistoricalEmployeesFetcher),
        ("HistoricalEps", FMPHistoricalEpsFetcher),
        ("HistoricalMarketCap", FmpHistoricalMarketCapFetcher),
        ("HistoricalSplits", FMPHistoricalSplitsFetcher),
        ("IncomeStatementGrowth", FMPIncomeStatementGrowthFetcher),
        ("IndexHistorical", FMPIndexHistoricalFetcher),
        ("InsiderTrading", FMPInsiderTradingFetcher),
        ("KeyExecutives", FMPKeyExecutivesFetcher),
        ("MarketSnapshots", FMPMarketSnapshotsFetcher),
        ("NportDisclosure", FMPNportDisclosureFetcher),
        ("PricePerformance", FMPPricePerformanceFetcher),
        ("PriceTarget", FMPPriceTargetFetcher),
        ("PriceTargetConsensus", FMPPriceTargetConsensusFetcher),
        ("RevenueBusinessLine", FMPRevenueBusinessLineFetcher),
        ("RevenueGeographic", FMPRevenueGeographicFetcher),
        ("RiskPremium", FMPRiskPremiumFetcher),
        ("ShareStatistics", FMPShareStatisticsFetcher),
        ("TreasuryRates", FMPTreasuryRatesFetcher),
        ("WorldNews", FMPWorldNewsFetcher),
        ("YieldCurve", FMPYieldCurveFetcher),
        # Phase-0 intraday fetchers (fmp-day-trading PRD 2026-07-06 §5.1).
        # NOTE (P2.1): AftermarketQuote + EquityIntradayHistorical promoted
        # to tier-1 dedicated_fetchers above.
        # NOTE (P2.2): ExchangeMarketHours also promoted to tier-1 with
        # a 24h TTL via create_ttl_wrapper_class (see models/
        # exchange_market_hours.py). The two entries kept here remain tier-2
        # passthrough forever per PRD §5.1 (batch-short IS the cheap poll
        # primitive so caching would defeat the point; indicators are rarely
        # used).
        ("AftermarketTrade", FMPAftermarketTradeFetcher),
        ("EquityQuoteBatchShort", FMPEquityQuoteBatchShortFetcher),
        ("TechnicalIndicatorIntraday", FMPTechnicalIndicatorIntradayFetcher),
        ("GovernmentTrades", FMPGovernmentTradesFetcher),
    ]

    # Start with dedicated fetchers (no wrapping)
    cached_fetchers = dedicated_fetchers.copy()

    # Add fallback-wrapped fetchers
    for endpoint_name, original_fetcher in fetcher_mapping:
        cached_fetchers[endpoint_name] = create_cached_fetcher_class(
            original_fetcher, endpoint_name
        )

    return cached_fetchers


# Create all cached fetchers
_cached_fetchers = create_all_cached_fetchers()

# Define the FMP Cached provider
fmp_cached_provider = Provider(
    name="fmp_cached",
    website="https://financialmodelingprep.com",
    description="""Financial Modeling Prep provider with MySQL caching support.
This provider wraps the standard FMP provider and adds intelligent caching
to reduce API calls and improve performance. All data is cached in a MySQL
database with configurable TTL settings.""",
    credentials=["api_key"],  # Same as FMP - generic api_key name
    fetcher_dict=_cached_fetchers,
    repr_name="Financial Modeling Prep (Cached)",
    deprecated_credentials={
        "API_KEY_FINANCIALMODELINGPREP": "fmp_api_key"
    },  # Map to user setting
    instructions="""Configure your FMP API key and MySQL database connection:

1. Get FMP API Key from: https://site.financialmodelingprep.com/developer/docs
2. Set up MySQL database and add connection details to ~/.openbb_platform/user_settings.json:

{
    "credentials": {
        "fmp_api_key": "your_fmp_api_key_here",
        "mysql_host": "localhost",
        "mysql_port": 3306,
        "mysql_user": "openbb_user", 
        "mysql_password": "your_password",
        "mysql_database": "openbb_cache"
    }
}

The provider will automatically create the cache database and tables on first use.""",
)
