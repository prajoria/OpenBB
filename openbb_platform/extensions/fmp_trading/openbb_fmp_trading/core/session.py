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
    SessionEndEvent,
    SessionStartEvent,
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
