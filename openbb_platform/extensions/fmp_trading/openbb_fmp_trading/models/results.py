"""Session-result + health-report models (PRD §6.2.6)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

from openbb_core.provider.abstract.data import Data
from pydantic import AliasChoices, Field

from openbb_fmp_trading.models.plan import DailyPlan
from openbb_fmp_trading.models.session_state import BandwidthState, PnLSnapshot


class SessionResult(Data):
    """End-of-day session summary — the terminal object obb.fmp_trading.run() returns."""

    session_id: str
    trading_date: date = Field(
        description="Trading date the session ran for.",
        # Backward-compat: older serialized results use `date`. Renamed
        # for consistency with DailyPlan.trading_date (see #744).
        validation_alias=AliasChoices("trading_date", "date"),
    )
    exchange: str
    started_at: datetime
    ended_at: datetime
    exit_code: int = Field(
        description=(
            "0=clean, 1=risk breach mid-session, 2=FMP 401, 3=bandwidth halt, "
            "4=veto storm, 5=non-flat at close, 78=no-op day (holiday)."
        )
    )
    daily_plan: DailyPlan | None = Field(
        default=None,
        description="None only when session ran with no DailyPlan (dry-run/tests).",
    )
    final_pnl: PnLSnapshot
    final_bandwidth: BandwidthState | None = None
    total_ticks: int = 0
    total_signals: int = 0
    total_orders: int = 0
    total_fills: int = 0
    total_vetoes: int = 0
    total_alerts_fired: int = 0
    flat_at_close: bool = Field(
        description="True iff no positions open at session_end."
    )
    journal_path: Path


class HealthReport(Data):
    """obb.fmp_trading.doctor() output (P1.6 populates)."""

    ts: datetime
    fmp_credentials_ok: bool
    mysql_cache_ok: bool
    exchange_calendars_ok: bool
    techtrade_version: str
    techtrade_ok: bool
    agent_extra_installed: bool
    xlsxwriter_extra_installed: bool
    validation_extra_installed: bool
    bandwidth_remaining_pct: float
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ReportManifest(Data):
    """obb.fmp_trading.report() output — paths to rendered artifacts (P5)."""

    session_id: str
    session_date: date | None = Field(
        default=None,
        description="Trading date the report covers (extracted from session_start).",
    )
    md_path: Path | None = None
    xlsx_path: Path | None = None
    json_path: Path | None = None
    included_agent_narrative: bool = False
    session_events_count: int = Field(
        default=0,
        description="Total journaled events consumed to produce this report.",
    )
    agent_backend: Literal["claude", "openai", "none"] | None = Field(
        default=None,
        description="Provenance if an EndOfDayReportEvent was in the journal.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Non-fatal warnings — e.g. 'xlsx skipped: openbb-techtrade "
            "not installed'. format='all' still returns a manifest even "
            "when xlsx failed; the operator sees the warning here."
        ),
    )


class ReplayResult(Data):
    """obb.fmp_trading.replay() output — reconstructed session (P5.3).

    Same shape a live IntradaySession would have produced on the
    original run — minus BandwidthState (per PRD §8.7, bandwidth is
    session-scoped ephemeral). ``diverged_at_tick`` is populated iff the
    replayed run's emitted events disagreed with the recorded events at
    that tick position.
    """

    session_id: str
    session_date: date
    daily_plan: DailyPlan | None = None
    events_replayed: int = 0
    diverged_at_tick: int | None = Field(
        default=None,
        description=(
            "0-based tick index of the first divergence, or None if the "
            "replayed run matched the recorded events end-to-end. When "
            "raise_on_divergence=True (default) the function raises "
            "ReplayDivergenceError instead of returning this field set."
        ),
    )
