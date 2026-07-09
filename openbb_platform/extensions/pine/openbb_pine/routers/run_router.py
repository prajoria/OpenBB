"""Run sub-router: ``POST /pine/run`` + ``POST /pine/run_byo`` (D3 §4.1).

**M1 facade split** (bead 0e9.11 — smoke-test finding 0e9.9 STEP 4). The
canonical single-endpoint shape ``POST /pine/run(source, provider|data, …)``
worked via direct API but failed via the ``obb.pine.run()`` static facade
because openbb-core's ``@validate`` decorator coerces the ``data`` param
through ``Union[list, dict, DataFrame, Data, …]`` that rejects ``None``
defaults. Rather than fight upstream, we split at the facade layer into
two disjoint-signature methods:

* ``POST /pine/run`` — provider mode only (no ``data`` param)
* ``POST /pine/run_byo`` — BYO records only (no ``provider``/``interval``/
  ``start``/``end``)

Both share the internal ``_compile_and_run()`` helper that owns the
compile-then-execute pipeline. The split is ONLY at the openbb-core-facing
signature — the runtime + compiler layers stay unchanged.

Pipeline (both endpoints):

    1. Provider validation via ``resolve_provider()`` (run only) — raises
       ``PineProviderError`` on non-FMP with the PRD §13.8 structured message.
    2. Compile: ``compile_pine(source, target_version=6, params=…)`` →
       ``CompiledModule`` (cached under ``~/.openbb/pine_cache/<sha[:2]>/<sha>.py``
       per D1 §6).
    3. Execute: ``run_compiled(compiled, provider_or_data=…, symbol=…, …)`` →
       ``OBBject`` with DataFrame plots + ``.extra`` per D2 §6.1.

Note: ``POST /pine/strategies/run`` lives in a sibling ``strategies_router.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_pine.compiler import compile_pine
from openbb_pine.errors import PineDataValidationError
from openbb_pine.runtime.executor import run_compiled
from openbb_pine.runtime.provider_selection import resolve_provider
from openbb_pine.telemetry import OpenBBTelemetrySink

router = Router(prefix="", description="Compile and run Pine scripts over OHLCV.")


# ---------------------------------------------------------------------------
# Internal helpers (test seams)
# ---------------------------------------------------------------------------


def _byo_records_to_dataframe(
    records: list[dict[str, Any]],
    tz: str = "UTC",
) -> pd.DataFrame:
    """Materialise a records list into a ``pd.DataFrame`` with a tz-aware
    ``DatetimeIndex`` — the shape BYODataProvider (D2 §3) expects.

    Only the ``records`` payload shape is wired end-to-end at M1 (per PRD §4.10).
    Parquet/CSV/Arrow URL formats are Phase-1 follow-ups tracked as a separate
    bead.

    Raises
    ------
    PineDataValidationError
        Records empty, missing 'date' column, or schema-invalid.
    """
    if not records:
        raise PineDataValidationError(
            defects=["records payload is empty"],
            context="records",
        )
    df = pd.DataFrame(records)
    if "date" not in df.columns:
        raise PineDataValidationError(
            defects=["records missing required 'date' column"],
            context="records.date",
        )
    df["date"] = pd.to_datetime(df["date"], utc=(tz.upper() == "UTC"))
    if tz.upper() != "UTC":
        df["date"] = df["date"].dt.tz_localize(tz).dt.tz_convert("UTC")
    df = df.set_index("date").sort_index()
    return df


def _parse_iso_datetime(s: str | datetime | None) -> datetime | None:
    """ISO date/datetime string → tz-aware UTC datetime. Passes ``datetime``
    objects through (Pydantic model construction may pre-coerce)."""
    if s is None:
        return None
    dt = s if isinstance(s, datetime) else datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _compile_and_run(
    *,
    source: str,
    provider_or_data: str | pd.DataFrame | None,
    symbol: str | None,
    interval: str | None = None,
    start: str | None = None,
    end: str | None = None,
    params: dict[str, Any] | None = None,
    timeout_s: int | None = None,
) -> OBBject:
    """Shared pipeline: compile_pine → run_compiled → OBBject.

    Called by BOTH /pine/run (provider mode) and /pine/run_byo (BYO mode).
    Provider validation is the caller's responsibility (resolve_provider
    must fire BEFORE this so PineProviderError propagates cleanly).

    E0.4 telemetry: instantiate a per-request
    :class:`~openbb_pine.telemetry.OpenBBTelemetrySink`, inject it into
    ``compile_pine(telemetry=...)``, then surface the per-request counts
    on the returned ``OBBject.extra`` under the ``"pine_telemetry"`` key
    (D3 §4.6 already reserves the slot). The envelope shape is::

        extra["pine_telemetry"] = {
            "unsupported_features": {"PF010": 1, ...},
            "unsupported_builtins": {"ta.ichimoku": 1, ...},
        }

    Both maps are empty when the compile succeeded without touching any
    unsupported code path — the keys are always present so downstream
    consumers can address them unconditionally.

    We intentionally namespace under ``pine_telemetry`` (nested dict)
    rather than flat ``pine_unsupported_*`` keys so the envelope stays
    tidy when more counter dimensions land (compile-cache hit rate,
    codegen node-count, PyneCore exec time). Per-request isolation is
    strict — the module-global :data:`openbb_pine.telemetry._DEFAULT_SINK`
    is NOT written to from this path; use ``compile_pine(telemetry=...)``
    to observe compiler-side counts from tests or operator tooling.
    """
    telemetry_sink = OpenBBTelemetrySink()
    compiled = compile_pine(
        source,
        target_version=6,
        params=params or None,
        telemetry=telemetry_sink,
    )
    obbject = run_compiled(
        compiled,
        provider_or_data=provider_or_data,
        symbol=symbol,
        interval=interval,
        start=_parse_iso_datetime(start),
        end=_parse_iso_datetime(end),
        params=params,
        timeout_s=timeout_s,
    )
    # Surface per-request telemetry on the OBBject envelope. ``run_compiled``
    # always returns an OBBject with a dict ``extra`` (see
    # ``runtime/executor.py``), so we mutate in place — no None guard needed.
    obbject.extra["pine_telemetry"] = {
        "unsupported_features": telemetry_sink.get_unsupported_feature_counts(),
        "unsupported_builtins": telemetry_sink.get_unsupported_builtin_counts(),
    }
    return obbject


# ---------------------------------------------------------------------------
# POST /pine/run — provider mode
# ---------------------------------------------------------------------------


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Run a Pine script over FMP-supplied OHLCV.",
            code=[
                'src = open("bb.pine").read()',
                'obb.pine.run(source=src, provider="fmp_cached", symbol="AAPL", '
                'interval="1d", start="2024-01-01", end="2024-12-31")',
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
    timeout_s: int = 30,
) -> OBBject:
    """Compile and execute a Pine script over an FMP-provided OHLCV series.

    Provider-mode only. For BYO OHLCV records, use ``obb.pine.run_byo(...)``.

    M1 wire-up per bead 0e9.5.61; facade-split per bead 0e9.11.
    Provider validation via ``resolve_provider()`` fires FIRST so non-FMP
    names surface the rich ``PineProviderError`` (with tracking URL + supported
    tuple) instead of a downstream compile/exec error.

    Parameters
    ----------
    source : str
        Pine v5 or v6 source text.
    provider : str
        ``"fmp"`` or ``"fmp_cached"``. Non-FMP values raise
        :class:`PineProviderError` per PRD §13.8. Default ``"fmp_cached"``.
    symbol : str
        Ticker. Default ``"AAPL"``.
    interval : str
        Bar interval, e.g. ``"1d"``, ``"1h"``. Default ``"1d"``.
    start, end : str, optional
        ISO date/datetime strings.
    params : dict, optional
        Pine input overrides (threaded into runtime for future PineComp use).
    timeout_s : int
        Per-script wall-clock cap (seconds). Default 30.

    Returns
    -------
    OBBject
        Bare per D3 §5. ``.results`` is a ``pd.DataFrame`` indexed by
        timestamp with one column per ``plot()`` call. ``.extra`` carries
        D2 §6.1 keys.

    Raises
    ------
    PineProviderError
        Non-FMP provider name.
    PineSyntaxError / PineTypeError / PineUnsupportedBuiltinError
        Compile-time errors.
    PineFMPUnreachableError / PineFMPRequiredError
        Runtime data-side errors.
    PineExecTimeoutError / PineSecurityError
        Runtime enforcement failures.
    """
    resolve_provider(provider)  # raises PineProviderError on non-FMP
    return _compile_and_run(
        source=source,
        provider_or_data=provider,
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
        params=params,
        timeout_s=timeout_s,
    )


# ---------------------------------------------------------------------------
# POST /pine/run_byo — BYO records mode
# ---------------------------------------------------------------------------


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Run a Pine script over BYO OHLCV records.",
            code=[
                'records = [',
                '    {"date": "2024-01-02T00:00:00Z", "open": 184.1, "high": 186.4,',
                '     "low": 183.9, "close": 185.6, "volume": 52341900},',
                '    # ... more bars ...',
                ']',
                'obb.pine.run_byo(source=open("rsi.pine").read(), '
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
    timeout_s: int = 30,
) -> OBBject:
    """Compile and execute a Pine script over BYO OHLCV records.

    BYO-mode only. For FMP-provider mode, use ``obb.pine.run(...)``. Split
    from the canonical ``/pine/run`` per bead 0e9.11 to sidestep the
    openbb-core ``@validate`` union-coercion on the ``data`` param.

    Records must be a non-empty ``list[dict]`` where each dict has at least
    ``date`` (ISO string), ``open``, ``high``, ``low``, ``close``, ``volume``.
    Timestamps are coerced to a tz-aware ``DatetimeIndex`` per the ``tz``
    parameter (default UTC).

    Parameters
    ----------
    source : str
        Pine v5 or v6 source text.
    records : list[dict]
        BYO OHLCV bars. Required non-empty; required 'date' column.
    symbol : str
        Symbol label surfaced to the script's ``syminfo`` context.
        Default ``"BYO"``.
    tz : str
        IANA timezone for the bar timestamps. Default ``"UTC"``.
    params : dict, optional
        Pine input overrides.
    timeout_s : int
        Per-script wall-clock cap (seconds). Default 30.

    Returns
    -------
    OBBject
        Same shape as ``run()``. ``.extra["provider_used"]`` will be
        ``"byo"``.

    Raises
    ------
    PineDataValidationError
        Records empty, missing 'date', or schema-invalid.
    (Same compile-time + runtime errors as ``run()``.)
    """
    df = _byo_records_to_dataframe(records, tz=tz)
    return _compile_and_run(
        source=source,
        provider_or_data=df,
        symbol=symbol,
        params=params,
        timeout_s=timeout_s,
    )


__all__ = ["router"]
