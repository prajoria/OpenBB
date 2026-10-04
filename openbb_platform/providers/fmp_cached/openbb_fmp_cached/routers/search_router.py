"""Identifier and text-search routes."""

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

router = Router(prefix="", description="FMP identifier and text search.")


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
                "subCategory": "Search",
                "refetchInterval": False,
            },
        )(func)

    return decorator


@_command("SearchCik", "Search companies by string-preserving CIK.", {"cik"})
async def search_cik(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "SearchCusip",
    "Search securities by CUSIP text.",
    {"cusip", "query"},
    {"query"},
)
async def search_cusip(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "SearchIsin",
    "Search securities by ISIN text.",
    {"isin", "query"},
    {"query"},
)
async def search_isin(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("SearchName", "Search securities by company name.", {"query"})
async def search_name(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("SearchSymbol", "Search securities by ticker text.", {"query"})
async def search_symbol(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "SearchExchangeVariants",
    "Search exchange-specific symbol variants.",
    {"symbol", "query"},
    {"query"},
)
async def search_exchange_variants(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())
