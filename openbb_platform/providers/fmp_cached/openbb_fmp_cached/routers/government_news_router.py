"""Government disclosures, news, articles and COT routes."""

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

router = Router(prefix="", description="FMP government disclosure and news data.")


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
    arguments: set[str], cached_arguments: set[str] | None = None
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
        parameters = {"provider": "fmp_cached"}
        if "symbols" in (cached_arguments or arguments):
            parameters["symbols"] = "BTCUSD,ETHUSD"
        if "senate_id" in (cached_arguments or arguments):
            parameters["senate_id"] = "A000360"
        return router.command(
            model=model,
            operation_id=f"fmp_cached_{func.__name__}",
            dependencies=[Depends(_reject_unknown(arguments, cached_arguments))],
            examples=[APIEx(parameters=parameters)],
            widget_config={
                "name": func.__name__.replace("_", " ").title(),
                "description": description,
                "category": "FMP Cached",
                "subCategory": "Government and News",
                "refetchInterval": False,
            },
        )(func)

    return decorator


@_command("CommitmentOfTradersAnalysis", "Get COT analysis.", {"symbol"}, set())
async def commitment_of_traders_analysis(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("CommitmentOfTradersReport", "Get COT reports.", {"symbol"}, set())
async def commitment_of_traders_report(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("FmpArticles", "Get FMP articles as external data.", {"page", "limit"}, set())
async def fmp_articles(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("HouseLatest", "Get latest House disclosures.", {"page", "limit"}, set())
async def house_latest(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "NewsCrypto", "Get crypto news by symbols.", {"symbols", "from", "to"}, {"symbols"}
)
async def news_crypto(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("NewsCryptoLatest", "Get latest crypto news.", {"page", "limit"}, set())
async def news_crypto_latest(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "NewsForex", "Get forex news by symbols.", {"symbols", "from", "to"}, {"symbols"}
)
async def news_forex(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("NewsForexLatest", "Get latest forex news.", {"page", "limit"}, set())
async def news_forex_latest(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("SenateLatest", "Get latest Senate disclosures.", {"page", "limit"}, set())
async def senate_latest(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("SenateNetWorth", "Get Senate member net worth.", {"senate_id"})
async def senate_net_worth(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("SenateNetWorthAggregated", "Get aggregated Senate net worth.", {"senate_id"})
async def senate_net_worth_aggregated(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("SenatePositions", "Get Senate positions.", {"name"}, set())
async def senate_positions(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("SenateProfile", "Get Senate profiles.", {"name"}, set())
async def senate_profile(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())
