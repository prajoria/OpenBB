"""No-look-ahead enforcement: a bar-*t* signal fills at *t+1* only (#78, PRD §13, §5.1).

THE acceptance gate of #78. A signal is computed from the close of bar *t* (the session
``_AS_OF``); the realized fill must never use a price from bar *t* itself. ``simulate`` consumes a
forward OHLCV window whose ``bars[0]`` *is* session *t+1*, so no-look-ahead is structural -- but
this golden locks it loudly: the fixture deliberately holds a *bar t* with a DISTINCT open
(``_BAR_T_OPEN``) that is **not** passed into the window, then asserts (a) the entry fill is stamped
*t+1*, never *t*; (b) the entry price derives from ``bars[0].open`` (*t+1*) and is provably **not**
the bar-*t*-derived price; (c) the stamp is tz-aware; and (d) a stop that *would* have triggered on
bar *t* does not fill until a forward bar *>= t+1* touches it. The full FillList is also locked
against a committed golden JSON within DEFAULT_TOL. Regenerate intentionally after a *reviewed*
change with TECHTRADE_REGEN_GOLDEN=1 -- never blindly.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from openbb_techtrade.execution.broker import simulate
from openbb_techtrade.models import Order
from openbb_techtrade.testing import assert_matches_golden, to_jsonable

pytestmark = pytest.mark.golden

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

_QTY = Decimal("263")
_STOP = Decimal("117.60")
_TARGET = Decimal("129.00")
_BPS = Decimal("5") / Decimal("10000")

# Bar t == the signal session (Fri 2024-01-12). DELIBERATELY NOT passed into the window: its
# distinct open is the bait a look-ahead regression would bite on.
_AS_OF = date(2024, 1, 12)
_BAR_T_OPEN = Decimal("999.00")
# t+1 == the next XNYS session strictly after _AS_OF (Mon 1/15 is MLK -> Tue 2024-01-16).
_T1 = date(2024, 1, 16)
_T2 = date(2024, 1, 17)
_TS_T1 = datetime(2024, 1, 16, 21, 0, tzinfo=timezone.utc)  # 16:00 ET -> UTC
_TS_T2 = datetime(2024, 1, 17, 21, 0, tzinfo=timezone.utc)


def _bar(open_, high, low, close, timestamp):
    return {
        "open": Decimal(open_), "high": Decimal(high), "low": Decimal(low),
        "close": Decimal(close), "volume": Decimal("1000000"), "timestamp": timestamp,
    }


def _orders() -> list[Order]:
    """The canonical long legs: market entry + contingent stop + target (#77 shape)."""
    return [
        Order(symbol="GOLD", side="buy", quantity=_QTY, order_type="market", tif="day", intent="entry"),
        Order(symbol="GOLD", side="sell", quantity=_QTY, order_type="stop",
              stop_price=_STOP, tif="gtc", intent="exit_stop"),
        Order(symbol="GOLD", side="sell", quantity=_QTY, order_type="limit",
              limit_price=_TARGET, tif="gtc", intent="exit_target"),
    ]


def _window() -> list[dict]:
    """The forward window starting at t+1; bar t (open 999.00) is intentionally absent."""
    return [
        _bar("121.40", "122", "120.0", "121", _TS_T1),  # t+1: entry fills here; low 120 > stop
        _bar("119", "120", "117.00", "118", _TS_T2),     # t+2: low 117 <= 117.60 -> stop fills
    ]


def _fills():
    return simulate(_orders(), _window())


def test_signal_at_t_fills_at_t_plus_one_only():
    """Assert the entry is stamped t+1 (never t) and priced off bar t+1's open, not bar t's."""
    entry = _fills()[0]
    # (a) timestamp identity: filled at t+1, never the signal bar t
    assert entry.timestamp.date() == _T1
    assert entry.timestamp.date() != _AS_OF
    # (b) price provenance: derives from bar t+1 open (+ adverse slippage), NOT bar t open
    t1_open = Decimal("121.40")
    assert entry.price == t1_open + t1_open * _BPS
    assert entry.price != _BAR_T_OPEN + _BAR_T_OPEN * _BPS
    # (c) tz-aware (Q-F)
    assert entry.timestamp.tzinfo is not None


def test_stop_that_would_trigger_on_bar_t_waits_for_a_forward_bar():
    """Assert the forward walk never reaches back to bar t: the stop fills at t+2, not t."""
    fills = _fills()
    assert [f.order_ref for f in fills] == ["GOLD:entry", "GOLD:exit_stop"]
    stop_fill = fills[1]
    assert stop_fill.timestamp.date() == _T2
    assert stop_fill.timestamp.date() != _AS_OF
    assert stop_fill.price == _STOP - _STOP * _BPS


def test_no_lookahead_fills_match_golden():
    """Assert the full FillList (entry + stop, prices/commission/slippage/ts) matches the golden."""
    snapshot = [to_jsonable(f) for f in _fills()]
    assert_matches_golden("no_lookahead_golden", snapshot, fixture_dir=_FIXTURE_DIR)


def test_no_lookahead_is_deterministic():
    """Assert two simulations of the same window produce identical fills (pure, no hidden state)."""
    assert [f.model_dump() for f in _fills()] == [f.model_dump() for f in _fills()]
