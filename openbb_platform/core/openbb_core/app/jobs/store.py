"""Job store contracts and persisted schedule models."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any, Protocol

from openbb_core.app.jobs.models import JobDefinition, JobResult, JobRun
from openbb_core.app.jobs.schedules import DailySchedule, IntervalSchedule, ensure_utc
from pydantic import BaseModel, ConfigDict, Field, field_validator

JobSchedule = DailySchedule | IntervalSchedule | None


def _validate_json_dict(value: dict[str, Any], field_name: str) -> dict[str, Any]:
    """Require a JSON-serializable dictionary payload."""
    try:
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be JSON-serializable") from error

    return value


class JobScheduleRecord(BaseModel):
    """Persisted scheduling metadata for a registered job definition."""

    model_config = ConfigDict(frozen=True)

    job_name: str
    handler_version: int = Field(ge=1)
    enabled: bool = False
    schedule: JobSchedule = None
    default_params: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(ge=1)
    retry_backoff_seconds: int = Field(ge=1)
    overlap_policy: str
    next_run_at: datetime | None = None
    last_scheduled_at: datetime | None = None
    updated_at: datetime

    @field_validator("default_params")
    @classmethod
    def validate_default_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Require JSON-safe default parameters."""
        return _validate_json_dict(value, "default_params")

    @field_validator("next_run_at", "last_scheduled_at", "updated_at")
    @classmethod
    def validate_datetimes(cls, value: datetime | None) -> datetime | None:
        """Normalize optional datetimes to UTC."""
        return None if value is None else ensure_utc(value)


class JobStoreHealth(BaseModel):
    """Queue and worker health snapshot."""

    model_config = ConfigDict(frozen=True)

    definition_count: int = 0
    total_runs: int = 0
    queued_runs: int = 0
    running_runs: int = 0
    succeeded_runs: int = 0
    warning_runs: int = 0
    failed_runs: int = 0
    cancelled_runs: int = 0
    active_workers: int = 0
    stale_runs: int = 0
    due_runs: int = 0


class JobStore(Protocol):
    """Persistence contract for durable job scheduling and run state."""

    def initialize(self) -> None:
        """Create or migrate the underlying schema."""

    def close(self) -> None:
        """Close any open resources held by the store."""

    def reconcile_definitions(
        self,
        definitions: Iterable[JobDefinition],
        *,
        now: datetime,
        schedules_enabled: bool = True,
    ) -> list[JobScheduleRecord]:
        """Insert or update durable schedule rows for registered definitions."""

    def list_schedules(self) -> list[JobScheduleRecord]:
        """Return all persisted schedule records."""

    def get_schedule(self, job_name: str) -> JobScheduleRecord:
        """Return the persisted schedule record for one job."""

    def enqueue_run(self, run: JobRun) -> JobRun:
        """Persist a queued run, honoring dedupe keys."""

    def enqueue_due_schedules(
        self,
        *,
        now: datetime,
        validate_params: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> list[JobRun]:
        """Process all due schedule occurrences, returning the queued runs created."""

    def get_run(self, run_id: str) -> JobRun:
        """Return a persisted run by identifier."""

    def claim_next(self, *, worker_id: str, now: datetime) -> JobRun | None:
        """Atomically claim the next runnable job for a worker."""

    def heartbeat_worker(
        self,
        worker_id: str,
        *,
        now: datetime,
        process_id: int | None = None,
        hostname: str | None = None,
    ) -> None:
        """Record or refresh a worker heartbeat."""

    def complete_run(
        self,
        run_id: str,
        result: JobResult,
        *,
        finished_at: datetime,
    ) -> JobRun:
        """Mark a running job as complete."""

    def fail_run(
        self,
        run_id: str,
        error: Exception,
        *,
        finished_at: datetime,
        retry_at: datetime | None = None,
    ) -> JobRun:
        """Fail a running job or re-queue it for retry."""

    def cancel_run(self, run_id: str, *, finished_at: datetime) -> JobRun:
        """Cancel a queued job."""

    def recover_abandoned_runs(
        self,
        *,
        now: datetime,
        lease_timeout: timedelta,
    ) -> list[JobRun]:
        """Recover stale runs or fail them when retry attempts are exhausted."""

    def health_snapshot(
        self,
        *,
        now: datetime | None = None,
        lease_timeout: timedelta | None = None,
    ) -> JobStoreHealth:
        """Return a queue and worker health snapshot."""
