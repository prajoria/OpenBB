"""Analyst recommendations, ratings, grades and target routes."""

# ruff: noqa: D103
# pylint: disable=unused-argument

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

router = Router(prefix="", description="FMP analyst ratings and recommendations.")


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


async def _reject_unknown(request: Request) -> None:
    unknown = set(request.query_params) - {"provider", "symbol"}
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown query arguments: {', '.join(sorted(unknown))}",
        )


def _command(model: str, description: str):
    def decorator(func):
        func.__doc__ = description
        return router.command(
            model=model,
            operation_id=f"fmp_cached_{func.__name__}",
            dependencies=[Depends(_reject_unknown)],
            examples=[APIEx(parameters={"provider": "fmp_cached", "symbol": "AAPL"})],
            widget_config={
                "name": func.__name__.replace("_", " ").title(),
                "description": description,
                "category": "FMP Cached",
                "subCategory": "Analyst",
                "refetchInterval": False,
            },
        )(func)

    return decorator


@_command("AnalystRecommendations", "Get analyst recommendations.")
async def analyst_recommendations(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("RatingsSnapshot", "Get the current ratings snapshot.")
async def ratings_snapshot(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("RatingsHistorical", "Get historical ratings.")
async def ratings_historical(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("PriceTargetSummary", "Get the analyst price-target summary.")
async def price_target_summary(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("Grades", "Get individual analyst grade changes.")
async def grades(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("GradesHistorical", "Get historical analyst grade counts.")
async def grades_historical(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("GradesConsensus", "Get the current analyst grade consensus.")
async def grades_consensus(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())
