"""Statement extras, TTM, DCF and as-reported routes."""

# ruff: noqa: D103
# pylint: disable=unused-argument

from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request
from openbb_core.app.model.command_context import CommandContext
from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.provider_interface import (
    ExtraParams,
    ProviderChoices,
    StandardParams,
)
from openbb_core.app.query import Query
from openbb_core.app.router import Router

router = Router(prefix="", description="FMP statement extras and as-reported data.")


async def _dispatch(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await OBBject.from_query(
        Query(
            cc=cc,
            provider_choices=provider_choices,
            standard_params=standard_params,
            extra_params=extra_params,
        )
    )


def _reject_unknown(arguments: set[str]) -> Callable:
    async def dependency(request: Request) -> None:
        unknown = set(request.query_params) - {"provider"} - arguments
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown query arguments: {', '.join(sorted(unknown))}",
            )

    return dependency


def _command(model: str, description: str, arguments: set[str]):
    def decorator(func):
        func.__doc__ = description
        if "cik" in arguments:
            parameters: dict[str, Any] = {
                "provider": "fmp_cached",
                "cik": "0000320193",
            }
        elif "year" in arguments:
            parameters = {
                "provider": "fmp_cached",
                "symbol": "AAPL",
                "year": 2025,
                "period": "FY",
            }
        else:
            parameters = {"provider": "fmp_cached", "symbol": "AAPL"}
        return router.command(
            model=model,
            operation_id=f"fmp_cached_{func.__name__}",
            dependencies=[Depends(_reject_unknown(arguments))],
            examples=[APIEx(parameters=parameters)],
            widget_config={
                "name": func.__name__.replace("_", " ").title(),
                "description": description,
                "category": "FMP Cached",
                "subCategory": "Statements",
                "refetchInterval": False,
            },
        )(func)

    return decorator


@_command("KeyMetricsTtm", "Get trailing-twelve-month key metrics.", {"symbol"})
async def key_metrics_ttm(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("RatiosTtm", "Get trailing-twelve-month financial ratios.", {"symbol"})
async def ratios_ttm(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("FinancialScores", "Get financial health scores.", {"symbol"})
async def financial_scores(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("OwnerEarnings", "Get owner earnings.", {"symbol"})
async def owner_earnings(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("EnterpriseValues", "Get enterprise values.", {"symbol"})
async def enterprise_values(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("FinancialGrowth", "Get financial growth metrics.", {"symbol"})
async def financial_growth(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("FinancialReportsDates", "Get available financial report dates.", {"symbol"})
async def financial_reports_dates(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("DiscountedCashFlow", "Get discounted cash flow valuation.", {"symbol"})
async def discounted_cash_flow(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "LeveredDiscountedCashFlow",
    "Get levered discounted cash flow valuation.",
    {"symbol"},
)
async def levered_discounted_cash_flow(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "CustomDiscountedCashFlow", "Get custom discounted cash flow valuation.", {"symbol"}
)
async def custom_discounted_cash_flow(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "CustomLeveredDiscountedCashFlow", "Get custom levered DCF valuation.", {"symbol"}
)
async def custom_levered_discounted_cash_flow(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("ProfileCik", "Get a company profile by string-preserving CIK.", {"cik"})
async def profile_cik(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("IncomeStatementAsReported", "Get income statements as reported.", {"symbol"})
async def income_statement_as_reported(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "BalanceSheetStatementAsReported", "Get balance sheets as reported.", {"symbol"}
)
async def balance_sheet_statement_as_reported(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "CashFlowStatementAsReported", "Get cash flow statements as reported.", {"symbol"}
)
async def cash_flow_statement_as_reported(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "FinancialStatementFullAsReported",
    "Get full financial statements as reported.",
    {"symbol"},
)
async def financial_statement_full_as_reported(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "FinancialReportsJson",
    "Get structured financial report JSON.",
    {"symbol", "year", "period"},
)
async def financial_reports_json(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())
