"""FMP Provider Modules."""

from openbb_core.provider.abstract.provider import Provider
from openbb_fmp.models.aftermarket_quote import FMPAftermarketQuoteFetcher
from openbb_fmp.models.aftermarket_trade import FMPAftermarketTradeFetcher
from openbb_fmp.models.analyst_estimates import FMPAnalystEstimatesFetcher
from openbb_fmp.models.analyst_ratings import (
    FMPGradesConsensusFetcher,
    FMPGradesFetcher,
    FMPGradesHistoricalFetcher,
    FMPPriceTargetSummaryFetcher,
    FMPRatingsHistoricalFetcher,
    FMPRatingsSnapshotFetcher,
)
from openbb_fmp.models.available_indices import FMPAvailableIndicesFetcher
from openbb_fmp.models.balance_sheet import FMPBalanceSheetFetcher
from openbb_fmp.models.balance_sheet_growth import FMPBalanceSheetGrowthFetcher
from openbb_fmp.models.calendar_dividend import FMPCalendarDividendFetcher
from openbb_fmp.models.calendar_earnings import FMPCalendarEarningsFetcher
from openbb_fmp.models.calendar_events import FMPCalendarEventsFetcher
from openbb_fmp.models.calendar_ipo import FMPCalendarIpoFetcher
from openbb_fmp.models.calendar_splits import FMPCalendarSplitsFetcher
from openbb_fmp.models.cash_flow import FMPCashFlowStatementFetcher
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
from openbb_fmp.models.equity_historical import FMPEquityHistoricalFetcher
from openbb_fmp.models.equity_intraday_historical import (
    FMPEquityIntradayHistoricalFetcher,
)
from openbb_fmp.models.equity_losers import FMPLosersFetcher
from openbb_fmp.models.equity_most_active import FMPEquityActiveFetcher
from openbb_fmp.models.equity_ownership import FMPEquityOwnershipFetcher
from openbb_fmp.models.equity_peers import FMPEquityPeersFetcher
from openbb_fmp.models.equity_profile import FMPEquityProfileFetcher
from openbb_fmp.models.equity_quote import FMPEquityQuoteFetcher
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
from openbb_fmp.models.exchange_market_hours import FMPExchangeMarketHoursFetcher
from openbb_fmp.models.executive_compensation import FMPExecutiveCompensationFetcher
from openbb_fmp.models.financial_ratios import FMPFinancialRatiosFetcher
from openbb_fmp.models.forward_ebitda_estimates import FMPForwardEbitdaEstimatesFetcher
from openbb_fmp.models.forward_eps_estimates import FMPForwardEpsEstimatesFetcher
from openbb_fmp.models.government_trades import FMPGovernmentTradesFetcher
from openbb_fmp.models.historical_dividends import FMPHistoricalDividendsFetcher
from openbb_fmp.models.historical_employees import FMPHistoricalEmployeesFetcher
from openbb_fmp.models.historical_eps import FMPHistoricalEpsFetcher
from openbb_fmp.models.historical_market_cap import FmpHistoricalMarketCapFetcher
from openbb_fmp.models.historical_splits import FMPHistoricalSplitsFetcher
from openbb_fmp.models.income_statement import FMPIncomeStatementFetcher
from openbb_fmp.models.income_statement_growth import FMPIncomeStatementGrowthFetcher
from openbb_fmp.models.index_constituents import FMPIndexConstituentsFetcher
from openbb_fmp.models.index_historical import FMPIndexHistoricalFetcher
from openbb_fmp.models.indexes_extras import (
    FMPDowjonesConstituentFetcher,
    FMPHistoricalDowjonesConstituentFetcher,
    FMPHistoricalIndustryPeFetcher,
    FMPHistoricalIndustryPerformanceFetcher,
    FMPHistoricalNasdaqConstituentFetcher,
    FMPHistoricalSectorPeFetcher,
    FMPHistoricalSectorPerformanceFetcher,
    FMPHistoricalSp500ConstituentFetcher,
    FMPIndustryPeSnapshotFetcher,
    FMPIndustryPerformanceSnapshotFetcher,
    FMPNasdaqConstituentFetcher,
    FMPSectorPeSnapshotFetcher,
    FMPSectorPerformanceSnapshotFetcher,
    FMPSp500ConstituentFetcher,
)
from openbb_fmp.models.insider_trading import FMPInsiderTradingFetcher
from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipFetcher
from openbb_fmp.models.key_executives import FMPKeyExecutivesFetcher
from openbb_fmp.models.key_metrics import FMPKeyMetricsFetcher
from openbb_fmp.models.market_snapshots import FMPMarketSnapshotsFetcher
from openbb_fmp.models.nport_disclosure import FMPNportDisclosureFetcher
from openbb_fmp.models.price_performance import FMPPricePerformanceFetcher
from openbb_fmp.models.price_target import FMPPriceTargetFetcher
from openbb_fmp.models.price_target_consensus import FMPPriceTargetConsensusFetcher
from openbb_fmp.models.quotes_extras import (
    FMPBatchAftermarketQuoteFetcher,
    FMPBatchAftermarketTradeFetcher,
    FMPBatchQuoteFetcher,
    FMPBatchQuoteShortFetcher,
    FMPMarketCapBatchFetcher,
    FMPMarketCapFetcher,
    FMPStockPriceChangeFetcher,
    FMPStockQuoteFetcher,
    FMPStockQuoteShortFetcher,
)
from openbb_fmp.models.revenue_business_line import FMPRevenueBusinessLineFetcher
from openbb_fmp.models.revenue_geographic import FMPRevenueGeographicFetcher
from openbb_fmp.models.risk_premium import FMPRiskPremiumFetcher
from openbb_fmp.models.share_statistics import FMPShareStatisticsFetcher
from openbb_fmp.models.available_lists_extras import (
    FMPAvailableExchangesFetcher,
    FMPAvailableIndustriesFetcher,
    FMPAvailableSectorsFetcher,
)
from openbb_fmp.models.market_hours_search_extras import (
    FMPAllExchangeMarketHoursFetcher,
    FMPAvailableCountriesFetcher,
    FMPCikListFetcher,
    FMPFinancialStatementSymbolListFetcher,
    FMPHolidaysByExchangeFetcher,
    FMPProfileCikFetcher,
    FMPSearchCikFetcher,
    FMPSearchCusipFetcher,
    FMPSearchExchangeVariantsFetcher,
    FMPSearchIsinFetcher,
    FMPSearchNameFetcher,
    FMPSearchSymbolFetcher,
    FMPSymbolChangeFetcher,
)
from openbb_fmp.models.dcf_reference_extras import (
    FMPActivelyTradingListFetcher,
    FMPCommoditiesListFetcher,
    FMPCryptocurrencyListFetcher,
    FMPCustomDiscountedCashFlowFetcher,
    FMPCustomLeveredDiscountedCashFlowFetcher,
    FMPDiscountedCashFlowFetcher,
    FMPEtfListFetcher,
    FMPForexListFetcher,
    FMPIndexListFetcher,
    FMPLeveredDiscountedCashFlowFetcher,
    FMPStockListFetcher,
)
from openbb_fmp.models.government_extras import (
    FMPHouseLatestFetcher,
    FMPSenateLatestFetcher,
    FMPSenateNetWorthAggregatedFetcher,
    FMPSenateNetWorthFetcher,
    FMPSenatePositionsFetcher,
    FMPSenateProfileFetcher,
)
from openbb_fmp.models.sec_extras import (
    FMPAllIndustryClassificationFetcher,
    FMPIndustryClassificationSearchFetcher,
    FMPSecFilings8kFetcher,
    FMPSecProfileFetcher,
    FMPStandardIndustrialClassificationListFetcher,
)
from openbb_fmp.models.news_extras import (
    FMPFmpArticlesFetcher,
    FMPNewsCryptoFetcher,
    FMPNewsCryptoLatestFetcher,
    FMPNewsForexFetcher,
    FMPNewsForexLatestFetcher,
)
from openbb_fmp.models.fundraising_extras import (
    FMPCrowdfundingOfferingsFetcher,
    FMPCrowdfundingOfferingsLatestFetcher,
    FMPCrowdfundingOfferingsSearchFetcher,
    FMPFundraisingFetcher,
    FMPFundraisingLatestFetcher,
    FMPFundraisingSearchFetcher,
    FMPIposDisclosureFetcher,
    FMPIposProspectusFetcher,
    FMPMergersAcquisitionsLatestFetcher,
    FMPMergersAcquisitionsSearchFetcher,
)
from openbb_fmp.models.economics_extras import (
    FMPCommitmentOfTradersAnalysisFetcher,
    FMPCommitmentOfTradersListFetcher,
    FMPCommitmentOfTradersReportFetcher,
    FMPEconomicIndicatorsFetcher,
    FMPMarketRiskPremiumFetcher,
)
from openbb_fmp.models.statements_extras import (
    FMPBalanceSheetStatementAsReportedFetcher,
    FMPCashFlowStatementAsReportedFetcher,
    FMPEnterpriseValuesFetcher,
    FMPFinancialGrowthFetcher,
    FMPFinancialReportsDatesFetcher,
    FMPFinancialReportsJsonFetcher,
    FMPFinancialScoresFetcher,
    FMPFinancialStatementFullAsReportedFetcher,
    FMPIncomeStatementAsReportedFetcher,
    FMPKeyMetricsTtmFetcher,
    FMPOwnerEarningsFetcher,
    FMPRatiosTtmFetcher,
)
from openbb_fmp.models.technical_indicator_intraday import (
    FMPTechnicalIndicatorIntradayFetcher,
)
from openbb_fmp.models.treasury_rates import FMPTreasuryRatesFetcher
from openbb_fmp.models.world_news import FMPWorldNewsFetcher
from openbb_fmp.models.yield_curve import FMPYieldCurveFetcher

fmp_provider = Provider(
    name="fmp",
    website="https://financialmodelingprep.com",
    description="""Financial Modeling Prep is a new concept that informs you about
stock market information (news, currencies, and stock prices).""",
    credentials=["api_key"],
    fetcher_dict={
        "AftermarketQuote": FMPAftermarketQuoteFetcher,
        "AftermarketTrade": FMPAftermarketTradeFetcher,
        "AnalystEstimates": FMPAnalystEstimatesFetcher,
        # Analyst / Ratings / Grades — Tier-A parity port from fmp_cached
        # (#1482-#1487). See openbb_fmp.models.analyst_ratings for
        # design notes; #1481 (AnalystRecommendations) is deferred
        # because FMP retired /stable/analyst-stock-recommendations.
        "Grades": FMPGradesFetcher,
        "GradesConsensus": FMPGradesConsensusFetcher,
        "GradesHistorical": FMPGradesHistoricalFetcher,
        "PriceTargetSummary": FMPPriceTargetSummaryFetcher,
        "RatingsHistorical": FMPRatingsHistoricalFetcher,
        "RatingsSnapshot": FMPRatingsSnapshotFetcher,
        "AvailableIndices": FMPAvailableIndicesFetcher,
        "BalanceSheet": FMPBalanceSheetFetcher,
        "BalanceSheetGrowth": FMPBalanceSheetGrowthFetcher,
        "CalendarDividend": FMPCalendarDividendFetcher,
        "CalendarEarnings": FMPCalendarEarningsFetcher,
        "CalendarEvents": FMPCalendarEventsFetcher,
        "CalendarIpo": FMPCalendarIpoFetcher,
        "CalendarSplits": FMPCalendarSplitsFetcher,
        "CashFlowStatement": FMPCashFlowStatementFetcher,
        "CashFlowStatementGrowth": FMPCashFlowStatementGrowthFetcher,
        "CompanyFilings": FMPCompanyFilingsFetcher,
        "CompanyNews": FMPCompanyNewsFetcher,
        "CryptoHistorical": FMPCryptoHistoricalFetcher,
        "CryptoSearch": FMPCryptoSearchFetcher,
        "CurrencyHistorical": FMPCurrencyHistoricalFetcher,
        "CurrencyPairs": FMPCurrencyPairsFetcher,
        "CurrencySnapshots": FMPCurrencySnapshotsFetcher,
        "DiscoveryFilings": FMPDiscoveryFilingsFetcher,
        "EarningsCallTranscript": FMPEarningsCallTranscriptFetcher,
        "EconomicCalendar": FMPEconomicCalendarFetcher,
        "EquityActive": FMPEquityActiveFetcher,
        "EquityHistorical": FMPEquityHistoricalFetcher,
        "EquityIntradayHistorical": FMPEquityIntradayHistoricalFetcher,
        "EquityOwnership": FMPEquityOwnershipFetcher,
        "EquityPeers": FMPEquityPeersFetcher,
        "EquityInfo": FMPEquityProfileFetcher,
        "EquityGainers": FMPGainersFetcher,
        "EquityLosers": FMPLosersFetcher,
        "EquityQuote": FMPEquityQuoteFetcher,
        "EquityQuoteBatchShort": FMPEquityQuoteBatchShortFetcher,
        "EquityScreener": FMPEquityScreenerFetcher,
        "EsgScore": FMPEsgScoreFetcher,
        "EtfCountries": FMPEtfCountriesFetcher,
        "EtfEquityExposure": FMPEtfEquityExposureFetcher,
        "EtfHoldings": FMPEtfHoldingsFetcher,
        "EtfInfo": FMPEtfInfoFetcher,
        "EtfPricePerformance": FMPPricePerformanceFetcher,
        "EtfSearch": FMPEtfSearchFetcher,
        "EtfSectors": FMPEtfSectorsFetcher,
        "ExchangeMarketHours": FMPExchangeMarketHoursFetcher,
        "ExecutiveCompensation": FMPExecutiveCompensationFetcher,
        "FinancialRatios": FMPFinancialRatiosFetcher,
        "ForwardEbitdaEstimates": FMPForwardEbitdaEstimatesFetcher,
        "ForwardEpsEstimates": FMPForwardEpsEstimatesFetcher,
        "HistoricalDividends": FMPHistoricalDividendsFetcher,
        "HistoricalEmployees": FMPHistoricalEmployeesFetcher,
        "HistoricalEps": FMPHistoricalEpsFetcher,
        "HistoricalMarketCap": FmpHistoricalMarketCapFetcher,
        "HistoricalSplits": FMPHistoricalSplitsFetcher,
        "IncomeStatement": FMPIncomeStatementFetcher,
        "IncomeStatementGrowth": FMPIncomeStatementGrowthFetcher,
        "IndexConstituents": FMPIndexConstituentsFetcher,
        "IndexHistorical": FMPIndexHistoricalFetcher,
        "InsiderTrading": FMPInsiderTradingFetcher,
        "InstitutionalOwnership": FMPInstitutionalOwnershipFetcher,
        "KeyExecutives": FMPKeyExecutivesFetcher,
        "KeyMetrics": FMPKeyMetricsFetcher,
        "MarketSnapshots": FMPMarketSnapshotsFetcher,
        "NportDisclosure": FMPNportDisclosureFetcher,
        "PricePerformance": FMPPricePerformanceFetcher,
        "PriceTarget": FMPPriceTargetFetcher,
        "PriceTargetConsensus": FMPPriceTargetConsensusFetcher,
        "RevenueBusinessLine": FMPRevenueBusinessLineFetcher,
        "RevenueGeographic": FMPRevenueGeographicFetcher,
        "RiskPremium": FMPRiskPremiumFetcher,
        "ShareStatistics": FMPShareStatisticsFetcher,
        # Statements-extras — Tier-A parity port (#1488-#1499). See
        # openbb_fmp.models.statements_extras for design notes.
        "EnterpriseValues": FMPEnterpriseValuesFetcher,
        "FinancialGrowth": FMPFinancialGrowthFetcher,
        "FinancialScores": FMPFinancialScoresFetcher,
        "KeyMetricsTtm": FMPKeyMetricsTtmFetcher,
        "OwnerEarnings": FMPOwnerEarningsFetcher,
        "RatiosTtm": FMPRatiosTtmFetcher,
        "IncomeStatementAsReported": FMPIncomeStatementAsReportedFetcher,
        "BalanceSheetStatementAsReported": FMPBalanceSheetStatementAsReportedFetcher,
        "CashFlowStatementAsReported": FMPCashFlowStatementAsReportedFetcher,
        "FinancialStatementFullAsReported": FMPFinancialStatementFullAsReportedFetcher,
        "FinancialReportsDates": FMPFinancialReportsDatesFetcher,
        "FinancialReportsJson": FMPFinancialReportsJsonFetcher,
        # Quotes-extras — Tier-A parity port (#1506-#1514).
        "BatchQuote": FMPBatchQuoteFetcher,
        "BatchQuoteShort": FMPBatchQuoteShortFetcher,
        "BatchAftermarketQuote": FMPBatchAftermarketQuoteFetcher,
        "BatchAftermarketTrade": FMPBatchAftermarketTradeFetcher,
        "StockQuote": FMPStockQuoteFetcher,
        "StockQuoteShort": FMPStockQuoteShortFetcher,
        "StockPriceChange": FMPStockPriceChangeFetcher,
        "MarketCap": FMPMarketCapFetcher,
        "MarketCapBatch": FMPMarketCapBatchFetcher,
        # Indexes-extras — Tier-A parity port (#1515-#1528).
        "DowjonesConstituent": FMPDowjonesConstituentFetcher,
        "HistoricalDowjonesConstituent": FMPHistoricalDowjonesConstituentFetcher,
        "Sp500Constituent": FMPSp500ConstituentFetcher,
        "HistoricalSp500Constituent": FMPHistoricalSp500ConstituentFetcher,
        "NasdaqConstituent": FMPNasdaqConstituentFetcher,
        "HistoricalNasdaqConstituent": FMPHistoricalNasdaqConstituentFetcher,
        "SectorPerformanceSnapshot": FMPSectorPerformanceSnapshotFetcher,
        "HistoricalSectorPerformance": FMPHistoricalSectorPerformanceFetcher,
        "SectorPeSnapshot": FMPSectorPeSnapshotFetcher,
        "HistoricalSectorPe": FMPHistoricalSectorPeFetcher,
        "IndustryPerformanceSnapshot": FMPIndustryPerformanceSnapshotFetcher,
        "HistoricalIndustryPerformance": FMPHistoricalIndustryPerformanceFetcher,
        "IndustryPeSnapshot": FMPIndustryPeSnapshotFetcher,
        "HistoricalIndustryPe": FMPHistoricalIndustryPeFetcher,
        # Economics-extras — Tier-A parity port (#1529-#1533).
        "EconomicIndicators": FMPEconomicIndicatorsFetcher,
        "MarketRiskPremium": FMPMarketRiskPremiumFetcher,
        "CommitmentOfTradersAnalysis": FMPCommitmentOfTradersAnalysisFetcher,
        "CommitmentOfTradersList": FMPCommitmentOfTradersListFetcher,
        "CommitmentOfTradersReport": FMPCommitmentOfTradersReportFetcher,
        # Fundraising-extras — Tier-A parity port (#1534-#1543).
        "Fundraising": FMPFundraisingFetcher,
        "FundraisingLatest": FMPFundraisingLatestFetcher,
        "FundraisingSearch": FMPFundraisingSearchFetcher,
        "CrowdfundingOfferings": FMPCrowdfundingOfferingsFetcher,
        "CrowdfundingOfferingsLatest": FMPCrowdfundingOfferingsLatestFetcher,
        "CrowdfundingOfferingsSearch": FMPCrowdfundingOfferingsSearchFetcher,
        "MergersAcquisitionsLatest": FMPMergersAcquisitionsLatestFetcher,
        "MergersAcquisitionsSearch": FMPMergersAcquisitionsSearchFetcher,
        "IposDisclosure": FMPIposDisclosureFetcher,
        "IposProspectus": FMPIposProspectusFetcher,
        # News-extras — Tier-A parity port (#1544-#1548).
        "NewsCrypto": FMPNewsCryptoFetcher,
        "NewsCryptoLatest": FMPNewsCryptoLatestFetcher,
        "NewsForex": FMPNewsForexFetcher,
        "NewsForexLatest": FMPNewsForexLatestFetcher,
        "FmpArticles": FMPFmpArticlesFetcher,
        # SEC-extras — Tier-A parity port (#1549-#1553).
        "SecFilings8K": FMPSecFilings8kFetcher,
        "SecProfile": FMPSecProfileFetcher,
        "StandardIndustrialClassificationList": FMPStandardIndustrialClassificationListFetcher,
        "AllIndustryClassification": FMPAllIndustryClassificationFetcher,
        "IndustryClassificationSearch": FMPIndustryClassificationSearchFetcher,
        # Government-extras — Tier-A parity port (#1554-#1559).
        "HouseLatest": FMPHouseLatestFetcher,
        "SenateLatest": FMPSenateLatestFetcher,
        "SenateNetWorth": FMPSenateNetWorthFetcher,
        "SenateNetWorthAggregated": FMPSenateNetWorthAggregatedFetcher,
        "SenatePositions": FMPSenatePositionsFetcher,
        "SenateProfile": FMPSenateProfileFetcher,
        # DCF-extras — Tier-A parity port (#1560-#1563).
        "DiscountedCashFlow": FMPDiscountedCashFlowFetcher,
        "LeveredDiscountedCashFlow": FMPLeveredDiscountedCashFlowFetcher,
        "CustomDiscountedCashFlow": FMPCustomDiscountedCashFlowFetcher,
        "CustomLeveredDiscountedCashFlow": FMPCustomLeveredDiscountedCashFlowFetcher,
        # Reference-list extras — Tier-A parity port (#1564-#1570).
        "StockList": FMPStockListFetcher,
        "EtfList": FMPEtfListFetcher,
        "IndexList": FMPIndexListFetcher,
        "CommoditiesList": FMPCommoditiesListFetcher,
        "ForexList": FMPForexListFetcher,
        "CryptocurrencyList": FMPCryptocurrencyListFetcher,
        "ActivelyTradingList": FMPActivelyTradingListFetcher,
        # Market-hours + Search extras — Tier-A parity port (#1571-#1572, #1467-#1477).
        "AllExchangeMarketHours": FMPAllExchangeMarketHoursFetcher,
        "HolidaysByExchange": FMPHolidaysByExchangeFetcher,
        "SearchSymbol": FMPSearchSymbolFetcher,
        "SearchName": FMPSearchNameFetcher,
        "SearchCik": FMPSearchCikFetcher,
        "SearchCusip": FMPSearchCusipFetcher,
        "SearchIsin": FMPSearchIsinFetcher,
        "SearchExchangeVariants": FMPSearchExchangeVariantsFetcher,
        "CikList": FMPCikListFetcher,
        "ProfileCik": FMPProfileCikFetcher,
        "SymbolChange": FMPSymbolChangeFetcher,
        "FinancialStatementSymbolList": FMPFinancialStatementSymbolListFetcher,
        "AvailableCountries": FMPAvailableCountriesFetcher,
        # Available-lists extras — final Tier-A parity port (#1478-#1480).
        "AvailableExchanges": FMPAvailableExchangesFetcher,
        "AvailableIndustries": FMPAvailableIndustriesFetcher,
        "AvailableSectors": FMPAvailableSectorsFetcher,
        "TechnicalIndicatorIntraday": FMPTechnicalIndicatorIntradayFetcher,
        "TreasuryRates": FMPTreasuryRatesFetcher,
        "WorldNews": FMPWorldNewsFetcher,
        "EtfHistorical": FMPEquityHistoricalFetcher,
        "YieldCurve": FMPYieldCurveFetcher,
        "GovernmentTrades": FMPGovernmentTradesFetcher,
    },
    repr_name="Financial Modeling Prep (FMP)",
    deprecated_credentials={"API_KEY_FINANCIALMODELINGPREP": "fmp_api_key"},
    instructions='Go to: https://site.financialmodelingprep.com/developer/docs\n\n![FinancialModelingPrep](https://user-images.githubusercontent.com/46355364/207821920-64553d05-d461-4984-b0fe-be0368c71186.png)\n\nClick on, "Get my API KEY here", and sign up for a free account.\n\n![FinancialModelingPrep](https://user-images.githubusercontent.com/46355364/207822184-a723092e-ef42-4f87-8c55-db150f09741b.png)\n\nWith an account created, sign in and navigate to the Dashboard, which shows the assigned token. by pressing the "Dashboard" button which will show the API key.\n\n![FinancialModelingPrep](https://user-images.githubusercontent.com/46355364/207823170-dd8191db-e125-44e5-b4f3-2df0e115c91d.png)',  # noqa: E501  pylint: disable=line-too-long
)
