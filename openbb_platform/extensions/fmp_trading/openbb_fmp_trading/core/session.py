"""IntradaySession — market-hours state machine (PRD §8.2, P2.3).

Owns the tick clock, watchlist quote polling cadence, and the session-scoped
journal. Does NOT own signal math (delegated to techtrade — wired in P2.4)
or agent turns (Phase 3).

Chokepoint invariant: every call to ``broker.submit()`` funnels through
``_process_signal()`` → ``RiskManager.propose_trade()``. That single-caller
guarantee is what P7's architecture test (``test_broker_chokepoint.py``)
enforces mechanically — without it the risk gates could be bypassed by
any future contributor who calls ``broker.submit()`` from a new site.

Journal-event style: we use the typed subclasses from
``openbb_fmp_trading.models.journal_events`` (SessionStartEvent, TickEvent,
SessionEndEvent, ...) rather than the generic ``JournalEvent(event_type="x")``
pattern from the plan doc. The subclasses fix event_type at class level so
typos surface at import time; both patterns emit the same wire format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from openbb_fmp_trading.models.journal_events import (
    FillEvent,
    OrderEvent,
    SessionEndEvent,
    SessionStartEvent,
    VetoEvent,
)
from openbb_fmp_trading.models.plan import DailyPlan


def _utc_now_stamp() -> str:
    """Session-id timestamp helper (kept as a module-level fn for test patching)."""
    return datetime.now(timezone.utc).strftime("s%Y%m%d%H%M%S")


@dataclass
class IntradaySession:
    """Market-hours state machine — see module docstring for chokepoint contract."""

    plan: DailyPlan
    journal: Any            # openbb_core_journal.JournalWriter (J4 / P1.4)
    risk_manager: Any       # RiskManager (Phase 1 P1.2)
    broker: Any             # BrokerInterface — PaperBroker in v1 (P2.4)
    bandwidth: Any          # BandwidthMeter (Phase 1 P1.3)
    session_id: str = field(default_factory=_utc_now_stamp)
    _ticks_processed: int = 0
    _flat_window_open: bool = False

    def __post_init__(self) -> None:
        """Emit SessionStartEvent as soon as the session is constructed.

        Doing this in __post_init__ (rather than a separate .start() call)
        means the journal has a session_start marker for every IntradaySession
        that ever existed — including ones that crash before their first
        tick. That guarantee is what makes the P7 golden-test replay work.
        """
        self.journal.write(
            SessionStartEvent(
                ts=datetime.now(timezone.utc),
                session_id=self.session_id,
                payload={
                    "date": str(self.plan.date),
                    "watchlist": list(self.plan.watchlist),
                    "preset": self.plan.preset,
                    "agent_backend": self.plan.agent_backend,
                },
            )
        )

    def emit(self, event: Any) -> None:
        """Single journal-write funnel. Every tick-loop event lands here.

        Kept trivial on purpose: any accounting (rate limiting, sampling,
        redaction) can be added here later without touching the tick loop.
        """
        self.journal.write(event)
        self._ticks_processed += 1

    def close(self, flat_at_close: bool) -> None:
        """Emit SessionEndEvent. Called by the session runner at market close
        or on abnormal shutdown."""
        self.journal.write(
            SessionEndEvent(
                ts=datetime.now(timezone.utc),
                session_id=self.session_id,
                payload={
                    "flat_at_close": flat_at_close,
                    "total_ticks": self._ticks_processed,
                },
            )
        )

    def _process_signal(self, plan: Any, tick: Any) -> list[Any]:
        """The ONLY caller of ``self.broker.submit()`` in the entire codebase.

        Chokepoint contract (PRD §8.6 / P7): every proposed order funnels
        through ``RiskManager.propose_trade()`` here — no other path submits.
        Enforced by ``tests/architecture/test_broker_chokepoint.py`` which
        greps for ``broker.submit(`` and asserts this method is the sole
        call site. Adding a second call site anywhere in the codebase must
        break that architecture test — that's the whole point.

        Flow per tick with an approved plan:
          1. RiskManager evaluates 8 gates → TradeDecision(APPROVED|REJECTED)
          2. If REJECTED: emit one VetoEvent with reason_code (G1..G8), return.
             No broker call. No further events.
          3. If APPROVED: emit one PlanEvent (informational — no PlanEvent
             typed subclass yet, use OrderEvent for each order below).
          4. For each order in plan.orders: broker.submit(order, bar=tick's
             latest bar for the symbol) → emit OrderEvent, then FillEvent
             iff the broker returned a fill.

        Bar selection: uses the last element of
        ``tick.bars_recent[plan.symbol]`` — the tick's most-recent 5-min bar
        for the traded symbol. This is what PaperBroker uses for the
        next-bar-open fill simulation (see techtrade #78 / P2.6 golden test).

        Args:
            plan:  A TradePlan-like object with ``.symbol``, ``.intent``, and
                   ``.orders`` (each order has ``.ref``, ``.symbol``, ``.qty``,
                   ``.intent``). We don't type this strictly here so the
                   session stays decoupled from ``openbb_techtrade`` schema
                   churn — the chokepoint invariant is what matters.
            tick:  A TickData-like object with ``.ts`` and
                   ``.bars_recent[symbol]``.

        Returns:
            The list of emitted events in wire order (also emitted through
            ``self.emit()`` so the journal has them). Returning the list
            makes wiring tests trivial — they can assert on shape without
            introspecting the journal mock.
        """
        events: list[Any] = []
        decision = self.risk_manager.propose_trade(plan, tick)
        if decision.verdict == "REJECTED":
            veto = VetoEvent(
                ts=tick.ts,
                session_id=self.session_id,
                payload={
                    "reason_code": decision.reason_code,
                    "gate": decision.gate,
                    "reason": decision.reason,
                    "plan_symbol": getattr(plan, "symbol", None),
                    "plan_intent": getattr(plan, "intent", None),
                },
            )
            events.append(veto)
            self.emit(veto)
            return events

        # APPROVED path: submit every order in the plan through the broker.
        # No PlanEvent subclass — we emit one OrderEvent per order which
        # gives higher-fidelity attribution than a single plan-level event.
        bars_for_symbol = tick.bars_recent.get(plan.symbol) or []
        latest_bar = bars_for_symbol[-1] if bars_for_symbol else None

        for order in plan.orders:
            fill = self.broker.submit(order, bar=latest_bar)
            order_event = OrderEvent(
                ts=tick.ts,
                session_id=self.session_id,
                payload={
                    "order_ref": getattr(order, "ref", None),
                    "symbol": getattr(order, "symbol", None),
                    "qty": str(getattr(order, "qty", "")),
                    "intent": getattr(order, "intent", None),
                },
            )
            events.append(order_event)
            self.emit(order_event)
            if fill is not None:
                fill_event = FillEvent(
                    ts=tick.ts,
                    session_id=self.session_id,
                    payload={
                        "order_ref": getattr(order, "ref", None),
                        "fill_price": str(getattr(fill, "price", "")),
                        "fill_qty": str(getattr(fill, "qty", "")),
                        "commission": str(getattr(fill, "commission", "")),
                    },
                )
                events.append(fill_event)
                self.emit(fill_event)
        return events
