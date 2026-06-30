"""End-to-end Pine runtime entry point — D2 section 6 (R7).

Wires together the runtime layers landed in waves 1B/1C/1D:

* **Provider selection** (R3, ``provider_selection.resolve_provider``)
* **Data sources** (R1 ``FMPOHLCVProvider`` + R2 ``BYODataProvider``)
* **Restricted exec / T3** (R4 ``restricted.build_restricted_namespace`` + a
  belt-and-braces AST-scan in ``_pynecore_glue.scan_for_forbidden_imports``
  -- see notes in ``_pynecore_glue.py``)
* **Wall-clock + memory caps / T2** (R5 ``limits.enforce_limits``)
* **PyneCore** ``ScriptRunner`` (the vendored Apache-2.0 substrate)

and returns an ``OBBject`` with the contract D2 section 6.1 / PRD section 4.5
locks in:

* ``results``: ``pd.DataFrame`` indexed by tz-aware ``DatetimeIndex``, one
  column per ``plot()`` call. Unnamed plots get ``plot_N``; named plots use
  their title (de-duplicated by PyneCore itself, see ``lib/plot.py:56``).
* ``extra``: the 7 keys ``alerts``, ``orders``, ``attribution``,
  ``compile_cache_hit``, ``exec_ms``, ``provider_used``, ``bars_consumed``.
  ``attribution`` is the literal ``POWERED_BY_FULL`` imported from
  ``openbb_pine.attribution`` (single source of truth per the af08128d3
  consolidation note in D2 section 6.4).

Nothing here owns the FMP retry loop -- the providers already wrap their own
fetches in ``call_with_retry`` (R6). The executor's job is composition only.
"""

from __future__ import annotations

import tempfile
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Literal

import pandas as pd

from openbb_core.app.model.obbject import OBBject

from openbb_pine.attribution import POWERED_BY_FULL
from openbb_pine.errors import (
    PineExecTimeoutError,
    PineProviderError,
    PineSecurityError,
)
from openbb_pine.runtime._pynecore_glue import (
    capture_alerts,
    ensure_pyne_header,
    make_default_syminfo,
    scan_for_forbidden_imports,
)
from openbb_pine.runtime.byo_provider import BYODataProvider
from openbb_pine.runtime.fmp_provider import (
    FMPOHLCVProvider,
    FMPRequest,
    infer_asset_class,
)
from openbb_pine.runtime.limits import DEFAULT_TIMEOUT_S, enforce_limits

if TYPE_CHECKING:  # pragma: no cover -- typing-only
    from openbb_pine.compiler.types import CompiledModule
    from pynecore.types.ohlcv import OHLCV


# --- Provider-type alias (mirrors ``Literal`` from FMPRequest) ----------------

ProviderOrData = Literal["fmp", "fmp_cached"] | pd.DataFrame | Path | str
"""What ``run_compiled(provider_or_data=...)`` accepts.

* ``"fmp"`` / ``"fmp_cached"``: route through ``FMPOHLCVProvider``.
* ``pd.DataFrame``: wrap in ``BYODataProvider``.
* ``Path`` (or ``str`` ending in ``.parquet`` / ``.csv``): load the file with
  pandas and then wrap in ``BYODataProvider``. The lazy load keeps simple
  cases (in-memory DataFrame) free of disk I/O.
"""


# --- Provider construction ----------------------------------------------------


def _resolve_data_source(
    provider_or_data: Any,
    *,
    symbol: str | None,
    interval: str | None,
    start: datetime | None,
    end: datetime | None,
    user_settings: Any | None,
) -> Any:
    """Return the active provider for one ``run_compiled()`` call.

    Branches:
      1. ``str`` in the FMP allowlist -> ``FMPOHLCVProvider``.
      2. ``pd.DataFrame`` -> ``BYODataProvider`` over the frame.
      3. ``Path`` / ``str`` ending in ``.parquet`` / ``.csv`` -> load + wrap.
      4. Anything else -> raise ``TypeError`` (caller passed an unsupported
         object). ``PineProviderError`` is the right type for non-FMP provider
         *names*; a wrong-typed Python object is a developer mistake.

    The branch order matches the docstring contract above. ``str`` is checked
    BEFORE ``Path`` because ``isinstance(s, str)`` matches first and we want
    the provider-name fast-path to win.
    """
    # Branch 1: provider name string.
    if isinstance(provider_or_data, str) and not provider_or_data.endswith(
        (".parquet", ".csv", ".feather", ".arrow")
    ):
        if symbol is None or interval is None:
            raise ValueError(
                "FMP-backed runs require both `symbol` and `interval` arguments"
            )
        req = FMPRequest(
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
            asset_class=infer_asset_class(symbol),
        )
        # FMPOHLCVProvider.__init__ validates the provider via resolve_provider,
        # so a non-FMP value raises PineProviderError here (D2 §4 / PRD §13.8).
        return FMPOHLCVProvider(req, provider=provider_or_data, settings=user_settings)

    # Branch 2: in-memory DataFrame.
    if isinstance(provider_or_data, pd.DataFrame):
        return BYODataProvider(
            provider_or_data,
            symbol=symbol or "BYO",
            interval=interval,
        )

    # Branch 3: filesystem path -> load via pandas, then BYO.
    if isinstance(provider_or_data, (str, Path)):
        path = Path(provider_or_data)
        if not path.exists():
            raise FileNotFoundError(f"BYO data path does not exist: {path!s}")
        suffix = path.suffix.lower()
        if suffix == ".parquet":
            df = pd.read_parquet(path)
        elif suffix == ".csv":
            df = pd.read_csv(path, index_col=0, parse_dates=True)
        elif suffix in {".feather", ".arrow"}:
            df = pd.read_feather(path)
        else:
            raise ValueError(
                f"Unsupported BYO file format {suffix!r}; use parquet, csv, or feather"
            )
        return BYODataProvider(df, symbol=symbol or path.stem, interval=interval)

    raise TypeError(
        f"Unsupported provider_or_data type: {type(provider_or_data).__name__}; "
        "expected 'fmp', 'fmp_cached', pd.DataFrame, or filesystem path."
    )


# --- Result emission ----------------------------------------------------------


def _collect_results(
    candles_and_plots: Iterable[tuple["OHLCV", dict[str, Any]]],
) -> pd.DataFrame:
    """Drain pre-copied ``(candle, plot_snapshot)`` pairs into a DataFrame.

    Per D2 section 6.2, we deliberately concatenate at the end rather than
    streaming a Pydantic list, because the PRD section 6 wall-clock budget
    (<=500 ms p50) is tighter than the per-yield-write cost.

    The caller MUST pass in **already-copied** plot dicts (see
    ``run_compiled``). PyneCore's ``run_iter()`` yields
    ``(candle, lib._plot_data)`` and then CLEARS ``lib._plot_data`` after
    the yield (``script_runner.py:811``). A post-hoc ``list(...)`` of the
    iterator captures the same (cleared) reference for every bar -- the
    snapshot must happen inside the loop body.
    """
    rows: list[dict[str, Any]] = []
    timestamps: list[int] = []
    for candle, plot_data in candles_and_plots:
        timestamps.append(int(candle.timestamp))
        rows.append(plot_data if plot_data else {})

    # Build the DataFrame. Even if every plot dict is empty (a script with
    # no plot() calls), we still want a frame indexed by the bar timestamps
    # so downstream code can join to other surfaces. Empty plot dicts ->
    # zero columns; the DatetimeIndex carries the bar count.
    idx = pd.DatetimeIndex(
        [datetime.fromtimestamp(ts, tz=timezone.utc) for ts in timestamps],
        name="date",
    )
    if not rows or all(not r for r in rows):
        return pd.DataFrame(index=idx)

    # Union of keys across all yielded plot dicts (a script may add a plot
    # mid-run via conditional logic, though that is unusual). DataFrame
    # construction handles missing keys -> NaN.
    return pd.DataFrame(rows, index=idx)


# --- The runtime entry point --------------------------------------------------


def run_compiled(
    compiled: "CompiledModule",
    *,
    provider_or_data: ProviderOrData,
    symbol: str | None = None,
    interval: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    params: dict[str, Any] | None = None,  # noqa: ARG001 -- C5 future hook
    timeout_s: int | None = None,
    allow_byo_only: bool = False,  # noqa: ARG001 -- doctor wires this in P4
    user_settings: Any | None = None,
    asset_class: str | None = None,  # noqa: ARG001 -- inferred from symbol
) -> OBBject:
    """Run a compiled @pyne module end-to-end and return an ``OBBject``.

    Parameters
    ----------
    compiled
        A ``CompiledModule`` produced by D1's codegen (or a hand-built one
        in tests). The ``source`` is materialised to a tempfile so PyneCore's
        ``@pyne`` AST hook can fire on import.
    provider_or_data
        Data source -- see ``ProviderOrData`` alias. For ``"fmp"`` /
        ``"fmp_cached"`` we route through ``FMPOHLCVProvider``; for a
        ``DataFrame`` we wrap in ``BYODataProvider``; for a filesystem path
        we load+wrap.
    symbol, interval, start, end
        FMP-mode parameters. Ignored for BYO mode where the DataFrame carries
        its own bar grid.
    params
        Reserved for C5 (compiler inputs). Threaded but unused in M1.
    timeout_s
        Wall-clock cap in seconds (default ``DEFAULT_TIMEOUT_S = 30``).
    allow_byo_only
        Doctor-CLI wiring placeholder (D2 section 8); P4 propagates the flag
        in. The executor accepts it for forward compatibility.
    user_settings
        Optional ``openbb_core`` user-settings object whose
        ``defaults.commands["equity.price.historical"]["provider"]`` is
        respected by ``resolve_provider`` (D2 section 4).
    asset_class
        Reserved for callers who want to override the
        ``infer_asset_class(symbol)`` heuristic. Unused in M1.

    Returns
    -------
    ``OBBject`` with ``results`` (DataFrame) and ``extra`` (dict) as
    documented in D2 section 6.1.

    Raises
    ------
    PineSecurityError
        The compiled source references a forbidden module (defense in depth
        with D1's T1 allowlist).
    PineExecTimeoutError
        The script exceeded ``timeout_s`` wall-clock seconds.
    PineProviderError
        ``provider_or_data`` named a provider outside ``{"fmp", "fmp_cached"}``.
    PineDataValidationError
        BYO DataFrame failed the schema validation.
    PineFMPUnreachableError
        FMP / fmp_cached retried out after the budget.
    """
    # --- T3 second line of defense ---------------------------------------
    # See _pynecore_glue for the rationale. The user code is executed
    # through PyneCore which needs __import__; restrictor here is the AST scan.
    offenders = scan_for_forbidden_imports(compiled.source)
    if offenders:
        raise PineSecurityError(
            f"Compiled module references forbidden modules: {sorted(set(offenders))}. "
            "This is a T3 sandbox-violation; the compiler (T1) should have blocked it earlier."
        )

    # --- Provider construction ------------------------------------------
    provider = _resolve_data_source(
        provider_or_data,
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
        user_settings=user_settings,
    )

    # --- Materialise compiled source to a tempfile ----------------------
    # PyneCore's import_script(path) re-opens the file to verify the @pyne
    # magic docstring and then import_module-loads the stem. We give it a
    # tempfile whose stem will not collide with installed modules.
    source = ensure_pyne_header(compiled.source)
    sha_tag = (compiled.sha or "anon")[:12]
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        prefix=f"pyne_{sha_tag}_",
        encoding="utf-8",
        delete=False,
    ) as fh:
        fh.write(source)
        script_path = Path(fh.name)

    # --- Build syminfo + lazy PyneCore imports --------------------------
    primary_symbol = symbol or getattr(provider, "symbol", "BYO")
    primary_interval = interval or getattr(provider, "interval", None) or "1D"
    si = make_default_syminfo(
        primary_symbol,
        primary_interval,
        asset_class=(asset_class or getattr(provider, "asset_class", "equity")),
    )

    # ScriptRunner needs the @pyne AST hook installed; importing pynecore
    # (which our sys.path bridge has made importable) registers it.
    from pynecore import lib as _pyne_lib  # noqa: PLC0415
    from pynecore.core.script_runner import ScriptRunner  # noqa: PLC0415

    alerts: list[dict[str, Any]] = []
    timeout = timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S
    exec_started_ns: int | None = None
    exec_ended_ns: int | None = None

    def _bar_index_now() -> int:
        return int(getattr(_pyne_lib, "bar_index", 0))

    def _ts_now() -> int:
        # _time is millis in PyneCore; convert to seconds for OBB OBBject contract.
        ms = int(getattr(_pyne_lib, "_time", 0) or 0)
        return ms // 1000 if ms else 0

    try:
        runner = ScriptRunner(
            script_path=script_path,
            ohlcv_iter=provider.iter_ohlcv(),
            syminfo=si,
        )

        # The alert capture + wall-clock cap wrap ``run_iter()`` together so
        # an in-flight alert that exceeds the budget still raises cleanly
        # (the alert callback finishes synchronously inside the script call).
        # Per-yield copy is REQUIRED -- PyneCore reuses lib._plot_data across
        # yields and clears it after each yield (script_runner.py:811). A
        # post-hoc copy via list(runner.run_iter()) captures the same
        # (cleared) dict for every bar. We materialise (candle, dict(plot))
        # inside the generator so the snapshot is taken BEFORE the clear.
        candles_and_plots: list[tuple[Any, dict[str, Any]]] = []
        with capture_alerts(
            alerts,
            bar_index_getter=_bar_index_now,
            timestamp_getter=_ts_now,
        ), enforce_limits(timeout_s=timeout):
            exec_started_ns = _time.perf_counter_ns()
            # Indicators yield 2-tuples; strategies yield 3-tuples. We only
            # care about (candle, plot_data) here -- the trades tuple element
            # is consumed by the strategy emitter in Phase 2.
            for tup in runner.run_iter():
                candle = tup[0]
                plot_data = tup[1]
                candles_and_plots.append((candle, dict(plot_data) if plot_data else {}))
            exec_ended_ns = _time.perf_counter_ns()
    except PineExecTimeoutError:
        # Make sure we still measure elapsed even on timeout, for debug.
        if exec_ended_ns is None:
            exec_ended_ns = _time.perf_counter_ns()
        raise
    finally:
        try:
            script_path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover -- best-effort cleanup
            pass

    # --- Build OBBject ---------------------------------------------------
    results_df = _collect_results(candles_and_plots)

    if exec_started_ns is None or exec_ended_ns is None:
        exec_ms = 0
    else:
        exec_ms = max(0, (exec_ended_ns - exec_started_ns) // 1_000_000)

    extra: dict[str, Any] = {
        "alerts": alerts,
        # M1 indicator path -> orders always []; strategy fill engine lands
        # in M2 (D2 §10 OUT OF SCOPE table).
        "orders": [],
        "attribution": POWERED_BY_FULL,
        "compile_cache_hit": getattr(compiled, "cache_status", "miss") == "hit",
        "exec_ms": int(exec_ms),
        "provider_used": getattr(provider, "provider_used", "unknown"),
        "bars_consumed": int(getattr(provider, "bars_consumed", 0)),
    }

    return OBBject(results=results_df, extra=extra)


__all__ = ["ProviderOrData", "run_compiled"]
