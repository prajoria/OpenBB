"""Order generation + ``TradePlan`` assembly (issue #77, PRD §13, §9.3).

Two pure, network-free functions turn the #76 sized levels into broker-ready output:

* :func:`generate_orders` is a deterministic mapper -- it takes the already-sized #76
  levels (entry / stop / target / qty) plus a :class:`MoverSignal` and emits the canonical
  ``Order`` list: an ``entry`` leg first, then the contingent ``exit_stop`` / ``exit_target``
  / ``exit_time`` / ``exit_signal`` legs, each tagged with its ``intent`` and the
  direction-correct ``side`` (long: ``buy`` to enter, ``sell`` to exit; short: ``sell_short``
  then ``buy_to_cover``). It does **no** indicator / stop / target / sizing math (that is #76's
  :mod:`~openbb_techtrade.engine.rules`); a ``flat`` signal yields an empty list.
* :func:`build_trade_plan` orchestrates the #76 sizing (:func:`apply_rule`), the order mapping,
  and a self-contained inline :class:`Recommendation`, into the :class:`TradePlan` skeleton.

**Why the recommendation is built inline (cross-plan resolution).**
``TradePlan.recommendation`` is a *required* field whose canonical builder ships in #80, but
issues are implemented in number order as standalone commits, so #77 cannot import #80. Per the
pipeline contract, :func:`build_trade_plan` therefore assembles a self-contained
:class:`Recommendation` from the data it already holds (entry / stop / target / qty / atr / score
/ direction -> action via direction, conviction via a tiny local ``|score|`` bucketing, levels,
sizing, and a basic deterministic one-line ``reasoning`` with ``top_factors=[]``, ``caveats=""``).
#80 later introduces ``engine/execution.py`` and refactors this function to *delegate* to it; the
``recommendation`` parameter here is the seam for that delegation (pass one in to skip the inline
build).

**Decimal discipline (contract §1):** every money / quantity value stays a ``Decimal`` (the levels
arrive as ``Decimal`` from #76 and are mapped onto ``Order`` / ``Recommendation`` fields verbatim --
no float arithmetic on prices). Percentages and ratios (the recommendation's distance / R:R fields)
are ``float``, computed via exact ``Decimal`` division coerced at the boundary.
"""

from __future__ import annotations

from decimal import Decimal

from openbb_techtrade.engine.rules import apply_rule
from openbb_techtrade.models import EntryExitRule, MoverSignal, Order, Recommendation, TradePlan

#: Per-direction ``(entry_side, exit_side)`` mapping (Q-B). ``flat`` emits no orders.
_SIDES: dict[str, tuple[str, str]] = {
    "long": ("buy", "sell"),
    "short": ("sell_short", "buy_to_cover"),
}

#: Per-direction recommended action (frozen ``Recommendation.action`` literals).
_ACTIONS: dict[str, str] = {"long": "BUY", "short": "SELL_SHORT", "flat": "HOLD/FLAT"}


def generate_orders(
    signal: MoverSignal,
    *,
    entry: Decimal,
    stop: Decimal | None,
    target: Decimal | None,
    qty: Decimal,
    rule: EntryExitRule,
) -> list[Order]:
    """Map sized #76 levels onto the canonical entry-first ``Order`` list (PRD §13).

    Emits one ``entry`` leg, then the contingent ``exit_stop`` / ``exit_target`` /
    ``exit_time`` / ``exit_signal`` legs in canonical enum order. ``exit_stop`` is a ``stop``
    order carrying ``stop``; ``exit_target`` is a ``limit`` order carrying ``target``; the
    event-driven ``exit_time`` / ``exit_signal`` are ``market`` rows with no price (their
    trigger lives on the :class:`EntryExitRule` and is realized by #78). ``exit_time`` is
    emitted only when ``rule.max_holding_bars is not None``; ``exit_signal`` only when
    ``rule.exit_on_opposite`` is true. Every leg carries the full ``qty`` (exits close the
    whole position). A ``flat`` signal has no position to express and yields ``[]``.

    Parameters
    ----------
    signal : MoverSignal
        The signal whose ``direction`` drives the side mapping and ``symbol`` is echoed.
    entry : Decimal
        Planned entry reference price (the entry leg is ``market``, so this is not a price
        field on the entry order; it is accepted for a uniform level signature).
    stop : Decimal | None
        Planned stop price (``None`` only for a flat signal).
    target : Decimal | None
        Planned target price (``None`` only for a flat signal).
    qty : Decimal
        Position size carried by every leg.
    rule : EntryExitRule
        Carries the ``max_holding_bars`` / ``exit_on_opposite`` exit-gating flags.

    Returns
    -------
    list[Order]
        The canonical order list, or ``[]`` for a flat signal.
    """
    direction = signal.direction
    if direction == "flat":
        return []

    entry_side, exit_side = _SIDES[direction]
    symbol = signal.symbol

    orders = [
        Order(symbol=symbol, side=entry_side, quantity=qty, order_type="market", tif="day", intent="entry"),
        Order(
            symbol=symbol, side=exit_side, quantity=qty,
            order_type="stop", stop_price=stop, tif="gtc", intent="exit_stop",
        ),
        Order(
            symbol=symbol, side=exit_side, quantity=qty,
            order_type="limit", limit_price=target, tif="gtc", intent="exit_target",
        ),
    ]
    if rule.max_holding_bars is not None:
        orders.append(
            Order(symbol=symbol, side=exit_side, quantity=qty, order_type="market", tif="gtc", intent="exit_time")
        )
    if rule.exit_on_opposite:
        orders.append(
            Order(symbol=symbol, side=exit_side, quantity=qty, order_type="market", tif="gtc", intent="exit_signal")
        )
    return orders


def _conviction_for(score: float) -> str:
    """Bucket ``|score|`` into a conviction label (``High`` >= 0.7, ``Medium`` >= 0.4, else ``Low``).

    A tiny local bucketing (the contract keeps #77 self-contained rather than importing #74's
    ``conviction_for``); #80 replaces the whole inline recommendation with the canonical builder.
    """
    magnitude = abs(score)
    if magnitude >= 0.7:
        return "High"
    if magnitude >= 0.4:
        return "Medium"
    return "Low"


def _inline_recommendation(
    signal: MoverSignal,
    *,
    levels: dict,
    atr: float,
    rule: EntryExitRule,
    account_size: Decimal,
) -> Recommendation:
    """Assemble the self-contained #77 :class:`Recommendation` from already-held data.

    Maps the #76 ``levels`` (entry / stop / target / qty / risk_per_share) plus ``atr`` and the
    signal's ``score`` / ``direction`` onto every frozen ``Recommendation`` field, with a basic
    deterministic one-line ``reasoning``, ``top_factors=[]`` and ``caveats=""``. A ``flat`` signal
    has no defensible levels, so its prices collapse to ``entry`` and all distances / risk / R:R
    are zero. #80 supersedes this with the templated narrative builder.
    """
    entry: Decimal = levels["entry"]
    stop: Decimal | None = levels["stop"]
    target: Decimal | None = levels["target"]
    qty: Decimal = levels["qty"]
    risk_per_share: Decimal = levels["risk_per_share"]
    action = _ACTIONS[signal.direction]
    conviction = _conviction_for(signal.score)

    if stop is None or target is None:  # flat: no position, prices collapse to entry, risk is zero
        stop_price = target_price = entry
        stop_distance_pct = target_distance_pct = risk_reward = risk_pct_of_notional = 0.0
        reasoning = f"{action} {signal.symbol}: score {signal.score:+.2f} below entry threshold; no position."
    else:
        stop_price, target_price = stop, target
        stop_dist = abs(entry - stop)
        target_dist = abs(target - entry)
        stop_distance_pct = float(stop_dist / entry) * 100.0
        target_distance_pct = float(target_dist / entry) * 100.0
        risk_reward = float(target_dist / stop_dist)
        risk_pct_of_notional = float(risk_per_share * qty / account_size) * 100.0
        reasoning = (
            f"{action} {signal.symbol}: {conviction} conviction (score {signal.score:+.2f}); "
            f"entry {entry}, stop {stop}, target {target}; {risk_reward:.1f}R, {qty} sh."
        )

    return Recommendation(
        symbol=signal.symbol, segment=signal.segment, as_of=signal.as_of,
        action=action, conviction=conviction, score=signal.score,
        entry_price=entry, stop_price=stop_price, target_price=target_price,
        stop_distance_pct=stop_distance_pct, target_distance_pct=target_distance_pct,
        risk_reward=risk_reward, atr=atr, position_size=qty, risk_per_share=risk_per_share,
        risk_pct_of_notional=risk_pct_of_notional, time_stop_bars=rule.max_holding_bars,
        reasoning=reasoning, caveats="",
    )


def build_trade_plan(
    signal: MoverSignal,
    *,
    entry: Decimal,
    atr: float,
    rule: EntryExitRule = EntryExitRule(),
    account_size: Decimal = Decimal("100000"),
    risk_per_trade: float = 0.01,
    recommendation: Recommendation | None = None,
) -> TradePlan:
    """Assemble a per-symbol :class:`TradePlan` skeleton from a signal + entry + ATR (PRD §9.3).

    Runs the #76 :func:`apply_rule` to size the levels, maps them to the order list via
    :func:`generate_orders`, and attaches a :class:`Recommendation` -- the caller-supplied one if
    given (the #80 delegation seam), else a self-contained inline build (:func:`_inline_recommendation`).
    ``simulated_fills`` (#78) and ``validation`` (#82) take their model defaults. A ``flat`` signal
    yields an empty ``orders`` list and a zero-size HOLD/FLAT plan.

    Parameters
    ----------
    signal : MoverSignal
        The confluence signal; ``direction`` drives sides / action, ``score`` drives conviction.
    entry : Decimal
        Planned entry reference price (the #76 ``entry_ref``).
    atr : float
        ATR(14) reading feeding the #76 stop / target sizing.
    rule : EntryExitRule, optional
        Stop / target / exit-gating rule; defaults to ``EntryExitRule()``.
    account_size : Decimal, optional
        Abstract notional account size for sizing (Q6); defaults to ``Decimal("100000")``.
    risk_per_trade : float, optional
        Fraction of notional risked per trade; defaults to ``0.01``.
    recommendation : Recommendation | None, optional
        A pre-built recommendation to attach (the #80 delegation seam); when ``None`` (default)
        an inline one is assembled.

    Returns
    -------
    TradePlan
        The plan skeleton: ``signal`` / ``rule`` / ``position_size`` / ``orders`` populated, an
        inline (or supplied) ``recommendation``, default ``simulated_fills`` / ``validation``.
    """
    levels = apply_rule(
        signal, entry=entry, atr=atr, rule=rule,
        account_size=account_size, risk_per_trade=risk_per_trade,
    )
    orders = generate_orders(
        signal, entry=levels["entry"], stop=levels["stop"],
        target=levels["target"], qty=levels["qty"], rule=rule,
    )
    rec = recommendation or _inline_recommendation(
        signal, levels=levels, atr=atr, rule=rule, account_size=account_size,
    )
    return TradePlan(
        symbol=signal.symbol,
        segment=signal.segment,
        as_of=signal.as_of,
        signal=signal,
        rule=rule,
        position_size=levels["qty"],
        orders=orders,
        recommendation=rec,
    )
