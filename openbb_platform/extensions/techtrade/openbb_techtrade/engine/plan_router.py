"""Engine sub-router: ``plan`` + ``orders`` + ``simulate`` + ``scan`` (PRD §9.2, issues #77-#79).

The plan face of ``obb.techtrade.*``. :func:`plan` runs the #75 signal chain over an explicit
symbol set or a GICS segment and assembles one #77 :class:`~openbb_techtrade.models.TradePlan`
per ranked signal -- each carrying the #76-sized levels, the broker-ready order legs, and an inline
:class:`~openbb_techtrade.models.Recommendation`. :func:`orders` materializes a single plan's order
list (accepting an in-memory plan or one round-tripped through JSON). :func:`simulate` (#78)
paper-fills a set of order legs against a forward OHLCV window and returns the realized FillList.
:func:`scan` (#79) screens all 11 GICS sectors through the same chain and returns the actionable
plans cross-segment ranked by conviction. All are auto-wired onto ``obb.techtrade.*`` by the lazy
sub-router include in ``techtrade_router._include_subrouters`` (which already lists this module).

The commands are **thin**: each maps its arguments to a pure helper in
:mod:`~openbb_techtrade.engine.plan` (:func:`build_plans` / :func:`materialize_orders`),
:mod:`~openbb_techtrade.execution.broker` (:func:`simulate`), or
:mod:`~openbb_techtrade.engine.scan` (:func:`scan_segments`) and wraps the result in an ``OBBject``,
exactly mirroring ``signals_router`` -> ``build_signals``. Each returns a bare ``OBBject`` (no
parametrized model) so the static package builder renders a valid, importable return annotation --
see ``techtrade_router`` and ``package_builder.build_func_returns``. The conceptual
``list[TradePlan]`` / ``list[Order]`` payload types are documented in the docstrings.

Note: this module deliberately does **not** use ``from __future__ import annotations``. The
``orders`` command takes a ``plan: TradePlan`` model parameter, and the static package builder must
see the real :class:`TradePlan` class (not a stringized annotation) to emit its import into the
generated package -- mirroring ``quantitative_router``'s ``data: list[Data]`` convention.
"""

from openbb_core.app.model.example import APIEx, PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_techtrade.models import Order, TradePlan

router = Router(prefix="", description="Assemble per-symbol technical trade plans and orders.")


@router.command(
    methods=["GET"],
    examples=[
        APIEx(
            description="Plan a single GICS segment with the trend-follow preset.",
            parameters={"segment": "Information Technology"},
        ),
        APIEx(
            description="Plan an explicit symbol set with mean-reversion.",
            parameters={"symbols": ["AAPL", "MSFT"], "preset": "mean_revert"},
        ),
    ],
)
def plan(
    segment: str | None = None,
    symbols: list[str] | None = None,
    preset: str = "trend_follow",
    risk: float = 0.01,
    as_of: str | None = None,
) -> OBBject:
    """Assemble per-symbol trade plans for a symbol set or a GICS segment (PRD §9.2, issue #77).

    Runs the #75 confluence signal chain under the named ``preset`` over either an explicit
    ``symbols`` set or a ``segment``'s ranked top movers, then assembles one ``TradePlan`` per
    ranked signal -- sizing the #76 stop / target / quantity at ``risk`` of notional, mapping the
    broker-ready order legs, and attaching an inline recommendation. The plans preserve the signal
    chain's ranking order. The requested ``as_of`` is snapped back to the most recent trading
    session before scoring, so each plan is look-ahead-free.

    Parameters
    ----------
    segment : str | None, optional
        A single GICS sector name (e.g. ``"Information Technology"``) to resolve into its ranked
        top movers, or ``None`` to plan an explicit ``symbols`` set. Defaults to ``None``.
    symbols : list[str] | None, optional
        Explicit instrument symbols to plan; takes precedence over ``segment``. Defaults to ``None``.
    preset : str, optional
        Named confluence preset: ``"trend_follow"`` (default) / ``"mean_revert"`` / ``"breakout"``.
    risk : float, optional
        Fraction of notional risked per trade, fed to the #76 sizing. Defaults to ``0.01``.
    as_of : str | None, optional
        ISO date to plan as of; snapped to the most recent session. Defaults to today when ``None``.

    Returns
    -------
    OBBject
        OBBject whose ``results`` is a list[TradePlan], one per ranked signal.
    """
    from openbb_techtrade.engine.plan import build_plans

    return OBBject(
        results=build_plans(symbols=symbols, segment=segment, preset=preset, risk=risk, as_of=as_of)
    )


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Materialize the order legs from a plan built above.",
            code=[
                "plans = obb.techtrade.plan(segment='Information Technology').results",
                "orders = obb.techtrade.orders(plan=plans[0]).results",
            ],
        ),
    ],
)
def orders(plan: TradePlan) -> OBBject:
    """Materialize the broker-ready order legs of a single trade plan (PRD §9.2, issue #77).

    Re-validates the supplied ``plan`` (an in-memory :class:`TradePlan` or one deserialized from
    JSON) and returns its order legs unchanged -- an idempotent round-trip. A flat plan carries no
    position and yields an empty list.

    Parameters
    ----------
    plan : TradePlan
        The trade plan whose orders to materialize.

    Returns
    -------
    OBBject
        OBBject whose ``results`` is a list[Order] (empty for a flat plan).
    """
    from openbb_techtrade.engine.plan import materialize_orders

    return OBBject(results=materialize_orders(plan))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Paper-fill an order set against a forward OHLCV window.",
            code=[
                "plans = obb.techtrade.plan(segment='Information Technology').results",
                "orders = obb.techtrade.orders(plan=plans[0]).results",
                "fills = obb.techtrade.simulate(orders=orders, bars=forward_bars).results",
            ],
        ),
    ],
)
def simulate(orders: list[Order], bars: list) -> OBBject:
    """Paper-fill a set of order legs against a forward OHLCV window (PRD §14.1, issue #78).

    Drives the #78 :class:`~openbb_techtrade.execution.broker.PaperBroker` over ``bars`` (whose
    first row is the next-bar-open session *t+1*): fills the ``entry`` leg at ``bars[0]`` open with
    adverse slippage, then walks the contingent ``exit_stop`` / ``exit_target`` / ``exit_time`` legs
    bar-by-bar, taking the first triggered exit with a conservative stop-wins tie-break. The signal
    bar *t* is never read, so the result is no-look-ahead by construction. An empty order list (a
    flat plan) yields an empty FillList.

    Parameters
    ----------
    orders : list[Order]
        The canonical #77 order legs to simulate (entry first, then contingent exits).
    bars : list
        The forward OHLCV window starting at *t+1*; each bar carries ``open`` / ``high`` / ``low``
        and a ``timestamp`` or ``date``.

    Returns
    -------
    OBBject
        OBBject whose ``results`` is a list[Fill] -- the FillList (empty for a flat plan).
    """
    from openbb_techtrade.execution.broker import simulate as simulate_orders

    return OBBject(results=simulate_orders(orders, bars))


@router.command(
    methods=["GET"],
    examples=[
        APIEx(
            description="Default cross-segment scan with paper-fill.",
            parameters={},
        ),
        APIEx(
            description="Top-5 movers per sector by volume; no fills.",
            parameters={"metric": "volume", "top_n": 5, "simulate": False},
        ),
    ],
)
def scan(
    metric: str = "pct_change",
    top_n: int = 10,
    preset: str = "trend_follow",
    risk: float | None = None,
    as_of: str | None = None,
    simulate: bool = True,
    limit: int | None = None,
) -> OBBject:
    """Screen all 11 GICS sectors into a cross-segment ranked plan list (PRD §9.2, issue #79).

    The one-call orchestrator: ranks each sector's top ``top_n`` movers by ``metric``, runs them
    through the #75 signals -> #76 rules/sizing -> #77 orders chain, optionally paper-fills via #78,
    then returns the actionable plans **cross-segment ranked** by ``|signal.score|`` descending
    (symbol, then segment, tie-break). ``metric`` selects *which movers* per sector enter the chain;
    it is **not** the cross-segment plan-rank key. ``as_of`` is snapped once to the last ``XNYS``
    session (look-ahead-free) and threaded to every sector. ``simulate=False`` returns the order
    skeletons only; ``limit`` slices the top of the ranked list. Skipped sectors / symbols (transient
    fetch failures) surface in ``OBBject.warnings`` rather than aborting the scan.

    Parameters
    ----------
    metric : str, optional
        Mover rank metric (``pct_change`` / ``volume`` / ``gap`` / ``rel_volume``). Defaults to
        ``"pct_change"``.
    top_n : int, optional
        Per-segment mover cap. Defaults to ``10`` (up to ``11 x top_n`` plans returned, sorted).
    preset : str, optional
        Confluence/rule preset. Defaults to ``"trend_follow"``.
    risk : float | None, optional
        Risk-per-trade fraction for #76 sizing; ``None`` uses the chain default ``0.01``.
    as_of : str | None, optional
        ISO date to scan as of; snapped to the most recent session. Defaults to today when ``None``.
    simulate : bool, optional
        Request inline #78 fills. Defaults to ``True``. NOTE (v1): the live command does not yet
        fetch forward (``t+1...``) bars, so no fills are attached over the HTTP surface regardless of
        this flag -- the ranked order skeletons are returned either way. The live forward-bar fetcher
        is a tracked follow-up; the ``scan_segments`` ``bars=`` seam already fills when a window is
        supplied (exercised offline).
    limit : int | None, optional
        Optional global top-of-list slice after the cross-segment sort. Defaults to ``None``.

    Returns
    -------
    OBBject
        OBBject whose ``results`` is a list[TradePlan], cross-segment ranked (empty when no
        actionable setup is found).
    """
    from openbb_techtrade.engine.scan import scan_segments

    return OBBject(results=scan_segments(
        metric=metric, top_n=top_n, preset=preset, risk=risk,
        as_of=as_of, simulate=simulate, limit=limit,
    ))
