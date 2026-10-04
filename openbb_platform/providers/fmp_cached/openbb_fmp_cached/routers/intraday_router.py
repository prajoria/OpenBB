"""Intraday, aftermarket, market-hours and single-parameter routes."""

# ruff: noqa: D103
# pylint: disable=unused-argument

from collections.abc import Callable

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

router = Router(prefix="", description="FMP intraday and market-session data.")


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
        unknown = set(request.query_params) - arguments - {"provider"}
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown query arguments: {', '.join(sorted(unknown))}",
            )

    return dependency


def _command(model: str, description: str, arguments: set[str]):
    def decorator(func):
        func.__doc__ = description
        return router.command(
            model=model,
            operation_id=f"fmp_cached_{func.__name__}",
            dependencies=[Depends(_reject_unknown(arguments))],
            examples=[APIEx(parameters={"provider": "fmp_cached"})],
            widget_config={
                "name": func.__name__.replace("_", " ").title(),
                "description": description,
                "category": "FMP Cached",
                "subCategory": "Intraday",
                "refetchInterval": False,
            },
        )(func)

    return decorator


@_command(
    "EquityIntradayHistorical",
    "Get intraday equity history with session filters.",
    {
        "symbol",
        "interval",
        "start_date",
        "end_date",
        "extended_hours",
    },
)
async def equity_intraday_historical(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "ExchangeMarketHours",
    "Get the current exchange market-hours reference.",
    set(),
)
async def exchange_market_hours(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("AftermarketTrade", "Get the latest aftermarket trade.", {"symbol"})
async def aftermarket_trade(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("AftermarketQuote", "Get the latest aftermarket quote.", {"symbol"})
async def aftermarket_quote(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("CompanyNotes", "Get company notes.", {"symbol"})
async def company_notes(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "ExecutiveCompensationBenchmark",
    "Get executive-compensation benchmarks by year.",
    {"year"},
)
async def executive_compensation_benchmark(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "HolidaysByExchange",
    "Get exchange holidays and timezone-aware sessions.",
    {"exchange"},
)
async def holidays_by_exchange(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "TechnicalIndicatorIntraday",
    "Get an intraday technical indicator.",
    {"symbol", "indicator", "period_length", "timeframe"},
)
async def technical_indicator_intraday(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "EquityQuoteBatchShort",
    "Get compact quotes for one or more symbols.",
    {"symbol"},
)
async def equity_quote_batch_short(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())
