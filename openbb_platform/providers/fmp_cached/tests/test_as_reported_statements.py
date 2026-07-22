"""Unit tests for W1 as-reported + financial-reports-json fetchers (#1142 #1146-#1149)."""

from __future__ import annotations

import pytest


@pytest.fixture
def _as_reported_rows():
    return [
        {
            "symbol": "AAPL",
            "fiscalYear": 2025,
            "period": "FY",
            "reportedCurrency": "USD",
            "date": "2025-09-26",
            "data": {"revenue": 383285000000, "netIncome": 100000000000},
        }
    ]


def test_income_statement_as_reported_maps_fields(_as_reported_rows):
    """FiscalYear + reportedCurrency remap; nested 'data' dict preserved."""
    from openbb_fmp_cached.models.as_reported_statements import (
        FMPCachedIncomeStatementAsReportedFetcher,
    )

    out = FMPCachedIncomeStatementAsReportedFetcher.transform_data(
        None, _as_reported_rows
    )
    assert out[0].symbol == "AAPL"
    assert out[0].fiscal_year == 2025
    assert out[0].reported_currency == "USD"
    assert out[0].data == {"revenue": 383285000000, "netIncome": 100000000000}


def test_balance_sheet_as_reported_same_shape(_as_reported_rows):
    """Balance-sheet-as-reported uses the same shared Data class."""
    from openbb_fmp_cached.models.as_reported_statements import (
        FMPCachedBalanceSheetAsReportedFetcher,
    )

    out = FMPCachedBalanceSheetAsReportedFetcher.transform_data(None, _as_reported_rows)
    assert out[0].fiscal_year == 2025


def test_cash_flow_as_reported_same_shape(_as_reported_rows):
    """Cash-flow-as-reported uses the same shared Data class."""
    from openbb_fmp_cached.models.as_reported_statements import (
        FMPCachedCashFlowAsReportedFetcher,
    )

    out = FMPCachedCashFlowAsReportedFetcher.transform_data(None, _as_reported_rows)
    assert out[0].reported_currency == "USD"


def test_full_as_reported_same_shape(_as_reported_rows):
    """Full-as-reported uses the same shared Data class."""
    from openbb_fmp_cached.models.as_reported_statements import (
        FMPCachedFinancialStatementFullAsReportedFetcher,
    )

    out = FMPCachedFinancialStatementFullAsReportedFetcher.transform_data(
        None, _as_reported_rows
    )
    assert out[0].date == "2025-09-26"


def test_financial_reports_json_extra_allow():
    """financial-reports-json has arbitrary sections — extra=allow preserves them."""
    from openbb_fmp_cached.models.as_reported_statements import (
        FMPCachedFinancialReportsJsonData,
    )

    row = {
        "symbol": "AAPL",
        "period": "Q1",
        "year": "2025",
        "Cover Page": [{"info": "..."}],
        "Balance Sheet": [{"cash": 1000}],
    }
    obj = FMPCachedFinancialReportsJsonData.model_validate(row)
    assert obj.symbol == "AAPL"
    assert obj.period == "Q1"
    assert obj.year == "2025"
    d = obj.model_dump()
    # Sections preserved via extra=allow (dict keys w/ spaces)
    assert "Cover Page" in d
    assert "Balance Sheet" in d


def test_financial_reports_json_requires_three_params():
    """_SymbolYearPeriodQueryParams requires symbol + year + period."""
    from openbb_fmp_cached.models.as_reported_statements import (
        _SymbolYearPeriodQueryParams,
    )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _SymbolYearPeriodQueryParams(symbol="AAPL")  # missing year+period
    # Full params succeed
    q = _SymbolYearPeriodQueryParams(symbol="AAPL", year="2025", period="Q1")
    assert q.symbol == "AAPL"
    assert q.year == "2025"
    assert q.period == "Q1"


def test_all_five_registered_in_provider():
    """Provider registration is what makes the coverage gate see them."""
    from openbb_fmp_cached import fmp_cached_provider

    for name in (
        "IncomeStatementAsReported",
        "BalanceSheetStatementAsReported",
        "CashFlowStatementAsReported",
        "FinancialStatementFullAsReported",
        "FinancialReportsJson",
    ):
        assert name in fmp_cached_provider.fetcher_dict, f"{name} not registered"


def test_as_reported_query_field_is_symbol():
    """All 4 as-reported fetchers use symbol= param."""
    from openbb_fmp_cached.models.as_reported_statements import (
        FMPCachedBalanceSheetAsReportedFetcher,
        FMPCachedCashFlowAsReportedFetcher,
        FMPCachedFinancialStatementFullAsReportedFetcher,
        FMPCachedIncomeStatementAsReportedFetcher,
    )

    for f in (
        FMPCachedIncomeStatementAsReportedFetcher,
        FMPCachedBalanceSheetAsReportedFetcher,
        FMPCachedCashFlowAsReportedFetcher,
        FMPCachedFinancialStatementFullAsReportedFetcher,
    ):
        assert f._query_field == "symbol", f"{f.__name__} wrong param"


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out."""
    from openbb_fmp_cached.models.as_reported_statements import (
        FMPCachedIncomeStatementAsReportedFetcher,
    )

    assert FMPCachedIncomeStatementAsReportedFetcher.transform_data(None, []) == []
