"""Static directory, list, constituent and market-risk routes."""

# Route documentation is supplied by the shared command decorator.
# ruff: noqa: D103
# Dispatcher parameters are consumed through ``Query(**locals())``.
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

router = Router(prefix="", description="FMP reference and directory data.")


async def _dispatch(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await OBBject.from_query(Query(**locals()))


async def _reject_unknown_arguments(request: Request) -> None:
    unknown = set(request.query_params) - {"provider"}
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown query arguments: {', '.join(sorted(unknown))}",
        )


def _command(model: str, name: str, description: str):
    def decorator(func):
        func.__doc__ = description
        return router.command(
            model=model,
            operation_id=f"fmp_cached_{func.__name__}",
            dependencies=[Depends(_reject_unknown_arguments)],
            examples=[APIEx(parameters={"provider": "fmp_cached"})],
            widget_config={
                "name": name,
                "description": description,
                "category": "FMP Cached",
                "subCategory": "Reference",
                "refetchInterval": False,
            },
        )(func)

    return decorator


@_command("StockList", "FMP Stock List", "List supported stocks.")
async def stock_list(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("EtfList", "FMP ETF List", "List supported exchange-traded funds.")
async def etf_list(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("CikList", "FMP CIK List", "List SEC CIK references.")
async def cik_list(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "FinancialStatementSymbolList",
    "FMP Financial Statement Symbols",
    "List symbols with financial statements.",
)
async def financial_statement_symbol_list(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "CommitmentOfTradersList",
    "FMP COT Symbols",
    "List Commitment of Traders symbols.",
)
async def commitment_of_traders_list(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "ActivelyTradingList",
    "FMP Actively Trading List",
    "List actively traded instruments.",
)
async def actively_trading_list(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("AvailableCountries", "FMP Countries", "List available countries.")
async def available_countries(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("AvailableExchanges", "FMP Exchanges", "List available exchanges.")
async def available_exchanges(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("AvailableIndustries", "FMP Industries", "List available industries.")
async def available_industries(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("AvailableSectors", "FMP Sectors", "List available sectors.")
async def available_sectors(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("CommoditiesList", "FMP Commodities", "List commodity symbols.")
async def commodities_list(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("CryptocurrencyList", "FMP Cryptocurrencies", "List crypto symbols.")
async def cryptocurrency_list(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("ForexList", "FMP Forex Pairs", "List foreign-exchange symbols.")
async def forex_list(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("IndexList", "FMP Indices", "List market-index symbols.")
async def index_list(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("DowjonesConstituent", "Dow Jones Constituents", "List current constituents.")
async def dowjones_constituent(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("NasdaqConstituent", "Nasdaq Constituents", "List current constituents.")
async def nasdaq_constituent(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("Sp500Constituent", "S&P 500 Constituents", "List current constituents.")
async def sp500_constituent(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("MarketRiskPremium", "Market Risk Premium", "List market-risk references.")
async def market_risk_premium(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("RiskPremium", "Country Risk Premium", "List country risk references.")
async def risk_premium(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())
