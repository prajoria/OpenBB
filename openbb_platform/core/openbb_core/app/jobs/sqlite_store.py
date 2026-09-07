"""SQLite-backed durable job store."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import contextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from openbb_core.app.jobs.models import (
    MAX_ERROR_MESSAGE_LENGTH,
    MAX_ERROR_TYPE_LENGTH,
    JobDefinition,
    JobResult,
    JobRun,
)
from openbb_core.app.jobs.schedules import DailySchedule, IntervalSchedule, ensure_utc
from openbb_core.app.jobs.store import JobScheduleRecord, JobStoreHealth

UTC = timezone.utc
DEFAULT_BUSY_TIMEOUT_MS = 5_000


def _utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


class AbandonedRunRecoveryError(RuntimeError):
    """Raised when a stale running job cannot be re-queued safely."""


def _serialize_datetime(value: datetime | None) -> str | None:
    """Serialize a UTC datetime for SQLite persistence."""
    return None if value is None else ensure_utc(value).isoformat()


def _deserialize_datetime(value: str | None) -> datetime | None:
    """Parse a serialized UTC datetime."""
    return None if value is None else ensure_utc(datetime.fromisoformat(value))


def _serialize_json(value: dict[str, Any] | list[Any] | None) -> str | None:
    """Serialize a JSON payload in canonical form."""
    if value is None:
        return None

    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _deserialize_json(value: str | None) -> Any:
    """Parse a JSON payload if present."""
    return None if value is None else json.loads(value)


def _bounded_error_details(
    error: Exception, *, prefix: str | None = None
) -> tuple[str, str]:
    """Return bounded error details suitable for persistence."""
    error_type = type(error).__name__[:MAX_ERROR_TYPE_LENGTH]
    message = str(error).strip() or repr(error)
    if prefix:
        message = f"{prefix}: {message}"

    return error_type, message[:MAX_ERROR_MESSAGE_LENGTH]


def _serialize_schedule(
    schedule: DailySchedule | IntervalSchedule | None,
) -> tuple[str | None, str | None, str | None]:
    """Serialize a schedule into kind and JSON columns."""
    if schedule is None:
        return None, None, None

    if isinstance(schedule, DailySchedule):
        return "daily", schedule.model_dump_json(), schedule.timezone

    return "interval", schedule.model_dump_json(), "UTC"


def _deserialize_schedule(
    kind: str | None, schedule_json: str | None
) -> DailySchedule | IntervalSchedule | None:
    """Hydrate a schedule record from SQLite columns."""
    if kind is None or schedule_json is None:
        return None

    data = json.loads(schedule_json)
    if kind == "daily":
        return DailySchedule.model_validate(data)
    if kind == "interval":
        return IntervalSchedule.model_validate(data)

    raise ValueError(f"Unsupported schedule kind: {kind}")


class SqliteJobStore:
    """Single-host SQLite persistence for durable jobs."""

    def __init__(
        self,
        path: Path,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        """Initialize the SQLite store."""
        self._path = Path(path)
        self._busy_timeout_ms = busy_timeout_ms
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self._path,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._apply_pragmas()

    def initialize(self) -> None:
        """Create the durable schema if it does not already exist."""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS job_schedule (
                job_name TEXT PRIMARY KEY,
                handler_version INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                schedule_kind TEXT,
                schedule_json TEXT,
                timezone TEXT,
                default_params_json TEXT NOT NULL DEFAULT '{}',
                max_attempts INTEGER NOT NULL,
                retry_backoff_seconds INTEGER NOT NULL,
                overlap_policy TEXT NOT NULL,
                next_run_at TEXT,
                last_scheduled_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_run (
                run_id TEXT PRIMARY KEY,
                job_name TEXT NOT NULL,
                handler_version INTEGER NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                params_json TEXT NOT NULL,
                scheduled_for TEXT,
                available_at TEXT,
                attempt INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL,
                dedupe_key TEXT UNIQUE,
                worker_id TEXT,
                heartbeat_at TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                result_json TEXT,
                warnings_json TEXT,
                error_type TEXT,
                error_message TEXT,
                FOREIGN KEY (job_name) REFERENCES job_schedule(job_name)
            );

            CREATE TABLE IF NOT EXISTS job_worker (
                worker_id TEXT PRIMARY KEY,
                process_id INTEGER,
                hostname TEXT,
                started_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_job_run_runnable
                ON job_run (status, available_at, created_at);
            CREATE INDEX IF NOT EXISTS idx_job_run_job_name_status
                ON job_run (job_name, status);
            CREATE INDEX IF NOT EXISTS idx_job_schedule_next_run
                ON job_schedule (enabled, next_run_at);
            CREATE INDEX IF NOT EXISTS idx_job_worker_heartbeat
                ON job_worker (heartbeat_at);
            """
        )

    def close(self) -> None:
        """Close the SQLite connection."""
        self._connection.close()

    def reconcile_definitions(
        self,
        definitions: Iterable[JobDefinition],
        *,
        now: datetime,
        schedules_enabled: bool = True,
    ) -> list[JobScheduleRecord]:
        """Upsert durable schedule rows for the supplied definitions."""
        now_utc = ensure_utc(now, "now")

        with self._transaction(immediate=True) as connection:
            for definition in definitions:
                existing = connection.execute(
                    "SELECT * FROM job_schedule WHERE job_name = ?",
                    (definition.name,),
                ).fetchone()

                kind, schedule_json, timezone_name = _serialize_schedule(
                    definition.schedule
                )
                default_params_json = _serialize_json(definition.default_params) or "{}"
                enabled = bool(existing["enabled"]) if existing else False
                if definition.schedule is not None:
                    if existing is None:
                        enabled = schedules_enabled
                else:
                    enabled = False

                last_scheduled_at = (
                    _deserialize_datetime(existing["last_scheduled_at"])
                    if existing
                    else None
                )
                next_run_at = (
                    _deserialize_datetime(existing["next_run_at"]) if existing else None
                )
                existing_schedule = (
                    _deserialize_schedule(existing["schedule_kind"], existing["schedule_json"])
                    if existing
                    else None
                )

                if definition.schedule is None or not enabled:
                    next_run_at = None
                elif next_run_at is None or existing_schedule != definition.schedule:
                    anchor = last_scheduled_at or now_utc
                    next_run_at = definition.schedule.next_after(anchor)

                connection.execute(
                    """
                    INSERT INTO job_schedule (
                        job_name,
                        handler_version,
                        enabled,
                        schedule_kind,
                        schedule_json,
                        timezone,
                        default_params_json,
                        max_attempts,
                        retry_backoff_seconds,
                        overlap_policy,
                        next_run_at,
                        last_scheduled_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_name) DO UPDATE SET
                        handler_version = excluded.handler_version,
                        enabled = excluded.enabled,
                        schedule_kind = excluded.schedule_kind,
                        schedule_json = excluded.schedule_json,
                        timezone = excluded.timezone,
                        default_params_json = excluded.default_params_json,
                        max_attempts = excluded.max_attempts,
                        retry_backoff_seconds = excluded.retry_backoff_seconds,
                        overlap_policy = excluded.overlap_policy,
                        next_run_at = excluded.next_run_at,
                        last_scheduled_at = excluded.last_scheduled_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        definition.name,
                        definition.version,
                        int(enabled),
                        kind,
                        schedule_json,
                        timezone_name,
                        default_params_json,
                        definition.max_attempts,
                        definition.retry_backoff_seconds,
                        definition.overlap_policy,
                        _serialize_datetime(next_run_at),
                        _serialize_datetime(last_scheduled_at),
                        _serialize_datetime(now_utc),
                    ),
                )

        return self.list_schedules()

    def list_schedules(self) -> list[JobScheduleRecord]:
        """Return all persisted schedule rows."""
        rows = self._connection.execute(
            "SELECT * FROM job_schedule ORDER BY job_name"
        ).fetchall()
        return [self._row_to_schedule(row) for row in rows]

    def get_schedule(self, job_name: str) -> JobScheduleRecord:
        """Return one persisted schedule record."""
        row = self._connection.execute(
            "SELECT * FROM job_schedule WHERE job_name = ?",
            (job_name,),
        ).fetchone()
        if row is None:
            raise KeyError(job_name)

        return self._row_to_schedule(row)

    def enqueue_run(self, run: JobRun) -> JobRun:
        """Persist a queued run, returning the existing row on dedupe collisions."""
        with self._transaction(immediate=True) as connection:
            try:
                self._insert_run(connection, run)
            except sqlite3.IntegrityError:
                if run.dedupe_key is None:
                    raise
                row = connection.execute(
                    "SELECT * FROM job_run WHERE dedupe_key = ?",
                    (run.dedupe_key,),
                ).fetchone()
                if row is None:
                    raise
                return self._row_to_run(row)

        return self.get_run(run.run_id)

    def enqueue_due_schedules(
        self,
        *,
        now: datetime,
        validate_params: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> list[JobRun]:
        """Enqueue every scheduled occurrence due at or before the supplied instant."""
        now_utc = ensure_utc(now, "now")
        due_job_names = [
            row["job_name"]
            for row in self._connection.execute(
                """
                SELECT job_name
                FROM job_schedule
                WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?
                ORDER BY next_run_at, job_name
                """,
                (_serialize_datetime(now_utc),),
            ).fetchall()
        ]
        enqueued: list[JobRun] = []

        for job_name in due_job_names:
            enqueued.extend(
                self._enqueue_due_schedule(
                    job_name=job_name,
                    now=now_utc,
                    validate_params=validate_params,
                )
            )

        return enqueued

    def get_run(self, run_id: str) -> JobRun:
        """Return one persisted run."""
        row = self._connection.execute(
            "SELECT * FROM job_run WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)

        return self._row_to_run(row)

    def claim_next(self, *, worker_id: str, now: datetime) -> JobRun | None:
        """Atomically claim the next runnable job."""
        now_utc = ensure_utc(now, "now")

        with self._transaction(immediate=True) as connection:
            self._upsert_worker(connection, worker_id=worker_id, now=now_utc)

            row = connection.execute(
                """
                SELECT r.*
                FROM job_run r
                JOIN job_schedule s ON s.job_name = r.job_name
                WHERE r.status = 'queued'
                  AND COALESCE(r.available_at, r.created_at) <= ?
                  AND NOT (
                    s.overlap_policy = 'forbid'
                    AND EXISTS (
                        SELECT 1
                        FROM job_run active
                        WHERE active.job_name = r.job_name
                          AND active.status = 'running'
                          AND active.run_id <> r.run_id
                    )
                  )
                ORDER BY
                    COALESCE(r.available_at, r.created_at),
                    COALESCE(r.scheduled_for, r.created_at),
                    r.created_at,
                    r.run_id
                LIMIT 1
                """,
                (_serialize_datetime(now_utc),),
            ).fetchone()

            if row is None:
                return None

            current = self._row_to_run(row)
            running = current.mark_running(worker_id=worker_id, started_at=now_utc)
            connection.execute(
                """
                UPDATE job_run
                SET status = ?, worker_id = ?, heartbeat_at = ?, updated_at = ?, started_at = ?
                WHERE run_id = ?
                """,
                (
                    running.status,
                    worker_id,
                    _serialize_datetime(now_utc),
                    _serialize_datetime(running.updated_at),
                    _serialize_datetime(running.started_at),
                    running.run_id,
                ),
            )

        return self.get_run(running.run_id)

    def heartbeat_worker(
        self,
        worker_id: str,
        *,
        now: datetime,
        process_id: int | None = None,
        hostname: str | None = None,
    ) -> None:
        """Record a worker heartbeat."""
        now_utc = ensure_utc(now, "now")
        with self._transaction(immediate=True) as connection:
            self._upsert_worker(
                connection,
                worker_id=worker_id,
                now=now_utc,
                process_id=process_id,
                hostname=hostname,
            )

    def complete_run(
        self,
        run_id: str,
        result: JobResult,
        *,
        finished_at: datetime,
    ) -> JobRun:
        """Mark a running job as complete."""
        finished = ensure_utc(finished_at, "finished_at")
        with self._transaction(immediate=True) as connection:
            current = self._get_run_in_transaction(connection, run_id)
            completed = current.complete(result=result, finished_at=finished)
            connection.execute(
                """
                UPDATE job_run
                SET status = ?, updated_at = ?, finished_at = ?, result_json = ?,
                    warnings_json = ?, error_type = NULL, error_message = NULL,
                    heartbeat_at = ?, cancel_requested = 0
                WHERE run_id = ?
                """,
                (
                    completed.status,
                    _serialize_datetime(completed.updated_at),
                    _serialize_datetime(completed.finished_at),
                    _serialize_json(completed.result.summary if completed.result else None),
                    _serialize_json(completed.result.warnings if completed.result else []),
                    _serialize_datetime(finished),
                    run_id,
                ),
            )

        return self.get_run(run_id)

    def fail_run(
        self,
        run_id: str,
        error: Exception,
        *,
        finished_at: datetime,
        retry_at: datetime | None = None,
    ) -> JobRun:
        """Fail or retry a running job."""
        finished = ensure_utc(finished_at, "finished_at")
        with self._transaction(immediate=True) as connection:
            current = self._get_run_in_transaction(connection, run_id)
            if retry_at is not None:
                retried = current.schedule_retry(available_at=retry_at)
                connection.execute(
                    """
                    UPDATE job_run
                    SET status = ?, source = ?, attempt = ?, available_at = ?,
                        worker_id = NULL, heartbeat_at = NULL, updated_at = ?,
                        started_at = NULL, finished_at = NULL, result_json = NULL,
                        warnings_json = NULL, error_type = NULL, error_message = NULL,
                        cancel_requested = 0
                    WHERE run_id = ?
                    """,
                    (
                        retried.status,
                        retried.source,
                        retried.attempt,
                        _serialize_datetime(retried.available_at),
                        _serialize_datetime(retried.updated_at),
                        run_id,
                    ),
                )
            else:
                failed = current.fail(error=error, finished_at=finished)
                connection.execute(
                    """
                    UPDATE job_run
                    SET status = ?, updated_at = ?, finished_at = ?, error_type = ?,
                        error_message = ?, heartbeat_at = ?, cancel_requested = 0
                    WHERE run_id = ?
                    """,
                    (
                        failed.status,
                        _serialize_datetime(failed.updated_at),
                        _serialize_datetime(failed.finished_at),
                        failed.error_type,
                        failed.error_message,
                        _serialize_datetime(finished),
                        run_id,
                    ),
                )

        return self.get_run(run_id)

    def cancel_run(self, run_id: str, *, finished_at: datetime) -> JobRun:
        """Cancel a queued run."""
        finished = ensure_utc(finished_at, "finished_at")
        with self._transaction(immediate=True) as connection:
            current = self._get_run_in_transaction(connection, run_id)
            cancelled = current.cancel(finished_at=finished)
            connection.execute(
                """
                UPDATE job_run
                SET status = ?, updated_at = ?, finished_at = ?, cancel_requested = 1
                WHERE run_id = ?
                """,
                (
                    cancelled.status,
                    _serialize_datetime(cancelled.updated_at),
                    _serialize_datetime(cancelled.finished_at),
                    run_id,
                ),
            )

        return self.get_run(run_id)

    def recover_abandoned_runs(
        self,
        *,
        now: datetime,
        lease_timeout: timedelta,
    ) -> list[JobRun]:
        """Recover stale running runs or fail them when their attempt budget is spent."""
        now_utc = ensure_utc(now, "now")
        cutoff = now_utc - lease_timeout
        recovered: list[JobRun] = []

        with self._transaction(immediate=True) as connection:
            rows = connection.execute(
                """
                SELECT r.*
                FROM job_run r
                LEFT JOIN job_worker w ON w.worker_id = r.worker_id
                WHERE r.status = 'running'
                  AND (
                    r.worker_id IS NULL
                    OR w.worker_id IS NULL
                    OR w.heartbeat_at < ?
                  )
                ORDER BY r.updated_at, r.run_id
                """,
                (_serialize_datetime(cutoff),),
            ).fetchall()

            for row in rows:
                current = self._row_to_run(row)
                if current.attempt < current.max_attempts:
                    reset = current.schedule_retry(available_at=now_utc)
                    connection.execute(
                        """
                        UPDATE job_run
                        SET status = ?, source = ?, attempt = ?, available_at = ?,
                            worker_id = NULL, heartbeat_at = NULL, updated_at = ?,
                            started_at = NULL, finished_at = NULL, result_json = NULL,
                            warnings_json = NULL, error_type = NULL, error_message = NULL,
                            cancel_requested = 0
                        WHERE run_id = ?
                        """,
                        (
                            reset.status,
                            reset.source,
                            reset.attempt,
                            _serialize_datetime(reset.available_at),
                            _serialize_datetime(reset.updated_at),
                            reset.run_id,
                        ),
                    )
                    recovered.append(reset)
                    continue

                failed = current.fail(
                    error=AbandonedRunRecoveryError(
                        "Worker lease expired; abandoned-run recovery would exceed "
                        f"max_attempts={current.max_attempts}"
                    ),
                    finished_at=now_utc,
                )
                connection.execute(
                    """
                    UPDATE job_run
                    SET status = ?, updated_at = ?, finished_at = ?, error_type = ?,
                        error_message = ?, heartbeat_at = NULL, cancel_requested = 0
                    WHERE run_id = ?
                    """,
                    (
                        failed.status,
                        _serialize_datetime(failed.updated_at),
                        _serialize_datetime(failed.finished_at),
                        failed.error_type,
                        failed.error_message,
                        failed.run_id,
                    ),
                )
                recovered.append(failed)

        return recovered

    def _enqueue_due_schedule(
        self,
        *,
        job_name: str,
        now: datetime,
        validate_params: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> list[JobRun]:
        """Process one due schedule in its own transaction."""
        enqueued: list[JobRun] = []

        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM job_schedule
                WHERE job_name = ?
                  AND enabled = 1
                  AND next_run_at IS NOT NULL
                  AND next_run_at <= ?
                """,
                (job_name, _serialize_datetime(now)),
            ).fetchone()
            if row is None:
                return enqueued

            schedule_record = self._row_to_schedule(row)
            schedule = schedule_record.schedule
            if schedule is None:
                return enqueued

            next_run_at = schedule_record.next_run_at
            last_scheduled_at = schedule_record.last_scheduled_at
            while next_run_at is not None and next_run_at <= now:
                dedupe_key = f"schedule:{schedule_record.job_name}:{next_run_at.isoformat()}"
                params = schedule_record.default_params

                if validate_params is not None:
                    try:
                        params = validate_params(schedule_record.job_name, params)
                    except Exception as error:
                        self._record_invalid_scheduled_run(
                            connection,
                            schedule_record=schedule_record,
                            scheduled_for=next_run_at,
                            dedupe_key=dedupe_key,
                            error=error,
                            now=now,
                        )
                        last_scheduled_at = next_run_at
                        next_run_at = schedule.next_after(next_run_at)
                        continue

                run = JobRun(
                    run_id=self._new_run_id(),
                    job_name=schedule_record.job_name,
                    handler_version=schedule_record.handler_version,
                    source="schedule",
                    status="queued",
                    params=params,
                    scheduled_for=next_run_at,
                    available_at=next_run_at,
                    attempt=1,
                    max_attempts=schedule_record.max_attempts,
                    dedupe_key=dedupe_key,
                    created_at=now,
                    updated_at=now,
                )
                try:
                    self._insert_run(connection, run)
                    enqueued.append(run)
                except sqlite3.IntegrityError:
                    pass

                last_scheduled_at = next_run_at
                next_run_at = schedule.next_after(next_run_at)

            connection.execute(
                """
                UPDATE job_schedule
                SET next_run_at = ?, last_scheduled_at = ?, updated_at = ?
                WHERE job_name = ?
                """,
                (
                    _serialize_datetime(next_run_at),
                    _serialize_datetime(last_scheduled_at),
                    _serialize_datetime(now),
                    schedule_record.job_name,
                ),
            )

        return enqueued

    def _record_invalid_scheduled_run(
        self,
        connection: sqlite3.Connection,
        *,
        schedule_record: JobScheduleRecord,
        scheduled_for: datetime,
        dedupe_key: str,
        error: Exception,
        now: datetime,
    ) -> None:
        """Persist invalid scheduled configuration as a failed run."""
        error_type, error_message = _bounded_error_details(
            error,
            prefix=f"Invalid scheduled configuration for {schedule_record.job_name}",
        )
        failed_run = JobRun(
            run_id=self._new_run_id(),
            job_name=schedule_record.job_name,
            handler_version=schedule_record.handler_version,
            source="schedule",
            status="failed",
            params=schedule_record.default_params,
            scheduled_for=scheduled_for,
            available_at=scheduled_for,
            attempt=1,
            max_attempts=schedule_record.max_attempts,
            dedupe_key=dedupe_key,
            created_at=now,
            updated_at=now,
            finished_at=now,
            error_type=error_type,
            error_message=error_message,
        )
        with suppress(sqlite3.IntegrityError):
            self._insert_run(connection, failed_run)

    def health_snapshot(
        self,
        *,
        now: datetime | None = None,
        lease_timeout: timedelta | None = None,
    ) -> JobStoreHealth:
        """Return aggregate queue and worker counts."""
        lease = lease_timeout or timedelta(minutes=5)
        now_utc = _utc_now() if now is None else ensure_utc(now, "now")
        cutoff = now_utc - lease

        definition_count = self._count("SELECT COUNT(*) FROM job_schedule")
        total_runs = self._count("SELECT COUNT(*) FROM job_run")
        queued_runs = self._count(
            "SELECT COUNT(*) FROM job_run WHERE status = 'queued'"
        )
        running_runs = self._count(
            "SELECT COUNT(*) FROM job_run WHERE status = 'running'"
        )
        succeeded_runs = self._count(
            "SELECT COUNT(*) FROM job_run WHERE status = 'succeeded'"
        )
        warning_runs = self._count(
            "SELECT COUNT(*) FROM job_run WHERE status = 'succeeded_with_warnings'"
        )
        failed_runs = self._count(
            "SELECT COUNT(*) FROM job_run WHERE status = 'failed'"
        )
        cancelled_runs = self._count(
            "SELECT COUNT(*) FROM job_run WHERE status = 'cancelled'"
        )
        active_workers = self._count(
            "SELECT COUNT(*) FROM job_worker WHERE heartbeat_at >= ?",
            (_serialize_datetime(cutoff),),
        )
        stale_runs = self._count(
            """
            SELECT COUNT(*)
            FROM job_run r
            LEFT JOIN job_worker w ON w.worker_id = r.worker_id
            WHERE r.status = 'running'
              AND (
                r.worker_id IS NULL
                OR w.worker_id IS NULL
                OR w.heartbeat_at < ?
              )
            """,
            (_serialize_datetime(cutoff),),
        )
        due_runs = self._count(
            """
            SELECT COUNT(*)
            FROM job_run
            WHERE status = 'queued' AND COALESCE(available_at, created_at) <= ?
            """,
            (_serialize_datetime(now_utc),),
        )
        latest_heartbeat_row = self._connection.execute(
            "SELECT MAX(heartbeat_at) FROM job_worker"
        ).fetchone()
        latest_heartbeat = _deserialize_datetime(latest_heartbeat_row[0])
        worker_heartbeat_age_seconds = (
            None
            if latest_heartbeat is None
            else max(0.0, (now_utc - latest_heartbeat).total_seconds())
        )
        last_successful_run_by_job = {
            row["job_name"]: _deserialize_datetime(row["last_successful_run_at"])
            for row in self._connection.execute(
                """
                SELECT
                    schedule.job_name,
                    MAX(run.finished_at) AS last_successful_run_at
                FROM job_schedule AS schedule
                LEFT JOIN job_run AS run
                  ON run.job_name = schedule.job_name
                 AND run.status IN ('succeeded', 'succeeded_with_warnings')
                GROUP BY schedule.job_name
                ORDER BY schedule.job_name
                """
            ).fetchall()
        }

        return JobStoreHealth(
            definition_count=definition_count,
            total_runs=total_runs,
            queued_runs=queued_runs,
            running_runs=running_runs,
            succeeded_runs=succeeded_runs,
            warning_runs=warning_runs,
            failed_runs=failed_runs,
            cancelled_runs=cancelled_runs,
            active_workers=active_workers,
            stale_runs=stale_runs,
            due_runs=due_runs,
            queue_depth=queued_runs,
            worker_heartbeat_age_seconds=worker_heartbeat_age_seconds,
            last_successful_run_by_job=last_successful_run_by_job,
        )

    def _apply_pragmas(self) -> None:
        """Configure SQLite for multi-process durability."""
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        self._connection.execute("PRAGMA synchronous = NORMAL")

    @contextmanager
    def _transaction(self, *, immediate: bool = False):
        """Run a short explicit transaction."""
        self._connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield self._connection
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")

    def _row_to_schedule(self, row: sqlite3.Row) -> JobScheduleRecord:
        """Convert a SQLite row into a schedule record."""
        return JobScheduleRecord(
            job_name=row["job_name"],
            handler_version=row["handler_version"],
            enabled=bool(row["enabled"]),
            schedule=_deserialize_schedule(row["schedule_kind"], row["schedule_json"]),
            default_params=_deserialize_json(row["default_params_json"]) or {},
            max_attempts=row["max_attempts"],
            retry_backoff_seconds=row["retry_backoff_seconds"],
            overlap_policy=row["overlap_policy"],
            next_run_at=_deserialize_datetime(row["next_run_at"]),
            last_scheduled_at=_deserialize_datetime(row["last_scheduled_at"]),
            updated_at=_deserialize_datetime(row["updated_at"]) or _utc_now(),
        )

    def _row_to_run(self, row: sqlite3.Row) -> JobRun:
        """Convert a SQLite row into a persisted run model."""
        summary = _deserialize_json(row["result_json"])
        warnings = _deserialize_json(row["warnings_json"]) or []
        result = (
            JobResult(summary=summary or {}, warnings=warnings)
            if summary is not None or warnings
            else None
        )
        return JobRun(
            run_id=row["run_id"],
            job_name=row["job_name"],
            handler_version=row["handler_version"],
            source=row["source"],
            status=row["status"],
            params=_deserialize_json(row["params_json"]) or {},
            scheduled_for=_deserialize_datetime(row["scheduled_for"]),
            available_at=_deserialize_datetime(row["available_at"]),
            attempt=row["attempt"],
            max_attempts=row["max_attempts"],
            dedupe_key=row["dedupe_key"],
            worker_id=row["worker_id"],
            created_at=_deserialize_datetime(row["created_at"]) or _utc_now(),
            updated_at=_deserialize_datetime(row["updated_at"]) or _utc_now(),
            started_at=_deserialize_datetime(row["started_at"]),
            finished_at=_deserialize_datetime(row["finished_at"]),
            result=result,
            error_type=row["error_type"],
            error_message=row["error_message"],
        )

    def _insert_run(self, connection: sqlite3.Connection, run: JobRun) -> None:
        """Insert a run row into the database."""
        connection.execute(
            """
            INSERT INTO job_run (
                run_id,
                job_name,
                handler_version,
                source,
                status,
                params_json,
                scheduled_for,
                available_at,
                attempt,
                max_attempts,
                dedupe_key,
                worker_id,
                heartbeat_at,
                cancel_requested,
                created_at,
                updated_at,
                started_at,
                finished_at,
                result_json,
                warnings_json,
                error_type,
                error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.job_name,
                run.handler_version,
                run.source,
                run.status,
                _serialize_json(run.params),
                _serialize_datetime(run.scheduled_for),
                _serialize_datetime(run.available_at),
                run.attempt,
                run.max_attempts,
                run.dedupe_key,
                run.worker_id,
                None,
                0,
                _serialize_datetime(run.created_at),
                _serialize_datetime(run.updated_at),
                _serialize_datetime(run.started_at),
                _serialize_datetime(run.finished_at),
                _serialize_json(run.result.summary if run.result else None),
                _serialize_json(run.result.warnings if run.result else []),
                run.error_type,
                run.error_message,
            ),
        )

    def _get_run_in_transaction(
        self, connection: sqlite3.Connection, run_id: str
    ) -> JobRun:
        """Load one run while holding a transaction."""
        row = connection.execute(
            "SELECT * FROM job_run WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)

        return self._row_to_run(row)

    def _upsert_worker(
        self,
        connection: sqlite3.Connection,
        *,
        worker_id: str,
        now: datetime,
        process_id: int | None = None,
        hostname: str | None = None,
    ) -> None:
        """Insert or refresh a worker row."""
        hostname_value = hostname or socket.gethostname()
        process_id_value = process_id if process_id is not None else os.getpid()
        connection.execute(
            """
            INSERT INTO job_worker (
                worker_id, process_id, hostname, started_at, heartbeat_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(worker_id) DO UPDATE SET
                process_id = excluded.process_id,
                hostname = excluded.hostname,
                heartbeat_at = excluded.heartbeat_at
            """,
            (
                worker_id,
                process_id_value,
                hostname_value,
                _serialize_datetime(now),
                _serialize_datetime(now),
            ),
        )

    def _count(self, query: str, params: tuple[Any, ...] = ()) -> int:
        """Execute a scalar count query."""
        return int(self._connection.execute(query, params).fetchone()[0])

    def _new_run_id(self) -> str:
        """Generate a monotonically increasing-style run identifier."""
        return f"run-{int(_utc_now().timestamp() * 1_000_000)}-{os.urandom(4).hex()}"
