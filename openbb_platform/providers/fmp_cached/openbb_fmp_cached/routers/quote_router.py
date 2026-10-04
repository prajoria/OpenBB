"""Batch quote, market-cap and stock-price reference routes."""

# ruff: noqa: D103
# pylint: disable=unused-argument

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request
from openbb_core.app.model.abstract.error import OpenBBError
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

router = Router(prefix="", description="FMP quote and market snapshot data.")
MAX_BATCH_SYMBOLS = 100


def _parameter_values(params: Any) -> dict:
    if params is None:
        return {}
    if hasattr(params, "model_dump"):
        return params.model_dump()
    if is_dataclass(params) and not isinstance(params, type):
        return asdict(params)
    return vars(params)


def _symbol_values(params: dict) -> list[str]:
    raw = params.get("symbols")
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    return [
        symbol.strip()
        for value in values
        for symbol in str(value).split(",")
        if symbol.strip()
    ]


async def _dispatch(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    params = {
        **_parameter_values(standard_params),
        **_parameter_values(extra_params),
    }
    if "symbol" in params and (
        params["symbol"] is None or not str(params["symbol"]).strip()
    ):
        raise OpenBBError("A non-empty symbol is required.")
    if "symbols" in params:
        symbols = _symbol_values(params)
        if not symbols:
            raise OpenBBError("At least one symbol is required.")
        if len(symbols) > MAX_BATCH_SYMBOLS:
            raise OpenBBError(
                f"Batch quote routes accept at most {MAX_BATCH_SYMBOLS} symbols."
            )
        provider = _parameter_values(provider_choices).get("provider")
        if provider == "fmp_cached" and not isinstance(params["symbols"], str):
            setattr(extra_params, "symbols", ",".join(symbols))
    return await OBBject.from_query(
        Query(
            cc=cc,
            provider_choices=provider_choices,
            standard_params=standard_params,
            extra_params=extra_params,
        )
    )


def _reject_unknown(argument: str | None):
    async def dependency(request: Request) -> None:
        allowed = {"provider"} | ({argument} if argument else set())
        unknown = set(request.query_params) - allowed
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown query arguments: {', '.join(sorted(unknown))}",
            )

    return dependency


def _command(model: str, description: str, argument: str | None):
    def decorator(func):
        func.__doc__ = description
        return router.command(
            model=model,
            operation_id=f"fmp_cached_{func.__name__}",
            dependencies=[Depends(_reject_unknown(argument))],
            examples=[APIEx(parameters={"provider": "fmp_cached"})],
            widget_config={
                "name": func.__name__.replace("_", " ").title(),
                "description": description,
                "category": "FMP Cached",
                "subCategory": "Quotes",
                "refetchInterval": False,
            },
        )(func)

    return decorator


@_command("MarketCap", "Get a single-symbol market capitalization.", "symbol")
async def market_cap(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("SharesFloat", "Get a single-symbol shares-float snapshot.", "symbol")
async def shares_float(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("StockPriceChange", "Get stock-price change horizons.", "symbol")
async def stock_price_change(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("StockQuote", "Get a full stock quote.", "symbol")
async def stock_quote(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("StockQuoteShort", "Get a compact stock quote.", "symbol")
async def stock_quote_short(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("MarketCapBatch", "Get market caps for a bounded symbol batch.", "symbols")
async def market_cap_batch(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("BatchQuote", "Get full quotes for a bounded symbol batch.", "symbols")
async def batch_quote(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "BatchQuoteShort", "Get compact quotes for a bounded symbol batch.", "symbols"
)
async def batch_quote_short(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "BatchAftermarketTrade",
    "Get aftermarket trades for a bounded symbol batch.",
    "symbols",
)
async def batch_aftermarket_trade(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "BatchAftermarketQuote",
    "Get aftermarket quotes for a bounded symbol batch.",
    "symbols",
)
async def batch_aftermarket_quote(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "AllExchangeMarketHours",
    "List current market hours for all exchanges.",
    None,
)
async def all_exchange_market_hours(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())
