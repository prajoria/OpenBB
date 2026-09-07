"""TechTrade job definitions for the OpenBB jobs service (issue #1934).

Exposes two allowlisted, typed jobs discovered by the core jobs worker through the
``openbb_job_extension`` entry-point group:

- ``techtrade.daily_scan`` -- runs the cross-segment scan and persists widget-ready
  snapshots (weekdays 03:00 local, before the US cash open);
- ``techtrade.prune_snapshots`` -- enforces snapshot retention (daily 04:00 local).

Handlers return a core ``JobResult`` (bounded JSON-safe summary + warnings). They read
nothing sensitive and persist no credentials: a scan reads market data through the
normal OpenBB provider path and writes only derived, public trade rows. Schedules are
timezone-aware; the local zone defaults to the market's ``America/New_York`` and is
overridable with ``OPENBB_JOBS_TIMEZONE`` (or configured per-job in the durable
schedule table without a code change).
"""

from __future__ import annotations

import os
from typing import Any

from openbb_core.app.jobs.models import (
    MAX_WARNING_COUNT,
    MAX_WARNING_LENGTH,
    JobContext,
    JobDefinition,
    JobResult,
)
from openbb_core.app.jobs.schedules import DailySchedule
from pydantic import BaseModel, Field

from openbb_techtrade.engine.scan_runner import run_scan
from openbb_techtrade.snapshots.sqlite import SqliteScanSnapshotStore
from openbb_techtrade.snapshots.store import DEFAULT_RETENTION

#: Weekdays Monday-Friday (matches ``datetime.weekday()`` 0=Mon..4=Fri).
_TRADING_WEEKDAYS = (0, 1, 2, 3, 4)

#: Environment override for the schedule timezone; falls back to the market zone.
_TIMEZONE_ENV = "OPENBB_JOBS_TIMEZONE"
_DEFAULT_TIMEZONE = "America/New_York"


def _default_timezone() -> str:
    """Return the IANA timezone used for TechTrade job schedules.

    Honors ``OPENBB_JOBS_TIMEZONE`` when set, then the machine's local zone (via the
    optional ``tzlocal`` dependency), and finally the market's ``America/New_York`` --
    the sensible "local" for a pre-open US scan and matches the XNYS session the engine
    snaps against.
    """
    override = os.environ.get(_TIMEZONE_ENV)
    if override:
        return override

    try:  # pragma: no cover - depends on optional dependency availability
        from tzlocal import get_localzone_name

        local = get_localzone_name()
    except Exception:  # pragma: no cover - tzlocal missing or unresolved
        local = None
    if local:
        return local

    return _DEFAULT_TIMEZONE


def _bounded_warnings(messages: list[str]) -> list[str]:
    """Clamp warning count and per-message length to the JobResult limits."""
    return [message[:MAX_WARNING_LENGTH] for message in messages[:MAX_WARNING_COUNT]]


class DailyScanParams(BaseModel):
    """Parameters for ``techtrade.daily_scan``."""

    segments: list[str] | None = Field(
        default=None,
        description="Segments to persist; defaults to every GICS sector.",
    )
    top_n: int = Field(
        default=3, ge=1, le=50, description="Per-segment mover cap forwarded to the scan."
    )
    preset: str = Field(
        default="trend_follow", description="Confluence/rule preset for the scan."
    )
    as_of: str | None = Field(
        default=None, description="Session date (YYYY-MM-DD); defaults to today."
    )


class PruneSnapshotsParams(BaseModel):
    """Parameters for ``techtrade.prune_snapshots``."""

    keep: int = Field(
        default=DEFAULT_RETENTION,
        ge=1,
        le=1000,
        description="Snapshots retained per (kind, segment).",
    )


def _run_daily_scan(context: JobContext, params: DailyScanParams) -> JobResult:
    """Run the cross-segment scan and persist snapshots (handler)."""
    # The current worker seam does not surface a per-run cancellation flag to handlers,
    # so no ``should_cancel`` hook is wired here; ``run_scan`` still supports cooperative
    # between-segment cancellation for when that seam becomes available.
    result = run_scan(
        segments=params.segments,
        top_n=params.top_n,
        preset=params.preset,
        as_of=params.as_of,
    )
    return JobResult(
        summary=result.to_summary(),
        warnings=_bounded_warnings(result.warnings),
    )


def _run_prune_snapshots(context: JobContext, params: PruneSnapshotsParams) -> JobResult:
    """Enforce snapshot retention (handler)."""
    store = SqliteScanSnapshotStore()
    try:
        deleted = store.prune_snapshots(keep=params.keep)
    finally:
        store.close()

    summary: dict[str, Any] = {"deleted": deleted, "keep": params.keep}
    return JobResult(summary=summary, warnings=[])


def get_job_definitions() -> list[JobDefinition]:
    """Return the TechTrade job definitions for the ``openbb_job_extension`` group."""
    timezone = _default_timezone()
    return [
        JobDefinition(
            name="techtrade.daily_scan",
            description="Run the cross-segment TechTrade scan and persist widget snapshots.",
            params_model=DailyScanParams,
            handler=_run_daily_scan,
            schedule=DailySchedule(
                hour=3, minute=0, timezone=timezone, weekdays=_TRADING_WEEKDAYS
            ),
            default_params={"top_n": 3, "preset": "trend_follow"},
            max_attempts=1,
            overlap_policy="forbid",
        ),
        JobDefinition(
            name="techtrade.prune_snapshots",
            description="Prune persisted TechTrade scan snapshots to the retention limit.",
            params_model=PruneSnapshotsParams,
            handler=_run_prune_snapshots,
            schedule=DailySchedule(hour=4, minute=0, timezone=timezone),
            default_params={"keep": DEFAULT_RETENTION},
            max_attempts=1,
            overlap_policy="forbid",
        ),
    ]
