"""Strategies sub-router: ``POST /pine/strategies/run`` (D3 §4.3 / D5 §8.1).

**bd-4d0 flip** (Wave 22 — 2026-07-11). The M1 501 stub is replaced by a
real dispatch through the shared ``_compile_and_run()`` helper defined in
:mod:`openbb_pine.routers.run_router` (bead 0e9.11). The endpoint now
compiles and executes a Pine strategy end-to-end and returns a bare
``OBBject`` per PRD §16.6 (M1-shipping finding — typed models deferred).

Pipeline:

    1. ``resolve_provider(provider)`` — non-FMP names raise ``PineProviderError``.
    2. ``_compile_and_run(...)`` — shared with ``/pine/run``; owns compile
       + execute + telemetry.
    3. Post-compile script-type gate — if the compiled unit is not a
       ``strategy(...)`` declaration, raise ``PineTypeError`` with rule
       ``PT099`` so callers get a structured "wrong endpoint" signal
       instead of an indicator-shaped OBBject.
    4. ``_apply_strategy_params(result, strategy_params)`` — merges caller
       overrides (e.g. ``initial_capital``) onto ``result.extra['stats']``.

Returns a bare OBBject with ``.extra`` carrying ``stats``, ``equity_curve``,
``orders``, ``alerts``, ``script_type='strategy'``, and the standard
attribution/telemetry envelope (D5 §8.1).
"""

from __future__ import annotations

from typing import Any

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_pine.errors import PineTypeError
from openbb_pine.routers._models import PineByoData
from openbb_pine.routers.run_router import (
    _byo_records_to_dataframe,
    _compile_and_run,
)
from openbb_pine.runtime.provider_selection import resolve_provider
from pyne_compiler.errors.codes import ERROR_CODES, ErrorCodeSpec

# bd-4d0 — register PT099 (fork-side "wrong endpoint" gate). PT001-008 are
# reserved by D1 §4.4 for compile-time type-checker rules; PT099 is the
# routing-layer variant this endpoint raises when the caller sends a
# non-strategy source to /pine/strategies/run. Registration must happen at
# import time so ``test_error_model.TestErrorCodeEnforcement`` (which scans
# rule= kwargs across the codebase) resolves the literal against the
# central registry without needing a pynecore-submodule edit.
if "PT099" not in ERROR_CODES:
    ERROR_CODES["PT099"] = ErrorCodeSpec(
        code="PT099",
        class_name="PineTypeError",
        short_description="Wrong endpoint: source is not a strategy",
        detailed_description=(
            "``/pine/strategies/run`` was called with a source whose top-level "
            "declaration is not ``strategy(...)`` (e.g. an ``indicator(...)`` "
            "or ``library(...)`` script). Use ``/pine/run`` for indicators. "
            "See D5 §8.1."
        ),
        since_version="0.next",
        tracking_label="pine-strategy-router",
    )

router = Router(
    prefix="/strategies",
    description="Run Pine strategies over OHLCV (bd-4d0 — real at M2).",
)


def _apply_strategy_params(
    result: OBBject,
    strategy_params: dict[str, Any],
) -> None:
    """Merge caller-supplied strategy overrides onto the ``result`` envelope.

    At M2-shipping the only lever the router surfaces is a shallow merge
    onto ``result.extra['stats']`` so callers can annotate the returned
    envelope with values (e.g. ``initial_capital``) that upstream Pine
    ``strategy(...)`` inputs did not carry. Deeper param semantics (e.g.
    re-running with a different ``commission_value``) land in a follow-up
    bead — the shape here is the minimum needed to unblock bd-250 /
    bd-cht per D5 §8.1.
    """
    if not strategy_params:
        return
    extra = getattr(result, "extra", None)
    if not isinstance(extra, dict):
        return
    stats = extra.setdefault("stats", {})
    if isinstance(stats, dict):
        stats.update(strategy_params)


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Run a Pine strategy over FMP-supplied OHLCV.",
            code=[
                'src = open("breakout.pine").read()',
                'obb.pine.strategies.run(source=src, provider="fmp_cached", '
                'symbol="AAPL", interval="1d", start="2024-01-01", '
                'end="2024-12-31")',
            ],
        ),
    ],
)
async def run(
    source: str,
    provider: str = "fmp_cached",
    symbol: str = "AAPL",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
    params: dict[str, Any] | None = None,
    data: PineByoData | None = None,  # noqa: ARG001 -- reserved for BYO follow-up
    strategy_params: dict[str, Any] | None = None,
    timeout_s: int = 30,
) -> OBBject:
    """Compile and execute a Pine strategy over an FMP-provided OHLCV series.

    Provider validation fires FIRST so non-FMP names surface
    :class:`PineProviderError` per PRD §13.8. On success the returned
    ``OBBject.extra`` carries ``script_type='strategy'``, ``stats``
    (KPIs), ``equity_curve``, ``orders``, ``alerts``, ``attribution``,
    and ``pine_telemetry`` (D5 §8.1).

    Raises
    ------
    PineProviderError
        Non-FMP provider name.
    PineTypeError
        Rule ``PT099`` — source is not a ``strategy(...)`` declaration.
        Use ``/pine/run`` for indicators.
    PineSyntaxError / PineTypeError / PineUnsupportedBuiltinError
        Compile-time errors.
    PineFMPUnreachableError / PineFMPRequiredError
        Runtime data-side errors.
    PineExecTimeoutError / PineSecurityError
        Runtime enforcement failures.
    """
    resolve_provider(provider)
    result = _compile_and_run(
        source=source,
        provider_or_data=provider,
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
        params=params,
        timeout_s=timeout_s,
    )
    extra = getattr(result, "extra", None) or {}
    if extra.get("script_type") != "strategy":
        raise PineTypeError(
            rule="PT099",
            message=(
                "Source does not use strategy(...); "
                "use /pine/run for indicators."
            ),
        )
    _apply_strategy_params(result, strategy_params or {})
    return result


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Run a Pine strategy over caller-supplied OHLCV records.",
            code=[
                'records = [',
                '    {"date": "2024-01-02T00:00:00Z", "open": 184.1, "high": 186.4,',
                '     "low": 183.9, "close": 185.6, "volume": 52341900},',
                '    # ... more bars ...',
                ']',
                'obb.pine.strategies.run_byo(source=open("breakout.pine").read(), '
                'records=records, symbol="AAPL")',
            ],
        ),
    ],
)
async def run_byo(
    source: str,
    records: list[dict[str, Any]],
    symbol: str = "BYO",
    tz: str = "UTC",
    params: dict[str, Any] | None = None,
    strategy_params: dict[str, Any] | None = None,
    timeout_s: int = 30,
) -> OBBject:
    """Compile and execute a Pine strategy over caller-supplied OHLCV records.

    BYO-mode sibling of :func:`run`. Mirrors the facade-split pattern from
    bd-0e9.11 (indicators_router.run_byo): caller supplies a ``records``
    list which is materialised into a tz-aware ``DatetimeIndex`` DataFrame
    via the shared :func:`_byo_records_to_dataframe` helper, then dispatched
    through the same :func:`_compile_and_run` pipeline as the provider path.

    Same post-compile ``PT099`` script-type gate as :func:`run`: if the
    compiled source is not a ``strategy(...)`` declaration, raise
    :class:`PineTypeError` so callers of ``/pine/strategies/run_byo`` who
    accidentally submit an indicator get a structured "wrong endpoint"
    signal instead of an indicator-shaped OBBject.

    Parameters
    ----------
    source : str
        Pine v5 or v6 source text. Must be a ``strategy(...)`` script.
    records : list[dict]
        BYO OHLCV bars. Non-empty; required ``date`` column (ISO string).
    symbol : str
        Symbol label surfaced to the script's ``syminfo`` context.
        Default ``"BYO"``.
    tz : str
        IANA timezone for the bar timestamps. Default ``"UTC"``.
    params : dict, optional
        Pine input overrides.
    strategy_params : dict, optional
        Caller overrides merged onto ``result.extra['stats']``.
    timeout_s : int
        Per-script wall-clock cap (seconds). Default 30.

    Returns
    -------
    OBBject
        Same shape as :func:`run`. ``.extra["provider_used"]`` will be
        ``"byo"``.

    Raises
    ------
    PineDataValidationError
        Records empty, missing 'date', or schema-invalid.
    PineTypeError
        Rule ``PT099`` — source is not a ``strategy(...)`` declaration.
        Use ``/pine/run_byo`` for indicators.
    (Same compile-time + runtime errors as :func:`run`.)
    """
    df = _byo_records_to_dataframe(records, tz=tz)
    result = _compile_and_run(
        source=source,
        provider_or_data=df,
        symbol=symbol,
        params=params,
        timeout_s=timeout_s,
    )
    extra = getattr(result, "extra", None) or {}
    if extra.get("script_type") != "strategy":
        raise PineTypeError(
            rule="PT099",
            message=(
                "Source does not use strategy(...); "
                "use /pine/run_byo for indicators."
            ),
        )
    _apply_strategy_params(result, strategy_params or {})
    return result


__all__ = ["router"]
