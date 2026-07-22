"""Unit tests for W1 statement-extras fetchers (#1084 #1103-#1106 #1132-#1136 #1140 #1141)."""

from __future__ import annotations

import pytest


def test_key_metrics_ttm_extra_allow():
    """key-metrics-ttm returns many TTM columns — extra=allow preserves them."""
    from openbb_fmp_cached.models.statement_extras import (
        FMPCachedKeyMetricsTtmFetcher,
    )

    rows = [
        {
            "symbol": "AAPL",
            "marketCap": 4813e9,
            "enterpriseValueTTM": 4862e9,
            "evToSalesTTM": 10.77,
        }
    ]
    out = FMPCachedKeyMetricsTtmFetcher.transform_data(None, rows)
    assert out[0].symbol == "AAPL"
    d = out[0].model_dump()
    assert d["marketCap"] == 4813e9
    assert d["evToSalesTTM"] == pytest.approx(10.77)


def test_ratios_ttm_extra_allow():
    """ratios-ttm returns many ratio columns — extra=allow preserves them."""
    from openbb_fmp_cached.models.statement_extras import FMPCachedRatiosTtmFetcher

    rows = [{"symbol": "AAPL", "grossProfitMarginTTM": 0.478, "ebitMarginTTM": 0.327}]
    out = FMPCachedRatiosTtmFetcher.transform_data(None, rows)
    d = out[0].model_dump()
    assert d["grossProfitMarginTTM"] == pytest.approx(0.478)


def test_financial_scores_maps_altman_and_piotroski():
    """AltmanZScore + piotroskiScore + reportedCurrency all remap."""
    from openbb_fmp_cached.models.statement_extras import (
        FMPCachedFinancialScoresFetcher,
    )

    rows = [
        {
            "symbol": "AAPL",
            "reportedCurrency": "USD",
            "altmanZScore": 13.52,
            "piotroskiScore": 9,
            "workingCapital": 9473000000,
        }
    ]
    out = FMPCachedFinancialScoresFetcher.transform_data(None, rows)
    assert out[0].reported_currency == "USD"
    assert out[0].altman_z_score == pytest.approx(13.52)
    assert out[0].piotroski_score == 9


def test_owner_earnings_maps_fiscal_year_period():
    """ReportedCurrency + fiscalYear alias mapping."""
    from openbb_fmp_cached.models.statement_extras import (
        FMPCachedOwnerEarningsFetcher,
    )

    rows = [
        {
            "symbol": "AAPL",
            "reportedCurrency": "USD",
            "fiscalYear": "2026",
            "period": "Q2",
            "date": "2026-03-28",
        }
    ]
    out = FMPCachedOwnerEarningsFetcher.transform_data(None, rows)
    assert out[0].fiscal_year == "2026"
    assert out[0].period == "Q2"


def test_financial_reports_dates_maps_link_fields():
    """LinkJson + linkXlsx + fiscalYear alias mapping."""
    from openbb_fmp_cached.models.statement_extras import (
        FMPCachedFinancialReportsDatesFetcher,
    )

    rows = [
        {
            "symbol": "AAPL",
            "fiscalYear": 2026,
            "period": "Q2",
            "linkJson": "https://financialmodelingprep.com/stable/financial-reports-json?symbol=AAPL",
            "linkXlsx": "https://financialmodelingprep.com/stable/financial-reports-xlsx?symbol=AAPL",
        }
    ]
    out = FMPCachedFinancialReportsDatesFetcher.transform_data(None, rows)
    assert out[0].link_json.startswith("https://")
    assert out[0].link_xlsx.startswith("https://")


def test_dcf_typed_fields():
    """discounted-cash-flow has 3 core fields."""
    from openbb_fmp_cached.models.statement_extras import FMPCachedDcfFetcher

    rows = [
        {"symbol": "AAPL", "date": "2026-07-21", "dcf": 148.35, "Stock Price": 327.87}
    ]
    out = FMPCachedDcfFetcher.transform_data(None, rows)
    assert out[0].dcf == pytest.approx(148.35)
    # 'Stock Price' preserved via extra=allow (has a space in name)
    d = out[0].model_dump()
    assert "Stock Price" in d


def test_custom_dcf_year_str():
    """custom-DCF returns year as string, not int."""
    from openbb_fmp_cached.models.statement_extras import FMPCachedCustomDcfFetcher

    rows = [{"year": "2030", "symbol": "AAPL", "revenue": 529e9}]
    out = FMPCachedCustomDcfFetcher.transform_data(None, rows)
    assert out[0].year == "2030"
    assert isinstance(out[0].year, str)


def test_profile_cik_uses_cik_query_field():
    """profile-cik requires cik param, not symbol."""
    from openbb_fmp_cached.models.statement_extras import FMPCachedProfileCikFetcher

    assert FMPCachedProfileCikFetcher._query_field == "cik"


def test_all_twelve_registered_in_provider():
    """Provider registration is what makes the coverage gate see them."""
    from openbb_fmp_cached import fmp_cached_provider

    for name in (
        "KeyMetricsTtm",
        "RatiosTtm",
        "FinancialScores",
        "OwnerEarnings",
        "EnterpriseValues",
        "FinancialGrowth",
        "FinancialReportsDates",
        "DiscountedCashFlow",
        "LeveredDiscountedCashFlow",
        "CustomDiscountedCashFlow",
        "CustomLeveredDiscountedCashFlow",
        "ProfileCik",
    ):
        assert name in fmp_cached_provider.fetcher_dict, f"{name} not registered"


def test_query_field_configuration():
    """11 use 'symbol', profile-cik uses 'cik'."""
    from openbb_fmp_cached.models.statement_extras import (
        FMPCachedCustomDcfFetcher,
        FMPCachedCustomLeveredDcfFetcher,
        FMPCachedDcfFetcher,
        FMPCachedEnterpriseValuesFetcher,
        FMPCachedFinancialGrowthFetcher,
        FMPCachedFinancialReportsDatesFetcher,
        FMPCachedFinancialScoresFetcher,
        FMPCachedKeyMetricsTtmFetcher,
        FMPCachedLeveredDcfFetcher,
        FMPCachedOwnerEarningsFetcher,
        FMPCachedProfileCikFetcher,
        FMPCachedRatiosTtmFetcher,
    )

    for f in (
        FMPCachedKeyMetricsTtmFetcher,
        FMPCachedRatiosTtmFetcher,
        FMPCachedFinancialScoresFetcher,
        FMPCachedOwnerEarningsFetcher,
        FMPCachedEnterpriseValuesFetcher,
        FMPCachedFinancialGrowthFetcher,
        FMPCachedFinancialReportsDatesFetcher,
        FMPCachedDcfFetcher,
        FMPCachedLeveredDcfFetcher,
        FMPCachedCustomDcfFetcher,
        FMPCachedCustomLeveredDcfFetcher,
    ):
        assert f._query_field == "symbol", f"{f.__name__} wrong param"
    assert FMPCachedProfileCikFetcher._query_field == "cik"


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out."""
    from openbb_fmp_cached.models.statement_extras import FMPCachedDcfFetcher

    assert FMPCachedDcfFetcher.transform_data(None, []) == []
