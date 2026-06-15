"""scan orchestrator: all 11 GICS sectors -> cross-segment ranked TradePlans (issue #79, PRD §9.2).

The one-call orchestrator behind ``obb.techtrade.scan``. It is pure **composition** over the
already-built techtrade chain (the design §19 / L4 anti-duplication contract): it owns ONLY the
fan-out across sectors (left edge) and the final cross-segment rank (right edge). Every stage in
between is an existing engine call --

* ``movers.list_movers(segment=None, ...)`` (#70) -- ranks the top movers of all 11 GICS sectors in
  canonical ``GICS_SECTOR_ETFS`` order;
* ``plan.build_plans(symbols=..., segment=...)`` (#75 signals -> #76 rules/sizing -> #77 orders +
  inline ``Recommendation``) -- assembles one ``TradePlan`` per mover;
* ``execution.broker.simulate(orders, bars)`` (#78) -- paper-fills each plan's orders when a forward
  ``t+1...`` window is supplied.

Because #77's ``plan`` exposes no reusable ``build_plans_for_symbols`` seam, this v1 uses the
design-approved **B1** shape (§0.2 Q-B answer): loop ``build_plans`` once per ``MoverList`` (the
literal "loop ``plan(segment=s)`` x11"), with **segment-level** skip-and-continue around each build
and **per-symbol** skip-and-continue around each ``simulate``. Failures emit ``warnings.warn`` so the
command runner surfaces them in ``OBBject.warnings`` (design Q-E). The single new ordering logic is
:func:`_rank_key`: a total-order key ``(-round(abs(score), 9), symbol, segment)`` -- conviction
magnitude first (direction-neutral), then symbol, then segment (a symbol can appear in two sector
ETFs, so segment closes the order). Ranking reads only the **pre-fill** ``signal.score`` so the order
is identical with or without ``simulate`` (design Q-C C3). Determinism rests on a single parent-side
``resolve_session(as_of, "XNYS")`` snap threaded everywhere, the fixed sector order, and the 9-dp
rounding (= ``testing.DEFAULT_TOL``).

This module imports the chain engines (``movers`` / ``plan`` / ``execution.broker``) and ``models``
ONLY -- never ``indicators`` / ``confluence`` / ``rules`` / ``orders`` (the chain-math it composes,
never re-implements; a unit test guards this §19 boundary).
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from openbb_techtrade.engine.movers import list_movers, resolve_session
from openbb_techtrade.engine.plan import build_plans
from openbb_techtrade.execution.broker import simulate as simulate_orders
from openbb_techtrade.models import MoverSignal, TradePlan

#: Default risk fraction (mirrors plan.build_plans' 0.01) used when ``risk`` is left ``None``.
_DEFAULT_RISK = 0.01
#: Rounding epsilon for the rank key; matches ``testing.DEFAULT_TOL`` so float noise never reorders.
_RANK_EPSILON = 9


def _rank_key(plan: TradePlan) -> tuple[float, str, str]:
    """Cross-segment total-order sort key: ``(-round(|score|, 9), symbol, segment)`` (design §3).

    Primary key is conviction magnitude (``|signal.score|``) descending, so the most decisive setups
    float to the top regardless of side (a strong short ranks like a strong long). Ties break to a
    **total** order by ``symbol`` then ``segment`` -- the latter is required because a symbol can
    surface in two sector ETFs, so ``symbol`` alone is not unique across segments. The key reads only
    the pre-fill ``signal.score`` so the order is identical whether or not ``simulate`` ran.

    Parameters
    ----------
    plan : TradePlan
        The plan to derive a sort key for.

    Returns
    -------
    tuple[float, str, str]
        ``(-round(abs(score), 9), symbol, segment)``.
    """
    score = plan.signal.score
    return (-round(abs(score), _RANK_EPSILON), plan.symbol, plan.segment)


def scan_segments(
    metric: str = "pct_change",
    top_n: int = 10,
    *,
    preset: str = "trend_follow",
    risk: float | None = None,
    as_of: date | str | None = None,
    simulate: bool = True,
    limit: int | None = None,
    candidate_fetcher: Callable[..., list[dict]] | None = None,
    signal_fetcher: Callable[..., list[MoverSignal]] | None = None,
    level_fetcher: Callable[..., tuple[Decimal, float]] | None = None,
    bars: dict[str, list] | None = None,
    broker: object | None = None,
) -> list[TradePlan]:
    """Screen all 11 GICS sectors and return cross-segment ranked ``TradePlan``s (PRD §9.2, #79).

    The one-call orchestrator. Snaps ``as_of`` once to the last ``XNYS`` session, ranks each sector's
    top ``top_n`` movers by ``metric`` (``movers.list_movers(segment=None, ...)``), then -- per sector
    (the design-approved **B1** shape) -- assembles a ``TradePlan`` for that sector's movers via
    ``plan.build_plans(symbols=..., segment=...)`` (the #75->#76->#77 chain). When ``simulate`` and a
    forward bar window is supplied for a plan's symbol, the plan's orders are paper-filled (#78) and
    the fills attached. Non-actionable plans (flat / sub-threshold -> empty ``orders``) are filtered,
    and the survivors are sorted by :func:`_rank_key` (conviction magnitude, total-order tie-break).
    A build or fill failure for one sector / symbol is skipped with a ``warnings.warn`` (surfaced in
    ``OBBject.warnings``) rather than aborting the whole scan (design Q-E).

    Parameters
    ----------
    metric : str, optional
        The **mover** rank metric (``pct_change`` / ``volume`` / ``gap`` / ``rel_volume``) selecting
        *which* movers per sector enter the chain. **Not** the cross-segment plan-rank key (that is
        always ``|signal.score|``, §3). Defaults to ``"pct_change"``.
    top_n : int, optional
        Per-segment mover cap (reuses ``movers``/``SegmentConfig`` semantics). The returned list holds
        up to ``11 x top_n`` actionable plans, fully sorted. Defaults to ``10``.
    preset : str, optional
        Confluence/rule preset forwarded to the signal chain. Defaults to ``"trend_follow"``.
    risk : float | None, optional
        Risk-per-trade fraction fed to the #76 sizing; ``None`` uses the chain default ``0.01``.
    as_of : date | str | None, optional
        Requested date, snapped **once** parent-side to the last ``XNYS`` session and threaded down
        (no per-sector re-snap -> no look-ahead drift). Defaults to today when ``None``.
    simulate : bool, optional
        Run #78 fills inline when ``True`` (and a forward window is available); ``False`` returns the
        order skeletons only. Ranking is pre-fill, so the order is identical either way. Defaults to
        ``True``.
    limit : int | None, optional
        Optional global top-of-list slice applied after the cross-segment sort. Defaults to ``None``
        (return the full sorted set).
    candidate_fetcher : Callable[..., list[dict]] | None, optional
        Mover-candidate seam forwarded to ``list_movers``; injected by tests for an offline universe.
    signal_fetcher : Callable[..., list[MoverSignal]] | None, optional
        Ranked-signal seam forwarded to ``build_plans``; injected by tests.
    level_fetcher : Callable[..., tuple[Decimal, float]] | None, optional
        ``(entry, atr)`` seam forwarded to ``build_plans``; injected by tests.
    bars : dict[str, list] | None, optional
        Per-symbol forward (``t+1...``) OHLCV windows for the fill simulation. When ``None`` no fills
        are produced (the live forward-bar fetcher is a follow-up; the skeleton is still ranked).
    broker : object | None, optional
        Broker forwarded to ``simulate``; ``None`` uses the default ``PaperBroker``.

    Returns
    -------
    list[TradePlan]
        Actionable plans across all 11 sectors, cross-segment ranked by ``|signal.score|`` desc
        (symbol, segment tie-break); ``[]`` when no actionable plan is found.
    """
    session = resolve_session(as_of, "XNYS")
    risk_fraction = risk if risk is not None else _DEFAULT_RISK

    mover_lists = list_movers(
        segment=None, metric=metric, top_n=top_n, as_of=session,
        candidate_fetcher=candidate_fetcher,
    )

    plans: list[TradePlan] = []
    for mover_list in mover_lists:
        symbols = [mover.symbol for mover in mover_list.movers]
        if not symbols:
            continue
        try:
            segment_plans = build_plans(
                symbols=symbols, segment=mover_list.segment, preset=preset,
                risk=risk_fraction, as_of=session,
                signal_fetcher=signal_fetcher, level_fetcher=level_fetcher,
            )
        except Exception as exc:  # noqa: BLE001 - skip-and-continue isolation (design Q-E)
            warnings.warn(
                f"scan: skipped segment {mover_list.segment!r}: {exc}", stacklevel=2,
            )
            continue
        plans.extend(segment_plans)

    if simulate and bars is not None:
        plans = [_with_fills(plan, bars, broker) for plan in plans]

    actionable = [plan for plan in plans if plan.orders]
    ranked = sorted(actionable, key=_rank_key)
    return ranked[:limit] if limit is not None else ranked


def _with_fills(plan: TradePlan, bars: dict[str, list], broker: object | None) -> TradePlan:
    """Return ``plan`` with paper fills attached for its symbol's forward window (skip on failure).

    Looks up the plan's symbol in ``bars``; when a non-empty forward window and order list are both
    present, runs ``execution.broker.simulate`` and attaches the resulting fills via ``model_copy``.
    A missing window, empty orders, or a simulation error leaves the plan unchanged (per-symbol
    skip-and-continue with a ``warnings.warn`` on error, design Q-E). Ranking never depends on fills,
    so a skipped fill does not affect the plan's position in the output.

    Parameters
    ----------
    plan : TradePlan
        The plan whose orders to fill.
    bars : dict[str, list]
        Per-symbol forward (``t+1...``) OHLCV windows.
    broker : object | None
        Broker forwarded to ``simulate`` (``None`` -> default ``PaperBroker``).

    Returns
    -------
    TradePlan
        The plan with ``simulated_fills`` populated, or the original plan unchanged.
    """
    window = bars.get(plan.symbol)
    if not window or not plan.orders:
        return plan
    try:
        fills = simulate_orders(plan.orders, window, broker=broker)
    except Exception as exc:  # noqa: BLE001 - per-symbol fill isolation (design Q-E)
        warnings.warn(f"scan: skipped fills for {plan.symbol!r}: {exc}", stacklevel=2)
        return plan
    return plan.model_copy(update={"simulated_fills": fills})
