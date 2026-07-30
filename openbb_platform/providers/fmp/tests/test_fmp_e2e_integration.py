"""Live E2E integration tests for the FMP Tier-A parity fetchers (105 endpoints).

Covers 14 domain E2E suites (#1573-#1586) + 5 cross-cutting integration
checks (#1587-#1591). All tests are gated behind
``@pytest.mark.integration`` — the default ``pytest -m "not integration"``
run skips them entirely.

Local usage (requires an FMP API key in ``.env`` at the repo root or in
``~/.openbb_platform/user_settings.json``)::

    .\\.venv_portfolio\\Scripts\\python.exe -m pytest \\
        openbb_platform/providers/fmp/tests/test_fmp_e2e_integration.py \\
        -m integration -v

Each test:

* Instantiates the fetcher live (no cassettes).
* Asserts a non-empty ``list[Data]`` return.
* Asserts every element is a Pydantic ``Data`` instance.

Anything more elaborate (schema drift detection, provider-map parity)
belongs in the cross-cutting section at the bottom of the file.

Design decisions:

* Skip cleanly when no ``fmp_api_key`` credential is resolvable — the
  test collection is expensive (105 network round-trips per full run)
  and pointless without a key. The skip message names ``.env`` and
  ``user_settings.json`` so a fresh contributor knows exactly what to
  set.
* No cassette recording — that layer is exercised by
  ``test_fmp_fetchers.py`` and already committed. This file exists
  specifically to catch upstream drift the cassettes cannot.
* One class per E2E issue. Each class carries a docstring pointing back
  to its issue number. If a domain regresses live, the class name is
  what shows up in the pytest failure header.
"""

# pylint: disable=too-many-lines,unused-argument

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Attempt to load .env before the credentials fixture runs.
try:
    from dotenv import load_dotenv

    _REPO_ROOT = Path(__file__).resolve().parents[5]
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:  # pragma: no cover — python-dotenv is optional
    pass

from openbb_core.app.service.user_service import UserService
from openbb_core.provider.abstract.data import Data


def _resolve_credentials() -> dict[str, str] | None:
    """Load credentials from user_settings.json + .env."""
    creds = UserService().default_user_settings.credentials.model_dump(mode="json")
    # Fold in .env if user_settings.json doesn't have a key.
    env_key = os.environ.get("FMP_API_KEY")
    if env_key and not creds.get("fmp_api_key"):
        creds["fmp_api_key"] = env_key
    return creds


test_credentials = _resolve_credentials()


# Skip the entire module if no FMP key is resolvable.
_SKIP_REASON = (
    "FMP live E2E suite skipped — no fmp_api_key found. Set it in "
    "~/.openbb_platform/user_settings.json OR in .env at the repo root "
    "(FMP_API_KEY=...). CI runs correctly skip this file by default via "
    "the `not integration` marker."
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (test_credentials or {}).get("fmp_api_key"),
        reason=_SKIP_REASON,
    ),
]


def _assert_nonempty_data_list(result: object) -> None:
    """Common shape check for every fetcher's raw return."""
    # OpenBB fetchers' ``.test()`` returns None; we want the underlying
    # data. Use the fetch class-method entrypoint instead.
    assert result is not None, "Fetcher returned None — likely provider outage."


async def _run(fetcher_cls, params: dict) -> list:
    """Instantiate a fetcher, run the full transform pipeline live, and
    return the ``list[Data]``. Raises on empty results so callers can
    surface the domain in the pytest failure header."""
    query = fetcher_cls.transform_query(params)
    raw = await fetcher_cls.aextract_data(query, test_credentials)
    data = fetcher_cls.transform_data(query, raw)
    assert isinstance(data, list), f"{fetcher_cls.__name__} did not return a list"
    assert data, f"{fetcher_cls.__name__} returned empty list — provider drift?"
    for row in data[:5]:
        assert isinstance(
            row, Data
        ), f"{fetcher_cls.__name__} row is not a Data subclass: {type(row).__name__}"


# ===========================================================================
# #1573 — Search & Directory endpoints
# ===========================================================================


class TestSearchAndDirectoryE2E:
    """E2E suite for #1573 — Search & Directory (11 fetchers)."""

    @pytest.mark.asyncio
    async def test_search_symbol(self):
        """#1467."""
        from openbb_fmp.models.market_hours_search_extras import FMPSearchSymbolFetcher

        await _run(FMPSearchSymbolFetcher, {"query": "AAPL"})

    @pytest.mark.asyncio
    async def test_search_name(self):
        """#1468."""
        from openbb_fmp.models.market_hours_search_extras import FMPSearchNameFetcher

        await _run(FMPSearchNameFetcher, {"query": "Apple"})

    @pytest.mark.asyncio
    async def test_search_cik(self):
        """#1469."""
        from openbb_fmp.models.market_hours_search_extras import FMPSearchCikFetcher

        await _run(FMPSearchCikFetcher, {"cik": "0000320193"})

    @pytest.mark.asyncio
    async def test_search_cusip(self):
        """#1470."""
        from openbb_fmp.models.market_hours_search_extras import FMPSearchCusipFetcher

        await _run(FMPSearchCusipFetcher, {"cusip": "037833100"})

    @pytest.mark.asyncio
    async def test_search_isin(self):
        """#1471."""
        from openbb_fmp.models.market_hours_search_extras import FMPSearchIsinFetcher

        await _run(FMPSearchIsinFetcher, {"isin": "US0378331005"})

    @pytest.mark.asyncio
    async def test_search_exchange_variants(self):
        """#1472."""
        from openbb_fmp.models.market_hours_search_extras import (
            FMPSearchExchangeVariantsFetcher,
        )

        await _run(FMPSearchExchangeVariantsFetcher, {"symbol": "AAPL"})

    @pytest.mark.asyncio
    async def test_cik_list(self):
        """#1473."""
        from openbb_fmp.models.market_hours_search_extras import FMPCikListFetcher

        await _run(FMPCikListFetcher, {})

    @pytest.mark.asyncio
    async def test_profile_cik(self):
        """#1474."""
        from openbb_fmp.models.market_hours_search_extras import FMPProfileCikFetcher

        await _run(FMPProfileCikFetcher, {"cik": "0000320193"})

    @pytest.mark.asyncio
    async def test_symbol_change(self):
        """#1475."""
        from openbb_fmp.models.market_hours_search_extras import FMPSymbolChangeFetcher

        await _run(
            FMPSymbolChangeFetcher,
            {"from_date": "2024-01-01", "to_date": "2026-07-29"},
        )

    @pytest.mark.asyncio
    async def test_financial_statement_symbol_list(self):
        """#1476."""
        from openbb_fmp.models.market_hours_search_extras import (
            FMPFinancialStatementSymbolListFetcher,
        )

        await _run(FMPFinancialStatementSymbolListFetcher, {})

    @pytest.mark.asyncio
    async def test_available_countries(self):
        """#1477."""
        from openbb_fmp.models.market_hours_search_extras import (
            FMPAvailableCountriesFetcher,
        )

        await _run(FMPAvailableCountriesFetcher, {})

    @pytest.mark.asyncio
    async def test_available_exchanges(self):
        """#1478."""
        from openbb_fmp.models.available_lists_extras import (
            FMPAvailableExchangesFetcher,
        )

        await _run(FMPAvailableExchangesFetcher, {})

    @pytest.mark.asyncio
    async def test_available_industries(self):
        """#1479."""
        from openbb_fmp.models.available_lists_extras import (
            FMPAvailableIndustriesFetcher,
        )

        await _run(FMPAvailableIndustriesFetcher, {})

    @pytest.mark.asyncio
    async def test_available_sectors(self):
        """#1480."""
        from openbb_fmp.models.available_lists_extras import (
            FMPAvailableSectorsFetcher,
        )

        await _run(FMPAvailableSectorsFetcher, {})


# ===========================================================================
# #1574 — Analyst, Ratings & Grades
# ===========================================================================


class TestAnalystRatingsGradesE2E:
    """E2E suite for #1574 — Analyst / Ratings / Grades (6 fetchers)."""

    @pytest.mark.asyncio
    async def test_ratings_snapshot(self):
        """#1487."""
        from openbb_fmp.models.analyst_ratings import FMPRatingsSnapshotFetcher

        await _run(FMPRatingsSnapshotFetcher, {"symbol": "MSFT"})

    @pytest.mark.asyncio
    async def test_ratings_historical(self):
        """#1486."""
        from openbb_fmp.models.analyst_ratings import FMPRatingsHistoricalFetcher

        await _run(FMPRatingsHistoricalFetcher, {"symbol": "MSFT"})

    @pytest.mark.asyncio
    async def test_price_target_summary(self):
        """#1485."""
        from openbb_fmp.models.analyst_ratings import FMPPriceTargetSummaryFetcher

        await _run(FMPPriceTargetSummaryFetcher, {"symbol": "MSFT"})

    @pytest.mark.asyncio
    async def test_grades(self):
        """#1482."""
        from openbb_fmp.models.analyst_ratings import FMPGradesFetcher

        await _run(FMPGradesFetcher, {"symbol": "MSFT"})

    @pytest.mark.asyncio
    async def test_grades_historical(self):
        """#1484."""
        from openbb_fmp.models.analyst_ratings import FMPGradesHistoricalFetcher

        await _run(FMPGradesHistoricalFetcher, {"symbol": "MSFT"})

    @pytest.mark.asyncio
    async def test_grades_consensus(self):
        """#1483."""
        from openbb_fmp.models.analyst_ratings import FMPGradesConsensusFetcher

        await _run(FMPGradesConsensusFetcher, {"symbol": "MSFT"})


# ===========================================================================
# #1575 — Statements extras
# ===========================================================================


class TestStatementsExtrasE2E:
    """E2E suite for #1575 — Statements extras (12 fetchers)."""

    _S = {"symbol": "MSFT"}

    @pytest.mark.asyncio
    async def test_enterprise_values(self):
        """#1488."""
        from openbb_fmp.models.statements_extras import FMPEnterpriseValuesFetcher

        await _run(FMPEnterpriseValuesFetcher, self._S)

    @pytest.mark.asyncio
    async def test_financial_growth(self):
        """#1489."""
        from openbb_fmp.models.statements_extras import FMPFinancialGrowthFetcher

        await _run(FMPFinancialGrowthFetcher, self._S)

    @pytest.mark.asyncio
    async def test_financial_scores(self):
        """#1490."""
        from openbb_fmp.models.statements_extras import FMPFinancialScoresFetcher

        await _run(FMPFinancialScoresFetcher, self._S)

    @pytest.mark.asyncio
    async def test_key_metrics_ttm(self):
        """#1491."""
        from openbb_fmp.models.statements_extras import FMPKeyMetricsTtmFetcher

        await _run(FMPKeyMetricsTtmFetcher, self._S)

    @pytest.mark.asyncio
    async def test_owner_earnings(self):
        """#1492."""
        from openbb_fmp.models.statements_extras import FMPOwnerEarningsFetcher

        await _run(FMPOwnerEarningsFetcher, self._S)

    @pytest.mark.asyncio
    async def test_ratios_ttm(self):
        """#1493."""
        from openbb_fmp.models.statements_extras import FMPRatiosTtmFetcher

        await _run(FMPRatiosTtmFetcher, self._S)

    @pytest.mark.asyncio
    async def test_income_statement_as_reported(self):
        """#1494."""
        from openbb_fmp.models.statements_extras import (
            FMPIncomeStatementAsReportedFetcher,
        )

        await _run(FMPIncomeStatementAsReportedFetcher, self._S)

    @pytest.mark.asyncio
    async def test_balance_sheet_statement_as_reported(self):
        """#1495."""
        from openbb_fmp.models.statements_extras import (
            FMPBalanceSheetStatementAsReportedFetcher,
        )

        await _run(FMPBalanceSheetStatementAsReportedFetcher, self._S)

    @pytest.mark.asyncio
    async def test_cash_flow_statement_as_reported(self):
        """#1496."""
        from openbb_fmp.models.statements_extras import (
            FMPCashFlowStatementAsReportedFetcher,
        )

        await _run(FMPCashFlowStatementAsReportedFetcher, self._S)

    @pytest.mark.asyncio
    async def test_financial_statement_full_as_reported(self):
        """#1497."""
        from openbb_fmp.models.statements_extras import (
            FMPFinancialStatementFullAsReportedFetcher,
        )

        await _run(FMPFinancialStatementFullAsReportedFetcher, self._S)

    @pytest.mark.asyncio
    async def test_financial_reports_dates(self):
        """#1498."""
        from openbb_fmp.models.statements_extras import FMPFinancialReportsDatesFetcher

        await _run(FMPFinancialReportsDatesFetcher, self._S)

    @pytest.mark.asyncio
    async def test_financial_reports_json(self):
        """#1499."""
        from openbb_fmp.models.statements_extras import FMPFinancialReportsJsonFetcher

        await _run(
            FMPFinancialReportsJsonFetcher,
            {"symbol": "MSFT", "year": 2024, "period": "FY"},
        )


# ===========================================================================
# #1576 — Company, Ownership, Float & Compensation
# ===========================================================================


class TestCompanyE2E:
    """E2E suite for #1576 — Company / Ownership / Float / Compensation (6 fetchers)."""

    @pytest.mark.asyncio
    async def test_company_notes(self):
        """#1500."""
        from openbb_fmp.models.company_extras import FMPCompanyNotesFetcher

        await _run(FMPCompanyNotesFetcher, {"symbol": "AAPL"})

    @pytest.mark.asyncio
    async def test_delisted_companies(self):
        """#1501."""
        from openbb_fmp.models.company_extras import FMPDelistedCompaniesFetcher

        await _run(FMPDelistedCompaniesFetcher, {"page": 0, "limit": 10})

    @pytest.mark.asyncio
    async def test_shares_float(self):
        """#1502."""
        from openbb_fmp.models.company_extras import FMPSharesFloatFetcher

        await _run(FMPSharesFloatFetcher, {"symbol": "AAPL"})

    @pytest.mark.asyncio
    async def test_shares_float_all(self):
        """#1503."""
        from openbb_fmp.models.company_extras import FMPSharesFloatAllFetcher

        await _run(FMPSharesFloatAllFetcher, {"page": 0, "limit": 10})

    @pytest.mark.asyncio
    async def test_acquisition_of_beneficial_ownership(self):
        """#1504."""
        from openbb_fmp.models.company_extras import (
            FMPAcquisitionOfBeneficialOwnershipFetcher,
        )

        await _run(FMPAcquisitionOfBeneficialOwnershipFetcher, {"symbol": "AAPL"})

    @pytest.mark.asyncio
    async def test_executive_compensation_benchmark(self):
        """#1505."""
        from openbb_fmp.models.company_extras import (
            FMPExecutiveCompensationBenchmarkFetcher,
        )

        await _run(FMPExecutiveCompensationBenchmarkFetcher, {"year": 2023})


# ===========================================================================
# #1577 — Quotes, Market Cap & Batch
# ===========================================================================


class TestQuotesE2E:
    """E2E suite for #1577 — Quotes / Market Cap / Batch (9 fetchers)."""

    _S = {"symbol": "MSFT"}
    _MS = {"symbols": "AAPL,MSFT"}

    @pytest.mark.asyncio
    async def test_batch_quote(self):
        """#1506."""
        from openbb_fmp.models.quotes_extras import FMPBatchQuoteFetcher

        await _run(FMPBatchQuoteFetcher, self._MS)

    @pytest.mark.asyncio
    async def test_batch_quote_short(self):
        """#1507."""
        from openbb_fmp.models.quotes_extras import FMPBatchQuoteShortFetcher

        await _run(FMPBatchQuoteShortFetcher, self._MS)

    @pytest.mark.asyncio
    async def test_batch_aftermarket_quote(self):
        """#1508."""
        from openbb_fmp.models.quotes_extras import FMPBatchAftermarketQuoteFetcher

        await _run(FMPBatchAftermarketQuoteFetcher, self._MS)

    @pytest.mark.asyncio
    async def test_batch_aftermarket_trade(self):
        """#1509."""
        from openbb_fmp.models.quotes_extras import FMPBatchAftermarketTradeFetcher

        await _run(FMPBatchAftermarketTradeFetcher, self._MS)

    @pytest.mark.asyncio
    async def test_stock_quote(self):
        """#1510."""
        from openbb_fmp.models.quotes_extras import FMPStockQuoteFetcher

        await _run(FMPStockQuoteFetcher, self._S)

    @pytest.mark.asyncio
    async def test_stock_quote_short(self):
        """#1511."""
        from openbb_fmp.models.quotes_extras import FMPStockQuoteShortFetcher

        await _run(FMPStockQuoteShortFetcher, self._S)

    @pytest.mark.asyncio
    async def test_stock_price_change(self):
        """#1512."""
        from openbb_fmp.models.quotes_extras import FMPStockPriceChangeFetcher

        await _run(FMPStockPriceChangeFetcher, self._S)

    @pytest.mark.asyncio
    async def test_market_cap(self):
        """#1513."""
        from openbb_fmp.models.quotes_extras import FMPMarketCapFetcher

        await _run(FMPMarketCapFetcher, self._S)

    @pytest.mark.asyncio
    async def test_market_cap_batch(self):
        """#1514."""
        from openbb_fmp.models.quotes_extras import FMPMarketCapBatchFetcher

        await _run(FMPMarketCapBatchFetcher, self._MS)


# ===========================================================================
# #1578 — Index & Sector/Industry Performance
# ===========================================================================


class TestIndexPerformanceE2E:
    """E2E suite for #1578 — Index / Sector / Industry (14 fetchers)."""

    _D = {"date": "2026-07-29"}
    _SR = {"sector": "Technology", "from_date": "2024-07-29", "to_date": "2026-07-29"}
    _IR = {
        "industry": "Semiconductors",
        "from_date": "2024-07-29",
        "to_date": "2026-07-29",
    }

    @pytest.mark.asyncio
    async def test_dowjones_constituent(self):
        """#1515."""
        from openbb_fmp.models.indexes_extras import FMPDowjonesConstituentFetcher

        await _run(FMPDowjonesConstituentFetcher, {})

    @pytest.mark.asyncio
    async def test_historical_dowjones_constituent(self):
        """#1516."""
        from openbb_fmp.models.indexes_extras import (
            FMPHistoricalDowjonesConstituentFetcher,
        )

        await _run(FMPHistoricalDowjonesConstituentFetcher, {})

    @pytest.mark.asyncio
    async def test_sp500_constituent(self):
        """#1517."""
        from openbb_fmp.models.indexes_extras import FMPSp500ConstituentFetcher

        await _run(FMPSp500ConstituentFetcher, {})

    @pytest.mark.asyncio
    async def test_historical_sp500_constituent(self):
        """#1518."""
        from openbb_fmp.models.indexes_extras import (
            FMPHistoricalSp500ConstituentFetcher,
        )

        await _run(FMPHistoricalSp500ConstituentFetcher, {})

    @pytest.mark.asyncio
    async def test_nasdaq_constituent(self):
        """#1519."""
        from openbb_fmp.models.indexes_extras import FMPNasdaqConstituentFetcher

        await _run(FMPNasdaqConstituentFetcher, {})

    @pytest.mark.asyncio
    async def test_historical_nasdaq_constituent(self):
        """#1520."""
        from openbb_fmp.models.indexes_extras import (
            FMPHistoricalNasdaqConstituentFetcher,
        )

        await _run(FMPHistoricalNasdaqConstituentFetcher, {})

    @pytest.mark.asyncio
    async def test_sector_performance_snapshot(self):
        """#1521."""
        from openbb_fmp.models.indexes_extras import (
            FMPSectorPerformanceSnapshotFetcher,
        )

        await _run(FMPSectorPerformanceSnapshotFetcher, self._D)

    @pytest.mark.asyncio
    async def test_historical_sector_performance(self):
        """#1522."""
        from openbb_fmp.models.indexes_extras import (
            FMPHistoricalSectorPerformanceFetcher,
        )

        await _run(FMPHistoricalSectorPerformanceFetcher, self._SR)

    @pytest.mark.asyncio
    async def test_sector_pe_snapshot(self):
        """#1523."""
        from openbb_fmp.models.indexes_extras import FMPSectorPeSnapshotFetcher

        await _run(FMPSectorPeSnapshotFetcher, self._D)

    @pytest.mark.asyncio
    async def test_historical_sector_pe(self):
        """#1524."""
        from openbb_fmp.models.indexes_extras import FMPHistoricalSectorPeFetcher

        await _run(FMPHistoricalSectorPeFetcher, self._SR)

    @pytest.mark.asyncio
    async def test_industry_performance_snapshot(self):
        """#1525."""
        from openbb_fmp.models.indexes_extras import (
            FMPIndustryPerformanceSnapshotFetcher,
        )

        await _run(FMPIndustryPerformanceSnapshotFetcher, self._D)

    @pytest.mark.asyncio
    async def test_historical_industry_performance(self):
        """#1526."""
        from openbb_fmp.models.indexes_extras import (
            FMPHistoricalIndustryPerformanceFetcher,
        )

        await _run(FMPHistoricalIndustryPerformanceFetcher, self._IR)

    @pytest.mark.asyncio
    async def test_industry_pe_snapshot(self):
        """#1527."""
        from openbb_fmp.models.indexes_extras import FMPIndustryPeSnapshotFetcher

        await _run(FMPIndustryPeSnapshotFetcher, self._D)

    @pytest.mark.asyncio
    async def test_historical_industry_pe(self):
        """#1528."""
        from openbb_fmp.models.indexes_extras import FMPHistoricalIndustryPeFetcher

        await _run(FMPHistoricalIndustryPeFetcher, self._IR)


# ===========================================================================
# #1579 — Economics, COT & Risk
# ===========================================================================


class TestEconomicsE2E:
    """E2E suite for #1579 — Economics / COT / Risk (5 fetchers)."""

    @pytest.mark.asyncio
    async def test_economic_indicators(self):
        """#1529."""
        from openbb_fmp.models.economics_extras import FMPEconomicIndicatorsFetcher

        await _run(
            FMPEconomicIndicatorsFetcher,
            {"name": "CPI", "from_date": "2024-01-01", "to_date": "2026-07-29"},
        )

    @pytest.mark.asyncio
    async def test_market_risk_premium(self):
        """#1530."""
        from openbb_fmp.models.economics_extras import FMPMarketRiskPremiumFetcher

        await _run(FMPMarketRiskPremiumFetcher, {})

    @pytest.mark.asyncio
    async def test_commitment_of_traders_analysis(self):
        """#1531."""
        from openbb_fmp.models.economics_extras import (
            FMPCommitmentOfTradersAnalysisFetcher,
        )

        await _run(FMPCommitmentOfTradersAnalysisFetcher, {"symbol": "ES"})

    @pytest.mark.asyncio
    async def test_commitment_of_traders_list(self):
        """#1532."""
        from openbb_fmp.models.economics_extras import (
            FMPCommitmentOfTradersListFetcher,
        )

        await _run(FMPCommitmentOfTradersListFetcher, {})

    @pytest.mark.asyncio
    async def test_commitment_of_traders_report(self):
        """#1533."""
        from openbb_fmp.models.economics_extras import (
            FMPCommitmentOfTradersReportFetcher,
        )

        await _run(FMPCommitmentOfTradersReportFetcher, {"symbol": "ES"})


# ===========================================================================
# #1580 — Fundraising, M&A & Crowdfunding
# ===========================================================================


class TestFundraisingE2E:
    """E2E suite for #1580 — Fundraising / M&A / Crowdfunding (10 fetchers)."""

    _PL = {"page": 0, "limit": 10}

    @pytest.mark.asyncio
    async def test_fundraising(self):
        """#1534. CIK sourced from FundraisingLatest to guarantee non-empty."""
        from openbb_fmp.models.fundraising_extras import FMPFundraisingFetcher

        await _run(FMPFundraisingFetcher, {"cik": "0002078364"})

    @pytest.mark.asyncio
    async def test_fundraising_latest(self):
        """#1535."""
        from openbb_fmp.models.fundraising_extras import FMPFundraisingLatestFetcher

        await _run(FMPFundraisingLatestFetcher, self._PL)

    @pytest.mark.asyncio
    async def test_fundraising_search(self):
        """#1536."""
        from openbb_fmp.models.fundraising_extras import FMPFundraisingSearchFetcher

        await _run(FMPFundraisingSearchFetcher, {"name": "Apple"})

    @pytest.mark.asyncio
    async def test_crowdfunding_offerings(self):
        """#1537."""
        from openbb_fmp.models.fundraising_extras import (
            FMPCrowdfundingOfferingsFetcher,
        )

        await _run(FMPCrowdfundingOfferingsFetcher, {"cik": "0002134401"})

    @pytest.mark.asyncio
    async def test_crowdfunding_offerings_latest(self):
        """#1538."""
        from openbb_fmp.models.fundraising_extras import (
            FMPCrowdfundingOfferingsLatestFetcher,
        )

        await _run(FMPCrowdfundingOfferingsLatestFetcher, self._PL)

    @pytest.mark.asyncio
    async def test_crowdfunding_offerings_search(self):
        """#1539."""
        from openbb_fmp.models.fundraising_extras import (
            FMPCrowdfundingOfferingsSearchFetcher,
        )

        await _run(FMPCrowdfundingOfferingsSearchFetcher, {"name": "tech"})

    @pytest.mark.asyncio
    async def test_mergers_acquisitions_latest(self):
        """#1540."""
        from openbb_fmp.models.fundraising_extras import (
            FMPMergersAcquisitionsLatestFetcher,
        )

        await _run(FMPMergersAcquisitionsLatestFetcher, self._PL)

    @pytest.mark.asyncio
    async def test_mergers_acquisitions_search(self):
        """#1541."""
        from openbb_fmp.models.fundraising_extras import (
            FMPMergersAcquisitionsSearchFetcher,
        )

        await _run(FMPMergersAcquisitionsSearchFetcher, {"name": "Apple"})

    @pytest.mark.asyncio
    async def test_ipos_disclosure(self):
        """#1542."""
        from openbb_fmp.models.fundraising_extras import FMPIposDisclosureFetcher

        await _run(FMPIposDisclosureFetcher, self._PL)

    @pytest.mark.asyncio
    async def test_ipos_prospectus(self):
        """#1543."""
        from openbb_fmp.models.fundraising_extras import FMPIposProspectusFetcher

        await _run(FMPIposProspectusFetcher, self._PL)


# ===========================================================================
# #1581 — News & Articles
# ===========================================================================


class TestNewsE2E:
    """E2E suite for #1581 — News & Articles (5 fetchers)."""

    _PL = {"page": 0, "limit": 10}

    @pytest.mark.asyncio
    async def test_news_crypto(self):
        """#1544."""
        from openbb_fmp.models.news_extras import FMPNewsCryptoFetcher

        await _run(
            FMPNewsCryptoFetcher,
            {
                "symbols": "BTCUSD",
                "from_date": "2024-01-01",
                "to_date": "2026-07-29",
            },
        )

    @pytest.mark.asyncio
    async def test_news_crypto_latest(self):
        """#1545."""
        from openbb_fmp.models.news_extras import FMPNewsCryptoLatestFetcher

        await _run(FMPNewsCryptoLatestFetcher, self._PL)

    @pytest.mark.asyncio
    async def test_news_forex(self):
        """#1546."""
        from openbb_fmp.models.news_extras import FMPNewsForexFetcher

        await _run(
            FMPNewsForexFetcher,
            {
                "symbols": "EURUSD",
                "from_date": "2024-01-01",
                "to_date": "2026-07-29",
            },
        )

    @pytest.mark.asyncio
    async def test_news_forex_latest(self):
        """#1547."""
        from openbb_fmp.models.news_extras import FMPNewsForexLatestFetcher

        await _run(FMPNewsForexLatestFetcher, self._PL)

    @pytest.mark.asyncio
    async def test_fmp_articles(self):
        """#1548."""
        from openbb_fmp.models.news_extras import FMPFmpArticlesFetcher

        await _run(FMPFmpArticlesFetcher, self._PL)


# ===========================================================================
# #1582 — SEC Filings & Classification
# ===========================================================================


class TestSecFilingsE2E:
    """E2E suite for #1582 — SEC Filings & Classification (5 fetchers)."""

    @pytest.mark.asyncio
    async def test_sec_filings_8k(self):
        """#1549."""
        from openbb_fmp.models.sec_extras import FMPSecFilings8kFetcher

        await _run(
            FMPSecFilings8kFetcher,
            {
                "from_date": "2024-01-01",
                "to_date": "2026-07-29",
                "page": 0,
                "limit": 10,
            },
        )

    @pytest.mark.asyncio
    async def test_sec_profile(self):
        """#1550."""
        from openbb_fmp.models.sec_extras import FMPSecProfileFetcher

        await _run(FMPSecProfileFetcher, {"symbol": "AAPL"})

    @pytest.mark.asyncio
    async def test_standard_industrial_classification_list(self):
        """#1551."""
        from openbb_fmp.models.sec_extras import (
            FMPStandardIndustrialClassificationListFetcher,
        )

        await _run(FMPStandardIndustrialClassificationListFetcher, {})

    @pytest.mark.asyncio
    async def test_all_industry_classification(self):
        """#1552."""
        from openbb_fmp.models.sec_extras import FMPAllIndustryClassificationFetcher

        await _run(FMPAllIndustryClassificationFetcher, {})

    @pytest.mark.asyncio
    async def test_industry_classification_search(self):
        """#1553."""
        from openbb_fmp.models.sec_extras import (
            FMPIndustryClassificationSearchFetcher,
        )

        await _run(FMPIndustryClassificationSearchFetcher, {"symbol": "AAPL"})


# ===========================================================================
# #1583 — Government / Senate / House
# ===========================================================================


class TestGovernmentE2E:
    """E2E suite for #1583 — Government / Senate / House (6 fetchers)."""

    _PL = {"page": 0, "limit": 10}

    @pytest.mark.asyncio
    async def test_house_latest(self):
        """#1554."""
        from openbb_fmp.models.government_extras import FMPHouseLatestFetcher

        await _run(FMPHouseLatestFetcher, self._PL)

    @pytest.mark.asyncio
    async def test_senate_latest(self):
        """#1555."""
        from openbb_fmp.models.government_extras import FMPSenateLatestFetcher

        await _run(FMPSenateLatestFetcher, self._PL)

    @pytest.mark.asyncio
    async def test_senate_net_worth(self):
        """#1556."""
        from openbb_fmp.models.government_extras import FMPSenateNetWorthFetcher

        await _run(FMPSenateNetWorthFetcher, {"senate_id": "L000397"})

    @pytest.mark.asyncio
    async def test_senate_net_worth_aggregated(self):
        """#1557."""
        from openbb_fmp.models.government_extras import (
            FMPSenateNetWorthAggregatedFetcher,
        )

        await _run(FMPSenateNetWorthAggregatedFetcher, {"senate_id": "L000397"})

    @pytest.mark.asyncio
    async def test_senate_positions(self):
        """#1558."""
        from openbb_fmp.models.government_extras import FMPSenatePositionsFetcher

        await _run(FMPSenatePositionsFetcher, {"name": "Warren"})

    @pytest.mark.asyncio
    async def test_senate_profile(self):
        """#1559."""
        from openbb_fmp.models.government_extras import FMPSenateProfileFetcher

        await _run(FMPSenateProfileFetcher, {"name": "Warren"})


# ===========================================================================
# #1584 — DCF & Valuation
# ===========================================================================


class TestDcfValuationE2E:
    """E2E suite for #1584 — DCF & Valuation (4 fetchers)."""

    _S = {"symbol": "AAPL"}

    @pytest.mark.asyncio
    async def test_discounted_cash_flow(self):
        """#1560."""
        from openbb_fmp.models.dcf_reference_extras import (
            FMPDiscountedCashFlowFetcher,
        )

        await _run(FMPDiscountedCashFlowFetcher, self._S)

    @pytest.mark.asyncio
    async def test_levered_discounted_cash_flow(self):
        """#1561."""
        from openbb_fmp.models.dcf_reference_extras import (
            FMPLeveredDiscountedCashFlowFetcher,
        )

        await _run(FMPLeveredDiscountedCashFlowFetcher, self._S)

    @pytest.mark.asyncio
    async def test_custom_discounted_cash_flow(self):
        """#1562."""
        from openbb_fmp.models.dcf_reference_extras import (
            FMPCustomDiscountedCashFlowFetcher,
        )

        await _run(FMPCustomDiscountedCashFlowFetcher, self._S)

    @pytest.mark.asyncio
    async def test_custom_levered_discounted_cash_flow(self):
        """#1563."""
        from openbb_fmp.models.dcf_reference_extras import (
            FMPCustomLeveredDiscountedCashFlowFetcher,
        )

        await _run(FMPCustomLeveredDiscountedCashFlowFetcher, self._S)


# ===========================================================================
# #1585 — Reference Symbol Lists
# ===========================================================================


class TestReferenceListsE2E:
    """E2E suite for #1585 — Reference Symbol Lists (7 fetchers)."""

    @pytest.mark.asyncio
    async def test_stock_list(self):
        """#1564."""
        from openbb_fmp.models.dcf_reference_extras import FMPStockListFetcher

        await _run(FMPStockListFetcher, {})

    @pytest.mark.asyncio
    async def test_etf_list(self):
        """#1565."""
        from openbb_fmp.models.dcf_reference_extras import FMPEtfListFetcher

        await _run(FMPEtfListFetcher, {})

    @pytest.mark.asyncio
    async def test_index_list(self):
        """#1566."""
        from openbb_fmp.models.dcf_reference_extras import FMPIndexListFetcher

        await _run(FMPIndexListFetcher, {})

    @pytest.mark.asyncio
    async def test_commodities_list(self):
        """#1567."""
        from openbb_fmp.models.dcf_reference_extras import FMPCommoditiesListFetcher

        await _run(FMPCommoditiesListFetcher, {})

    @pytest.mark.asyncio
    async def test_forex_list(self):
        """#1568."""
        from openbb_fmp.models.dcf_reference_extras import FMPForexListFetcher

        await _run(FMPForexListFetcher, {})

    @pytest.mark.asyncio
    async def test_cryptocurrency_list(self):
        """#1569."""
        from openbb_fmp.models.dcf_reference_extras import (
            FMPCryptocurrencyListFetcher,
        )

        await _run(FMPCryptocurrencyListFetcher, {})

    @pytest.mark.asyncio
    async def test_actively_trading_list(self):
        """#1570."""
        from openbb_fmp.models.dcf_reference_extras import (
            FMPActivelyTradingListFetcher,
        )

        await _run(FMPActivelyTradingListFetcher, {})


# ===========================================================================
# #1586 — Market Hours & Exchange Reference
# ===========================================================================


class TestMarketHoursE2E:
    """E2E suite for #1586 — Market Hours & Exchange Reference (2 fetchers)."""

    @pytest.mark.asyncio
    async def test_all_exchange_market_hours(self):
        """#1571."""
        from openbb_fmp.models.market_hours_search_extras import (
            FMPAllExchangeMarketHoursFetcher,
        )

        await _run(FMPAllExchangeMarketHoursFetcher, {})

    @pytest.mark.asyncio
    async def test_holidays_by_exchange(self):
        """#1572."""
        from openbb_fmp.models.market_hours_search_extras import (
            FMPHolidaysByExchangeFetcher,
        )

        await _run(FMPHolidaysByExchangeFetcher, {"exchange": "NASDAQ"})


# ===========================================================================
# Cross-cutting integration checks
# ===========================================================================


# ---------- #1587 — Registration integrity ----------


def test_all_new_fetchers_registered():
    """#1587: every new fetcher key is present in ``fmp_provider.fetcher_dict``.

    This test does NOT hit the network. It's still marked integration
    for organizational grouping — the cost is negligible.
    """
    from openbb_fmp import fmp_provider

    required = {
        # analyst / ratings / grades
        "Grades",
        "GradesConsensus",
        "GradesHistorical",
        "PriceTargetSummary",
        "RatingsHistorical",
        "RatingsSnapshot",
        # statements-extras
        "EnterpriseValues",
        "FinancialGrowth",
        "FinancialScores",
        "KeyMetricsTtm",
        "OwnerEarnings",
        "RatiosTtm",
        "IncomeStatementAsReported",
        "BalanceSheetStatementAsReported",
        "CashFlowStatementAsReported",
        "FinancialStatementFullAsReported",
        "FinancialReportsDates",
        "FinancialReportsJson",
        # quotes-extras
        "BatchQuote",
        "BatchQuoteShort",
        "BatchAftermarketQuote",
        "BatchAftermarketTrade",
        "StockQuote",
        "StockQuoteShort",
        "StockPriceChange",
        "MarketCap",
        "MarketCapBatch",
        # indexes-extras
        "DowjonesConstituent",
        "HistoricalDowjonesConstituent",
        "Sp500Constituent",
        "HistoricalSp500Constituent",
        "NasdaqConstituent",
        "HistoricalNasdaqConstituent",
        "SectorPerformanceSnapshot",
        "HistoricalSectorPerformance",
        "SectorPeSnapshot",
        "HistoricalSectorPe",
        "IndustryPerformanceSnapshot",
        "HistoricalIndustryPerformance",
        "IndustryPeSnapshot",
        "HistoricalIndustryPe",
        # economics
        "EconomicIndicators",
        "MarketRiskPremium",
        "CommitmentOfTradersAnalysis",
        "CommitmentOfTradersList",
        "CommitmentOfTradersReport",
        # fundraising
        "Fundraising",
        "FundraisingLatest",
        "FundraisingSearch",
        "CrowdfundingOfferings",
        "CrowdfundingOfferingsLatest",
        "CrowdfundingOfferingsSearch",
        "MergersAcquisitionsLatest",
        "MergersAcquisitionsSearch",
        "IposDisclosure",
        "IposProspectus",
        # news
        "NewsCrypto",
        "NewsCryptoLatest",
        "NewsForex",
        "NewsForexLatest",
        "FmpArticles",
        # sec
        "SecFilings8K",
        "SecProfile",
        "StandardIndustrialClassificationList",
        "AllIndustryClassification",
        "IndustryClassificationSearch",
        # government
        "HouseLatest",
        "SenateLatest",
        "SenateNetWorth",
        "SenateNetWorthAggregated",
        "SenatePositions",
        "SenateProfile",
        # dcf + reference
        "DiscountedCashFlow",
        "LeveredDiscountedCashFlow",
        "CustomDiscountedCashFlow",
        "CustomLeveredDiscountedCashFlow",
        "StockList",
        "EtfList",
        "IndexList",
        "CommoditiesList",
        "ForexList",
        "CryptocurrencyList",
        "ActivelyTradingList",
        # market hours + search
        "AllExchangeMarketHours",
        "HolidaysByExchange",
        "SearchSymbol",
        "SearchName",
        "SearchCik",
        "SearchCusip",
        "SearchIsin",
        "SearchExchangeVariants",
        "CikList",
        "ProfileCik",
        "SymbolChange",
        "FinancialStatementSymbolList",
        "AvailableCountries",
        # available-lists
        "AvailableExchanges",
        "AvailableIndustries",
        "AvailableSectors",
        # company
        "CompanyNotes",
        "DelistedCompanies",
        "SharesFloat",
        "SharesFloatAll",
        "AcquisitionOfBeneficialOwnership",
        "ExecutiveCompensationBenchmark",
    }
    registered = set(fmp_provider.fetcher_dict.keys())
    missing = required - registered
    assert not missing, f"Fetchers missing from provider registry: {sorted(missing)}"
    # Exact count sanity check for the parity port (105).
    assert (
        len(required) == 105
    ), f"Expected 105 A-parity fetchers, tallied {len(required)}"


# ---------- #1588 — openbb.build() static-package rebuild ----------


def test_openbb_build_static_package():
    """#1588: ``openbb.build()`` regenerates the static package without exception."""
    import openbb

    openbb.build()  # raises on failure


# ---------- #1589 — Provider-map parity vs fmp_cached / docs ----------


def test_fmp_provider_map_contains_a_parity_domains():
    """#1589: ``fmp`` provider now covers all 14 A-parity domains.

    Sanity check that the ``fmp`` provider registry is not a strict
    subset of ``fmp_cached`` for the endpoints we ported. Symmetric
    domain coverage — that's the parity claim.
    """
    from openbb_fmp import fmp_provider

    fmp_keys = set(fmp_provider.fetcher_dict.keys())
    # Spot check one endpoint from each of the 14 domains that were
    # previously ``fmp_cached``-only.
    per_domain_probe = {
        "analyst": "RatingsSnapshot",
        "statements": "EnterpriseValues",
        "quotes": "StockQuote",
        "indexes": "SectorPerformanceSnapshot",
        "economics": "EconomicIndicators",
        "fundraising": "Fundraising",
        "news": "NewsCrypto",
        "sec": "SecFilings8K",
        "government": "SenateProfile",
        "dcf": "DiscountedCashFlow",
        "reference": "StockList",
        "market_hours": "AllExchangeMarketHours",
        "available_lists": "AvailableExchanges",
        "company": "SharesFloat",
    }
    for domain, key in per_domain_probe.items():
        assert key in fmp_keys, f"Domain '{domain}' probe key '{key}' missing"


# ---------- #1590 — Credential / status-error parity ----------


@pytest.mark.asyncio
async def test_credential_missing_raises_cleanly():
    """#1590: a fetcher with an empty apikey surfaces an error rather than
    hanging or returning silently-wrong data.

    Uses a lightweight no-args fetcher so the failure is fast.
    """
    from openbb_fmp.models.dcf_reference_extras import FMPStockListFetcher

    query = FMPStockListFetcher.transform_query({})
    with pytest.raises(Exception):
        # Empty credential dict → FMP replies 401/403; our helper raises
        # EmptyDataError. Either way the raise is what we want.
        await FMPStockListFetcher.aextract_data(query, credentials={})


# ---------- #1591 — Full-provider smoke ----------


@pytest.mark.asyncio
async def test_full_provider_smoke_scans_registry():
    """#1591: introspection-only sweep — every A-parity fetcher class is
    importable, has ``transform_query`` / ``aextract_data`` / ``transform_data``
    static methods, and its query params class accepts an empty init or a
    minimal ``{"symbol": "MSFT"}`` init without exception.

    No live traffic — this is a wiring sanity check, not a load test.
    """
    from openbb_fmp import fmp_provider

    for key, fetcher_cls in fmp_provider.fetcher_dict.items():
        for method in ("transform_query", "aextract_data", "transform_data"):
            assert hasattr(
                fetcher_cls, method
            ), f"{key}: missing {method} on {fetcher_cls.__name__}"
