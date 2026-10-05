"""Statement extras, DCF and as-reported route tests."""

# ruff: noqa: D103

import json
from dataclasses import make_dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_fmp.models.statements_extras import FMPFinancialScoresFetcher
from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.routers import statements_router
from openbb_fmp_cached.routers.statements_router import router
from pydantic import ValidationError

MODELS = {
    "KeyMetricsTtm": ("key_metrics_ttm", ("symbol",)),
    "RatiosTtm": ("ratios_ttm", ("symbol",)),
    "FinancialScores": ("financial_scores", ("symbol",)),
    "OwnerEarnings": ("owner_earnings", ("symbol",)),
    "EnterpriseValues": ("enterprise_values", ("symbol",)),
    "FinancialGrowth": ("financial_growth", ("symbol",)),
    "FinancialReportsDates": ("financial_reports_dates", ("symbol",)),
    "DiscountedCashFlow": ("discounted_cash_flow", ("symbol",)),
    "LeveredDiscountedCashFlow": (
        "levered_discounted_cash_flow",
        ("symbol",),
    ),
    "CustomDiscountedCashFlow": (
        "custom_discounted_cash_flow",
        ("symbol",),
    ),
    "CustomLeveredDiscountedCashFlow": (
        "custom_levered_discounted_cash_flow",
        ("symbol",),
    ),
    "ProfileCik": ("profile_cik", ("cik",)),
    "IncomeStatementAsReported": (
        "income_statement_as_reported",
        ("symbol",),
    ),
    "BalanceSheetStatementAsReported": (
        "balance_sheet_statement_as_reported",
        ("symbol",),
    ),
    "CashFlowStatementAsReported": (
        "cash_flow_statement_as_reported",
        ("symbol",),
    ),
    "FinancialStatementFullAsReported": (
        "financial_statement_full_as_reported",
        ("symbol",),
    ),
    "FinancialReportsJson": (
        "financial_reports_json",
        ("symbol", "year", "period"),
    ),
}


def _manifest() -> list[dict]:
    path = Path(__file__).parents[1] / "openbb_fmp_cached/assets/model_routes.json"
    return json.loads(path.read_text(encoding="utf-8"))["routes"]


def test_seventeen_statement_models_have_explicit_routes():
    evidence = {row["model"]: row for row in _manifest() if row["model"] in MODELS}
    assert set(evidence) == set(MODELS)
    paths = {route.path for route in router.api_router.routes}
    for model, (command, arguments) in MODELS.items():
        assert evidence[model]["command"] == command
        assert set(evidence[model]["arguments"]) == set(arguments)
        assert f"/{command}" in paths


@pytest.mark.parametrize(
    ("model", "params"),
    [
        ("KeyMetricsTtm", {"symbol": "AAPL"}),
        ("RatiosTtm", {"symbol": "AAPL"}),
        ("ProfileCik", {"cik": "0000320193"}),
        (
            "FinancialReportsJson",
            {"symbol": "AAPL", "year": 2025, "period": "FY"},
        ),
    ],
)
def test_statement_queries_preserve_period_and_identifier_strings(model, params):
    fetcher = fmp_cached_provider.fetcher_dict[model]
    query = fetcher.transform_query(params)
    for key, value in params.items():
        assert getattr(query, key) == value


@pytest.mark.parametrize("model", MODELS)
def test_statement_required_arguments_are_enforced(model):
    fetcher = fmp_cached_provider.fetcher_dict[model]
    with pytest.raises(ValidationError):
        fetcher.transform_query({})


def test_as_reported_nullable_and_nested_fields_remain_structured():
    fetcher = fmp_cached_provider.fetcher_dict["IncomeStatementAsReported"]
    query = fetcher.transform_query({"symbol": "AAPL"})
    rows = fetcher.transform_data(
        query,
        [
            {
                "symbol": "AAPL",
                "fiscalYear": "2025",
                "period": "FY",
                "reportedCurrency": None,
                "date": "2025-09-30",
                "data": {"Revenue": 100},
            }
        ],
    )
    assert rows[0].reported_currency is None
    assert rows[0].data == {"Revenue": 100}


def test_financial_report_json_keeps_bounded_structured_result():
    fetcher = fmp_cached_provider.fetcher_dict["FinancialReportsJson"]
    query = fetcher.transform_query({"symbol": "AAPL", "year": 2025, "period": "Q1"})
    rows = fetcher.transform_data(
        query,
        [{"symbol": "AAPL", "year": "2025", "period": "Q1", "data": {"x": 1}}],
    )
    assert len(rows) == 1
    assert rows[0].data == {"x": 1}
    assert rows[0].year == 2025
    assert isinstance(rows[0].year, int)
    with pytest.raises(ValidationError):
        fetcher.transform_query({"symbol": "AAPL", "year": 2025, "period": "INVALID"})


def test_statement_routes_reject_unknown_arguments():
    """Route allowlists reject undocumented report and DCF controls."""
    app = FastAPI()
    app.include_router(router.api_router)
    response = TestClient(app).get(
        "/financial_reports_json",
        params={
            "provider": "fmp_cached",
            "symbol": "AAPL",
            "year": 2025,
            "period": "FY",
            "unbounded": "true",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown query arguments: unbounded"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", MODELS)
async def test_all_statement_commands_dispatch_synthetic_results(model):
    """Every promoted handler reaches Query/OBBject dispatch."""
    command = MODELS[model][0]
    function = getattr(statements_router, command)
    provider_choices = make_dataclass(
        "ProviderChoices",
        [("provider", str)],
    )(provider="fmp_cached")
    standard_params = make_dataclass("StandardParams", [])()
    extra_params = make_dataclass("ExtraParams", [])()
    response = statements_router.OBBject(results=[{"model": model}])
    with (
        patch.object(statements_router, "Query", return_value=object()) as query,
        patch.object(
            statements_router.OBBject,
            "from_query",
            new=AsyncMock(return_value=response),
        ) as from_query,
    ):
        result = await function(
            None,
            provider_choices,
            standard_params,
            extra_params,
        )
    assert result.results == [{"model": model}]
    query.assert_called_once()
    from_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_cached_entitlement_error_never_falls_back_to_fmp():
    """A cached-provider 402 remains an explicit provider failure."""
    fetcher = fmp_cached_provider.fetcher_dict["FinancialScores"]
    query = fetcher.transform_query({"symbol": "AAPL"})
    request = httpx.Request(
        "GET",
        "https://financialmodelingprep.com/stable/financial-scores",
    )
    response = httpx.Response(402, request=request)
    error = httpx.HTTPStatusError(
        "Payment Required",
        request=request,
        response=response,
    )
    with (
        patch.object(
            fetcher,
            "_fetch",
            new=AsyncMock(side_effect=error),
        ),
        patch.object(
            FMPFinancialScoresFetcher,
            "aextract_data",
            new=AsyncMock(),
        ) as fallback,pytest.raises(httpx.HTTPStatusError)
    ):
        await fetcher.aextract_data(
            query,
            {"fmp_cached_api_key": "redacted"},
        )
    fallback.assert_not_awaited()


def test_existing_fundamental_models_are_not_replaced():
    promoted = set(MODELS)
    assert promoted.isdisjoint(
        {
            "BalanceSheet",
            "IncomeStatement",
            "CashFlowStatement",
            "FinancialRatios",
            "KeyMetrics",
        }
    )
