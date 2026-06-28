"""Unit tests for the #78 PaperBroker fill simulation (PRD §14.1, contract §3).

Fully offline and deterministic. ``PaperBroker.submit`` is the only place a fill price is
decided: a ``market`` order (entry, or an event-driven ``exit_time`` / ``exit_signal``) fills at
the supplied bar's ``open`` plus an *adverse* per-share slippage (buys fill higher, sells lower);
a ``stop`` / ``limit`` exit fills only when the bar touches its level intrabar (long stop on
``low <= stop``, target on ``high >= limit``; short mirrored), at the level +- adverse slippage.
``simulate`` drives the broker across a forward OHLCV window (``bars[0]`` is the next-bar-open
session *t+1*), emitting the entry fill then walking the contingent stop / target / time exits
with a **conservative stop-wins tie-break**. Every money / quantity field is pinned to an exact
``Decimal`` (5 bps on 100.00 -> 0.05; on the #76 golden 117.60 stop -> 0.05880) so any drift in
the slippage sign, the bps math, the intrabar trigger comparisons, the tie-break, the Decimal
discipline, or the tz-aware timestamp localization is caught.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from openbb_techtrade.execution.broker import BrokerInterface, PaperBroker, simulate
from openbb_techtrade.models import Fill, Order

_QTY = Decimal("263")
_STOP = Decimal("117.60")  # #76 golden long stop (entry 121.40 - 2*1.90)
_TARGET = Decimal("129.00")  # #76 golden long target
_TS_T1 = datetime(2024, 1, 16, 21, 0, tzinfo=timezone.utc)  # t+1 session close (16:00 EST -> UTC)
_SLIP_BPS = Decimal("5") / Decimal("10000")


def _slip(level: Decimal) -> Decimal:
    """Per-share 5 bps slippage on a reference level (exact Decimal)."""
    return level * _SLIP_BPS


def _bar(open_, high, low, close, *, timestamp=_TS_T1, volume="1000000"):
    """Build a duck-typed OHLCV bar (a plain dict, like the unit OHLCV rows)."""
    return {
        "open": Decimal(open_),
        "high": Decimal(high),
        "low": Decimal(low),
        "close": Decimal(close),
        "volume": Decimal(volume),
        "timestamp": timestamp,
    }


def _entry(side: str = "buy") -> Order:
    return Order(symbol="TEST", side=side, quantity=_QTY, order_type="market", tif="day", intent="entry")


def _stop_order(side: str = "sell") -> Order:
    return Order(
        symbol="TEST", side=side, quantity=_QTY, order_type="stop",
        stop_price=_STOP, tif="gtc", intent="exit_stop",
    )


def _target_order(side: str = "sell") -> Order:
    return Order(
        symbol="TEST", side=side, quantity=_QTY, order_type="limit",
        limit_price=_TARGET, tif="gtc", intent="exit_target",
    )


def _long_exits() -> list[Order]:
    return [_stop_order("sell"), _target_order("sell")]


def test_paperbroker_satisfies_broker_interface():
    """Assert PaperBroker structurally satisfies the runtime_checkable Protocol (L3 swap-in)."""
    assert isinstance(PaperBroker(), BrokerInterface)


def test_entry_buy_fills_at_next_bar_open_plus_adverse_slippage():
    """Assert a long market entry fills at the bar open + 5 bps (buys fill higher, L1/L6)."""
    fill = PaperBroker().submit(_entry("buy"), _bar("100.00", "101", "99", "100.5"))
    assert isinstance(fill, Fill)
    assert fill.price == Decimal("100.05")  # 100.00 + 100.00*5/1e4
    assert fill.slippage == Decimal("0.05") * _QTY
    assert fill.commission == Decimal("0")
    assert fill.side == "buy"
    assert fill.quantity == _QTY
    assert fill.order_ref == "TEST:entry"


def test_entry_sell_short_fills_at_open_minus_adverse_slippage():
    """Assert a short market entry fills at the bar open - 5 bps (sells fill lower, L6)."""
    fill = PaperBroker().submit(_entry("sell_short"), _bar("100.00", "101", "99", "100.5"))
    assert fill.price == Decimal("99.95")
    assert fill.slippage == Decimal("0.05") * _QTY


def test_commission_per_share_applied_on_filled_quantity():
    """Assert per-share commission is charged on the full filled quantity (Decimal)."""
    fill = PaperBroker(commission_per_share=Decimal("0.01")).submit(
        _entry("buy"), _bar("100.00", "101", "99", "100.5")
    )
    assert fill.commission == Decimal("0.01") * _QTY


def test_long_stop_triggers_intrabar_on_low_at_level_minus_slip():
    """Assert a long stop fills when bar low <= stop, at stop - adverse slippage (sell)."""
    fill = PaperBroker().submit(_stop_order("sell"), _bar("120", "121", "117.00", "118"))
    assert fill is not None
    assert fill.price == _STOP - _slip(_STOP)  # 117.60 - 0.05880
    assert fill.order_ref == "TEST:exit_stop"


def test_long_target_triggers_intrabar_on_high_at_level_minus_slip():
    """Assert a long target fills when bar high >= target, at target - adverse slippage (sell)."""
    fill = PaperBroker().submit(_target_order("sell"), _bar("125", "130.00", "124", "129.5"))
    assert fill is not None
    assert fill.price == _TARGET - _slip(_TARGET)
    assert fill.order_ref == "TEST:exit_target"


def test_stop_and_target_return_none_when_bar_does_not_touch():
    """Assert contingent exits do not fill on a bar that never reaches the level."""
    broker = PaperBroker()
    bar = _bar("120", "121", "118.00", "119")  # low 118 > stop 117.60; high 121 < target 129
    assert broker.submit(_stop_order("sell"), bar) is None
    assert broker.submit(_target_order("sell"), bar) is None


def test_short_stop_and_target_mirrored():
    """Assert a short stop triggers on high>=stop and a short target on low<=target (buy_to_cover)."""
    broker = PaperBroker()
    stop = Order(symbol="TEST", side="buy_to_cover", quantity=_QTY, order_type="stop",
                 stop_price=Decimal("125.20"), tif="gtc", intent="exit_stop")
    target = Order(symbol="TEST", side="buy_to_cover", quantity=_QTY, order_type="limit",
                   limit_price=Decimal("113.80"), tif="gtc", intent="exit_target")
    stop_fill = broker.submit(stop, _bar("123", "125.50", "122", "124"))  # high 125.5 >= 125.20
    target_fill = broker.submit(target, _bar("116", "117", "113.00", "114"))  # low 113 <= 113.80
    # buy_to_cover is adverse-higher
    assert stop_fill.price == Decimal("125.20") + _slip(Decimal("125.20"))
    assert target_fill.price == Decimal("113.80") + _slip(Decimal("113.80"))


def test_fill_timestamp_localizes_date_only_bar_to_1600_et_utc():
    """Assert a date-only bar localizes the fill stamp to 16:00 America/New_York -> UTC (Q-F)."""
    bar = {"open": Decimal("100.00"), "high": Decimal("101"), "low": Decimal("99"),
           "close": Decimal("100"), "date": date(2024, 1, 16)}
    fill = PaperBroker().submit(_entry("buy"), bar)
    assert fill.timestamp.tzinfo is not None
    assert fill.timestamp == datetime(2024, 1, 16, 21, 0, tzinfo=timezone.utc)  # 16:00 EST -> 21:00 UTC


def test_fill_timestamp_accepts_iso_datetime_string():
    """Assert an ISO-string bar timestamp (REST/JSON round-trip) parses to a tz-aware UTC stamp."""
    bar = {"open": Decimal("100.00"), "high": Decimal("101"), "low": Decimal("99"),
           "close": Decimal("100"), "timestamp": "2024-01-16T21:00:00+00:00"}
    fill = PaperBroker().submit(_entry("buy"), bar)
    assert fill.timestamp == datetime(2024, 1, 16, 21, 0, tzinfo=timezone.utc)


def test_fill_timestamp_accepts_date_only_iso_string():
    """Assert a date-only ISO string localizes to 16:00 ET -> UTC like a date object (Q-F)."""
    bar = {"open": Decimal("100.00"), "high": Decimal("101"), "low": Decimal("99"),
           "close": Decimal("100"), "date": "2024-01-16"}
    fill = PaperBroker().submit(_entry("buy"), bar)
    assert fill.timestamp == datetime(2024, 1, 16, 21, 0, tzinfo=timezone.utc)


def test_fill_money_fields_are_decimal():
    """Assert no float leaks into the Fill money/quantity fields (L6)."""
    fill = PaperBroker().submit(_entry("buy"), _bar("100.00", "101", "99", "100.5"))
    for value in (fill.price, fill.commission, fill.slippage, fill.quantity):
        assert isinstance(value, Decimal)


def test_cancel_is_noop_and_positions_returns_a_list():
    """Assert the Protocol's cancel / positions are callable (live-readiness, C1)."""
    broker = PaperBroker()
    assert broker.cancel("TEST:entry") is None
    assert isinstance(broker.positions(), list)


def test_simulate_empty_orders_returns_no_fills():
    """Assert a flat plan (no orders) simulates to an empty FillList."""
    assert simulate([], [_bar("121.40", "125", "119", "123")]) == []


def test_simulate_entry_only_window_returns_just_the_entry_fill():
    """Assert a window where no exit triggers yields only the entry fill (entry at bars[0].open)."""
    bars = [_bar("121.40", "125", "119.0", "123")]  # low 119 > stop, high 125 < target
    fills = simulate([_entry("buy"), *_long_exits()], bars)
    assert [f.order_ref for f in fills] == ["TEST:entry"]
    assert fills[0].price == Decimal("121.40") + _slip(Decimal("121.40"))


def test_simulate_exit_can_trigger_on_entry_bar_t_plus_one():
    """Assert a stop touched intrabar on bars[0] (the entry session t+1) exits the same session."""
    bars = [
        # t+1: entry fills at open 121.40; low 117.00 <= stop 117.60 -> stop also fills this bar
        _bar("121.40", "122", "117.00", "118"),
    ]
    fills = simulate([_entry("buy"), *_long_exits()], bars)
    assert [f.order_ref for f in fills] == ["TEST:entry", "TEST:exit_stop"]
    assert fills[0].price == Decimal("121.40") + _slip(Decimal("121.40"))
    assert fills[1].price == _STOP - _slip(_STOP)


def test_simulate_walks_to_stop_exit_on_a_later_bar():
    """Assert the forward walk fills the entry at t+1 then the stop on the first touching bar."""
    bars = [
        _bar("121.40", "122", "120.0", "121"),   # t+1: entry fills here, no stop touch (low 120 > 117.60)
        _bar("119", "120", "117.00", "118"),      # t+2: low 117 <= 117.60 -> stop fills
    ]
    fills = simulate([_entry("buy"), *_long_exits()], bars)
    assert [f.order_ref for f in fills] == ["TEST:entry", "TEST:exit_stop"]
    assert fills[0].price == Decimal("121.40") + _slip(Decimal("121.40"))
    assert fills[1].price == _STOP - _slip(_STOP)


def test_simulate_conservative_tie_break_stop_wins():
    """Assert when one bar touches BOTH stop and target, the stop fills (worst case, §14.1)."""
    bars = [
        _bar("121.40", "122", "121.0", "121.5"),         # t+1: entry, no exit
        _bar("120", "130.00", "117.00", "119"),           # t+2: low<=stop AND high>=target -> STOP wins
    ]
    fills = simulate([_entry("buy"), *_long_exits()], bars)
    assert [f.order_ref for f in fills] == ["TEST:entry", "TEST:exit_stop"]


def test_simulate_time_exit_fills_at_last_bar_when_no_stop_or_target():
    """Assert an exit_time leg closes the position at the last window bar's open (time stop)."""
    time_exit = Order(symbol="TEST", side="sell", quantity=_QTY, order_type="market",
                      tif="gtc", intent="exit_time")
    bars = [
        _bar("121.40", "125", "119.5", "123"),   # t+1 entry, no touch
        _bar("123", "126", "120.0", "124"),       # t+2 no touch
        _bar("124.00", "127", "121.5", "125"),    # t+3 last bar -> time exit at open 124.00 - slip
    ]
    fills = simulate([_entry("buy"), *_long_exits(), time_exit], bars)
    assert [f.order_ref for f in fills] == ["TEST:entry", "TEST:exit_time"]
    assert fills[-1].price == Decimal("124.00") - _slip(Decimal("124.00"))
