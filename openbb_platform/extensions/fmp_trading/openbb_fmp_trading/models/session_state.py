"""Session-state models (PRD §6.2.5) + TradeDecision (§8.1).

TradeDecision lives here rather than in a separate module because the
RiskManager returns it and journal events reference it — colocating with
the other session-state types minimizes import graph churn in P2's
IntradaySession wiring.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from pydantic import Field

from openbb_fmp_trading.models.market_data import (
    IntradayBar,
    Quote,
    SessionStatus,
)


class TickData(Data):
    """One tick of live market state.

    Consumed by AlertManager.evaluate() and RiskManager gates each poll cycle.
    """

    ts: datetime = Field(description="Tick timestamp (tz-aware).")
    quotes: dict[str, Quote] = Field(
        default_factory=dict,
        description="Latest quote per watchlist symbol.",
    )
    bars_recent: dict[str, list[IntradayBar]] = Field(
        default_factory=dict,
        description="Last N bars per symbol (window sized by indicator lookback).",
    )
    session_status: SessionStatus | None = Field(
        default=None,
        description=(
            "Exchange session-state snapshot. Only populated on bar-close ticks "
            "(tick_loop._build_tick_data skips the fetch on mid-bar ticks to "
            "keep the poll loop cheap). Consumers must handle None."
        ),
    )


class PnLSnapshot(Data):
    """Running session P&L. Derived from open positions + closed fills."""

    ts: datetime
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    day_pnl: Decimal = Field(description="realized + unrealized since session open.")
    day_dd_pct: float = Field(description="Negative on drawdown; 0 or positive otherwise.")
    positions_open: int
    positions_closed: int
    win_rate_today: float | None = Field(
        default=None,
        description="None until at least one closed position exists.",
    )


class BandwidthState(Data):
    """Month-scoped FMP bandwidth accounting (P6)."""

    month_used_bytes: int
    month_budget_bytes: int
    month_used_pct: float
    mode: Literal["normal", "conservation", "halted"]
    session_used_bytes: int


class RiskState(Data):
    """RiskManager runtime state. Journal-snapshotted on every change."""

    ts: datetime
    gates_active: list[str] = Field(
        default_factory=list,
        description="Gate reason_codes currently enforceable (e.g. G1..G8).",
    )
    gates_tripped_today: list[str] = Field(
        default_factory=list,
        description="Gates that fired at least once this session.",
    )
    cooldowns: dict[str, datetime] = Field(
        default_factory=dict,
        description="Symbol -> cooldown-expiry timestamp (G4 tracking).",
    )
    flat_by_close_window_open: bool = Field(
        default=False,
        description="True after G1's flat_by_close_time_et cutoff.",
    )
    day_dd_pct: float = 0.0
    open_position_count: int = 0
    max_open_positions: int = 5


class JournalEvent(Data):
    """One session-journal event. Written NDJSON-per-line by SessionJournal.

    NOTE (P1.4): the intent is to replace this local model with an import
    from openbb_core_journal.JournalEvent once J4 lands. Keeping the same
    field shape (ts / session_id / event_type / payload) makes the swap
    an import-only change.
    """

    ts: datetime
    session_id: str
    event_type: Literal[
        "session_start", "session_end",
        "tick", "signal", "plan", "order", "fill",
        "veto", "alert", "risk_state_change",
        "mode_change", "agent_turn_start", "agent_turn_end",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class TradeDecision(Data):
    """RiskManager verdict — the sole exit from propose_trade().

    Belongs with session-state (rather than its own module) because it's
    the boundary object between the RiskManager and the paper broker;
    journal events reference it.
    """

    verdict: Literal["APPROVED", "REJECTED"]
    reason: str | None = Field(
        default=None,
        description="Populated when REJECTED; None on APPROVED.",
    )
    reason_code: str | None = Field(
        default=None,
        description="Machine-readable enum (G1..G8) — filter journal by this.",
    )
    gate: str | None = Field(
        default=None,
        description="Which gate tripped (max_position_size, flat_by_close, ...).",
    )
    plan: dict[str, Any] = Field(
        default_factory=dict,
        description="Echo of the proposed plan for journal audit trail.",
    )
