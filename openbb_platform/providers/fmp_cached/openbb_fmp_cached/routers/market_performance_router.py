"""Sector and industry snapshot/history routes."""

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

router = Router(prefix="", description="FMP sector and industry performance.")


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


def _reject_unknown(
    arguments: set[str],
    cached_arguments: set[str] | None = None,
) -> Callable:
    async def dependency(request: Request) -> None:
        provider = request.query_params.get("provider")
        allowed = (
            cached_arguments
            if provider == "fmp_cached" and cached_arguments is not None
            else arguments
        )
        unknown = set(request.query_params) - {"provider"} - allowed
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown query arguments: {', '.join(sorted(unknown))}",
            )

    return dependency


def _command(
    model: str,
    description: str,
    arguments: set[str],
    cached_arguments: set[str] | None = None,
):
    def decorator(func):
        func.__doc__ = description
        return router.command(
            model=model,
            operation_id=f"fmp_cached_{func.__name__}",
            dependencies=[Depends(_reject_unknown(arguments, cached_arguments))],
            examples=[APIEx(parameters={"provider": "fmp_cached"})],
            widget_config={
                "name": func.__name__.replace("_", " ").title(),
                "description": description,
                "category": "FMP Cached",
                "subCategory": "Market Performance",
                "refetchInterval": False,
            },
        )(func)

    return decorator


@_command("SectorPerformanceSnapshot", "Get a sector performance snapshot.", {"date"})
async def sector_performance_snapshot(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "IndustryPerformanceSnapshot", "Get an industry performance snapshot.", {"date"}
)
async def industry_performance_snapshot(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("SectorPeSnapshot", "Get a sector PE snapshot.", {"date"})
async def sector_pe_snapshot(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("IndustryPeSnapshot", "Get an industry PE snapshot.", {"date"})
async def industry_pe_snapshot(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "HistoricalSectorPerformance",
    "Get historical sector performance.",
    {"sector", "from", "to"},
    {"sector"},
)
async def historical_sector_performance(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "HistoricalIndustryPerformance",
    "Get historical industry performance.",
    {"industry", "from", "to"},
    {"industry"},
)
async def historical_industry_performance(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "HistoricalSectorPe",
    "Get historical sector PE.",
    {"sector", "from", "to"},
    {"sector"},
)
async def historical_sector_pe(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "HistoricalIndustryPe",
    "Get historical industry PE.",
    {"industry", "from", "to"},
    {"industry"},
)
async def historical_industry_pe(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())
