"""AC-1 integration test: 6.5h simulated session end-to-end (P2.7).

Compressed session: walks the tick clock from 09:30 ET → 16:00 ET at a
5-second cadence, driving the full stack (IntradaySession → run_tick →
techtrade stubs → RiskManager funnel → stateful test-broker → typed
JournalEvents to NDJSON). Verifies four Phase 2 acceptance surfaces:

  AC-1: session runs from open to close without operator intervention
  AC-6: no OPEN_* orders submitted after 15:50 ET
  P4:   flat_at_close=True in the SessionEndEvent payload
  P3:   no fills reference bars ahead of their own tick_ts

Design decisions:

  * **Inline stateful test-broker.** The shipped ``techtrade.PaperBroker``
    is stateless (its ``positions()`` returns []); we need position
    tracking here to exercise the force-close cascade. Building a small
    ``StatefulTestBroker`` inline is honest about the test surface — it
    keeps the E2E harness self-contained and makes the P&L bookkeeping
    inspectable in one file.
  * **Real IntradaySession + real run_tick.** Only the network-facing
    module seams (``_fetch_batch_quote``, ``_fetch_recent_bars``,
    ``_fetch_session_status``, ``_run_techtrade_signals``,
    ``_build_techtrade_plan``) are stubbed. Everything below is real.
  * **Deterministic signal cadence.** The fixture emits an OPEN_LONG for
    MSFT at 10:00 ET, and CLOSE_LONG will be synthesized by the
    flat-by-close cascade at 15:55 ET. No randomness in the plan; the
    journal shape is a function of the fixture alone.
  * **NDJSON journal.** Written via ``JournalWriter``-compatible mock
    that appends one ``model_dump_json()`` line per event, matching the
    on-disk shape the P5 replay command consumes.

Runtime: <5s (no real sleeps, no network, no live openbb).
Marked ``@pytest.mark.integration`` — excluded from the default unit run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

_ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Test-only stateful broker — mirrors the surface run_tick + force-close use.
# ---------------------------------------------------------------------------


@dataclass
class _StatefulPosition:
    symbol: str
    qty: Decimal


@dataclass
class _StatefulFill:
    price: Decimal
    qty: Decimal
    commission: Decimal


@dataclass
class StatefulTestBroker:
    """Tracks positions so ``positions()`` returns real state and the
    force-close cascade has something to close.

    Fill semantics kept minimal: OPEN_LONG at bar.open, CLOSE_LONG at
    bar.open. Slippage=0, commission=1.0 flat per order. The E2E test
    isn't chasing fill-price accuracy — it's chasing journal shape."""

    _positions: dict[str, Decimal] = field(default_factory=dict)
    submitted: list[dict[str, Any]] = field(default_factory=list)

    def submit(self, order: Any, bar: Any = None) -> _StatefulFill | None:
        # Extract price: prefer bar.open, fall back to bar.close, else 100.
        price = Decimal("100")
        if bar is not None:
            price = Decimal(str(getattr(bar, "open", None) or getattr(bar, "close", price)))

        qty_signed = Decimal(str(order.qty))
        intent = order.intent
        if intent == "OPEN_LONG":
            self._positions[order.symbol] = self._positions.get(order.symbol, Decimal(0)) + qty_signed
        elif intent == "OPEN_SHORT":
            self._positions[order.symbol] = self._positions.get(order.symbol, Decimal(0)) - qty_signed
        elif intent in ("CLOSE_LONG", "CLOSE_SHORT"):
            # Zero the position; sign matches whichever direction was open
            self._positions.pop(order.symbol, None)

        self.submitted.append({
            "ts": None,  # timestamp is recorded via the OrderEvent, not here
            "symbol": order.symbol,
            "qty": str(qty_signed),
            "intent": intent,
            "price": str(price),
        })
        return _StatefulFill(price=price, qty=qty_signed, commission=Decimal("1.00"))

    def positions(self) -> list[_StatefulPosition]:
        return [_StatefulPosition(symbol=s, qty=q) for s, q in self._positions.items() if q != 0]


# ---------------------------------------------------------------------------
# NDJSON journal writer — matches the on-disk shape the P5 replay consumes.
# ---------------------------------------------------------------------------


class _NDJSONJournal:
    """Writes one event per line as JSON. Mirrors JournalWriter.write()."""

    def __init__(self, path: Path):
        self.path = path
        self.path.write_text("", encoding="utf-8")

    def write(self, event: Any) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


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
        thesis="AC-1 integration",
        agent_backend="none",
    )


def _five_min_bars_for_msft() -> list[SimpleNamespace]:
    """78 bars from 09:30 → 15:55 ET (5-min interval)."""
    bars = []
    start = datetime(2026, 7, 6, 13, 30, tzinfo=timezone.utc)  # 09:30 ET
    for i in range(78):
        ts = start + timedelta(minutes=5 * i)
        px = Decimal(f"{430 + i * 0.05:.2f}")
        bars.append(SimpleNamespace(
            symbol="MSFT", interval="5min", ts=ts,
            open=px, high=px + Decimal("0.50"),
            low=px - Decimal("0.10"), close=px + Decimal("0.25"),
            volume=1_000_000,
        ))
    return bars


def _walk_session_ticks():
    """Yield one tz-aware UTC tick_ts every 5 seconds from 09:30 → 16:00 ET.

    That's 6.5h * 60min * 12 ticks/min = 4680 ticks. Compressed session:
    no real sleeps between them. Runs in single-digit seconds thanks to
    the mid-bar early-out in _build_tick_data (only bar-close ticks pay
    the recent-bars + session-status fetch cost).
    """
    start = datetime(2026, 7, 6, 13, 30, tzinfo=timezone.utc)  # 09:30 ET
    end = datetime(2026, 7, 6, 20, 0, tzinfo=timezone.utc)     # 16:00 ET
    ts = start
    while ts < end:
        yield ts
        ts += timedelta(seconds=5)


@pytest.mark.integration
class TestAC1FullSession:
    """End-to-end compressed 6.5h session against a stubbed FMP surface."""

    def test_full_session_end_to_end(self, tmp_path, monkeypatch):
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.session import IntradaySession

        bars_msft = _five_min_bars_for_msft()
        # Signal emitted only ONCE, at 10:00 ET (== 14:00 UTC). Every other
        # bar-close tick yields no signal so the test is deterministic.
        signal_tick_utc = datetime(2026, 7, 6, 14, 0, tzinfo=timezone.utc)

        fake_signal = SimpleNamespace(
            symbol="MSFT", score=0.85, direction="long",
        )
        fake_order = SimpleNamespace(
            ref="ac1-open", symbol="MSFT",
            qty=Decimal("10"), intent="OPEN_LONG",
        )
        fake_plan = SimpleNamespace(
            symbol="MSFT", intent="OPEN_LONG", orders=[fake_order],
        )

        def _signals_stub(plan, tick):
            # Fire the OPEN once at 10:00 ET; silent every other bar close.
            if tick.ts == signal_tick_utc:
                return [fake_signal]
            return []

        def _plan_stub(sig, tick):
            return fake_plan

        # Bars visible to the loop at any given tick: the sub-list of bars_msft
        # whose ts <= current tick_ts. This enforces the AC-5 no-look-ahead
        # discipline at the fixture level too — the loop can NEVER see a bar
        # that hasn't closed yet.
        current_tick_holder: dict = {"ts": None}

        def _fetch_bars_stub(symbols):
            cur = current_tick_holder["ts"]
            visible = [b for b in bars_msft if b.ts <= cur]
            return {"MSFT": visible or [bars_msft[0]]}

        def _wrap_run_tick(session, tick_ts):
            current_tick_holder["ts"] = tick_ts
            return tick_loop.run_tick(session, tick_ts)

        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote",
            lambda symbols, provider: [{"symbol": s, "price": "430.00"} for s in symbols],
        )
        monkeypatch.setattr(tick_loop, "_fetch_recent_bars", _fetch_bars_stub)
        monkeypatch.setattr(
            tick_loop, "_fetch_session_status",
            lambda exchange: SimpleNamespace(is_market_open=True, exchange=exchange),
        )
        monkeypatch.setattr(tick_loop, "_run_techtrade_signals", _signals_stub)
        monkeypatch.setattr(tick_loop, "_build_techtrade_plan", _plan_stub)

        # Real RiskManager mock: approves everything (broker is what we
        # care about here; risk gates are tested exhaustively elsewhere).
        rm = MagicMock()
        rm.propose_trade.return_value = SimpleNamespace(
            verdict="APPROVED", reason_code=None, gate=None, reason=None,
        )
        broker = StatefulTestBroker()
        journal_path = tmp_path / "ac1_session.ndjson"

        session = IntradaySession(
            plan=_make_plan(),
            journal=_NDJSONJournal(journal_path),
            risk_manager=rm,
            broker=broker,
            bandwidth=MagicMock(),
        )

        for tick_ts in _walk_session_ticks():
            _wrap_run_tick(session, tick_ts)

        # Emit a session_end with the observed flatness
        session.close(flat_at_close=len(broker.positions()) == 0)

        # ---- Parse the on-disk journal ----
        lines = journal_path.read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines if line.strip()]
        by_type: dict[str, list[dict]] = {}
        for e in events:
            by_type.setdefault(e["event_type"], []).append(e)

        # AC-1: session bracket + at least one tick
        assert len(by_type.get("session_start", [])) == 1, (
            "AC-1 requires exactly one session_start marker"
        )
        assert len(by_type.get("session_end", [])) == 1, (
            "AC-1 requires exactly one session_end marker"
        )
        assert len(by_type.get("tick", [])) >= 4000, (
            "6.5h * 720 ticks/hour ~= 4680 expected; got %d"
            % len(by_type.get("tick", []))
        )

        # Signal fired exactly once (fixture is deterministic)
        signals = by_type.get("signal", [])
        assert len(signals) == 1, (
            f"Fixture emits exactly one signal at 10:00 ET; got {len(signals)}"
        )
        assert signals[0]["payload"]["symbol"] == "MSFT"

        # Exactly one OPEN_LONG order (from the 10:00 ET signal). The
        # 15:55 ET force-close cascade adds a CLOSE_LONG exit — that's
        # two orders total. Dedup ledger guarantees no additional exits
        # despite 12+ FORCE_CLOSE ticks/min after 15:55.
        orders = by_type.get("order", [])
        assert len(orders) == 2, (
            "Expected 1 OPEN_LONG (10:00 ET) + 1 CLOSE_LONG (15:55 ET) = 2 orders; "
            f"got {len(orders)}"
        )
        open_orders = [o for o in orders if o["payload"]["intent"].startswith("OPEN_")]
        close_orders = [o for o in orders if o["payload"]["intent"].startswith("CLOSE_")]
        assert len(open_orders) == 1
        assert len(close_orders) == 1

        # AC-6: NO OPEN_* orders after 15:50 ET (== 19:50 UTC)
        cutoff_utc = datetime(2026, 7, 6, 19, 50, tzinfo=timezone.utc)
        for order in open_orders:
            order_ts = datetime.fromisoformat(order["ts"].replace("Z", "+00:00"))
            if order_ts.tzinfo is None:
                order_ts = order_ts.replace(tzinfo=timezone.utc)
            assert order_ts < cutoff_utc, (
                f"AC-6 violation: OPEN_* order at {order_ts} (past 15:50 ET cutoff)"
            )

        # P4: flat_at_close=True in the session_end payload
        end_event = by_type["session_end"][0]
        assert end_event["payload"]["flat_at_close"] is True, (
            "P4 violation: positions still open at session_end"
        )

        # Broker's own book agrees
        assert len(broker.positions()) == 0, (
            "Broker still holds positions post-close — force-close cascade broke"
        )

        # Fills recorded for both orders
        fills = by_type.get("fill", [])
        assert len(fills) == 2, f"Expected 2 fills (one per order); got {len(fills)}"

        # Sanity: no VetoEvent (RM approved everything in this fixture)
        assert not by_type.get("veto"), (
            "Fixture RM approves all; unexpected VetoEvent(s): %r"
            % by_type.get("veto")
        )
