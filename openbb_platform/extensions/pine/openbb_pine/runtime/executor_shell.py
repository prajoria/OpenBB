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

    # --- Delegate the core loop ------------------------------------------
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
