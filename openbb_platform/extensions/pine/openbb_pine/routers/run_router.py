"""Run sub-router: ``POST /pine/run`` (D3 §4.1).

Compile + execute a Pine script over OHLCV. The M1 reality: codegen (C5,
bead 0e9.5.5) has not landed, so this endpoint is not yet runnable
end-to-end. Per the parent design (`pick (a) for /pine/run`), we return
HTTP 503 with a structured error envelope that points at the tracking
bead — the OpenAPI surface is still correct (clients can discover the
endpoint) but every call fails fast with a clear message rather than
crashing inside the executor.

Validation IS performed before the 503 — invalid provider names raise
:class:`PineProviderError` first (PRD §13.8 / D2 §4), and request-shape
validation fires through the Pydantic model. This means client-side
fixable problems surface with their real, structured errors; only the
"compile + execute" failure becomes the 503.

Once C5 lands, the body flips to::

    compiled = compile_pine_source(request.source)
    return run_compiled(compiled, provider_or_data=..., ...)

— a follow-up bead handles the flip.

Note on file layout: ``POST /pine/strategies/run`` lives in a sibling
``strategies_router.py`` (per the L0.2 ``pine_router._include_subrouters``
scaffold's expected import list), even though the parent bead's narrative
described both in this file. Split because the scaffold wires both
modules separately — keeping them together would require modifying
``pine_router.py``, which is L0.2 territory.
"""

from __future__ import annotations

from typing import Annotated, Any

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from pydantic import Field

from openbb_pine.errors import PineError
from openbb_pine.routers._models import (
    PineByoData,
    PineRunRequest,
)
from openbb_pine.runtime.provider_selection import resolve_provider

router = Router(prefix="", description="Compile and run Pine scripts over OHLCV.")


# Tracking-URL pointer for the M1 not-yet-implemented state. Module
# constant so tests can pin the exact string (and so a future C5 lander
# only has to delete one file's constant rather than chase string literals).
_COMPILER_TRACKING_URL = (
    "https://github.com/prajoria/OpenBB/issues?"
    "q=is%3Aissue+label%3Aproject%3Apine+bead%3A0e9.5.5"
)


class PineCompilerNotYetAvailableError(PineError):
    """503 — codegen (C5, bead 0e9.5.5) has not yet landed.

    Subclasses :class:`PineError` so the OpenBB middleware serializes it
    via the same path as every other Pine error (PRD §4.8 envelope). The
    ``code`` / ``tracking_url`` class attributes are surfaced into the
    envelope's ``detail`` block by the middleware's ``str(error.original)``
    rendering.
    """

    code: str = "PineCompilerNotYetAvailableError"
    tracking_url: str | None = _COMPILER_TRACKING_URL

    def __init__(
        self,
        *,
        message: str | None = None,
        bead: str = "0e9.5.5",
    ) -> None:
        self.bead = bead
        text = message or (
            f"Pine compiler (codegen C5) not yet implemented — "
            f"see PRD §8.1 Phase 1 / bead {bead}. Tracking: {_COMPILER_TRACKING_URL}"
        )
        super().__init__(text)


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Run a Pine script over FMP-supplied OHLCV (returns 503 at M1).",
            code=[
                'src = open("bb.pine").read()',
                'obb.pine.run(source=src, provider="fmp", symbol="AAPL", '
                'interval="1d", start="2024-01-01", end="2024-12-31")',
            ],
        ),
        PythonEx(
            description="Run over BYO OHLCV (returns 503 at M1).",
            code=[
                "from openbb_pine.routers._models import PineByoData",
                'data = PineByoData(format="records", records=[...])',
                'obb.pine.run(source=open("rsi.pine").read(), data=data, symbol="X")',
            ],
        ),
    ],
)
async def run(
    source: Annotated[str, Field(min_length=1, description="Pine v5 or v6 source.")],
    provider: Annotated[
        str | None, Field(description='"fmp" or "fmp_cached" — PRD §13.8 locks the set.')
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
    timeout_s: Annotated[
        int | None, Field(ge=1, description="Per-script wall-clock cap.")
    ] = None,
) -> OBBject:
    """Compile and execute a Pine script — M1 returns 503 (codegen pending).

    Validates the request and fast-fails non-FMP providers via
    :class:`PineProviderError`. When the request is valid, raises
    :class:`PineCompilerNotYetAvailableError` (a 503-with-tracking-URL
    structured error) until C5 lands.

    TODO(C5 0e9.5.5): swap the 503 for the real
    ``compile_pine_source(source)`` + ``run_compiled(...)`` chain.

    Parameters
    ----------
    source : str
        Pine v5 or v6 source text.
    provider : str, optional
        "fmp" or "fmp_cached". Non-FMP values raise PineProviderError
        BEFORE the 503 path (so clients see the structured FMP-only
        message, not a generic "compiler not yet ready").
    symbol : str, optional
        Ticker. Required when ``provider`` is set.
    interval, start, end : optional
        FMP-mode bar grid parameters.
    params : dict, optional
        Pine input overrides (will be threaded into the runtime once C5 lands).
    data : PineByoData, optional
        BYO OHLCV payload. Mutually mostly-exclusive with provider+symbol.
    timeout_s : int, optional
        Per-script wall-clock cap (seconds).

    Returns
    -------
    OBBject
        Bare ``OBBject`` per D3 §5 — the column schema is user-defined
        (script-emitted plot names). At M1 this never returns successfully.

    Raises
    ------
    PineProviderError
        Non-FMP provider name (PRD §13.8).
    PineCompilerNotYetAvailableError
        503 — codegen (C5, bead 0e9.5.5) has not landed.
    """
    # 1) Provider validation FIRST so non-FMP names get the rich
    #    PineProviderError (with tracking URL + supported tuple) instead
    #    of an opaque Pydantic literal_error. resolve_provider's
    #    structured error survives middleware serialization unchanged.
    #    The parameter is typed `str | None` (rather than Literal) for
    #    this reason; the model below double-checks the rest of the shape.
    if provider is not None:
        resolve_provider(provider)  # raises PineProviderError on non-FMP

    # 2) Request-shape validation via the Pydantic model. Catches
    #    "neither provider nor data set" / "provider set but no symbol".
    #    Pydantic's ValidationError maps to HTTP 422 in the middleware.
    PineRunRequest(
        source=source,
        provider=provider,  # type: ignore[arg-type]  - already validated above
        symbol=symbol,
        interval=interval,
        start=start,  # type: ignore[arg-type]
        end=end,  # type: ignore[arg-type]
        params=params or {},
        data=data,
        timeout_s=timeout_s,
    )

    # 3) M1: codegen (C5) hasn't landed -> structured 503.
    raise PineCompilerNotYetAvailableError()


__all__ = ["router", "PineCompilerNotYetAvailableError"]
