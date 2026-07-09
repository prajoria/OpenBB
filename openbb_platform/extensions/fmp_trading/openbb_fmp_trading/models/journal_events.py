"""Typed JournalEvent subclasses for fmp_trading (PRD §6.2.5, J4 retrofit).

Every intraday-session event type gets a dedicated subclass with its
event_type Literal fixed at class level. This gives:
  1. Static type-checking of event construction (mistyped event_type caught
     at import time, not at journal-write time)
  2. Dispatch clarity — downstream consumers can pattern-match on class
  3. Free discriminator support if we later want a Union[Event...] alias

Payload shapes are intentionally left dict[str, Any] here (inherited from
the base) — a future refactor can promote frequently-emitted payloads to
their own typed models. For v1 the flexibility beats the strictness.

Why "AlertFiredEvent" not "AlertEvent"?
  Because openbb_fmp_trading.models.alert already exports AlertEvent as the
  domain model for a fired alert (returned by AlertManager.evaluate()). This
  module needs a distinct name for the JOURNAL wrapper around that domain
  event, so we prefix "Fired" to disambiguate. Both classes carry the same
  payload shape by convention.
"""

from __future__ import annotations

from typing import Literal

from openbb_core_journal import JournalEvent


class SessionStartEvent(JournalEvent):
    """Session boot: exchange, starting equity, config snapshot."""

    event_type: Literal["session_start"] = "session_start"


class TickEvent(JournalEvent):
    """One tick of the IntradaySession loop. Payload: watchlist_size,
    quotes_fetched, mode (normal/conservation/halted)."""

    event_type: Literal["tick"] = "tick"


class SignalEvent(JournalEvent):
    """A techtrade confluence signal fired for a symbol. Payload: symbol,
    score, direction, votes."""

    event_type: Literal["signal"] = "signal"


class OrderEvent(JournalEvent):
    """A broker order created from a plan. Payload: symbol, intent, qty,
    limit_price / stop_price, side."""

    event_type: Literal["order"] = "order"


class FillEvent(JournalEvent):
    """A paper fill from PaperBroker.simulate(). Payload: symbol, price
    (after slippage), qty, slippage, commission."""

    event_type: Literal["fill"] = "fill"


class VetoEvent(JournalEvent):
    """A RiskManager REJECTED decision. Payload: symbol, reason_code (G1..G8),
    gate name, reason string, echo of the plan."""

    event_type: Literal["veto"] = "veto"


class AlertFiredEvent(JournalEvent):
    """An AlertManager alert fired. Payload matches models.alert.AlertEvent —
    alert_id, symbol, condition, context. Prefixed "Fired" to disambiguate
    from models.alert.AlertEvent (the domain object)."""

    event_type: Literal["alert"] = "alert"


class RiskStateChangeEvent(JournalEvent):
    """A RiskManager state transition (gate activated / deactivated, cooldown
    added, day_dd threshold crossed). Payload: gate, activated (bool), context."""

    event_type: Literal["risk_state_change"] = "risk_state_change"


class SessionEndEvent(JournalEvent):
    """Session teardown. Payload: flat_at_close, realized_pnl, exit_code, counters."""

    event_type: Literal["session_end"] = "session_end"


__all__ = [
    "AlertFiredEvent",
    "FillEvent",
    "OrderEvent",
    "RiskStateChangeEvent",
    "SessionEndEvent",
    "SessionStartEvent",
    "SignalEvent",
    "TickEvent",
    "VetoEvent",
]
