"""Pure entry/exit level math + risk-based position sizing (issue #76, PRD §13).

This module turns a confluence ``MoverSignal`` plus an entry price and an ATR(14)
reading into the four numbers a trade needs -- stop, target, risk-per-share, and a
risk-budget-honoring share quantity -- and nothing else. It is deliberately pure:
no network, no ``obb.*`` call, no router, no class state. Order legs (#77), paper
fills (#78), and the time-stop bar count live downstream; #76 only computes levels
and size.

Sign convention (PRD §13): for a ``long`` the stop sits ``atr_stop_mult * ATR``
*below* entry and the target ``target_r_multiple * risk`` *above*; a ``short`` is
mirrored. A ``flat`` signal has no defensible levels, so ``stop_price`` /
``target_price`` raise ``ValueError`` -- :func:`apply_rule` handles flat up front
and returns a zero-size dict.

Decimal discipline (cross-plan contract §1): every money / quantity value
(``entry``, ``stop``, ``target``, ``risk_per_share``, ``risk_budget``, ``qty``) is a
``Decimal``. The ATR and the rule multipliers arrive as ``float`` and are converted
to ``Decimal`` via ``Decimal(str(x))`` *inside* the math, so ``1.9`` becomes
``Decimal("1.9")`` and never the binary-float ``Decimal(1.9)``. The share floor uses
``Decimal.quantize(Decimal("1"), ROUND_DOWN)`` so the quantity stays a ``Decimal``
rather than round-tripping through ``math.floor`` and an ``int``.

Sizing inputs are abstract notional per the §20 Q6 decision -- ``account_size``
(default ``Decimal("100000")``) and ``risk_per_trade`` (default ``0.01``) -- so no
personal dollar amount is ever emitted.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Literal

from openbb_techtrade.models import EntryExitRule, MoverSignal

Direction = Literal["long", "short", "flat"]


def stop_price(entry: Decimal, atr: float, direction: Direction, rule: EntryExitRule) -> Decimal:
    """Compute the protective stop price for a directional entry.

    The stop distance is ``atr_stop_mult * ATR``; a ``long`` stop is that distance
    below entry, a ``short`` stop the same distance above. A ``flat`` direction has
    no position to protect and raises ``ValueError``.

    Parameters
    ----------
    entry : Decimal
        Planned entry price.
    atr : float
        ATR(14) indicator reading (converted to Decimal internally).
    direction : {"long", "short", "flat"}
        Trade direction from the signal.
    rule : EntryExitRule
        Carries ``atr_stop_mult`` (the ATR multiple).

    Returns
    -------
    Decimal
        The stop price.
    """
    dist = Decimal(str(rule.atr_stop_mult)) * Decimal(str(atr))
    if direction == "long":
        return entry - dist
    if direction == "short":
        return entry + dist
    raise ValueError(f"stop_price requires a long/short direction, got {direction!r}")


def target_price(entry: Decimal, stop: Decimal, direction: Direction, rule: EntryExitRule) -> Decimal:
    """Compute the R-multiple profit target from entry, stop, and direction.

    Risk (``1R``) is the absolute stop distance ``abs(entry - stop)``; the target is
    ``target_r_multiple`` of that risk beyond entry -- above for a ``long``, below for
    a ``short``. A ``flat`` direction raises ``ValueError``.

    Parameters
    ----------
    entry : Decimal
        Planned entry price.
    stop : Decimal
        Stop price (from :func:`stop_price`); defines ``1R``.
    direction : {"long", "short", "flat"}
        Trade direction from the signal.
    rule : EntryExitRule
        Carries ``target_r_multiple``.

    Returns
    -------
    Decimal
        The profit-target price.
    """
    risk = abs(entry - stop)
    offset = Decimal(str(rule.target_r_multiple)) * risk
    if direction == "long":
        return entry + offset
    if direction == "short":
        return entry - offset
    raise ValueError(f"target_price requires a long/short direction, got {direction!r}")


def position_size(
    entry: Decimal,
    stop: Decimal,
    *,
    account_size: Decimal,
    risk_per_trade: float,
) -> Decimal:
    """Compute a risk-budget-honoring whole-share position size.

    Sizes the position so the stop-loss equals a fixed risk fraction of notional:
    ``qty = floor((account_size * risk_per_trade) / abs(entry - stop))``. The floor
    is done with ``Decimal.quantize(..., ROUND_DOWN)`` so the result stays a Decimal
    (never over-risking by rounding up). The sizing inputs are abstract notional per
    the §20 Q6 decision -- no personal dollar amount is emitted.

    Parameters
    ----------
    entry : Decimal
        Planned entry price.
    stop : Decimal
        Stop price; ``abs(entry - stop)`` is the per-share risk (``1R``).
    account_size : Decimal
        Abstract notional account size (keyword-only).
    risk_per_trade : float
        Fraction of notional to risk per trade, e.g. 0.01 (keyword-only).

    Returns
    -------
    Decimal
        Whole-share position size.

    Raises
    ------
    ValueError
        If the per-share risk is zero (entry == stop), which has no defined size.
    """
    risk_per_share = abs(entry - stop)
    if risk_per_share == 0:
        raise ValueError("position_size requires a non-zero risk_per_share (entry == stop)")
    risk_budget = account_size * Decimal(str(risk_per_trade))
    qty = risk_budget / risk_per_share
    return qty.quantize(Decimal("1"), rounding=ROUND_DOWN)


def apply_rule(
    signal: MoverSignal,
    *,
    entry: Decimal,
    atr: float,
    rule: EntryExitRule = EntryExitRule(),
    account_size: Decimal = Decimal("100000"),
    risk_per_trade: float = 0.01,
) -> dict:
    """Turn a signal + entry + ATR into the full level/size dict for a trade.

    Orchestrates :func:`stop_price`, :func:`target_price`, and
    :func:`position_size`. A ``flat`` signal carries no trade, so it short-circuits
    to a zero-size, no-levels dict before any level math runs (which keeps the
    divide-by-zero impossible). All money / quantity values are ``Decimal``.

    Parameters
    ----------
    signal : MoverSignal
        Confluence signal; ``signal.direction`` drives the sign convention.
    entry : Decimal
        Planned entry price (keyword-only).
    atr : float
        ATR(14) reading (keyword-only).
    rule : EntryExitRule, optional
        Stop / target rule; defaults to ``EntryExitRule()``.
    account_size : Decimal, optional
        Abstract notional account size (Q6); defaults to ``Decimal("100000")``.
    risk_per_trade : float, optional
        Fraction of notional risked per trade (Q6); defaults to ``0.01``.

    Returns
    -------
    dict
        ``{"entry", "stop", "target", "qty", "risk_per_share"}`` -- all ``Decimal``
        where money; ``stop`` / ``target`` are ``None`` only for a flat signal.
    """
    direction = signal.direction
    if direction == "flat":
        return {
            "entry": entry,
            "stop": None,
            "target": None,
            "qty": Decimal(0),
            "risk_per_share": Decimal(0),
        }
    stop = stop_price(entry, atr, direction, rule)
    target = target_price(entry, stop, direction, rule)
    risk_per_share = abs(entry - stop)
    qty = position_size(entry, stop, account_size=account_size, risk_per_trade=risk_per_trade)
    return {
        "entry": entry,
        "stop": stop,
        "target": target,
        "qty": qty,
        "risk_per_share": risk_per_share,
    }
