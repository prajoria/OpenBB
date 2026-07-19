"""openbb-backtest soft-dependency bridge (D5 §6.1, GH #590).

The bridge is the seam between Pine strategy runs and ``openbb-backtest``'s
analytics layer. ``openbb-backtest`` is optional: if the user has installed
it, we hand off strategy results to ``openbb_backtest.analytics.ingest_pine_strategy``
so its KPI / attribution / risk analytics can cross-reference our run.
If it's absent, we no-op and document why in ``result.extra["warnings"]``.

Design contract (D5 §6.1):

* Called optionally by the strategy run pipeline (currently the
  ``/pine/strategies/run`` and ``/pine/strategies/run_byo`` handlers,
  after ``_apply_strategy_params``) when ``script_type == "strategy"``.
* Guard: silently no-op when ``result.extra.get("script_type") != "strategy"``.
  Rationale: only strategy runs have trade lists / equity curves worth
  handing to a backtest analytics layer; appending a "backtest not
  installed" warning to an *indicator* result would be misleading.
* Import guard: ``from openbb_backtest.analytics import ingest_pine_strategy``
  inside a ``try/except ImportError``. On ImportError, append a
  human-readable + docs-pointer-carrying warning to
  ``result.extra.setdefault("warnings", [])`` and return.
* Happy path: call ``ingest_pine_strategy(result)`` and let it mutate
  the result / do its analytics work. Do NOT swallow non-ImportError
  exceptions from the ingest — a real bug in the downstream analytics
  layer must surface (per CLAUDE.md R7.3: loud empties).

#589 (a separate follow-up issue) is responsible for the *payload*
translation — this module ships only the guard + call-site wiring. Once
#589 lands, ``ingest_pine_strategy`` receives a real translated payload;
until then, the happy-path branch is exercised only via the test's
synthetic ``sys.modules`` planting (there is no shipping consumer yet).

Warning wording (verbatim from D5 §6.1 with the small edit "See README
§Analytics integration" → "See openbb_pine README §Analytics integration"
so the docs pointer is unambiguous when the user is inside a workspace
with many READMEs).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover -- typing only
    from openbb_core.app.model.obbject import OBBject


_BACKTEST_MISSING_WARNING = (
    "openbb-backtest not installed — install it to enable KPI analytics "
    "cross-referencing. See openbb_pine README §Analytics integration."
)


def maybe_export_to_backtest(strategy_result: OBBject) -> None:
    """Hand off a Pine strategy result to openbb-backtest if available.

    Called optionally by the strategy run pipeline after
    ``_apply_strategy_params``. Semantics per D5 §6.1:

    * If ``strategy_result.extra["script_type"] != "strategy"`` (or the
      key is missing), silently no-op — the bridge is only meaningful
      for strategy runs.
    * Otherwise, attempt ``from openbb_backtest.analytics import ingest_pine_strategy``.
      On :class:`ImportError`, append :data:`_BACKTEST_MISSING_WARNING`
      to ``strategy_result.extra.setdefault("warnings", [])`` and return.
    * On successful import, invoke ``ingest_pine_strategy(strategy_result)``.
      Any exception from that call propagates (per CLAUDE.md R7.3).

    Parameters
    ----------
    strategy_result
        The :class:`OBBject` returned by the Pine strategy run pipeline.
        Mutated in place when a warning is appended; passed through to
        ``ingest_pine_strategy`` on the happy path.

    Returns
    -------
    None
        Side-effect only. Callers do not need to capture a return value.

    Notes
    -----
    #589 will replace the direct pass-through with a shape adapter that
    translates ``strategy_result.extra["stats"]`` / ``["orders"]`` into
    openbb-backtest's native ``BacktestResult`` model (D5 §6.2). This
    module ships only the guard + soft-import; the payload contract is
    #589's scope.
    """
    extra = getattr(strategy_result, "extra", None)
    if not isinstance(extra, dict):
        # Defensive: an OBBject without a dict-shaped .extra can't
        # possibly be a strategy result the strategies router produced.
        # No-op silently — this mirrors the "silent no-op for
        # non-strategy" branch below rather than raising, because the
        # bridge is optional and never the source of truth for validation.
        return

    if extra.get("script_type") != "strategy":
        # Non-strategy result routed here by mistake (or by a caller
        # exercising the seam pre-#589). Silently no-op — see docstring
        # rationale.
        return

    try:
        # Deferred import inside the function body is intentional: the
        # whole point of this bridge is to make openbb-backtest OPTIONAL.
        # Top-level import would defeat that and turn the soft-dep into
        # a hard-dep at module-import time.
        # pylint: disable-next=import-outside-toplevel  # intentional soft-dep guard
        from openbb_backtest.analytics import ingest_pine_strategy
    except ImportError:
        extra.setdefault("warnings", []).append(_BACKTEST_MISSING_WARNING)
        return

    ingest_pine_strategy(strategy_result)


__all__ = ["maybe_export_to_backtest"]
