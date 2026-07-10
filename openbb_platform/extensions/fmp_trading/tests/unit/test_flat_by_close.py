"""AC-6 tests: flat-by-close state machine + force-close cascade (P2.5).

Verifies three layers:

1. **State-machine boundaries** — enter_flat_window returns the correct
   WindowState at each of the four inflection points (before 15:50,
   at 15:50, at 15:55, after 15:55). Pure function of ``now_et``, no
   mocks needed.
2. **G1 rejection at 15:51 (AC-6)** — a synthetic order at 15:51 ET
   handed to a real IntradaySession with a RiskManager that vetoes via
   G1 produces exactly one VetoEvent with reason_code="flat_by_close_window"
   and NEVER calls broker.submit.
3. **Force-close cascade at 15:56** — during the FORCE_CLOSE window,
   run_tick synthesizes CLOSE_LONG / CLOSE_SHORT orders for every open
   position and funnels them through _process_signal (the chokepoint).

Env: ``exchange_calendars`` (already a project dep). No FMP calls.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

_ET = ZoneInfo("America/New_York")


class TestWindowStateBoundaries:
    """enter_flat_window returns the right state at each inflection.

    All inputs are tz-aware (per the security-fixed contract). We test at
    ET-native times so the intent is legible in the test body.
    """

    def test_normal_before_15_50(self):
        from openbb_fmp_trading.core.flat_by_close import (
            WindowState,
            enter_flat_window,
        )

        assert (
            enter_flat_window(datetime(2026, 7, 6, 15, 49, tzinfo=_ET))
            == WindowState.NORMAL
        )

    def test_no_new_opens_at_15_50(self):
        from openbb_fmp_trading.core.flat_by_close import (
            WindowState,
            enter_flat_window,
        )

        assert (
            enter_flat_window(datetime(2026, 7, 6, 15, 50, tzinfo=_ET))
            == WindowState.NO_NEW_OPENS
        )

    def test_no_new_opens_15_51(self):
        from openbb_fmp_trading.core.flat_by_close import (
            WindowState,
            enter_flat_window,
        )

        assert (
            enter_flat_window(datetime(2026, 7, 6, 15, 51, tzinfo=_ET))
            == WindowState.NO_NEW_OPENS
        )

    def test_force_close_at_15_55(self):
        from openbb_fmp_trading.core.flat_by_close import (
            WindowState,
            enter_flat_window,
        )

        assert (
            enter_flat_window(datetime(2026, 7, 6, 15, 55, tzinfo=_ET))
            == WindowState.FORCE_CLOSE
        )

    def test_force_close_after_15_55(self):
        from openbb_fmp_trading.core.flat_by_close import (
            WindowState,
            enter_flat_window,
        )

        assert (
            enter_flat_window(datetime(2026, 7, 6, 15, 56, tzinfo=_ET))
            == WindowState.FORCE_CLOSE
        )

    def test_explicit_override_respected(self):
        """Test-injection escape hatch: caller-provided times bypass the
        exchange_calendars auto-scaling."""
        from openbb_fmp_trading.core.flat_by_close import (
            WindowState,
            enter_flat_window,
        )

        # Pretend we want no-opens at 10:00 ET, force-close at 10:05 ET
        assert enter_flat_window(
            datetime(2026, 7, 6, 10, 4, tzinfo=_ET),
            no_new_opens_time=time(10, 0),
            force_close_time=time(10, 5),
        ) == WindowState.NO_NEW_OPENS
        assert enter_flat_window(
            datetime(2026, 7, 6, 10, 5, tzinfo=_ET),
            no_new_opens_time=time(10, 0),
            force_close_time=time(10, 5),
        ) == WindowState.FORCE_CLOSE


class TestUTCToETTimezoneContract:
    """Security-review regression guard: UTC datetimes convert correctly.

    2026-07-06 is in EDT (UTC-4). 19:49 UTC == 15:49 EDT (NORMAL);
    19:56 UTC == 15:56 EDT (FORCE_CLOSE). Before the security fix, the
    naive .time() path would treat 19:49 UTC as if it were 19:49 ET,
    silently returning FORCE_CLOSE — a broken risk control.
    """

    def test_utc_1949_is_et_1549_normal(self):
        from openbb_fmp_trading.core.flat_by_close import (
            WindowState,
            enter_flat_window,
        )

        assert enter_flat_window(
            datetime(2026, 7, 6, 19, 49, tzinfo=timezone.utc)
        ) == WindowState.NORMAL

    def test_utc_1956_is_et_1556_force_close(self):
        from openbb_fmp_trading.core.flat_by_close import (
            WindowState,
            enter_flat_window,
        )

        assert enter_flat_window(
            datetime(2026, 7, 6, 19, 56, tzinfo=timezone.utc)
        ) == WindowState.FORCE_CLOSE

    def test_utc_1951_is_et_1551_no_new_opens(self):
        from openbb_fmp_trading.core.flat_by_close import (
            WindowState,
            enter_flat_window,
        )

        assert enter_flat_window(
            datetime(2026, 7, 6, 19, 51, tzinfo=timezone.utc)
        ) == WindowState.NO_NEW_OPENS

    def test_naive_datetime_raises(self):
        """Defensive assertion: naive datetime is a caller bug."""
        from openbb_fmp_trading.core.flat_by_close import enter_flat_window

        with pytest.raises(ValueError, match="tz-aware"):
            enter_flat_window(datetime(2026, 7, 6, 15, 49))


class TestAC6RejectionAt1551:
    """AC-6: order submitted at 15:51 → REJECTED(G1); broker.submit NEVER called."""

    def _plan(self):
        from openbb_fmp_trading.models.config import RiskConfig
        from openbb_fmp_trading.models.plan import DailyPlan

        return DailyPlan(
            as_of=datetime(2026, 7, 6, 13, 25, tzinfo=timezone.utc),
            date=date(2026, 7, 6),
            watchlist=["MSFT"],
            preset="intraday_momentum",
            alerts=[],
            session_risk=RiskConfig(),
            thesis="AC-6 test",
            agent_backend="none",
        )

    def test_process_signal_emits_veto_at_15_51(self):
        from openbb_fmp_trading.core.session import IntradaySession
        from openbb_fmp_trading.models.journal_events import (
            FillEvent,
            OrderEvent,
            VetoEvent,
        )

        rm = MagicMock()
        rm.propose_trade.return_value = MagicMock(
            verdict="REJECTED",
            reason_code="flat_by_close_window",
            gate="flat_by_close",
            reason="No new opens after 15:50 ET",
        )
        broker = MagicMock()
        session = IntradaySession(
            plan=self._plan(),
            journal=MagicMock(),
            risk_manager=rm,
            broker=broker,
            bandwidth=MagicMock(),
        )

        # Synthetic order at 15:51 ET (== 19:51 UTC)
        tick = MagicMock(
            ts=datetime(2026, 7, 6, 19, 51, tzinfo=timezone.utc),
            bars_recent={"MSFT": [MagicMock()]},
        )
        plan = MagicMock(
            symbol="MSFT",
            intent="OPEN_LONG",
            orders=[MagicMock(ref="o1", symbol="MSFT", qty=Decimal("10"))],
        )
        events = session._process_signal(plan, tick)

        # AC-6: exactly one VetoEvent, correct reason_code
        vetoes = [e for e in events if isinstance(e, VetoEvent)]
        assert len(vetoes) == 1
        assert vetoes[0].payload["reason_code"] == "flat_by_close_window"
        assert vetoes[0].payload["gate"] == "flat_by_close"

        # Chokepoint invariant: broker.submit was NEVER called
        broker.submit.assert_not_called()
        assert not any(isinstance(e, (OrderEvent, FillEvent)) for e in events)


class TestForceCloseCascade:
    """FORCE_CLOSE window: open positions get synthetic exit orders through
    the chokepoint."""

    def _plan(self):
        from openbb_fmp_trading.models.config import RiskConfig
        from openbb_fmp_trading.models.plan import DailyPlan

        return DailyPlan(
            as_of=datetime(2026, 7, 6, 13, 25, tzinfo=timezone.utc),
            date=date(2026, 7, 6),
            watchlist=["MSFT", "AAPL"],
            preset="intraday_momentum",
            alerts=[],
            session_risk=RiskConfig(),
            thesis="force-close test",
            agent_backend="none",
        )

    def test_force_close_synthesizes_exit_for_every_open_position(
        self, monkeypatch
    ):
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.session import IntradaySession
        from openbb_fmp_trading.models.journal_events import (
            FillEvent,
            OrderEvent,
        )

        # Two open positions: 10 long MSFT, 5 short AAPL
        pos_msft = MagicMock(symbol="MSFT", qty=Decimal("10"))
        pos_aapl = MagicMock(symbol="AAPL", qty=Decimal("-5"))

        rm = MagicMock()
        rm.propose_trade.return_value = MagicMock(
            verdict="APPROVED", reason_code=None, gate=None, reason=None
        )
        broker = MagicMock()
        broker.positions.return_value = [pos_msft, pos_aapl]
        broker.submit.return_value = MagicMock(
            price=Decimal("430.00"),
            qty=Decimal("10"),
            commission=Decimal("1.00"),
        )

        # Stub all fetch seams so run_tick doesn't touch the network
        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote",
            lambda symbols, provider: [{"symbol": s, "price": "430"} for s in symbols],
        )
        monkeypatch.setattr(
            tick_loop, "_fetch_recent_bars",
            lambda symbols: {s: [MagicMock(close=Decimal("430"))] for s in symbols},
        )
        monkeypatch.setattr(
            tick_loop, "_fetch_session_status", lambda exchange: MagicMock()
        )
        # Not a bar close - proves force-close runs INDEPENDENTLY of the
        # signal cascade cadence (P4 semantics)
        monkeypatch.setattr(
            tick_loop, "_is_signal_bar_close", lambda ts, preset: False
        )

        session = IntradaySession(
            plan=self._plan(),
            journal=MagicMock(),
            risk_manager=rm,
            broker=broker,
            bandwidth=MagicMock(),
        )
        # 15:56 ET == 19:56 UTC — FORCE_CLOSE window
        events = tick_loop.run_tick(
            session,
            tick_ts=datetime(2026, 7, 6, 19, 56, tzinfo=timezone.utc),
        )

        # Two exit orders queued — one per open position
        assert broker.submit.call_count == 2
        orders = [e for e in events if isinstance(e, OrderEvent)]
        assert len(orders) == 2

        # Long MSFT → CLOSE_LONG; short AAPL → CLOSE_SHORT
        intents = {o.payload["symbol"]: o.payload["intent"] for o in orders}
        assert intents == {"MSFT": "CLOSE_LONG", "AAPL": "CLOSE_SHORT"}

    def test_no_force_close_before_window(self, monkeypatch):
        """Before 15:55 the cascade is silent even if positions are open."""
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.session import IntradaySession

        rm = MagicMock()
        broker = MagicMock()
        broker.positions.return_value = [MagicMock(symbol="MSFT", qty=Decimal("10"))]

        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote", lambda symbols, provider: []
        )
        monkeypatch.setattr(
            tick_loop, "_is_signal_bar_close", lambda ts, preset: False
        )

        session = IntradaySession(
            plan=self._plan(),
            journal=MagicMock(),
            risk_manager=rm,
            broker=broker,
            bandwidth=MagicMock(),
        )
        # 15:49 ET == 19:49 UTC — NORMAL window
        tick_loop.run_tick(
            session,
            tick_ts=datetime(2026, 7, 6, 19, 49, tzinfo=timezone.utc),
        )
        broker.submit.assert_not_called()

    def test_force_close_idempotent_across_ticks(self, monkeypatch):
        """Security-review fix #2: repeated FORCE_CLOSE ticks must not
        resubmit exit orders for symbols already queued this session-date.

        Without the dedup ledger, a 5-second tick cadence would fire
        _force_close_positions 12+ times per minute, stacking duplicate
        exit orders in the broker queue."""
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.session import IntradaySession

        pos = MagicMock(symbol="MSFT", qty=Decimal("10"))
        rm = MagicMock()
        rm.propose_trade.return_value = MagicMock(
            verdict="APPROVED", reason_code=None, gate=None, reason=None
        )
        broker = MagicMock()
        broker.positions.return_value = [pos]  # same position present every tick
        broker.submit.return_value = MagicMock(
            price=Decimal("430"), qty=Decimal("10"), commission=Decimal("1")
        )

        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote",
            lambda symbols, provider: [{"symbol": s, "price": "430"} for s in symbols],
        )
        monkeypatch.setattr(
            tick_loop, "_is_signal_bar_close", lambda ts, preset: False
        )

        session = IntradaySession(
            plan=self._plan(),
            journal=MagicMock(),
            risk_manager=rm,
            broker=broker,
            bandwidth=MagicMock(),
        )
        # Three FORCE_CLOSE ticks (15:56, 15:57, 15:58 ET) — same session-date
        for minute in (56, 57, 58):
            tick_loop.run_tick(
                session,
                tick_ts=datetime(2026, 7, 6, 19, minute, tzinfo=timezone.utc),
            )
        # broker.submit called exactly ONCE despite three FORCE_CLOSE ticks
        assert broker.submit.call_count == 1

    def test_force_close_isolates_per_symbol_failure(self, monkeypatch):
        """Security-review fix #3: a failing _process_signal for one symbol
        must not prevent flattening the rest of the book."""
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.session import IntradaySession

        pos_msft = MagicMock(symbol="MSFT", qty=Decimal("10"))
        pos_aapl = MagicMock(symbol="AAPL", qty=Decimal("5"))

        rm = MagicMock()
        rm.propose_trade.return_value = MagicMock(
            verdict="APPROVED", reason_code=None, gate=None, reason=None
        )
        broker = MagicMock()
        broker.positions.return_value = [pos_msft, pos_aapl]
        # First submit raises (MSFT), second succeeds (AAPL)
        broker.submit.side_effect = [
            RuntimeError("simulated broker outage for MSFT"),
            MagicMock(price=Decimal("212"), qty=Decimal("5"), commission=Decimal("1")),
        ]

        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote",
            lambda symbols, provider: [{"symbol": s, "price": "1"} for s in symbols],
        )
        monkeypatch.setattr(
            tick_loop, "_is_signal_bar_close", lambda ts, preset: False
        )

        session = IntradaySession(
            plan=self._plan(),
            journal=MagicMock(),
            risk_manager=rm,
            broker=broker,
            bandwidth=MagicMock(),
        )
        # Should NOT raise despite MSFT's failure
        tick_loop.run_tick(
            session,
            tick_ts=datetime(2026, 7, 6, 19, 56, tzinfo=timezone.utc),
        )
        # AAPL still got its exit attempt after MSFT failed
        assert broker.submit.call_count == 2
