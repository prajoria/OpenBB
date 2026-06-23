"""Plan orchestrator: ranked signals -> per-symbol ``TradePlan`` skeletons (issue #77, PRD §9.2).

The pure core behind ``obb.techtrade.plan`` (and the materializer behind ``obb.techtrade.orders``).
:func:`build_plans` runs the #75 signal chain over an explicit symbol set or a GICS segment, sources
each signal's ``(entry, atr)`` levels, and assembles one #77 :class:`TradePlan` per signal via
:func:`~openbb_techtrade.engine.orders.build_trade_plan` (so the #76 sizing, the order mapping, and
the inline :class:`Recommendation` all flow through). The result preserves the signal chain's
ranking order verbatim -- there is no second sort.

The chain is::

    signals = signal_fetcher(symbols, segment, preset=..., as_of=...)   # #75 ranked MoverSignals
    plans   = [build_trade_plan(sig, entry=e, atr=a, risk_per_trade=risk)  # #77 sizing + orders + rec
               for sig in signals
               for (e, a) in [level_fetcher(sig.symbol, as_of=sig.as_of)]]
    return plans                                                        # ranking order preserved

This module is **pure and offline-testable** via two injectable seams, mirroring #75's
``panel_fetcher`` convention:

* ``signal_fetcher`` -- the ranked-signal source, defaulting to the live #75
  :func:`~openbb_techtrade.engine.signals.build_signals`.
* ``level_fetcher`` -- sources a symbol's ``(entry, atr)`` at its **own** ``as_of`` (so the levels
  are look-ahead-free: each plan is sized as of the session its signal was computed on), defaulting
  to :func:`_default_level_fetcher` (last close + ATR(14) from the #72/#73 panel stack).

:func:`materialize_orders` is the pure helper the ``orders`` command delegates to: it re-validates a
possibly-deserialized plan (a :class:`TradePlan` or a plain ``dict``) and returns its ``orders``, an
idempotent round-trip that lets the broker-facing ``orders`` face accept either an in-memory plan or
one reloaded from JSON.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from openbb_techtrade.engine.execution import build_recommendation
from openbb_techtrade.engine.orders import build_trade_plan
from openbb_techtrade.models import MoverSignal, Order, TradePlan


def _default_signal_fetcher(
    symbols: list[str] | None,
    segment: str | None,
    *,
    preset: str,
    as_of: date | str | None,
) -> list[MoverSignal]:
    """Compute ranked signals from the live #75 chain (the default ``signal_fetcher`` seam).

    Delegates to :func:`~openbb_techtrade.engine.signals.build_signals`, imported lazily so the
    unit suite (which injects an offline fake) never touches ``openbb``.

    Parameters
    ----------
    symbols : list[str] | None
        Explicit instrument symbols to score, or ``None`` to resolve from ``segment``.
    segment : str | None
        A GICS segment to resolve into its ranked top movers when ``symbols`` is ``None``.
    preset : str
        Named confluence preset (keyword-only).
    as_of : date | str | None
        Requested date, snapped to a session by the chain (keyword-only).

    Returns
    -------
    list[MoverSignal]
        The ranked signals (best first).
    """
    from openbb_techtrade.engine.signals import build_signals

    return build_signals(symbols=symbols, segment=segment, preset=preset, as_of=as_of)


def _default_level_fetcher(symbol: str, *, as_of: date) -> tuple[Decimal, float]:
    """Source a symbol's ``(entry, atr)`` from the live #72/#73 panel stack (integration-only).

    The default ``level_fetcher`` seam: fetches the symbol's OHLCV history through the #73 live
    fetcher, takes the last close as the planned ``entry`` (coerced to ``Decimal`` via
    ``Decimal(str(...))`` per the contract's Decimal discipline), and reads ``atr`` (ATR(14)) off
    the #72 indicator panel built from the same rows. ``openbb`` is reached only via the lazily
    imported #73 helpers, so the unit suite (which injects an offline fake) never touches it.

    Parameters
    ----------
    symbol : str
        The instrument symbol to source levels for.
    as_of : date
        The signal's own (already-snapped) session date; bounds the history with no look-ahead.

    Returns
    -------
    tuple[Decimal, float]
        The planned entry price (``Decimal``) and ATR(14) reading (``float``).

    Raises
    ------
    ValueError
        If no OHLCV history is available, or the panel has no ATR (too short a history).
    """
    from openbb_techtrade.engine.indicators import _default_ohlcv_fetcher, build_indicator_panel

    rows = _default_ohlcv_fetcher(symbol, as_of)
    if not rows:
        raise ValueError(f"level_fetcher found no OHLCV history for {symbol!r} as of {as_of}.")
    last = rows[-1]
    close = last.get("close") if isinstance(last, dict) else getattr(last, "close", None)
    if close is None:
        raise ValueError(f"level_fetcher found no close for {symbol!r} as of {as_of}.")
    entry = Decimal(str(close))
    panel = build_indicator_panel(symbol, as_of, rows)
    atr = panel.volatility.get("atr")
    if atr is None:
        raise ValueError(f"level_fetcher could not compute ATR for {symbol!r} as of {as_of}.")
    return entry, atr


def build_plans(
    symbols: list[str] | None = None,
    segment: str | None = None,
    *,
    preset: str = "trend_follow",
    risk: float = 0.01,
    as_of: date | str | None = None,
    signal_fetcher: Callable[..., list[MoverSignal]] | None = None,
    level_fetcher: Callable[..., tuple[Decimal, float]] | None = None,
) -> list[TradePlan]:
    """Assemble one :class:`TradePlan` per ranked signal for a symbol set or a GICS segment (PRD §9.2).

    Runs the injectable ``signal_fetcher`` (default the live #75 chain) to get the ranked signals,
    sources each signal's ``(entry, atr)`` through the injectable ``level_fetcher`` at the signal's
    own ``as_of`` (look-ahead-free), and assembles a #77 ``TradePlan`` per signal via
    :func:`~openbb_techtrade.engine.orders.build_trade_plan` (which runs the #76 sizing, maps the
    order list, and attaches an inline :class:`Recommendation`). The signal chain's ranking order is
    preserved -- there is no second sort. An empty signal set yields an empty list.

    Parameters
    ----------
    symbols : list[str] | None, optional
        Explicit instrument symbols to plan. Takes precedence over ``segment``.
    segment : str | None, optional
        A GICS segment to resolve into its ranked top movers when ``symbols`` is ``None``.
    preset : str, optional
        Named confluence preset passed to the signal chain. Defaults to ``"trend_follow"``.
    risk : float, optional
        Fraction of notional risked per trade, fed to the #76 sizing. Defaults to ``0.01``.
    as_of : date | str | None, optional
        Requested date, snapped to a session by the signal chain. Defaults to today when ``None``.
    signal_fetcher : Callable[..., list[MoverSignal]] | None, optional
        Ranked-signal source invoked as ``signal_fetcher(symbols, segment, preset=..., as_of=...)``;
        defaults to the live :func:`_default_signal_fetcher`. Tests inject an offline fake.
    level_fetcher : Callable[..., tuple[Decimal, float]] | None, optional
        Level source invoked as ``level_fetcher(symbol, as_of=signal.as_of)`` returning
        ``(entry, atr)``; defaults to the live :func:`_default_level_fetcher`. Tests inject a fake.

    Returns
    -------
    list[TradePlan]
        One plan per ranked signal, in signal-ranking order (empty when no signals).
    """
    fetch_signals = signal_fetcher or _default_signal_fetcher
    fetch_levels = level_fetcher or _default_level_fetcher

    signals = fetch_signals(symbols, segment, preset=preset, as_of=as_of)

    plans: list[TradePlan] = []
    for signal in signals:
        entry, atr = fetch_levels(signal.symbol, as_of=signal.as_of)
        plan = build_trade_plan(signal, entry=entry, atr=atr, risk_per_trade=risk)
        # #80 delegation seam: the #77 inline ``Recommendation`` is a self-contained stub;
        # replace it with the templated builder's narrative so the plan that flows downstream
        # carries the full ``reasoning`` / ``top_factors`` / ``caveats`` story (design Q-F).
        # ``build_recommendation`` is pure / return-only, so we attach via ``model_copy``.
        recommendation = build_recommendation(plan)
        plans.append(plan.model_copy(update={"recommendation": recommendation}))
    return plans


def materialize_orders(plan: TradePlan | dict) -> list[Order]:
    """Re-validate a plan (model or dict) and return its broker-ready ``orders`` (idempotent).

    The pure helper behind ``obb.techtrade.orders``: accepts either an in-memory :class:`TradePlan`
    or a deserialized ``dict`` (e.g. a plan round-tripped through JSON), coerces a ``dict`` back into
    a validated ``TradePlan`` so its ``orders`` are typed :class:`Order` models, and returns that
    order list unchanged. A flat plan carries no orders and yields ``[]``.

    Parameters
    ----------
    plan : TradePlan | dict
        The plan whose orders to materialize, as a model or a plain mapping.

    Returns
    -------
    list[Order]
        The plan's order legs (``[]`` for a flat plan).
    """
    if not isinstance(plan, TradePlan):
        plan = TradePlan.model_validate(plan)
    return plan.orders
