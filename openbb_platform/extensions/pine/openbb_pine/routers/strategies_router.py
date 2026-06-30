"""Strategies sub-router: ``POST /pine/strategies/run`` (D3 §4.3).

M1 = HTTP 501 always. The route is registered so the OpenAPI surface
locks at M1 — clients can discover the endpoint and authoring tools
generate the correct request shape from the typed
:class:`PineStrategiesRunRequest` model — but every call raises
:class:`PineStrategyNotYetImplementedError` until the M2 strategy fill
engine + KPI emitter lands (PRD §3.2, D3 §4.3). See bead ``0e9.5.6`` for
the M2 tracking.

The endpoint accepts the full M2 request shape today so a client written
against the published schema works unchanged once the body flips. Inputs
are intentionally *not* validated at M1 — the M2 lander will plumb them
into the same model that the OpenAPI schema already documents.
"""

from __future__ import annotations

from typing import Annotated, Any

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from pydantic import Field

from openbb_pine.errors import PineStrategyNotYetImplementedError
from openbb_pine.routers._models import PineByoData

router = Router(
    prefix="/strategies",
    description="Run Pine strategies (501 at M1; live at M2 per PRD §3.2).",
)


_STRATEGY_TRACKING_URL = (
    "https://github.com/prajoria/OpenBB/issues?"
    "q=is%3Aissue+label%3Aproject%3Apine+bead%3A0e9.5.6"
)


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Run a Pine strategy (501 at M1; live at M2).",
            code=[
                'src = open("breakout.pine").read()',
                'obb.pine.strategies.run(source=src, provider="fmp", symbol="AAPL", '
                'interval="1d", start="2024-01-01", end="2024-12-31")',
            ],
        ),
    ],
)
async def run(
    source: Annotated[str, Field(min_length=1, description="Pine v5 or v6 source.")],
    provider: Annotated[
        str | None, Field(description='"fmp" or "fmp_cached" — PRD §13.8.')
    ] = None,
    symbol: Annotated[
        str | None, Field(description="Ticker — required in provider mode.")
    ] = None,
    interval: Annotated[
        str | None, Field(description='Bar interval, e.g. "1d", "1h".')
    ] = None,
    start: Annotated[str | None, Field(description="ISO date.")] = None,
    end: Annotated[str | None, Field(description="ISO date.")] = None,
    params: Annotated[
        dict[str, Any] | None, Field(description="Pine input overrides.")
    ] = None,
    data: Annotated[
        PineByoData | None, Field(description="BYO OHLCV payload.")
    ] = None,
    strategy_params: Annotated[
        dict[str, Any] | None,
        Field(description="Strategy-specific overrides (capital, fees, slippage)."),
    ] = None,
    timeout_s: Annotated[
        int | None, Field(ge=1, description="Per-script wall-clock cap.")
    ] = None,
) -> OBBject:
    """Run a Pine strategy — M1 returns 501 always (D3 §4.3).

    Returns
    -------
    OBBject
        Bare ``OBBject`` per D3 §5 — the keys are user-defined at M2.
        At M1 always raises :class:`PineStrategyNotYetImplementedError`.

    Raises
    ------
    PineStrategyNotYetImplementedError
        501 — strategies land at M2 (see bead 0e9.5.6).
    """
    # Discard the inputs explicitly so static analyzers do not warn about
    # unused parameters — the parameters exist so the OpenAPI surface is
    # correct, not to be exercised.
    del source, provider, symbol, interval, start, end, params, data
    del strategy_params, timeout_s
    raise PineStrategyNotYetImplementedError(
        f"Strategies land at M2 per PRD §3.2; see bead 0e9.5.6. "
        f"Tracking: {_STRATEGY_TRACKING_URL}"
    )


__all__ = ["router"]
