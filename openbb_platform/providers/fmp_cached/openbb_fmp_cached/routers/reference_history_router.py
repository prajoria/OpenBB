"""Historical directory and change-reference routes."""

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

router = Router(prefix="", description="FMP historical reference directories.")


async def _dispatch(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await OBBject.from_query(Query(**locals()))


def _reject_unknown(
    allowed: set[str],
    cached_allowed: set[str] | None = None,
) -> Callable:
    async def dependency(request: Request) -> None:
        provider = request.query_params.get("provider")
        provider_allowed = (
            cached_allowed
            if provider == "fmp_cached" and cached_allowed is not None
            else allowed
        )
        unknown = set(request.query_params) - provider_allowed - {"provider"}
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown query arguments: {', '.join(sorted(unknown))}",
            )

    return dependency


def _command(
    model: str,
    description: str,
    arguments: set[str] | None = None,
    cached_arguments: set[str] | None = None,
):
    def decorator(func):
        func.__doc__ = description
        return router.command(
            model=model,
            operation_id=f"fmp_cached_{func.__name__}",
            dependencies=[
                Depends(
                    _reject_unknown(
                        arguments or set(),
                        cached_arguments,
                    )
                )
            ],
            examples=[APIEx(parameters={"provider": "fmp_cached"})],
            widget_config={
                "name": func.__name__.replace("_", " ").title(),
                "description": description,
                "category": "FMP Cached",
                "subCategory": "Reference History",
                "refetchInterval": False,
            },
        )(func)

    return decorator


@_command(
    "HistoricalDowjonesConstituent",
    "List historical Dow Jones constituent changes.",
)
async def historical_dowjones_constituent(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "HistoricalNasdaqConstituent",
    "List historical Nasdaq constituent changes.",
)
async def historical_nasdaq_constituent(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "HistoricalSp500Constituent",
    "List historical S&P 500 constituent changes.",
)
async def historical_sp500_constituent(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "SymbolChange",
    "List historical ticker-symbol changes.",
    {"from", "to"},
    set(),
)
async def symbol_change(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "SharesFloatAll",
    "List historical shares-float snapshots.",
    {"page", "limit"},
    set(),
)
async def shares_float_all(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())
