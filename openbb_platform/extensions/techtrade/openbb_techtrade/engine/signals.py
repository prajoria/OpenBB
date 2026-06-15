"""Signals orchestrator: movers -> panels -> confluence -> ranked MoverSignals (issue #75).

The pure core behind ``obb.techtrade.signals``. :func:`build_signals` runs the #74
confluence voting engine over an explicit symbol set or a whole GICS segment and
returns ranked :class:`~openbb_techtrade.models.MoverSignal`s -- each carrying a
composite score, a direction, and the per-indicator vote attribution that explains
*why* the engine voted the way it did, with the preset's weight tilt visible in every
``vote.weight``.

The chain is::

    weights  = resolve_preset(preset, weights)              # strategies/presets.py (#75)
    session  = resolve_session(as_of)                       # look-ahead-free snap (#70)
    universe = symbols  OR  list_movers(segment)            # Q-C universe resolution
    panels   = [panel_fetcher(sym, as_of=session) ...]      # #73 selector / #72 builder
    signals  = [build_signal(panel, label, weights=...) ]   # #74 score + direction + votes
    return     rank(signed score desc, tie symbol asc)      # contiguous rank_in_segment

This module is **pure and offline-testable**: every panel is sourced through the
injectable ``panel_fetcher`` seam (default :func:`_default_panel_fetcher`, which wraps
the live #73/#72 builder), so the unit + golden suites drive the full stack with
seeded fixture panels and no network. The segment path's universe resolution delegates
to :func:`~openbb_techtrade.engine.movers.list_movers`, whose own DI seams keep the
live fetch integration-only.

**Ranking is signed-score descending** (most-long first), tie-broken by ``symbol``
ascending, producing a contiguous ``1..N`` ``rank_in_segment`` (Q-C). A note on volume:
#74's :func:`~openbb_techtrade.engine.confluence.volume_confirmation` is a *signed* (not
direction-aware) multiplier with no ``sign(raw)`` term, so it confirms *long* (``raw>0``)
signals but is **inverted for short** (``raw<0``) signals -- bearish volume *damps* a
short's conviction instead of amplifying it. Because the locked pipeline contract makes
presets weights-only and freezes ``volume_confirmation``'s no-argument signature, that
behaviour is ratified and surfaced here (pinned by a command-layer ranking test); the
direction-aware engine fix is separate future scope.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from openbb_techtrade.engine.confluence import ConfluenceWeights, build_signal
from openbb_techtrade.models import IndicatorPanel, MoverSignal
from openbb_techtrade.strategies.presets import resolve_preset

#: Segment label stamped on signals when only an explicit symbol set is supplied.
_CUSTOM_SEGMENT = "custom"


def _default_panel_fetcher(symbol: str, *, as_of: date) -> IndicatorPanel:
    """Build a symbol's :class:`IndicatorPanel` from the live #73 selector (integration-only).

    The default ``panel_fetcher`` seam: delegates to the #73
    :func:`~openbb_techtrade.engine.indicators.build_panel_for_symbol`, which snaps the
    session, fetches OHLCV via fmp_cached, and computes the panel. Imported lazily so the
    unit/golden suites (which inject an offline fake) never touch ``openbb``.

    Parameters
    ----------
    symbol : str
        The instrument symbol to build a panel for.
    as_of : date
        Resolved session date (already snapped; no look-ahead).

    Returns
    -------
    IndicatorPanel
        The per-symbol indicator panel on ``as_of``.
    """
    from openbb_techtrade.engine.indicators import build_panel_for_symbol

    return build_panel_for_symbol(symbol, as_of=as_of)


def _resolve_universe(
    symbols: list[str] | None,
    segment: str | None,
    session: date,
) -> tuple[list[str], str]:
    """Resolve the candidate symbol list and the segment label to stamp on signals (Q-C).

    An explicit ``symbols`` set is used verbatim (label = ``segment`` if also given, else
    ``"custom"``). Otherwise a ``segment`` is resolved into its ranked top movers via the
    #70 :func:`~openbb_techtrade.engine.movers.list_movers` pipeline (live fetch behind its
    own DI seams). Passing neither is a programming error.

    Parameters
    ----------
    symbols : list[str] | None
        Explicit instrument symbols, or ``None`` to resolve from ``segment``.
    segment : str | None
        A GICS segment to resolve into top movers, or ``None`` when ``symbols`` is given.
    session : date
        The resolved session date for the movers ranking.

    Returns
    -------
    tuple[list[str], str]
        The candidate symbols and the segment label to stamp on each signal.

    Raises
    ------
    ValueError
        If both ``symbols`` and ``segment`` are ``None``.
    """
    if symbols:
        return list(symbols), segment if segment is not None else _CUSTOM_SEGMENT

    if segment is not None:
        from openbb_techtrade.engine.movers import list_movers

        mover_lists = list_movers(segment=segment, as_of=session)
        resolved = [mover.symbol for ml in mover_lists for mover in ml.movers]
        return resolved, segment

    raise ValueError("build_signals requires either symbols or segment (both were None).")


def _rank_signals(signals: list[MoverSignal]) -> list[MoverSignal]:
    """Sort signals by signed score descending and stamp a contiguous ``rank_in_segment``.

    Most-long first (signed ``score`` descending), deterministic tie-break by ``symbol``
    ascending, then a one-based contiguous ``1..N`` rank re-stamped onto each signal via
    ``model_copy`` (the source signals carry the default rank ``0``).

    Parameters
    ----------
    signals : list[MoverSignal]
        The unranked per-symbol signals.

    Returns
    -------
    list[MoverSignal]
        The signals sorted best-first, each with its ``rank_in_segment`` populated.
    """
    ordered = sorted(signals, key=lambda s: (-s.score, s.symbol))
    return [s.model_copy(update={"rank_in_segment": index}) for index, s in enumerate(ordered, start=1)]


def build_signals(
    symbols: list[str] | None = None,
    segment: str | None = None,
    *,
    preset: str = "trend_follow",
    weights: dict[str, float] | None = None,
    as_of: date | str | None = None,
    panel_fetcher: Callable[..., IndicatorPanel] | None = None,
) -> list[MoverSignal]:
    """Compute ranked confluence signals for a symbol set or a GICS segment (PRD §12.3, §9.2).

    Resolves the preset (+ optional custom ``weights`` override), snaps ``as_of`` to a
    trading session, resolves the universe (explicit ``symbols`` or a ``segment``'s top
    movers), builds each symbol's panel through the injectable ``panel_fetcher`` seam,
    scores it with the #74 engine, and ranks the results by signed score descending into
    a contiguous ``rank_in_segment`` (Q-C). The per-indicator votes (with the resolved
    preset weights) are carried through unchanged for full "why long?" attribution.

    Parameters
    ----------
    symbols : list[str] | None, optional
        Explicit instrument symbols to score. Takes precedence over ``segment``.
    segment : str | None, optional
        A GICS segment to resolve into its ranked top movers when ``symbols`` is ``None``.
    preset : str, optional
        Named confluence preset (``"trend_follow"`` default / ``"mean_revert"`` /
        ``"breakout"``).
    weights : dict[str, float] | None, optional
        Partial ``{family: weight}`` override merged over the preset (Q-D).
    as_of : date | str | None, optional
        Requested date, snapped to a session. Defaults to today when ``None``.
    panel_fetcher : Callable[..., IndicatorPanel] | None, optional
        Panel-builder seam invoked as ``panel_fetcher(symbol, as_of=session)``; defaults
        to the live :func:`_default_panel_fetcher`. Tests inject an offline fake.

    Returns
    -------
    list[MoverSignal]
        The ranked signals (best first), each carrying ``score`` / ``direction`` /
        ``votes`` / ``rank_in_segment``.

    Raises
    ------
    ValueError
        If neither ``symbols`` nor ``segment`` is given, or on an invalid preset /
        weights override (propagated from :func:`resolve_preset`).
    """
    from openbb_techtrade.engine.movers import resolve_session

    resolved_weights: ConfluenceWeights = resolve_preset(preset, weights)
    session = resolve_session(as_of)
    universe, label = _resolve_universe(symbols, segment, session)
    fetch = panel_fetcher or _default_panel_fetcher

    signals = [
        build_signal(fetch(symbol, as_of=session), label, weights=resolved_weights)
        for symbol in universe
    ]
    return _rank_signals(signals)
