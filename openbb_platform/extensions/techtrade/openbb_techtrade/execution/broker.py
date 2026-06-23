"""PaperBroker fill simulation -- the execution seam (issue #78, PRD §14.1, §13).

The pure, network-free core behind ``obb.techtrade.simulate``. Three pieces turn the #77
broker-style :class:`~openbb_techtrade.models.Order` legs into realized
:class:`~openbb_techtrade.models.Fill` rows under a strict **no-look-ahead** discipline:

* :class:`BrokerInterface` -- a ``runtime_checkable`` :class:`typing.Protocol`
  (``submit`` / ``cancel`` / ``positions``) so the paper broker shipped here can later be swapped
  for a real Alpaca/IBKR client behind the *same* call sites (PRD §14.1 swap-in-live).
* :class:`PaperBroker` -- the v1 implementation. ``submit`` is the **only** place a fill price is
  decided: a ``market`` order fills at the supplied bar's ``open``; a ``stop`` / ``limit`` exit
  fills only when the bar touches its level *intrabar* (long stop on ``low <= stop``, target on
  ``high >= limit``; short mirrored). Every fill carries an *adverse* per-share slippage (buys fill
  higher, sells lower; default 5 bps) and a per-share commission (default zero), with a tz-aware
  timestamp (from the bar's own ``timestamp`` when present, else the date-only session localized to
  16:00 America/New_York -> UTC).
* :func:`simulate` -- drives the broker across a forward OHLCV window (``bars[0]`` is the
  next-bar-open session *t+1*): it fills the entry at ``bars[0]`` then walks the contingent
  ``exit_stop`` / ``exit_target`` / ``exit_time`` legs bar-by-bar, taking the **first** exit with a
  **conservative stop-wins tie-break** (both touched in one bar -> the stop fills, the worse path).
  It never reads bar *t* (the signal bar), so a bar-*t* signal can fill no earlier than *t+1*.

**Decimal discipline (contract §1):** ``price`` / ``commission`` / ``slippage`` / ``quantity`` stay
``Decimal`` end-to-end; bar OHLC values are coerced via ``Decimal(str(...))`` at the boundary, and
slippage is computed as exact ``Decimal`` bps. This module is a leaf consumer of ``models`` only --
no ``openbb_backtest`` import -- so ``obb.techtrade.*`` imports cleanly with backtest absent
(Q7 / #85).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from openbb_techtrade.models import Fill, Order

#: Order sides that buy (fill at an *adverse-higher* price); the rest sell (adverse-lower).
_BUY_SIDES = frozenset({"buy", "buy_to_cover"})
#: Basis-point denominator (5 bps == 5 / 10_000).
_BPS = Decimal("10000")
#: Exchange-close localization for date-only daily bars (US equities close 16:00 ET).
_MARKET_TZ = ZoneInfo("America/New_York")
_CLOSE_HOUR = 16


@runtime_checkable
class BrokerInterface(Protocol):
    """The execution seam -- paper now, live later, identical call sites (PRD §14.1).

    A ``runtime_checkable`` Protocol so a unit test can assert
    ``isinstance(PaperBroker(...), BrokerInterface)`` and any future Alpaca/IBKR client satisfies
    the contract structurally, with no inheritance coupling.
    """

    def submit(self, order: Order, bar: object) -> Fill | None:
        """Attempt to fill ``order`` against ``bar``; return ``None`` when it does not fill."""
        ...

    def cancel(self, order_ref: str) -> None:
        """Cancel a resting order by reference (a no-op once filled)."""
        ...

    def positions(self) -> list:
        """Return the broker's current open-position book."""
        ...


def _get(bar: object, key: str) -> object:
    """Read ``key`` from an OHLCV bar exposing either dict keys or attributes.

    Mirrors the dict-or-attribute reader in :mod:`~openbb_techtrade.engine.indicators` so unit
    tests can pass plain dicts while the live path passes provider data objects.
    """
    if isinstance(bar, dict):
        return bar.get(key)
    return getattr(bar, key, None)


def _dec(value: object) -> Decimal:
    """Coerce a bar OHLC value to ``Decimal`` via ``Decimal(str(...))`` (contract §1)."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _fill_timestamp(bar: object) -> datetime:
    """Resolve a fill's tz-aware timestamp from the bar (PRD §14.1 / Q-F).

    Uses the bar's own ``timestamp`` when present (normalized to UTC -- a *naive* datetime is
    assumed to be ``America/New_York`` wall time, matching the date-only path below); otherwise
    localizes the date-only session to 16:00 ``America/New_York`` -> UTC, so a date-only daily bar
    still yields a deterministic tz-aware stamp the no-look-ahead golden can pin. Accepts
    ``datetime`` / ``date`` objects *and* their ISO-string forms, so a REST/JSON-round-tripped bar
    (where the field arrives as a string) resolves identically to an in-memory one.
    """
    raw = _get(bar, "timestamp")
    if raw is None:
        raw = _get(bar, "date")
    raw = _coerce_temporal(raw)
    if isinstance(raw, datetime):
        localized = raw if raw.tzinfo is not None else raw.replace(tzinfo=_MARKET_TZ)
        return localized.astimezone(timezone.utc)
    if isinstance(raw, date):
        close = datetime(raw.year, raw.month, raw.day, _CLOSE_HOUR, 0, tzinfo=_MARKET_TZ)
        return close.astimezone(timezone.utc)
    raise ValueError("Bar must carry a 'timestamp' (datetime) or 'date' (date) for the fill stamp.")


def _coerce_temporal(raw: object) -> object:
    """Parse an ISO ``datetime`` / ``date`` string into the matching object; pass others through.

    A date-only string (no ``T`` / space time separator) parses to :class:`date` so it takes the
    16:00-ET localization path rather than collapsing to a midnight :class:`datetime`; anything with
    a time component parses to :class:`datetime`.
    """
    if not isinstance(raw, str):
        return raw
    if "T" not in raw and " " not in raw:
        return date.fromisoformat(raw)
    return datetime.fromisoformat(raw)


@dataclass
class PaperBroker:
    """A simulated broker that fills orders at next-bar-open with slippage + commission (§14.1).

    Implements :class:`BrokerInterface` structurally. ``submit`` decides the single fill price; the
    forward walk and position bookkeeping live in :func:`simulate`, keeping the broker stateless per
    call (so it is trivially swapped for a live client).

    Parameters
    ----------
    commission_per_share : Decimal, optional
        Per-share commission charged on the filled quantity. Defaults to ``Decimal("0")`` (L5).
    slippage_bps : Decimal, optional
        Adverse slippage in basis points applied to the reference price. Defaults to
        ``Decimal("5")`` (L5).
    """

    commission_per_share: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("5")

    def submit(self, order: Order, bar: object) -> Fill | None:
        """Fill ``order`` against ``bar``, or return ``None`` when it does not trigger.

        A ``market`` order references the bar's ``open`` and always fills; a ``stop`` / ``limit``
        exit references its level and fills only when the bar touches it intrabar (§3.1/§3.2). The
        reference price is adjusted by an adverse per-share slippage (buys higher, sells lower), and
        commission is charged on the filled quantity.

        Parameters
        ----------
        order : Order
            The order leg to fill; its ``order_type`` / ``side`` / level drive the trigger + price.
        bar : object
            A duck-typed OHLCV bar (dict or attribute object) carrying ``open`` / ``high`` / ``low``
            and a ``timestamp`` or ``date``.

        Returns
        -------
        Fill | None
            The realized fill, or ``None`` when a contingent exit's level is not touched.
        """
        reference = self._reference_price(order, bar)
        if reference is None:
            return None

        slip_per_share = reference * self.slippage_bps / _BPS
        is_buy = order.side in _BUY_SIDES
        fill_price = reference + slip_per_share if is_buy else reference - slip_per_share
        quantity = order.quantity
        return Fill(
            order_ref=f"{order.symbol}:{order.intent}",
            timestamp=_fill_timestamp(bar),
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            price=fill_price,
            commission=self.commission_per_share * quantity,
            slippage=slip_per_share * quantity,
        )

    def cancel(self, order_ref: str) -> None:
        """Cancel a resting order by reference (a no-op in the v1 batch simulator)."""
        return None

    def positions(self) -> list:
        """Return the broker's open-position book (empty for the stateless paper broker)."""
        return []

    def _reference_price(self, order: Order, bar: object) -> Decimal | None:
        """Return the pre-slippage reference price, or ``None`` when a contingent exit is untouched.

        ``market`` -> bar ``open`` (always fills). ``stop`` -> the stop level when the bar trades
        through it (long ``low <= stop`` / short ``high >= stop``). ``limit`` -> the target level
        when reached (long ``high >= limit`` / short ``low <= limit``).
        """
        if order.order_type == "market":
            return _dec(_get(bar, "open"))

        is_buy = order.side in _BUY_SIDES
        if order.order_type == "stop":
            level = order.stop_price
            if level is None:
                return None
            high, low = _dec(_get(bar, "high")), _dec(_get(bar, "low"))
            triggered = high >= level if is_buy else low <= level
            return level if triggered else None
        if order.order_type == "limit":
            level = order.limit_price
            if level is None:
                return None
            high, low = _dec(_get(bar, "high")), _dec(_get(bar, "low"))
            triggered = low <= level if is_buy else high >= level
            return level if triggered else None
        return None


def simulate(orders: list[Order], bars: list, *, broker: BrokerInterface | None = None) -> list[Fill]:
    """Paper-fill ``orders`` across a forward bar window, returning the realized FillList (§14.1).

    ``bars[0]`` is the next-bar-open session *t+1*: the ``entry`` leg fills there, then the
    contingent ``exit_stop`` / ``exit_target`` / ``exit_time`` legs are walked bar-by-bar (the
    walk includes ``bars[0]`` itself, so a stop / target touched intrabar on the entry session
    closes the position the same session). The **first** triggered exit closes the position and
    ends the walk, with a **conservative stop-wins tie-break** (when one bar touches both the stop
    and the target, the stop fills). When no stop / target triggers within the window and an
    ``exit_time`` leg is present, the position is closed at the last bar's open (the time stop). An
    ``exit_signal`` leg (the opposite-signal exit) is intentionally **not** realized here: a pure
    OHLCV simulator has no forward signal chain to re-evaluate per bar, so that leg is skipped (its
    live realization belongs to the swap-in broker / live path, §14.1). The signal bar *t* is never
    read, so the result is no-look-ahead by construction. An empty order list (a flat plan) yields
    ``[]``.

    Parameters
    ----------
    orders : list[Order]
        The canonical #77 order legs (entry first, then contingent exits).
    bars : list
        The forward OHLCV window starting at *t+1*; each bar is a duck-typed dict / object.
    broker : BrokerInterface | None, optional
        The broker to fill through; defaults to a zero-commission, 5 bps :class:`PaperBroker`.

    Returns
    -------
    list[Fill]
        The realized fills (entry first, then at most one exit), or ``[]`` for a flat plan.
    """
    if not orders or not bars:
        return []

    broker = broker or PaperBroker()
    by_intent = {order.intent: order for order in orders}

    entry = by_intent.get("entry")
    if entry is None:
        return []
    entry_fill = broker.submit(entry, bars[0])
    if entry_fill is None:
        return []
    fills = [entry_fill]

    stop = by_intent.get("exit_stop")
    target = by_intent.get("exit_target")
    for bar in bars:  # stop checked before target -> conservative stop-wins tie-break
        if stop is not None:
            stop_fill = broker.submit(stop, bar)
            if stop_fill is not None:
                fills.append(stop_fill)
                return fills
        if target is not None:
            target_fill = broker.submit(target, bar)
            if target_fill is not None:
                fills.append(target_fill)
                return fills

    time_exit = by_intent.get("exit_time")
    if time_exit is not None:
        time_fill = broker.submit(time_exit, bars[-1])
        if time_fill is not None:
            fills.append(time_fill)
    return fills
