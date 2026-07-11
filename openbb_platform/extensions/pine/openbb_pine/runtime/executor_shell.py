"""OpenBB-fork-specific wrapper around ``executor_core`` — E0.3 split (bd-9zb).

Extracted from ``executor.py`` per Pine Extraction Design §6.E0.3. This
module owns the concerns that STAY in openbb-fork after the pynecore
extraction:

* Concrete provider instantiation (``FMPOHLCVProvider`` for
  ``"fmp"`` / ``"fmp_cached"``; ``BYODataProvider`` for a
  ``pd.DataFrame`` / filesystem path).
* Attaching the ``POWERED_BY_FULL`` attribution string to the response.
* Building the ``OBBject`` envelope with the D2 §6.1 ``.extra`` keys the
  REST / MCP / Workspace surfaces consume.
* Owning the FMP retry budget (``fmp_retry.call_with_retry``) at the
  boundary — the providers themselves are minimal (no retry loop
  inside), so the shell decides where the retry envelope wraps. Today
  the retry envelope lives inside :class:`FMPOHLCVProvider._fetch` (see
  bead E3.2 for the pending refactor to hoist retry OUT of the
  provider into this shell); this module carries the ``fmp_retry``
  import so the seam is documented in one place even while the retry
  call still lives inside the provider class.

The shell delegates the actual bar iteration to
:func:`~openbb_pine.runtime.executor_core.run_compiled`, then wraps the
returned ``(results_df, exec_ms, alerts)`` tuple in an ``OBBject`` with
D2 §6.1's seven ``.extra`` keys.

Clean-room note: I have not viewed TradingView or PyneComp source code.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd

from openbb_core.app.model.obbject import OBBject

from openbb_pine.attribution import POWERED_BY_FULL
from pyne_compiler.errors.base import PineUnsupportedFeatureError
from pyne_compiler.runtime import executor_core

# DO NOT REMOVE the ``fmp_retry`` import below. The retry envelope still
# lives inside ``FMPOHLCVProvider._fetch`` today; this shell carries the
# import so the pending hoist (retry moves OUT of the provider INTO this
# shell — tracked in bd-78w SITE 2 / E3) has a single grep-discoverable
# anchor. A future dead-import sweep MUST NOT strip this until the hoist
# lands and ``fmp_retry.call_with_retry`` is invoked from this module.
from openbb_pine.runtime import fmp_retry  # noqa: F401 -- seam anchor, see comment above
from openbb_pine.runtime.byo_provider import BYODataProvider
from openbb_pine.runtime.fmp_provider import (
    FMPOHLCVProvider,
    FMPRequest,
    infer_asset_class,
)

if TYPE_CHECKING:  # pragma: no cover -- typing-only
    from pyne_compiler.compiler.types import CompiledModule


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


# --- The runtime entry point --------------------------------------------------


def _run_strategy(
    compiled: "CompiledModule",
    *,
    provider: Any,
    symbol: str | None,
    interval: str | None,
    params: dict[str, Any] | None,  # noqa: ARG001 -- C5 future hook
    timeout_s: int | None,
    asset_class: str | None,
) -> OBBject:
    """Strategy branch of ``run_compiled`` — bd-liz (D5 §5.2).

    Mirrors ``executor_core.run_compiled`` for the pieces we cannot yet
    share (indicators yield 2-tuples; strategies yield 3-tuples and need
    per-bar equity capture + StrategyStatistics serialization).

    Emits an ``OBBject`` with the same seven core ``.extra`` keys as the
    indicator branch, PLUS:

      * ``stats`` — dict form of ``StrategyStatistics``
        (``serialize_strategy_statistics``).
      * ``equity_curve`` — list of per-bar ``{bar_index, equity, drawdown}``
        (``capture_equity_snapshot``).

    ``request.security`` prefetch + secondaries hook are installed for the
    bar loop when ``compiled.security_contexts`` is non-empty; the hook
    unwinds on exit even if the script raises.
    """
    import contextlib as _contextlib  # noqa: PLC0415
    import tempfile as _tempfile  # noqa: PLC0415
    import time as _time  # noqa: PLC0415
    from datetime import datetime as _datetime  # noqa: PLC0415
    from pathlib import Path as _Path  # noqa: PLC0415

    from pyne_compiler.errors.base import (  # noqa: PLC0415
        PineExecTimeoutError,
        PineSecurityError,
    )
    from pyne_compiler.runtime._pynecore_glue import (  # noqa: PLC0415
        capture_alerts,
        ensure_pyne_header,
        make_default_syminfo,
        scan_for_forbidden_imports,
    )
    from pyne_compiler.runtime.limits import (  # noqa: PLC0415
        DEFAULT_TIMEOUT_S,
        enforce_limits,
    )
    from pyne_compiler.runtime.security_dispatcher import (  # noqa: PLC0415
        prefetch_security_contexts,
    )
    from pyne_compiler.runtime.security_hook import (  # noqa: PLC0415
        install_secondaries_hook,
    )
    from pyne_compiler.runtime.strategy_types import (  # noqa: PLC0415
        capture_equity_snapshot,
        serialize_strategy_statistics,
    )

    # T3 second line of defense — mirrors executor_core.
    offenders = scan_for_forbidden_imports(compiled.source)
    if offenders:
        raise PineSecurityError(
            rule="SEC001",
            node_kind=f"forbidden imports: {sorted(set(offenders))}",
            hint=(
                "This is a T3 sandbox-violation; the compiler (T1) should "
                "have blocked it earlier."
            ),
        )

    # Materialise compiled source to a tempfile so ScriptRunner can
    # re-import through the ``@pyne`` AST hook.
    source = ensure_pyne_header(compiled.source)
    sha_tag = (compiled.sha or "anon")[:12]
    with _tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        prefix=f"pyne_{sha_tag}_",
        encoding="utf-8",
        delete=False,
    ) as fh:
        fh.write(source)
        script_path = _Path(fh.name)

    primary_symbol = symbol or getattr(provider, "symbol", "BYO")
    primary_interval = interval or getattr(provider, "interval", None) or "1D"
    si = make_default_syminfo(
        primary_symbol,
        primary_interval,
        asset_class=(asset_class or getattr(provider, "asset_class", "equity")),
    )

    # Deferred pynecore imports (sys.path bridge already installed).
    from pynecore import lib as _pyne_lib  # noqa: PLC0415
    from pynecore.core.script_runner import ScriptRunner  # noqa: PLC0415

    alerts: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    timeout = timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S
    exec_started_ns: int | None = None
    exec_ended_ns: int | None = None

    def _bar_index_now() -> int:
        return int(getattr(_pyne_lib, "bar_index", 0))

    def _ts_now() -> int:
        ms = int(getattr(_pyne_lib, "_time", 0) or 0)
        return ms // 1000 if ms else 0

    # Secondaries hook — only when the compiled module actually declares
    # request.security() contexts. Empty / None → nullcontext (no monkey
    # patch, no prefetch).
    security_contexts = getattr(compiled, "security_contexts", None) or {}
    if security_contexts:
        # Primary bar grid is what the provider hands to ScriptRunner; the
        # dispatcher aligns secondaries to that same grid.
        primary_df = getattr(provider, "df", None)
        if primary_df is None:
            primary_df = pd.DataFrame(list(provider.iter_ohlcv()))
        secondaries = prefetch_security_contexts(
            security_contexts, primary_df, provider=provider,
        )
        hook_ctx: Any = install_secondaries_hook(
            secondaries,
            security_contexts,
            get_current_bar_index=_bar_index_now,
        )
    else:
        hook_ctx = _contextlib.nullcontext()

    try:
        runner = ScriptRunner(
            script_path=script_path,
            ohlcv_iter=provider.iter_ohlcv(),
            syminfo=si,
        )

        candles_and_plots: list[tuple[Any, dict[str, Any]]] = []
        bar_index = 0
        with capture_alerts(
            alerts,
            bar_index_getter=_bar_index_now,
            timestamp_getter=_ts_now,
        ), enforce_limits(timeout_s=timeout), hook_ctx:
            exec_started_ns = _time.perf_counter_ns()
            for tup in runner.run_iter():
                candle = tup[0]
                plot_data = tup[1]
                # Per-yield copy — script_runner clears lib._plot_data
                # after each yield (executor_core R7 defense).
                candles_and_plots.append(
                    (candle, dict(plot_data) if plot_data else {})
                )
                # Equity snapshot — SimPosition.equity is (initial_capital
                # + netprofit + openprofit); .max_drawdown is the running
                # peak-to-trough magnitude PyneCore already tracks.
                position = getattr(runner.script, "position", None)
                if position is not None:
                    try:
                        eq_val = float(position.equity) if position.equity else float(
                            runner.script.initial_capital
                        )
                    except (TypeError, ValueError):
                        eq_val = float(runner.script.initial_capital)
                    try:
                        dd_val = float(position.max_drawdown)
                    except (TypeError, ValueError):
                        dd_val = 0.0
                    capture_equity_snapshot(
                        equity_curve,
                        bar_index=bar_index,
                        equity=eq_val,
                        drawdown=dd_val,
                    )
                bar_index += 1
            exec_ended_ns = _time.perf_counter_ns()
    except PineExecTimeoutError:
        if exec_ended_ns is None:
            exec_ended_ns = _time.perf_counter_ns()
        raise
    finally:
        try:
            script_path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover -- best-effort cleanup
            pass

    # --- Emit results + stats --------------------------------------------
    results_df = executor_core._collect_results(candles_and_plots)
    if exec_started_ns is None or exec_ended_ns is None:
        exec_ms = 0
    else:
        exec_ms = max(0, (exec_ended_ns - exec_started_ns) // 1_000_000)

    # Compute stats via PyneCore's aggregator — same code path the CSV
    # writer inside ScriptRunner uses, but we call it explicitly since
    # our OHLCV-iter driver never triggers ``self.strat_writer``.
    from pynecore.core.strategy_stats import (  # noqa: PLC0415
        calculate_strategy_statistics,
    )

    position = getattr(runner.script, "position", None)
    stats_obj = None
    if position is not None:
        stats_obj = calculate_strategy_statistics(
            position,
            float(runner.script.initial_capital),
            [pt["equity"] for pt in equity_curve] if equity_curve else None,
            getattr(runner, "first_price", None),
            getattr(runner, "last_price", None),
        )

    extra: dict[str, Any] = {
        "alerts": alerts,
        # M2 strategy branch: closed-trade summaries land in bd-4d0 /
        # strategies_router flip — the on-wire ``orders`` field stays
        # empty until then so the indicator contract matches.
        "orders": [],
        "attribution": POWERED_BY_FULL,
        "compile_cache_hit": getattr(compiled, "cache_status", "miss") == "hit",
        "exec_ms": int(exec_ms),
        "provider_used": getattr(provider, "provider_used", "unknown"),
        "bars_consumed": int(getattr(provider, "bars_consumed", 0)),
        "stats": serialize_strategy_statistics(stats_obj),
        "equity_curve": equity_curve,
    }

    return OBBject(results=results_df, extra=extra)


def run_compiled(
    compiled: "CompiledModule",
    *,
    provider_or_data: ProviderOrData,
    symbol: str | None = None,
    interval: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    params: dict[str, Any] | None = None,
    timeout_s: int | None = None,
    allow_byo_only: bool = False,  # noqa: ARG001 -- doctor wires this in P4
    user_settings: Any | None = None,
    asset_class: str | None = None,
) -> OBBject:
    """Run a compiled ``@pyne`` module end-to-end and return an ``OBBject``.

    Instantiates the concrete provider (FMP-cached / FMP / BYO), delegates
    the actual bar iteration to :func:`executor_core.run_compiled`, then
    wraps the returned raw pieces in an ``OBBject`` with the D2 §6.1
    ``.extra`` contract (``alerts``, ``orders``, ``attribution``,
    ``compile_cache_hit``, ``exec_ms``, ``provider_used``,
    ``bars_consumed``).

    Parameters
    ----------
    compiled
        A ``CompiledModule`` produced by D1's codegen (or a hand-built one
        in tests).
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
        Wall-clock cap in seconds (default from executor_core).
    allow_byo_only
        Doctor-CLI wiring placeholder (D2 §8); P4 propagates the flag in.
        The executor accepts it for forward compatibility.
    user_settings
        Optional ``openbb_core`` user-settings object whose
        ``defaults.commands["equity.price.historical"]["provider"]`` is
        respected by ``resolve_provider`` (D2 §4).
    asset_class
        Reserved for callers who want to override the
        ``infer_asset_class(symbol)`` heuristic.

    Returns
    -------
    ``OBBject`` with ``results`` (DataFrame) and ``extra`` (dict) as
    documented in D2 §6.1.

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
    # --- Provider construction (openbb-fork-specific) --------------------
    provider = _resolve_data_source(
        provider_or_data,
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
        user_settings=user_settings,
    )

    # --- Script-type dispatch (bd-liz — D5 §5.2) -------------------------
    script_type = getattr(compiled, "script_type", "indicator")
    if script_type == "library":
        # PF011 — library() is M3-deferred. The compiler already rejects
        # this at compile time; this defence catches hand-built
        # ``CompiledModule`` instances that skipped the compiler gate.
        raise PineUnsupportedFeatureError(
            "PF011 library decl - deferred (no Phase-1 use-case)",
        )

    if script_type == "strategy":
        return _run_strategy(
            compiled,
            provider=provider,
            symbol=symbol,
            interval=interval,
            params=params,
            timeout_s=timeout_s,
            asset_class=asset_class,
        )

    # --- Indicator branch — delegate to the core loop --------------------
    results_df, exec_ms, alerts = executor_core.run_compiled(
        compiled,
        provider=provider,
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
        params=params,
        timeout_s=timeout_s,
        asset_class=asset_class,
    )

    # --- Attach the openbb-fork-specific envelope ------------------------
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


__all__ = ["ProviderOrData", "run_compiled", "_resolve_data_source"]
