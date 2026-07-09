"""Session-result + health-report models (PRD §6.2.6)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from openbb_core.provider.abstract.data import Data
from pydantic import Field

from openbb_fmp_trading.models.plan import DailyPlan
from openbb_fmp_trading.models.session_state import BandwidthState, PnLSnapshot


class SessionResult(Data):
    """End-of-day session summary — the terminal object obb.fmp_trading.run() returns."""

    session_id: str
    date: date
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
    md_path: Path | None = None
    xlsx_path: Path | None = None
    json_path: Path | None = None
    included_agent_narrative: bool = False
