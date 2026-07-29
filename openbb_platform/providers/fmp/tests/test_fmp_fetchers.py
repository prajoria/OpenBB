"""Unit tests for FMP provider modules."""

import re
from datetime import date

import pytest
from openbb_core.app.service.user_service import UserService
from openbb_fmp.models.analyst_estimates import FMPAnalystEstimatesFetcher
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
from openbb_fmp.models.equity_losers import FMPLosersFetcher
from openbb_fmp.models.equity_most_active import FMPEquityActiveFetcher
from openbb_fmp.models.equity_ownership import FMPEquityOwnershipFetcher
from openbb_fmp.models.equity_peers import FMPEquityPeersFetcher
from openbb_fmp.models.equity_profile import FMPEquityProfileFetcher
from openbb_fmp.models.equity_quote import FMPEquityQuoteFetcher
from openbb_fmp.models.equity_screener import FMPEquityScreenerFetcher
from openbb_fmp.models.esg_score import FMPEsgScoreFetcher
from openbb_fmp.models.etf_countries import FMPEtfCountriesFetcher
from openbb_fmp.models.etf_equity_exposure import FMPEtfEquityExposureFetcher
from openbb_fmp.models.etf_holdings import FMPEtfHoldingsFetcher
from openbb_fmp.models.etf_info import FMPEtfInfoFetcher
from openbb_fmp.models.etf_search import FMPEtfSearchFetcher
from openbb_fmp.models.etf_sectors import FMPEtfSectorsFetcher
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
from openbb_fmp.models.index_constituents import (
    FMPIndexConstituentsFetcher,
)
from openbb_fmp.models.index_historical import FMPIndexHistoricalFetcher
from openbb_fmp.models.insider_trading import FMPInsiderTradingFetcher
from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipFetcher
from openbb_fmp.models.key_executives import FMPKeyExecutivesFetcher
from openbb_fmp.models.key_metrics import FMPKeyMetricsFetcher
from openbb_fmp.models.market_snapshots import FMPMarketSnapshotsFetcher
from openbb_fmp.models.nport_disclosure import FMPNportDisclosureFetcher
from openbb_fmp.models.price_performance import FMPPricePerformanceFetcher
from openbb_fmp.models.price_target import FMPPriceTargetFetcher
from openbb_fmp.models.price_target_consensus import FMPPriceTargetConsensusFetcher
from openbb_fmp.models.revenue_business_line import FMPRevenueBusinessLineFetcher
from openbb_fmp.models.revenue_geographic import FMPRevenueGeographicFetcher
from openbb_fmp.models.risk_premium import FMPRiskPremiumFetcher
from openbb_fmp.models.share_statistics import FMPShareStatisticsFetcher
from openbb_fmp.models.treasury_rates import FMPTreasuryRatesFetcher
from openbb_fmp.models.world_news import FMPWorldNewsFetcher
from openbb_fmp.models.yield_curve import FMPYieldCurveFetcher

test_credentials = UserService().default_user_settings.credentials.model_dump(
    mode="json"
)


def response_filter(response):
    """Filter the response."""
    if "Location" in response["headers"]:
        response["headers"]["Location"] = [
            re.sub(r"apikey=[^&]+", "apikey=MOCK_API_KEY", x)
            for x in response["headers"]["Location"]
        ]
    return response


@pytest.fixture(scope="module")
def vcr_config():
    """VCR configuration."""
    return {
        "filter_headers": [("User-Agent", None)],
        "filter_query_parameters": [
            ("apikey", "MOCK_API_KEY"),
        ],
        "before_record_response": response_filter,
    }


@pytest.mark.record_http
def test_fmp_company_filings_fetcher(credentials=test_credentials):
    """Test FMP company filings fetcher."""
    params = {
        "symbol": "AAPL",
        "form_type": "10-K",
        "limit": 2,
        "start_date": date(2024, 9, 20),
        "end_date": date(2024, 10, 20),
    }

    fetcher = FMPCompanyFilingsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_crypto_historical_fetcher(credentials=test_credentials):
    """Test FMP crypto historical fetcher."""
    params = {
        "symbol": "BTCUSD",
        "start_date": date(2023, 1, 1),
        "end_date": date(2023, 1, 10),
    }

    fetcher = FMPCryptoHistoricalFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_currency_historical_fetcher(credentials=test_credentials):
    """Test FMP currency historical fetcher."""
    params = {
        "symbol": "EURUSD",
        "start_date": date(2023, 1, 1),
        "end_date": date(2023, 1, 10),
    }

    fetcher = FMPCurrencyHistoricalFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_index_historical_fetcher(credentials=test_credentials):
    """Test FMP index historical fetcher."""
    params = {
        "symbol": "^DJI",
        "start_date": date(2023, 1, 1),
        "end_date": date(2023, 1, 10),
    }

    fetcher = FMPIndexHistoricalFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_equity_historical_fetcher(credentials=test_credentials):
    """Test FMP equity historical fetcher."""
    params = {
        "symbol": "AAPL",
        "start_date": date(2023, 1, 1),
        "end_date": date(2023, 1, 10),
        "interval": "1d",
    }

    fetcher = FMPEquityHistoricalFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_company_news_fetcher(credentials=test_credentials):
    """Test FMP company news fetcher."""
    params = {"symbol": "AAPL,MSFT", "limit": 1}

    fetcher = FMPCompanyNewsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_balance_sheet_fetcher(credentials=test_credentials):
    """Test FMP balance sheet fetcher."""
    params = {"symbol": "AAPL", "limit": 1}

    fetcher = FMPBalanceSheetFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_cash_flow_statement_fetcher(credentials=test_credentials):
    """Test FMP cash flow statement fetcher."""
    params = {"symbol": "AAPL", "limit": 1}

    fetcher = FMPCashFlowStatementFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_income_statement_fetcher(credentials=test_credentials):
    """Test FMP income statement fetcher."""
    params = {"symbol": "AAPL", "limit": 1}

    fetcher = FMPIncomeStatementFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_available_indices_fetcher(credentials=test_credentials):
    """Test FMP available indices fetcher."""
    params = {}

    fetcher = FMPAvailableIndicesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_key_executives_fetcher(credentials=test_credentials):
    """Test FMP key executives fetcher."""
    params = {"symbol": "AAPL"}

    fetcher = FMPKeyExecutivesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_world_news_fetcher(credentials=test_credentials):
    """Test FMP world news fetcher."""
    params = {"limit": 1}

    fetcher = FMPWorldNewsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_income_statement_growth_fetcher(credentials=test_credentials):
    """Test FMP income statement growth fetcher."""
    params = {"symbol": "AAPL", "limit": 1}

    fetcher = FMPIncomeStatementGrowthFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_balance_sheet_growth_fetcher(credentials=test_credentials):
    """Test FMP balance sheet growth fetcher."""
    params = {"symbol": "AAPL", "limit": 1, "period": "annual"}

    fetcher = FMPBalanceSheetGrowthFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_cash_flow_statement_growth_fetcher(credentials=test_credentials):
    """Test FMP cash flow statement growth fetcher."""
    params = {"symbol": "AAPL", "limit": 1, "period": "annual"}

    fetcher = FMPCashFlowStatementGrowthFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_share_statistics_fetcher(credentials=test_credentials):
    """Test FMP share statistics fetcher."""
    params = {"symbol": "AAPL,MSFT"}

    fetcher = FMPShareStatisticsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_revenue_geographic_fetcher(credentials=test_credentials):
    """Test FMP revenue geographic fetcher."""
    params = {"symbol": "AAPL", "period": "annual"}

    fetcher = FMPRevenueGeographicFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_revenue_business_line_fetcher(credentials=test_credentials):
    """Test FMP revenue business line fetcher."""
    params = {"symbol": "AAPL", "period": "annual"}

    fetcher = FMPRevenueBusinessLineFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_institutional_ownership_fetcher(credentials=test_credentials):
    """Test FMP institutional ownership fetcher."""
    params = {"symbol": "AAPL,MSFT", "year": 2025, "quarter": 2}

    fetcher = FMPInstitutionalOwnershipFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_insider_trading_fetcher(credentials=test_credentials):
    """Test FMP insider trading fetcher."""
    params = {"symbol": "AAPL", "limit": 1, "transaction_type": "purchase"}

    fetcher = FMPInsiderTradingFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_equity_ownership_fetcher(credentials=test_credentials):
    """Test FMP equity ownership fetcher."""
    params = {"symbol": "AAPL", "year": 2025, "quarter": 2, "limit": 1}

    fetcher = FMPEquityOwnershipFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_price_target_consensus_fetcher(credentials=test_credentials):
    """Test FMP price target consensus fetcher."""
    params = {"symbol": "AAPL,MSFT"}

    fetcher = FMPPriceTargetConsensusFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_price_target_fetcher(credentials=test_credentials):
    """Test FMP price target fetcher."""
    params = {"symbol": "AAPL", "limit": 1}

    fetcher = FMPPriceTargetFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_analyst_estimates_fetcher(credentials=test_credentials):
    """Test FMP analyst estimates fetcher."""
    params = {"symbol": "AAPL,MSFT", "limit": 1}

    fetcher = FMPAnalystEstimatesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_historical_eps_fetcher(credentials=test_credentials):
    """Test FMP historical EPS fetcher."""
    params = {"symbol": "AAPL,MSFT", "limit": 1}

    fetcher = FMPHistoricalEpsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_earnings_call_transcript_fetcher(credentials=test_credentials):
    """Test FMP earnings call transcript fetcher."""
    params = {"symbol": "AAPL", "year": 2025, "quarter": 3}

    fetcher = FMPEarningsCallTranscriptFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_historical_splits_fetcher(credentials=test_credentials):
    """Test FMP historical splits fetcher."""
    params = {"symbol": "AAPL"}

    fetcher = FMPHistoricalSplitsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_calendar_splits_fetcher(credentials=test_credentials):
    """Test FMP calendar splits fetcher."""
    params = {"start_date": date(2023, 1, 1), "end_date": date(2023, 1, 10)}

    fetcher = FMPCalendarSplitsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_historical_dividends_fetcher(credentials=test_credentials):
    """Test FMP historical dividends fetcher."""
    params = {"symbol": "AAPL", "limit": 1}

    fetcher = FMPHistoricalDividendsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_key_metrics_fetcher(credentials=test_credentials):
    """Test FMP key metrics fetcher."""
    params = {"symbol": "AAPL"}

    fetcher = FMPKeyMetricsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_treasury_rates_fetcher(credentials=test_credentials):
    """Test FMP treasury rates fetcher."""
    params = {"start_date": date(2023, 1, 1), "end_date": date(2023, 1, 10)}

    fetcher = FMPTreasuryRatesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_executive_compensation_fetcher(credentials=test_credentials):
    """Test FMP executive compensation fetcher."""
    params = {"symbol": "AAPL", "year": 2024}

    fetcher = FMPExecutiveCompensationFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_currency_pairs_fetcher(credentials=test_credentials):
    """Test FMP currency pairs fetcher."""
    params = {}

    fetcher = FMPCurrencyPairsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_equity_peers_fetcher(credentials=test_credentials):
    """Test FMP equity peers fetcher."""
    params = {"symbol": "AAPL"}

    fetcher = FMPEquityPeersFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_historical_employees_fetcher(credentials=test_credentials):
    """Test FMP historical employees fetcher."""
    params = {"symbol": "AAPL", "limit": 1}

    fetcher = FMPHistoricalEmployeesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_risk_premium_fetcher(credentials=test_credentials):
    """Test FMP risk premium fetcher."""
    params = {}

    fetcher = FMPRiskPremiumFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_index_constituents_fetcher(credentials=test_credentials):
    """Test FMP index constituents fetcher."""
    params = {"symbol": "dowjones", "historical": False}

    fetcher = FMPIndexConstituentsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_calendar_dividend_fetcher(credentials=test_credentials):
    """Test FMP calendar dividend fetcher."""
    params = {"start_date": date(2023, 11, 6), "end_date": date(2023, 11, 10)}

    fetcher = FMPCalendarDividendFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_equity_quote_fetcher(credentials=test_credentials):
    """Test FMP equity quote fetcher."""
    params = {"symbol": "AAPL"}

    fetcher = FMPEquityQuoteFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_equity_screener_fetcher(credentials=test_credentials):
    """Test FMP equity screener fetcher."""
    params = {
        "industry": "oil_gas_midstream",
        "sector": "energy",
        "beta_max": 0.5,
        "limit": 2,
    }

    fetcher = FMPEquityScreenerFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_financial_ratios_fetcher(credentials=test_credentials):
    """Test FMP financial ratios fetcher."""
    params = {"symbol": "AAPL"}

    fetcher = FMPFinancialRatiosFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_economic_calendar_fetcher(credentials=test_credentials):
    """Test FMP economic calendar fetcher."""
    params = {"start_date": date(2024, 1, 1), "end_date": date(2024, 3, 30)}

    fetcher = FMPEconomicCalendarFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_market_snapshots_fetcher(credentials=test_credentials):
    """Test FMP market snapshots fetcher."""
    params = {"market": "neo"}

    fetcher = FMPMarketSnapshotsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_etf_search_fetcher(credentials=test_credentials):
    """Test FMP ETF search fetcher."""
    params = {"query": "India", "exchange": "tsx"}

    fetcher = FMPEtfSearchFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_etf_info_fetcher(credentials=test_credentials):
    """Test FMP ETF info fetcher."""
    params = {"symbol": "IOO"}

    fetcher = FMPEtfInfoFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_etf_sectors_fetcher(credentials=test_credentials):
    """Test FMP ETF sectors fetcher."""
    params = {"symbol": "IOO"}

    fetcher = FMPEtfSectorsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_etf_holdings_fetcher(credentials=test_credentials):
    """Test FMP ETF holdings fetcher."""
    params = {"symbol": "DIA"}

    fetcher = FMPEtfHoldingsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_etf_nport_disclosure_fetcher(credentials=test_credentials):
    """Test FMP ETF N-PORT disclosure fetcher."""
    params = {"symbol": "DIA", "year": 2025, "quarter": 1}

    fetcher = FMPNportDisclosureFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_price_performance_fetcher(credentials=test_credentials):
    """Test FMP price performance fetcher."""
    params = {"symbol": "AAPL,SPY,BTCUSD"}

    fetcher = FMPPricePerformanceFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_etf_countries_fetcher(credentials=test_credentials):
    """Test FMP ETF countries fetcher."""
    params = {"symbol": "VTI,QQQ,VOO,IWM"}

    fetcher = FMPEtfCountriesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_discovery_filings_fetcher(credentials=test_credentials):
    """Test FMP discovery filings fetcher."""
    params = {
        "start_date": date(2025, 9, 20),
        "end_date": date(2025, 9, 22),
        "form_type": None,
        "limit": 2,
    }

    fetcher = FMPDiscoveryFilingsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_crypto_search_fetcher(credentials=test_credentials):
    """Test FMP crypto search fetcher."""
    params = {"query": "asd"}

    fetcher = FMPCryptoSearchFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_calendar_earnings_fetcher(credentials=test_credentials):
    """Test FMP calendar earnings fetcher."""
    params = {"symbol": "AAPL"}

    params = {
        "start_date": date(2023, 11, 6),
        "end_date": date(2023, 11, 10),
    }
    fetcher = FMPCalendarEarningsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_equity_profile_fetcher(credentials=test_credentials):
    """Test FMP equity profile fetcher."""
    params = {"symbol": "AAPL"}

    fetcher = FMPEquityProfileFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_etf_equity_exposure_fetcher(credentials=test_credentials):
    """Test FMP ETF equity exposure fetcher."""
    params = {"symbol": "CNST"}

    fetcher = FMPEtfEquityExposureFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_currency_snapshots_fetcher(credentials=test_credentials):
    """Test FMP currency snapshots fetcher."""
    params = {
        "base": "XAU",
        "quote_type": "indirect",
        "counter_currencies": "USD,EUR,GBP,JPY,HKD,AUD,CAD,CHF,SEK,NZD,SGD",
    }

    fetcher = FMPCurrencySnapshotsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_equity_forward_eps_fetcher(credentials=test_credentials):
    """Test FMP forward EPS estimates fetcher."""
    params = {
        "symbol": "MSFT,AAPL",
        "fiscal_period": "annual",
        "include_historical": False,
        "limit": None,
    }

    fetcher = FMPForwardEpsEstimatesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_equity_forward_ebitda_fetcher(credentials=test_credentials):
    """Test FMP forward EBITDA estimates fetcher."""
    params = {
        "symbol": "MSFT,AAPL",
        "fiscal_period": "annual",
        "include_historical": False,
        "limit": None,
    }

    fetcher = FMPForwardEbitdaEstimatesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_yield_curve_fetcher(credentials=test_credentials):
    """Test FMP Yield Curve Fetcher."""
    params = {"date": "2024-05-14,2023-05-14"}

    fetcher = FMPYieldCurveFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_historical_market_cap_fetcher(credentials=test_credentials):
    """Test FMP Historical Market Cap Fetcher."""
    params = {
        "symbol": "AAPL",
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 1, 31),
    }

    fetcher = FmpHistoricalMarketCapFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_government_trades_fetcher(credentials=test_credentials):
    """Test FMP government trades fetcher.
    params limit only functions when there is no parameter symbol.
    """
    params = {
        "chamber": "senate",
        "limit": 1,
    }
    fetcher = FMPGovernmentTradesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_calendar_events_fetcher(credentials=test_credentials):
    """Test FMP calendar events fetcher."""
    params = {
        "start_date": date(2025, 1, 7),
        "end_date": date(2025, 1, 10),
    }
    fetcher = FMPCalendarEventsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_equity_gainers_fetcher(credentials=test_credentials):
    """Test FMP equity gainers fetcher."""
    params = {}
    fetcher = FMPGainersFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_equity_losers_fetcher(credentials=test_credentials):
    """Test FMP equity losers fetcher."""
    params = {}
    fetcher = FMPLosersFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_esg_score(credentials=test_credentials):
    """Test FMP ESG score fetcher."""
    params = {"symbol": "AAPL"}
    fetcher = FMPEsgScoreFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_calendar_ipo_fetcher(credentials=test_credentials):
    """Test FMP calendar IPO fetcher."""
    params = {"start_date": date(2024, 9, 20), "end_date": date(2024, 10, 20)}
    fetcher = FMPCalendarIpoFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_equity_active_fetcher(credentials=test_credentials):
    """Test FMP equity active fetcher."""
    params = {}
    fetcher = FMPEquityActiveFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


# ---------------------------------------------------------------------------
# Analyst / Ratings / Grades — Tier-A parity port from fmp_cached
# (#1482 #1483 #1484 #1485 #1486 #1487).
# ---------------------------------------------------------------------------


@pytest.mark.record_http
def test_fmp_ratings_snapshot_fetcher(credentials=test_credentials):
    """Test FMP ratings snapshot fetcher (#1487)."""
    from openbb_fmp.models.analyst_ratings import FMPRatingsSnapshotFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPRatingsSnapshotFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_ratings_historical_fetcher(credentials=test_credentials):
    """Test FMP ratings historical fetcher (#1486)."""
    from openbb_fmp.models.analyst_ratings import FMPRatingsHistoricalFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPRatingsHistoricalFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_price_target_summary_fetcher(credentials=test_credentials):
    """Test FMP price target summary fetcher (#1485)."""
    from openbb_fmp.models.analyst_ratings import FMPPriceTargetSummaryFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPPriceTargetSummaryFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_grades_fetcher(credentials=test_credentials):
    """Test FMP grades fetcher (#1482)."""
    from openbb_fmp.models.analyst_ratings import FMPGradesFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPGradesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_grades_historical_fetcher(credentials=test_credentials):
    """Test FMP grades historical fetcher (#1484)."""
    from openbb_fmp.models.analyst_ratings import FMPGradesHistoricalFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPGradesHistoricalFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_grades_consensus_fetcher(credentials=test_credentials):
    """Test FMP grades consensus fetcher (#1483)."""
    from openbb_fmp.models.analyst_ratings import FMPGradesConsensusFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPGradesConsensusFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


# ---------------------------------------------------------------------------
# Statements-extras — Tier-A parity port from fmp_cached (#1488-#1499).
# ---------------------------------------------------------------------------


@pytest.mark.record_http
def test_fmp_enterprise_values_fetcher(credentials=test_credentials):
    """Test FMP enterprise values fetcher (#1488)."""
    from openbb_fmp.models.statements_extras import FMPEnterpriseValuesFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPEnterpriseValuesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_financial_growth_fetcher(credentials=test_credentials):
    """Test FMP financial growth fetcher (#1489)."""
    from openbb_fmp.models.statements_extras import FMPFinancialGrowthFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPFinancialGrowthFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_financial_scores_fetcher(credentials=test_credentials):
    """Test FMP financial scores fetcher (#1490)."""
    from openbb_fmp.models.statements_extras import FMPFinancialScoresFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPFinancialScoresFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_key_metrics_ttm_fetcher(credentials=test_credentials):
    """Test FMP key metrics TTM fetcher (#1491)."""
    from openbb_fmp.models.statements_extras import FMPKeyMetricsTtmFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPKeyMetricsTtmFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_owner_earnings_fetcher(credentials=test_credentials):
    """Test FMP owner earnings fetcher (#1492)."""
    from openbb_fmp.models.statements_extras import FMPOwnerEarningsFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPOwnerEarningsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_ratios_ttm_fetcher(credentials=test_credentials):
    """Test FMP ratios TTM fetcher (#1493)."""
    from openbb_fmp.models.statements_extras import FMPRatiosTtmFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPRatiosTtmFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_income_statement_as_reported_fetcher(credentials=test_credentials):
    """Test FMP income statement as-reported fetcher (#1494)."""
    from openbb_fmp.models.statements_extras import (
        FMPIncomeStatementAsReportedFetcher,
    )

    params = {"symbol": "MSFT"}
    fetcher = FMPIncomeStatementAsReportedFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_balance_sheet_statement_as_reported_fetcher(
    credentials=test_credentials,
):
    """Test FMP balance sheet as-reported fetcher (#1495)."""
    from openbb_fmp.models.statements_extras import (
        FMPBalanceSheetStatementAsReportedFetcher,
    )

    params = {"symbol": "MSFT"}
    fetcher = FMPBalanceSheetStatementAsReportedFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_cash_flow_statement_as_reported_fetcher(credentials=test_credentials):
    """Test FMP cash flow as-reported fetcher (#1496)."""
    from openbb_fmp.models.statements_extras import (
        FMPCashFlowStatementAsReportedFetcher,
    )

    params = {"symbol": "MSFT"}
    fetcher = FMPCashFlowStatementAsReportedFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_financial_statement_full_as_reported_fetcher(
    credentials=test_credentials,
):
    """Test FMP financial statement full as-reported fetcher (#1497)."""
    from openbb_fmp.models.statements_extras import (
        FMPFinancialStatementFullAsReportedFetcher,
    )

    params = {"symbol": "MSFT"}
    fetcher = FMPFinancialStatementFullAsReportedFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_financial_reports_dates_fetcher(credentials=test_credentials):
    """Test FMP financial reports dates fetcher (#1498)."""
    from openbb_fmp.models.statements_extras import FMPFinancialReportsDatesFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPFinancialReportsDatesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_financial_reports_json_fetcher(credentials=test_credentials):
    """Test FMP financial reports JSON fetcher (#1499).

    Requires ``year`` and ``period`` in addition to ``symbol``; FMP
    returns a single object (not a list) that we wrap.
    """
    from openbb_fmp.models.statements_extras import FMPFinancialReportsJsonFetcher

    params = {"symbol": "MSFT", "year": 2024, "period": "FY"}
    fetcher = FMPFinancialReportsJsonFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


# ---------------------------------------------------------------------------
# Quotes-extras — Tier-A parity port (#1506-#1514).
# ---------------------------------------------------------------------------


@pytest.mark.record_http
def test_fmp_batch_quote_fetcher(credentials=test_credentials):
    """Test FMP batch quote fetcher (#1506)."""
    from openbb_fmp.models.quotes_extras import FMPBatchQuoteFetcher

    params = {"symbols": "AAPL,MSFT"}
    fetcher = FMPBatchQuoteFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_batch_quote_short_fetcher(credentials=test_credentials):
    """Test FMP batch quote short fetcher (#1507)."""
    from openbb_fmp.models.quotes_extras import FMPBatchQuoteShortFetcher

    params = {"symbols": "AAPL,MSFT"}
    fetcher = FMPBatchQuoteShortFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_batch_aftermarket_quote_fetcher(credentials=test_credentials):
    """Test FMP batch aftermarket quote fetcher (#1508)."""
    from openbb_fmp.models.quotes_extras import FMPBatchAftermarketQuoteFetcher

    params = {"symbols": "AAPL,MSFT"}
    fetcher = FMPBatchAftermarketQuoteFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_batch_aftermarket_trade_fetcher(credentials=test_credentials):
    """Test FMP batch aftermarket trade fetcher (#1509)."""
    from openbb_fmp.models.quotes_extras import FMPBatchAftermarketTradeFetcher

    params = {"symbols": "AAPL,MSFT"}
    fetcher = FMPBatchAftermarketTradeFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_stock_quote_fetcher(credentials=test_credentials):
    """Test FMP stock quote fetcher (#1510)."""
    from openbb_fmp.models.quotes_extras import FMPStockQuoteFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPStockQuoteFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_stock_quote_short_fetcher(credentials=test_credentials):
    """Test FMP stock quote short fetcher (#1511)."""
    from openbb_fmp.models.quotes_extras import FMPStockQuoteShortFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPStockQuoteShortFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_stock_price_change_fetcher(credentials=test_credentials):
    """Test FMP stock price change fetcher (#1512)."""
    from openbb_fmp.models.quotes_extras import FMPStockPriceChangeFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPStockPriceChangeFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_market_cap_fetcher(credentials=test_credentials):
    """Test FMP market cap fetcher (#1513)."""
    from openbb_fmp.models.quotes_extras import FMPMarketCapFetcher

    params = {"symbol": "MSFT"}
    fetcher = FMPMarketCapFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_fmp_market_cap_batch_fetcher(credentials=test_credentials):
    """Test FMP market cap batch fetcher (#1514)."""
    from openbb_fmp.models.quotes_extras import FMPMarketCapBatchFetcher

    params = {"symbols": "AAPL,MSFT"}
    fetcher = FMPMarketCapBatchFetcher()
    result = fetcher.test(params, credentials)
    assert result is None
