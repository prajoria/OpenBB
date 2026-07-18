"""AC-5 golden test: no look-ahead in intraday (P2.6).

Invariant (PRD §P3): a signal computed off the CLOSE of 5-min bar t
results in a fill that references bar t+1's OPEN — never earlier, never
at close(t). This is the intraday twin of techtrade #78's daily-bar
golden test, applied at 5-min granularity.

Why "golden" and not "unit":
  * The invariant is architectural, not local. A regression could sneak
    in through changes to _build_tick_data, _process_signal, the broker's
    bar-selection logic, or a new caller of broker.submit. A unit test
    on one function would miss cross-file drift.
  * The assertion is on the WHICH-BAR the fill references, not on the
    presence of an event. Losing this invariant is a correctness bug that
    silently backdates fills; the test's job is to detect that specific
    class of regression.

Test seams:
  * All fetch functions in tick_loop are patched at module level (the
    same seam pattern the P2.4 wiring tests established).
  * broker.submit captures the ``bar`` argument passed to it — that bar
    is what the golden assertion checks. If _process_signal ever passes
    bar t (the current bar) instead of bar t+1 (the next-open), this test
    fails.

Runtime: <100ms. No network, no live openbb runtime.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _make_5min_bars(start: datetime, count: int) -> list:
    """Synthetic monotonically-increasing 5-min bars for a single symbol.

    Returns real IntradayBar instances — TickData.bars_recent is typed
    ``dict[str, list[IntradayBar]]`` and Pydantic rejects SimpleNamespace
    or MagicMock. Earlier this used SimpleNamespace for stable equality;
    IntradayBar (a pydantic Data model) has value-based equality that's
    equally stable.
    """
    from openbb_fmp_trading.models.market_data import IntradayBar

    bars = []
    for i in range(count):
        ts = start + timedelta(minutes=5 * i)
        bars.append(
            IntradayBar(
                symbol="MSFT",
                interval="5min",
                ts=ts,
                open=Decimal(f"{430 + i}.00"),
                high=Decimal(f"{430 + i}.50"),
                low=Decimal(f"{430 + i}.00"),
                close=Decimal(f"{430 + i}.25"),
                volume=1_000_000,
            )
        )
    return bars


def _make_plan():
    from openbb_fmp_trading.models.config import RiskConfig
    from openbb_fmp_trading.models.plan import DailyPlan

    return DailyPlan(
        as_of=datetime(2026, 7, 6, 13, 25, tzinfo=timezone.utc),
        trading_date=date(2026, 7, 6),
        watchlist=["MSFT"],
        preset="trend_follow",
        alerts=[],
        session_risk=RiskConfig(),
        thesis="AC-5 golden",
        agent_backend="none",
    )


class TestNoLookAheadAtFiveMinGranularity:
    """AC-5: signal off close(t) fills at open(t+1), never at close(t)."""

    def test_signal_at_bar_close_fills_at_next_bar_open(self, monkeypatch):
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.session import IntradaySession
        from openbb_fmp_trading.models.journal_events import FillEvent

        # Build 3 bars: 09:30, 09:35, 09:40 ET (13:30, 13:35, 13:40 UTC)
        # Signal fires at the close of bar 0 (== start of bar 1 at 13:35).
        # Fill MUST reference bar[1]'s open (431.00), NOT bar[0]'s close.
        bar0_start = datetime(2026, 7, 6, 13, 30, tzinfo=timezone.utc)
        bars = _make_5min_bars(bar0_start, count=3)
        signal_tick_ts = bars[1].ts  # 13:35 UTC — close of bar[0], open of bar[1]

        fake_sig = SimpleNamespace(symbol="MSFT", score=0.9, direction="long")
        fake_order = SimpleNamespace(
            ref="ac5-order", symbol="MSFT",
            qty=Decimal("10"), intent="OPEN_LONG",
        )
        fake_plan = SimpleNamespace(
            symbol="MSFT", intent="OPEN_LONG", orders=[fake_order]
        )

        # Capture the bar that broker.submit receives
        captured: dict = {}

        def _capture_submit(order, bar=None):
            captured["order"] = order
            captured["bar"] = bar
            # Simulate fill at the OPEN of the received bar
            return SimpleNamespace(
                price=bar.open if bar else Decimal("0"),
                qty=order.qty,
                commission=Decimal("1.00"),
            )

        broker = MagicMock()
        broker.submit.side_effect = _capture_submit
        broker.positions.return_value = []  # avoid force-close path

        rm = MagicMock()
        rm.propose_trade.return_value = SimpleNamespace(
            verdict="APPROVED", reason_code=None, gate=None, reason=None
        )

        # Stub all tick_loop seams so the run_tick call runs deterministically.
        # Bars fed to _fetch_recent_bars EXCLUDE bar[0] (the just-closed bar);
        # the "recent" window at the moment of signal fire contains bar[0]
        # itself as its most-recent element AND bar[1] as the fresh open.
        # The chokepoint's _process_signal passes bars_recent[symbol][-1] to
        # broker.submit — so if we place bar[1] at [-1], we're asserting the
        # loop hands the FRESH open bar to the broker, not the STALE close.
        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote",
            lambda symbols, provider: [{"symbol": "MSFT", "price": "431.00"}],
        )
        monkeypatch.setattr(
            tick_loop, "_fetch_recent_bars",
            lambda symbols: {"MSFT": bars[:2]},  # bar[0], bar[1] — bar[1] is [-1]
        )
        monkeypatch.setattr(
            tick_loop, "_fetch_session_status",
            # Return None — TickData.session_status is Optional[SessionStatus].
            # AC-5 doesn't read session_status; only asserts bar-vs-signal ordering.
            lambda exchange: None,
        )
        monkeypatch.setattr(
            tick_loop, "_run_techtrade_signals", lambda plan, tick: [fake_sig]
        )
        monkeypatch.setattr(
            tick_loop, "_build_techtrade_plan", lambda sig, tick: fake_plan
        )
        monkeypatch.setattr(
            tick_loop, "_is_signal_bar_close", lambda ts, preset: True
        )

        session = IntradaySession(
            plan=_make_plan(),
            journal=MagicMock(),
            risk_manager=rm,
            broker=broker,
            bandwidth=MagicMock(),
        )
        events = tick_loop.run_tick(session, tick_ts=signal_tick_ts)

        # ---- AC-5 assertions ----
        assert captured.get("bar") is not None, (
            "broker.submit was not called with a bar arg — AC-5 preconditions failed"
        )
        assert captured["bar"].ts == bars[1].ts, (
            f"Fill referenced bar at {captured['bar'].ts}, expected bar[1] at "
            f"{bars[1].ts}. This is a NO-LOOK-AHEAD violation — the fill must "
            "reference the NEXT bar's open, not the CURRENT bar's close (P3)."
        )
        assert captured["bar"].open == Decimal("431.00"), (
            "Fill price must equal bar[1]'s OPEN (431.00), not bar[0]'s CLOSE "
            "(430.25). If this fails, _process_signal is handing the stale bar "
            "to the broker."
        )

        # Fill event's payload reflects the correct next-bar-open price
        fill_events = [e for e in events if isinstance(e, FillEvent)]
        assert len(fill_events) == 1
        assert fill_events[0].payload["fill_price"] == "431.00"

    def test_no_signal_no_fill_on_non_bar_close_tick(self, monkeypatch):
        """Off-bar ticks must not fill — a look-ahead precursor guard."""
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.session import IntradaySession
        from openbb_fmp_trading.models.journal_events import FillEvent

        broker = MagicMock()
        broker.positions.return_value = []
        rm = MagicMock()

        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote", lambda symbols, provider: []
        )
        # Force is_signal_bar_close to False → no signal cascade
        monkeypatch.setattr(
            tick_loop, "_is_signal_bar_close", lambda ts, preset: False
        )

        session = IntradaySession(
            plan=_make_plan(),
            journal=MagicMock(),
            risk_manager=rm,
            broker=broker,
            bandwidth=MagicMock(),
        )
        events = tick_loop.run_tick(
            session,
            tick_ts=datetime(2026, 7, 6, 13, 33, tzinfo=timezone.utc),
        )

        broker.submit.assert_not_called()
        assert not any(isinstance(e, FillEvent) for e in events)
