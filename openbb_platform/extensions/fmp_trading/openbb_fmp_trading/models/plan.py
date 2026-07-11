"""DailyPlan — the pre-open agent's committed plan for the day (PRD §6.2.1)."""

from __future__ import annotations

from datetime import date, datetime

from openbb_core.provider.abstract.data import Data
from pydantic import Field

from openbb_fmp_trading.models.alert import AlertSpec
from openbb_fmp_trading.models.config import RiskConfig


class DailyPlan(Data):
    """The pre-open agent's committed plan for the day.

    Written to journal + committed to IntradaySession at 09:29 ET (P2).
    Immutable after commit — the intraday tick loop reads it, never mutates.
    """

    as_of: datetime = Field(description="Commit timestamp (tz-aware UTC).")
    date: date = Field(description="Trading date the plan applies to.")
    watchlist: list[str] = Field(
        description="10-30 symbols the intraday loop will track."
    )
    preset: str = Field(
        description="Techtrade preset name (e.g. intraday_momentum, trend_follow)."
    )
    alerts: list[AlertSpec] = Field(
        default_factory=list,
        description="Alert specs to register at session start (P4).",
    )
    session_risk: RiskConfig = Field(
        description="Risk gates for today (overrides DailyConfig.default_risk)."
    )
    thesis: str = Field(description="Agent's narrative rationale — 1-3 sentences.")
    agent_backend: str = Field(
        description="Provenance: which backend produced this plan (claude/openai/none)."
    )
    is_deterministic_fallback: bool = Field(
        default=False,
        description="True when the agent turn failed and deterministic fallback ran.",
    )
