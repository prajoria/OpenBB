"""Signal-wiring unit tests for run_tick + _process_signal (P2.4).

Verifies the chokepoint contract end-to-end:

1. **Approved signal path** — bar-close tick → techtrade signals → plan →
   RiskManager APPROVED → broker.submit called once per order → SignalEvent,
   OrderEvent, FillEvent all journaled in order.
2. **Rejected signal path** — RiskManager REJECTED → VetoEvent with the G-code
   → ``broker.submit`` NEVER called. This is the invariant the P7
   ``test_broker_chokepoint.py`` scan enforces mechanically.
3. **Non-bar-close ticks** — signals are NOT run mid-bar; only TickEvent
   emitted. Prevents fills on partial bars (a look-ahead precursor).
4. **No-signal bar-close** — bar closes but techtrade returns [] → no orders,
   no vetoes. Idle bars are cheap.

All techtrade + fetch functions are stubbed via ``monkeypatch.setattr`` on
the module-level seams in ``core.tick_loop`` — no live openbb import.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


def _stub_recent_bars(symbols):
    """One real IntradayBar per symbol — signal-wiring tests need
    bars_recent populated for broker.submit's `bar` arg."""
    from openbb_fmp_trading.models.market_data import IntradayBar

    ts = datetime(2026, 7, 6, 13, 35, tzinfo=timezone.utc)
    return {
        s: [
            IntradayBar(
                symbol=s,
                interval="5min",
                ts=ts,
                open=Decimal("430.00"),
                high=Decimal("430.30"),
                low=Decimal("429.90"),
                close=Decimal("430.25"),
                volume=1000,
            )
        ]
        for s in symbols
    }



def _make_plan():
    from openbb_fmp_trading.models.config import RiskConfig
    from openbb_fmp_trading.models.plan import DailyPlan

    return DailyPlan(
        as_of=datetime(2026, 7, 6, 13, 25, tzinfo=timezone.utc),
        trading_date=date(2026, 7, 6),
        watchlist=["MSFT"],
        preset="intraday_momentum",
        alerts=[],
        session_risk=RiskConfig(),
        thesis="test plan for P2.4 wiring",
        agent_backend="none",
    )


@pytest.fixture
def stub_techtrade(monkeypatch):
    """Stub all module-level seams so run_tick returns without live I/O.

    Yields the fake plan so the caller test can add its own assertions
    about which fields flow through the chokepoint.
    """
    from openbb_fmp_trading.core import tick_loop

    fake_sig = MagicMock(symbol="MSFT", score=0.72, direction="long")
    fake_order = MagicMock(
        ref="o1", symbol="MSFT", qty=Decimal("10"), intent="OPEN_LONG"
    )
    fake_plan = MagicMock(symbol="MSFT", intent="OPEN_LONG", orders=[fake_order])

    monkeypatch.setattr(
        tick_loop, "_fetch_batch_quote",
        lambda symbols, provider: [{"symbol": s, "price": "430.15"} for s in symbols],
    )
    monkeypatch.setattr(
        tick_loop, "_fetch_recent_bars",
        # Return one real IntradayBar per symbol — the signal wiring
        # test asserts broker.submit was called with a `bar` arg, so
        # bars_recent needs at least one entry. Using a MagicMock
        # (prior version) fails Pydantic validation on TickData.bars_recent.
        _stub_recent_bars,
    )
    monkeypatch.setattr(
        tick_loop, "_fetch_session_status",
        # Return None — TickData.session_status is Optional[SessionStatus].
        # signal-wiring tests don't read session_status; they only assert
        # the emit-chain shape.
        lambda exchange: None,
    )
    monkeypatch.setattr(
        tick_loop, "_run_techtrade_signals",
        lambda plan, tick: [fake_sig],
    )
    monkeypatch.setattr(
        tick_loop, "_build_techtrade_plan",
        lambda sig, tick: fake_plan,
    )
    monkeypatch.setattr(
        tick_loop, "_is_signal_bar_close",
        lambda ts, preset: True,
    )
    return {"signal": fake_sig, "order": fake_order, "plan": fake_plan}


def _make_session(rm, broker):
    """Real IntradaySession with mock RM/broker — journals to a MagicMock."""
    from openbb_fmp_trading.core.session import IntradaySession

    journal = MagicMock()
    return IntradaySession(
        plan=_make_plan(),
        journal=journal,
        risk_manager=rm,
        broker=broker,
        bandwidth=MagicMock(),
    )


class TestApprovedSignalPath:
    """P2.4 AC-1: APPROVED plan flows all the way to a FillEvent."""

    def test_approved_plan_submits_and_emits_full_event_chain(self, stub_techtrade):
        from openbb_fmp_trading.core.tick_loop import run_tick
        from openbb_fmp_trading.models.journal_events import (
            FillEvent,
            OrderEvent,
            SignalEvent,
            TickEvent,
        )

        rm = MagicMock()
        rm.propose_trade.return_value = MagicMock(
            verdict="APPROVED", reason_code=None, gate=None, reason=None
        )
        broker = MagicMock()
        broker.submit.return_value = MagicMock(
            price=Decimal("430.05"),
            qty=Decimal("10"),
            commission=Decimal("1.00"),
        )
        session = _make_session(rm, broker)

        events = run_tick(
            session, tick_ts=datetime(2026, 7, 6, 13, 35, tzinfo=timezone.utc)
        )

        # Emission ordering: tick → signal → order → fill
        types = [type(e).__name__ for e in events]
        assert types == ["TickEvent", "SignalEvent", "OrderEvent", "FillEvent"]

        # RiskManager saw the plan; broker.submit called exactly once with a bar arg
        rm.propose_trade.assert_called_once()
        broker.submit.assert_called_once()
        submit_kwargs = broker.submit.call_args
        # bar may be passed as kwarg or as the second positional arg. Check
        # both without IndexError'ing when only one positional is supplied.
        _bar_kw = submit_kwargs.kwargs.get("bar")
        _bar_pos = submit_kwargs.args[1] if len(submit_kwargs.args) > 1 else None
        assert _bar_kw is not None or _bar_pos is not None

        # Fill payload carries the price + commission for downstream P&L reconstruction
        fill = next(e for e in events if isinstance(e, FillEvent))
        assert fill.payload["fill_price"] == "430.05"
        assert fill.payload["commission"] == "1.00"


class TestRejectedSignalPath:
    """P2.4 AC-2: REJECTED plan produces a VetoEvent and NEVER touches broker."""

    def test_rejected_plan_emits_veto_and_skips_broker(self, stub_techtrade):
        from openbb_fmp_trading.core.tick_loop import run_tick
        from openbb_fmp_trading.models.journal_events import (
            FillEvent,
            OrderEvent,
            VetoEvent,
        )

        rm = MagicMock()
        rm.propose_trade.return_value = MagicMock(
            verdict="REJECTED",
            reason_code="max_position_size",
            gate="G6",
            reason="notional > 2% of equity",
        )
        broker = MagicMock()
        session = _make_session(rm, broker)

        events = run_tick(
            session, tick_ts=datetime(2026, 7, 6, 13, 35, tzinfo=timezone.utc)
        )

        # Chokepoint invariant: broker was never called
        broker.submit.assert_not_called()

        # Exactly one VetoEvent with the full G-code + gate name attribution
        vetoes = [e for e in events if isinstance(e, VetoEvent)]
        assert len(vetoes) == 1
        assert vetoes[0].payload["reason_code"] == "max_position_size"
        assert vetoes[0].payload["gate"] == "G6"
        assert vetoes[0].payload["plan_symbol"] == "MSFT"

        # No OrderEvent or FillEvent under rejection — journal integrity check
        assert not any(isinstance(e, (OrderEvent, FillEvent)) for e in events)


class TestNonBarCloseTick:
    """Off-bar ticks: TickEvent only. No signal call, no broker call."""

    def test_mid_bar_tick_does_not_run_signals(self, monkeypatch):
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.tick_loop import run_tick
        from openbb_fmp_trading.models.journal_events import (
            OrderEvent,
            SignalEvent,
            TickEvent,
        )

        # Force is_signal_bar_close to False regardless of tick_ts
        monkeypatch.setattr(tick_loop, "_is_signal_bar_close", lambda ts, preset: False)
        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote", lambda symbols, provider: []
        )
        signals_called = MagicMock()
        monkeypatch.setattr(tick_loop, "_run_techtrade_signals", signals_called)

        rm = MagicMock()
        broker = MagicMock()
        session = _make_session(rm, broker)

        events = run_tick(
            session, tick_ts=datetime(2026, 7, 6, 13, 33, tzinfo=timezone.utc)
        )

        assert len(events) == 1 and isinstance(events[0], TickEvent)
        signals_called.assert_not_called()
        rm.propose_trade.assert_not_called()
        broker.submit.assert_not_called()
        assert not any(isinstance(e, (SignalEvent, OrderEvent)) for e in events)


class TestIdleBarClose:
    """Bar closes but techtrade returned no signals — no orders, no vetoes."""

    def test_bar_close_with_no_signals_still_emits_tick_only(self, monkeypatch):
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.tick_loop import run_tick
        from openbb_fmp_trading.models.journal_events import (
            OrderEvent,
            SignalEvent,
            TickEvent,
            VetoEvent,
        )

        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote",
            lambda symbols, provider: [{"symbol": "MSFT", "price": "430"}],
        )
        monkeypatch.setattr(
            tick_loop, "_fetch_recent_bars", lambda symbols: {"MSFT": []},
        )
        monkeypatch.setattr(
            tick_loop, "_fetch_session_status", lambda exchange: None,
        )
        monkeypatch.setattr(tick_loop, "_is_signal_bar_close", lambda ts, preset: True)
        monkeypatch.setattr(tick_loop, "_run_techtrade_signals", lambda plan, tick: [])

        rm = MagicMock()
        broker = MagicMock()
        session = _make_session(rm, broker)

        events = run_tick(
            session, tick_ts=datetime(2026, 7, 6, 13, 35, tzinfo=timezone.utc)
        )

        assert [type(e).__name__ for e in events] == ["TickEvent"]
        rm.propose_trade.assert_not_called()
        broker.submit.assert_not_called()
        assert not any(isinstance(e, (SignalEvent, OrderEvent, VetoEvent)) for e in events)


class TestChokepointDirectCall:
    """_process_signal is a public-ish surface for P2.5 flat-by-close to call.

    Verify it works standalone (without going through run_tick) so the
    force-close path in P2.5 can call it directly with a synthetic MARKET
    SELL plan.
    """

    def test_process_signal_approved_multiple_orders(self):
        from openbb_fmp_trading.models.journal_events import FillEvent, OrderEvent

        rm = MagicMock()
        rm.propose_trade.return_value = MagicMock(
            verdict="APPROVED", reason_code=None, gate=None, reason=None
        )
        broker = MagicMock()
        broker.submit.side_effect = [
            MagicMock(price=Decimal("430.05"), qty=Decimal("5"), commission=Decimal("0.5")),
            MagicMock(price=Decimal("430.10"), qty=Decimal("5"), commission=Decimal("0.5")),
        ]
        session = _make_session(rm, broker)

        plan = MagicMock(
            symbol="MSFT",
            intent="OPEN_LONG",
            orders=[
                MagicMock(ref="o1", symbol="MSFT", qty=Decimal("5"), intent="OPEN_LONG"),
                MagicMock(ref="o2", symbol="MSFT", qty=Decimal("5"), intent="OPEN_LONG"),
            ],
        )
        tick = MagicMock(
            ts=datetime(2026, 7, 6, 13, 35, tzinfo=timezone.utc),
            bars_recent={"MSFT": [MagicMock(close=Decimal("430.25"))]},
        )
        events = session._process_signal(plan, tick)

        assert broker.submit.call_count == 2
        assert sum(isinstance(e, OrderEvent) for e in events) == 2
        assert sum(isinstance(e, FillEvent) for e in events) == 2
