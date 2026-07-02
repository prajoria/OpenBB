"""Run sub-router: ``POST /pine/run`` (D3 §4.1).

**M1 wire-up complete** (bead 0e9.5.61 — the P1-endpoints follow-up flip).
The full compile-and-execute chain landed via Waves 4 (C5 codegen) + 5A
(C6 cache) + 5B (36 stdlib bridges); this endpoint now calls it end-to-end
rather than returning the earlier 503 stub.

Pipeline per request:

    1. Provider validation via ``resolve_provider()`` (raises PineProviderError
       on non-FMP with the PRD §13.8 structured message).
    2. Request-shape validation via ``PineRunRequest`` (Pydantic).
    3. BYO-data materialisation: ``PineByoData(format="records", …)`` →
       ``pandas.DataFrame`` with DatetimeIndex. Only ``records`` is wired
       end-to-end today — the other formats (``parquet_url``, ``csv_url``,
       ``arrow_ipc_base64``) raise ``NotImplementedError`` per PRD §4.10.
    4. ``compile_pine(source, target_version=6, params=…)`` → ``CompiledModule``
       (cached under ``~/.openbb/pine_cache/<sha[:2]>/<sha>.py`` per D1 §6).
    5. ``run_compiled(compiled, provider_or_data=…, symbol=…, …)`` →
       ``OBBject`` with DataFrame plots + ``.extra`` per D2 §6.1
       (attribution/orders/alerts/exec_ms/compile_cache_hit/provider_used/
       bars_consumed).

Note on file layout: ``POST /pine/strategies/run`` lives in a sibling
``strategies_router.py`` (per the L0.2 ``pine_router._include_subrouters``
scaffold's expected import list).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

import pandas as pd
from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from pydantic import Field

from openbb_pine.compiler import compile_pine
from openbb_pine.errors import PineDataValidationError
from openbb_pine.routers._models import (
    PineByoData,
    PineRunRequest,
)
from openbb_pine.runtime.executor import run_compiled
from openbb_pine.runtime.provider_selection import resolve_provider

router = Router(prefix="", description="Compile and run Pine scripts over OHLCV.")


def _byo_to_dataframe(byo: PineByoData) -> pd.DataFrame:
    """Materialise a ``PineByoData`` payload into a ``pd.DataFrame`` with
    a tz-aware ``DatetimeIndex`` — the shape BYODataProvider (D2 §3) expects.

    Only ``format="records"`` is wired end-to-end at M1 (per PRD §4.10 note).
    Other formats surface as ``PineDataValidationError`` naming the deferral.
    """
    if byo.format != "records":
        raise PineDataValidationError(
            defects=[
                f"BYO format {byo.format!r} not wired end-to-end at M1; "
                f"only 'records' is supported. See PRD §4.10 (parquet_url/csv_url/"
                f"arrow_ipc_base64 are Phase 1 follow-ups)."
            ],
            context="format",
        )
    if not byo.records:
        raise PineDataValidationError(
            defects=["records payload is empty"],
            context="records",
        )
    df = pd.DataFrame(byo.records)
    if "date" not in df.columns:
        raise PineDataValidationError(
            defects=["records missing required 'date' column"],
            context="records.date",
        )
    # Coerce timestamps → tz-aware DatetimeIndex per BYODataProvider's schema.
    df["date"] = pd.to_datetime(df["date"], utc=(byo.tz.upper() == "UTC"))
    if byo.tz.upper() != "UTC":
        # Localise to the caller's tz then convert to UTC for canonical storage.
        df["date"] = df["date"].dt.tz_localize(byo.tz).dt.tz_convert("UTC")
    df = df.set_index("date").sort_index()
    return df


def _parse_iso_datetime(s: str | datetime | None) -> datetime | None:
    """Parse an ISO date/datetime string into a tz-aware UTC datetime.

    Tolerates already-parsed ``datetime`` objects (Pydantic coerces
    ``PineRunRequest.start`` / ``.end`` at model construction, so the
    validated model gives us datetimes; direct in-process callers may
    still pass raw strings).
    """
    if s is None:
        return None
    if isinstance(s, datetime):
        dt = s
    else:
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Run a Pine script over FMP-supplied OHLCV.",
            code=[
                'src = open("bb.pine").read()',
                'obb.pine.run(source=src, provider="fmp", symbol="AAPL", '
                'interval="1d", start="2024-01-01", end="2024-12-31")',
            ],
        ),
        PythonEx(
            description="Run over BYO OHLCV.",
            code=[
                "from openbb_pine.routers._models import PineByoData",
                'records = [{"date": "2024-01-02T00:00:00Z", "open": 184.1, '
                '"high": 186.4, "low": 183.9, "close": 185.6, "volume": 52341900}]',
                'data = PineByoData(format="records", records=records)',
                'obb.pine.run(source=open("rsi.pine").read(), data=data, symbol="X")',
            ],
        ),
    ],
)
async def run(
    source: str,
    provider: str | None = None,
    symbol: str | None = None,
    interval: str | None = None,
    start: str | None = None,
    end: str | None = None,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,  # PineByoData shape via dict; typed model breaks static facade
    timeout_s: int | None = None,
) -> OBBject:
    """Compile and execute a Pine script over provider- or BYO-supplied OHLCV.

    M1 wire-up per bead 0e9.5.61. Provider validation still fires FIRST so
    non-FMP names surface the rich ``PineProviderError`` (with tracking URL
    + supported tuple) instead of a Pydantic ``literal_error``. Request-
    shape validation catches "no provider AND no data" and similar defects.

    Parameters
    ----------
    source : str
        Pine v5 or v6 source text.
    provider : str, optional
        ``"fmp"`` or ``"fmp_cached"``. Non-FMP values raise
        :class:`PineProviderError` per PRD §13.8.
    symbol : str, optional
        Ticker. Required when ``provider`` is set (Pydantic model enforces).
    interval, start, end : str, optional
        FMP-mode bar-grid parameters. ISO date/datetime strings.
    params : dict, optional
        Pine input overrides (threaded into runtime for future PineComp use).
    data : PineByoData, optional
        BYO OHLCV payload. Mutually mostly-exclusive with provider+symbol —
        if both set, ``data`` wins with a warning in ``extra``.
    timeout_s : int, optional
        Per-script wall-clock cap (seconds). Overrides
        :data:`limits.DEFAULT_TIMEOUT_S`.

    Returns
    -------
    OBBject
        Bare per D3 §5. ``.results`` is a ``pd.DataFrame`` indexed by
        timestamp with one column per ``plot()`` call in the compiled
        script. ``.extra`` carries D2 §6.1 keys: ``alerts``, ``orders``,
        ``attribution`` (POWERED_BY_FULL literal), ``compile_cache_hit``,
        ``exec_ms``, ``provider_used``, ``bars_consumed``.

    Raises
    ------
    PineProviderError
        Non-FMP provider name (PRD §13.8).
    PineDataValidationError
        BYO payload has an unsupported ``format`` or schema defect.
    PineSyntaxError / PineTypeError / PineUnsupportedBuiltinError / …
        Compile-time errors from the C1..C8 chain; middleware serializes
        each per the PRD §4.8 envelope shape.
    PineFMPUnreachableError / PineFMPRequiredError
        Runtime data-side errors from R6 retry / R1 provider (D2 §7).
    PineExecTimeoutError / PineSecurityError
        Runtime enforcement failures from R5 / R4.
    """
    # 1) Provider validation FIRST so non-FMP names get the rich
    #    PineProviderError. resolve_provider's structured error survives
    #    middleware serialization unchanged.
    if provider is not None:
        resolve_provider(provider)  # raises PineProviderError on non-FMP

    # 2) Request-shape validation via the Pydantic model. Catches
    #    "neither provider nor data set" / "provider set but no symbol" etc.
    #    Pydantic's ValidationError maps to HTTP 422 in the middleware.
    validated = PineRunRequest(
        source=source,
        provider=provider,  # type: ignore[arg-type]  - already checked above
        symbol=symbol,
        interval=interval,
        start=start,  # type: ignore[arg-type]
        end=end,  # type: ignore[arg-type]
        params=params or {},
        data=data,
        timeout_s=timeout_s,
    )

    # 3) Compile: detect version → migrate if v5 → tokenize → parse →
    #    type-check → codegen → cache (D1 §6). This is the C5 + C6 + C7
    #    chain wired via Wave 5A's compile_pine() facade.
    compiled = compile_pine(
        validated.source,
        target_version=6,
        params=validated.params or None,
    )

    # 4) Determine data source. BYO wins over provider per PRD §4.8.2.
    if validated.data is not None:
        provider_or_data = _byo_to_dataframe(validated.data)
    else:
        # Provider mode. resolve_provider defaults are honoured inside
        # run_compiled; we pass the requested name (or None for default).
        provider_or_data = validated.provider  # type: ignore[assignment]

    # 5) Execute. run_compiled owns the FMPOHLCVProvider / BYODataProvider
    #    dispatch, limits + restricted-ns wrapping, PyneCore ScriptRunner
    #    iteration, plot/alert collection, and OBBject packing.
    return run_compiled(
        compiled,
        provider_or_data=provider_or_data,
        symbol=validated.symbol,
        interval=validated.interval,
        start=_parse_iso_datetime(validated.start),
        end=_parse_iso_datetime(validated.end),
        params=validated.params,
        timeout_s=validated.timeout_s,
    )


__all__ = ["router"]
