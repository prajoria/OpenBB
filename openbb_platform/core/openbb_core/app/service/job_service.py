"""Durable job service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from openbb_core.app.constants import JOBS_DB_PATH
from openbb_core.app.jobs.models import JobDefinition, JobResult, JobRun
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.schedules import DailySchedule, IntervalSchedule, ensure_utc
from openbb_core.app.jobs.sqlite_store import SqliteJobStore
from openbb_core.app.jobs.store import JobScheduleRecord, JobStore, JobStoreHealth
from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str

UTC = timezone.utc
DEFAULT_RUN_LEASE_TIMEOUT = timedelta(minutes=5)
DEFAULT_MAX_RETRY_BACKOFF_SECONDS = 3_600


def _utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


class RetryableJobError(Exception):
    """Exception type used for retryable job failures."""

    retryable = True


class JobDefinitionView(BaseModel):
    """Definition metadata exposed through the service layer."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: int = Field(ge=1)
    description: str
    schedule: DailySchedule | IntervalSchedule | None = None
    enabled: bool = False
    default_params: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(ge=1)
    retry_backoff_seconds: int = Field(ge=1)
    overlap_policy: str
    next_run_at: datetime | None = None
    last_scheduled_at: datetime | None = None


class JobHealth(JobStoreHealth):
    """Service-level queue health."""


class JobService:
    """Coordinate durable definitions, schedules, and queue state."""

    def __init__(
        self,
        *,
        store: JobStore | None = None,
        registry: JobRegistry | None = None,
        schedules_enabled: bool = True,
        run_lease_timeout: timedelta = DEFAULT_RUN_LEASE_TIMEOUT,
        max_retry_backoff_seconds: int = DEFAULT_MAX_RETRY_BACKOFF_SECONDS,
        reconcile_now: datetime | None = None,
    ) -> None:
        """Initialize the job service and reconcile known definitions."""
        self._store = store or SqliteJobStore(JOBS_DB_PATH)
        self._registry = registry or JobRegistry()
        self._schedules_enabled = schedules_enabled
        self._run_lease_timeout = run_lease_timeout
        self._max_retry_backoff_seconds = max_retry_backoff_seconds

        self._store.initialize()
        self.reconcile_definitions(now=reconcile_now)

    def reconcile_definitions(
        self, now: datetime | None = None
    ) -> list[JobScheduleRecord]:
        """Synchronize registered definitions into durable storage."""
        return self._store.reconcile_definitions(
            self._registry.definitions,
            now=self._normalize_now(now),
            schedules_enabled=self._schedules_enabled,
        )

    @property
    def registry(self) -> JobRegistry:
        """Return the registry used to resolve handlers for claimed runs."""
        return self._registry

    @property
    def run_lease_timeout(self) -> timedelta:
        """Return the worker lease timeout used to detect abandoned runs.

        A worker executing a long synchronous handler must heartbeat more
        frequently than this timeout, or its live run will be recovered and
        requeued by another worker.
        """
        return self._run_lease_timeout

    def list_definitions(self) -> list[JobDefinitionView]:
        """Return registered definitions plus their persisted schedule state."""
        persisted = {record.job_name: record for record in self._store.list_schedules()}
        views: list[JobDefinitionView] = []

        for definition in self._registry.definitions:
            record = persisted.get(definition.name)
            views.append(self._definition_view(definition, record))

        return views

    def enqueue(
        self,
        job_name: str,
        params: dict[str, object],
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> JobRun:
        """Validate and persist a manual job run."""
        definition = self._registry.get(job_name)
        normalized_now = self._normalize_now(now)
        validated = self._registry.validate_params(job_name, params)

        run = JobRun(
            run_id=uuid7str(),
            job_name=definition.name,
            handler_version=definition.version,
            source="manual",
            status="queued",
            params=validated.model_dump(mode="json"),
            available_at=normalized_now,
            attempt=1,
            max_attempts=definition.max_attempts,
            dedupe_key=idempotency_key,
            created_at=normalized_now,
            updated_at=normalized_now,
        )
        return self._store.enqueue_run(run)

    def enqueue_due(self, now: datetime | None = None) -> list[JobRun]:
        """Process all due schedule occurrences and return the queued runs created."""
        return self._store.enqueue_due_schedules(
            now=self._normalize_now(now),
            validate_params=self._validate_scheduled_params,
        )

    def recover_abandoned_runs(self, now: datetime | None = None) -> list[JobRun]:
        """Recover stale runs, failing them when recovery would exceed max_attempts."""
        return self._store.recover_abandoned_runs(
            now=self._normalize_now(now),
            lease_timeout=self._run_lease_timeout,
        )

    def get_run(self, run_id: str) -> JobRun:
        """Return a persisted run by identifier."""
        return self._store.get_run(run_id)

    def heartbeat(
        self,
        worker_id: str,
        now: datetime | None = None,
        *,
        process_id: int | None = None,
        hostname: str | None = None,
    ) -> None:
        """Refresh a worker's heartbeat so its active runs are not recovered.

        Callers executing long synchronous handlers must invoke this more
        frequently than ``run_lease_timeout`` for the duration of the
        handler, independent of when the handler itself returns.
        """
        self._store.heartbeat_worker(
            worker_id,
            now=self._normalize_now(now),
            process_id=process_id,
            hostname=hostname,
        )

    def claim_next(self, worker_id: str, now: datetime | None = None) -> JobRun | None:
        """Recover stale work and atomically claim the next runnable job."""
        normalized_now = self._normalize_now(now)
        self.recover_abandoned_runs(normalized_now)
        return self._store.claim_next(worker_id=worker_id, now=normalized_now)

    def complete(
        self,
        run_id: str,
        result: JobResult,
        finished_at: datetime | None = None,
    ) -> JobRun:
        """Mark a claimed job run as complete."""
        return self._store.complete_run(
            run_id,
            result,
            finished_at=self._normalize_now(finished_at),
        )

    def fail(
        self,
        run_id: str,
        error: Exception,
        finished_at: datetime | None = None,
    ) -> JobRun:
        """Fail a run or re-queue it for another attempt when retryable."""
        finished = self._normalize_now(finished_at)
        current = self._store.get_run(run_id)

        retry_at: datetime | None = None
        if self._is_retryable(error) and current.attempt < current.max_attempts:
            try:
                definition = self._registry.get(current.job_name)
            except KeyError:
                definition = None

            if definition is not None:
                delay_seconds = min(
                    definition.retry_backoff_seconds * (2 ** (current.attempt - 1)),
                    self._max_retry_backoff_seconds,
                )
                retry_at = finished + timedelta(seconds=delay_seconds)

        return self._store.fail_run(
            run_id,
            error,
            finished_at=finished,
            retry_at=retry_at,
        )

    def cancel(self, run_id: str, finished_at: datetime | None = None) -> JobRun:
        """Cancel a queued run."""
        return self._store.cancel_run(
            run_id,
            finished_at=self._normalize_now(finished_at),
        )

    def health(self, now: datetime | None = None) -> JobHealth:
        """Return aggregate queue, schedule, and worker health."""
        snapshot = self._store.health_snapshot(
            now=self._normalize_now(now),
            lease_timeout=self._run_lease_timeout,
        )
        return JobHealth.model_validate(snapshot.model_dump())

    def _definition_view(
        self,
        definition: JobDefinition,
        record: JobScheduleRecord | None,
    ) -> JobDefinitionView:
        """Combine the code-defined metadata with durable schedule state."""
        return JobDefinitionView(
            name=definition.name,
            version=definition.version,
            description=definition.description,
            schedule=record.schedule if record is not None else definition.schedule,
            enabled=record.enabled if record is not None else False,
            default_params=record.default_params
            if record is not None
            else definition.default_params,
            max_attempts=record.max_attempts if record is not None else definition.max_attempts,
            retry_backoff_seconds=record.retry_backoff_seconds
            if record is not None
            else definition.retry_backoff_seconds,
            overlap_policy=record.overlap_policy
            if record is not None
            else definition.overlap_policy,
            next_run_at=record.next_run_at if record is not None else None,
            last_scheduled_at=record.last_scheduled_at if record is not None else None,
        )

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        """Return whether a failure should be retried."""
        return bool(getattr(error, "retryable", False)) or isinstance(
            error, RetryableJobError
        )

    @staticmethod
    def _normalize_now(value: datetime | None) -> datetime:
        """Use the supplied UTC time or the current instant."""
        return _utc_now() if value is None else ensure_utc(value)

    def _validate_scheduled_params(
        self, job_name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Normalize scheduled parameters through the registered Pydantic model."""
        validated = self._registry.validate_params(job_name, params)
        return validated.model_dump(mode="json")
