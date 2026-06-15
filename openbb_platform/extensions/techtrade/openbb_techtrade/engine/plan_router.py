"""Engine sub-router: ``plan`` + ``orders`` (PRD §9.2, issue #77).

The plan face of ``obb.techtrade.*``. :func:`plan` runs the #75 signal chain over an explicit
symbol set or a GICS segment and assembles one #77 :class:`~openbb_techtrade.models.TradePlan`
per ranked signal -- each carrying the #76-sized levels, the broker-ready order legs, and an inline
:class:`~openbb_techtrade.models.Recommendation`. :func:`orders` materializes a single plan's order
list (accepting an in-memory plan or one round-tripped through JSON). :func:`simulate` (#78)
paper-fills a set of order legs against a forward OHLCV window and returns the realized FillList.
All are auto-wired onto ``obb.techtrade.*`` by the lazy sub-router include in
``techtrade_router._include_subrouters`` (which already lists this module).

The commands are **thin**: each maps its arguments to a pure helper in
:mod:`~openbb_techtrade.engine.plan` (:func:`build_plans` / :func:`materialize_orders`) and wraps the
result in an ``OBBject``, exactly mirroring ``signals_router`` -> ``build_signals``. Each returns a
bare ``OBBject`` (no parametrized model) so the static package builder renders a valid, importable
return annotation -- see ``techtrade_router`` and ``package_builder.build_func_returns``. The
conceptual ``list[TradePlan]`` / ``list[Order]`` payload types are documented in the docstrings.

This router also hosts ``scan`` (#79) once it ships; ``plan`` / ``orders`` land in #77 and
``simulate`` in #78.

Note: this module deliberately does **not** use ``from __future__ import annotations``. The
``orders`` command takes a ``plan: TradePlan`` model parameter, and the static package builder must
see the real :class:`TradePlan` class (not a stringized annotation) to emit its import into the
generated package -- mirroring ``quantitative_router``'s ``data: list[Data]`` convention.
"""

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_techtrade.models import Order, TradePlan

router = Router(prefix="", description="Assemble per-symbol technical trade plans and orders.")


@router.command(methods=["GET"])
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


@router.command(methods=["GET"])
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


@router.command(methods=["GET"])
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
