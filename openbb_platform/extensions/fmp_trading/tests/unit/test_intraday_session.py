"""Unit tests for the IntradaySession skeleton + tick loop (P2.3).

Verifies the two contracts P2.3 is supposed to ship:

1. **Construction emits SessionStartEvent** — the session_start marker
   lands in the journal via ``__post_init__``, so every IntradaySession that
   ever existed leaves a trace even if it crashes before tick 1.
2. **``run_tick`` polls quotes and emits exactly one TickEvent per tick**
   — no signals, no plans, no orders (that's P2.4). The event carries the
   quotes payload so downstream consumers can reconstruct the tick without
   a separate quote-fetch call.

Test seams:
  * ``_fetch_batch_quote`` is patched at the ``core.tick_loop`` module level
    rather than at ``openbb.obb`` — this is exactly why it lives as a
    module-level function and not a method (see ``tick_loop.py`` docstring).
  * The journal is a plain ``MagicMock``; the real ``JournalWriter``
    contract is exercised in ``openbb_core_journal.tests.test_j2_writer_reader``.

Env: no live OpenBB runtime needed. Runs in ~30ms.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


def _make_plan():
    """Construct a minimal DailyPlan the session can accept.

    RiskConfig / AlertSpec fields are required by the DailyPlan schema;
    we build the smallest legal instance rather than mocking the plan
    itself so future field additions surface as clear pytest errors here.
    """
    from openbb_fmp_trading.models.config import RiskConfig
    from openbb_fmp_trading.models.plan import DailyPlan

    return DailyPlan(
        as_of=datetime(2026, 7, 6, 13, 25, tzinfo=timezone.utc),
        trading_date=date(2026, 7, 6),
        watchlist=["MSFT", "AAPL"],
        preset="intraday_momentum",
        alerts=[],
        session_risk=RiskConfig(),
        thesis="test plan for P2.3 skeleton",
        agent_backend="none",
    )


class TestSessionConstruction:
    """P2.3 AC-A: Construction emits SessionStartEvent exactly once."""

    def test_construction_writes_session_start_event(self):
        from openbb_fmp_trading.core.session import IntradaySession
        from openbb_fmp_trading.models.journal_events import SessionStartEvent

        journal = MagicMock()
        IntradaySession(
            plan=_make_plan(),
            journal=journal,
            risk_manager=MagicMock(),
            broker=MagicMock(),
            bandwidth=MagicMock(),
        )

        assert journal.write.call_count == 1
        emitted = journal.write.call_args_list[0].args[0]
        assert isinstance(emitted, SessionStartEvent)
        assert emitted.event_type == "session_start"
        assert emitted.payload["watchlist"] == ["MSFT", "AAPL"]
        assert emitted.payload["preset"] == "intraday_momentum"

    def test_session_id_is_stable_across_emits(self):
        """session_id is generated once at __init__ and reused on every emit."""
        from openbb_fmp_trading.core.session import IntradaySession

        journal = MagicMock()
        session = IntradaySession(
            plan=_make_plan(),
            journal=journal,
            risk_manager=MagicMock(),
            broker=MagicMock(),
            bandwidth=MagicMock(),
        )
        start_id = journal.write.call_args_list[0].args[0].session_id
        assert session.session_id == start_id  # not regenerated per-emit

    def test_close_emits_session_end_event(self):
        from openbb_fmp_trading.core.session import IntradaySession
        from openbb_fmp_trading.models.journal_events import SessionEndEvent

        journal = MagicMock()
        session = IntradaySession(
            plan=_make_plan(),
            journal=journal,
            risk_manager=MagicMock(),
            broker=MagicMock(),
            bandwidth=MagicMock(),
        )
        session.close(flat_at_close=True)

        end_events = [
            c.args[0]
            for c in journal.write.call_args_list
            if isinstance(c.args[0], SessionEndEvent)
        ]
        assert len(end_events) == 1
        assert end_events[0].payload["flat_at_close"] is True
        assert end_events[0].payload["total_ticks"] == 0


class TestRunTick:
    """P2.3 AC-B: run_tick polls quotes and emits one TickEvent per tick."""

    @pytest.fixture(autouse=True)
    def _stub_extra_fetchers(self, monkeypatch):
        """Stub the extra fetchers that fire on bar-close ticks.

        `_build_tick_data` calls `_fetch_recent_bars` and
        `_fetch_session_status` when the tick is a bar close. Those hit
        `obb.fmp_trading.bars_intraday` / `.session_status` — routes NOT
        yet registered on the router (see #821). Individual tests only
        monkeypatch `_fetch_batch_quote`; add class-level stubs for the
        other two so the tests isolate the specific path under test.

        Also stub ``_run_techtrade_signals`` because a bar-close tick
        drives it through techtrade with the session's plan.preset —
        which is a MagicMock in these tests and fails pydantic
        validation inside techtrade's build_signals. The test is
        asserting the tick/quote path, not the signal cascade — the
        latter is exercised in test_tick_loop_signal_wiring.py.
        """
        from openbb_fmp_trading.core import tick_loop

        monkeypatch.setattr(
            tick_loop, "_fetch_recent_bars",
            lambda symbols: {s: [] for s in symbols},
        )
        monkeypatch.setattr(
            tick_loop, "_fetch_session_status", lambda exchange: None,
        )
        monkeypatch.setattr(
            tick_loop, "_run_techtrade_signals", lambda plan, tick: [],
        )

    def test_run_tick_polls_quotes_and_emits_tick_event(self, monkeypatch):
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.models.journal_events import TickEvent

        fake_quotes = [
            {"symbol": "MSFT", "price": Decimal("430.15"),
             "timestamp": datetime(2026, 7, 6, 13, 35, tzinfo=timezone.utc)},
            {"symbol": "AAPL", "price": Decimal("212.50"),
             "timestamp": datetime(2026, 7, 6, 13, 35, tzinfo=timezone.utc)},
        ]

        captured_call: dict = {}

        def _fake_batch(symbols, provider):
            captured_call["symbols"] = symbols
            captured_call["provider"] = provider
            return fake_quotes

        monkeypatch.setattr(tick_loop, "_fetch_batch_quote", _fake_batch)

        session = MagicMock()
        session.plan.watchlist = ["MSFT", "AAPL"]
        session.session_id = "s20260706133500"

        tick_ts = datetime(2026, 7, 6, 13, 35, tzinfo=timezone.utc)
        events = tick_loop.run_tick(session, tick_ts=tick_ts)

        # Contract: fmp_cached is the enforced provider (never raw fmp / yfinance)
        assert captured_call["provider"] == "fmp_cached"
        assert captured_call["symbols"] == ["MSFT", "AAPL"]

        # Exactly one TickEvent per tick
        assert len(events) == 1
        assert isinstance(events[0], TickEvent)
        assert events[0].event_type == "tick"
        assert events[0].session_id == "s20260706133500"
        assert events[0].payload["watchlist_size"] == 2
        assert events[0].payload["quotes_fetched"] == 2
        assert events[0].payload["quotes"][0]["symbol"] == "MSFT"

        # Emission funneled through session.emit (not direct journal.write)
        session.emit.assert_called_once()
        assert session.emit.call_args.args[0] is events[0]

    def test_run_tick_journals_no_signals_or_orders(self, monkeypatch):
        """P2.3 hard boundary: NO signal/plan/order/fill events yet — that's P2.4."""
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.models.journal_events import (
            OrderEvent,
            SignalEvent,
        )

        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote", lambda symbols, provider: []
        )
        session = MagicMock()
        session.plan.watchlist = ["MSFT"]
        session.session_id = "s20260706133500"

        events = tick_loop.run_tick(
            session, tick_ts=datetime(2026, 7, 6, 13, 35, tzinfo=timezone.utc)
        )
        for e in events:
            assert not isinstance(e, (SignalEvent, OrderEvent)), (
                "P2.3 must not emit signal/order events — P2.4 wires signals in"
            )

    def test_run_tick_three_smoke_iterations(self, monkeypatch):
        """PRD §11 replay contract: 3 ticks -> 3 TickEvents, no leakage between ticks."""
        from openbb_fmp_trading.core.session import IntradaySession
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.models.journal_events import (
            SessionStartEvent,
            TickEvent,
        )

        monkeypatch.setattr(
            tick_loop,
            "_fetch_batch_quote",
            lambda symbols, provider: [
                {"symbol": s, "price": Decimal("100.00"), "timestamp": None}
                for s in symbols
            ],
        )

        journal = MagicMock()
        session = IntradaySession(
            plan=_make_plan(),
            journal=journal,
            risk_manager=MagicMock(),
            broker=MagicMock(),
            bandwidth=MagicMock(),
        )
        for minute in (35, 36, 37):
            tick_loop.run_tick(
                session,
                tick_ts=datetime(2026, 7, 6, 13, minute, tzinfo=timezone.utc),
            )

        written = [c.args[0] for c in journal.write.call_args_list]
        assert sum(isinstance(e, SessionStartEvent) for e in written) == 1
        assert sum(isinstance(e, TickEvent) for e in written) == 3
        assert session._ticks_processed == 3
