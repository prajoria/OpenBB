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


class DailyPlanCommittedEvent(JournalEvent):
    """P3.1: pre-open turn produced a plan (either LLM or fallback).

    Payload keys:
      agent_backend             ("claude" | "openai" | "none")
      is_deterministic_fallback (bool)
      watchlist_size            (int)
      preset                    (str)
      model_id                  (str | None, A6)
      prompt_version            (str, A6)
    """

    event_type: Literal["daily_plan_committed"] = "daily_plan_committed"


class EndOfDayReportEvent(JournalEvent):
    """P3.2: post-close turn produced a report (either LLM or fallback).

    Payload keys:
      agent_backend, is_deterministic_fallback, briefing_md_length,
      recommendation_count, model_id, prompt_version.
    """

    event_type: Literal["end_of_day_report"] = "end_of_day_report"


class AgentFallbackEvent(JournalEvent):
    """T3 (P1): loud journal entry every time a fallback fires.

    Made visible per T3 because a stale watchlist that goes unnoticed at
    09:30 ET has caused real losses in this asset class.

    Payload keys:
      turn             ("pre_open" | "post_close")
      reason           (short human-readable label)
      source_error    (exception class name)
      fallback_source (which fallback tier: state_store | default_config)
    """

    event_type: Literal["agent_fallback"] = "agent_fallback"


class PromptInjectionRejectedEvent(JournalEvent):
    """A1 (P0): a deterministic post-LLM validator rejected something the
    LLM emitted (out-of-universe symbol, oversized watchlist, risk-loosening).

    Payload keys:
      defense_layer  ("tradable_universe" | "risk_clamp" |
                       "watchlist_size_cap")
      field          (name of the rejected field)
      offending_value (the value that was clipped or rejected)
    """

    event_type: Literal["prompt_injection_rejected"] = "prompt_injection_rejected"


__all__ = [
    "AgentFallbackEvent",
    "AlertFiredEvent",
    "DailyPlanCommittedEvent",
    "EndOfDayReportEvent",
    "FillEvent",
    "OrderEvent",
    "PromptInjectionRejectedEvent",
    "RiskStateChangeEvent",
    "SessionEndEvent",
    "SessionStartEvent",
    "SignalEvent",
    "TickEvent",
    "VetoEvent",
]
