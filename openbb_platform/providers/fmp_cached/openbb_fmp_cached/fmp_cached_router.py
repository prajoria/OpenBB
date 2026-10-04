"""Typed provider-owned routes for FMP Cached models."""

# Dispatcher parameters are consumed through ``Query(**locals())``.
# pylint: disable=unused-argument

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

router = Router(
    prefix="",
    description="Typed routes for FMP and the FMP Cached provider.",
)


@router.command(
    model="StockList",
    examples=[APIEx(parameters={"provider": "fmp_cached"})],
    widget_config={
        "name": "FMP Stock List",
        "description": "List stocks through the typed FMP provider dispatcher.",
        "category": "FMP Cached",
        "subCategory": "Reference",
        "refetchInterval": False,
    },
)
async def stock_list(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """List supported stocks using the registered provider dispatcher."""
    return await OBBject.from_query(Query(**locals()))
