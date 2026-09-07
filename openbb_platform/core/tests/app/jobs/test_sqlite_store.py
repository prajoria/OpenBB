"""Tests for the durable SQLite job store."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

from openbb_core.app.jobs.models import JobContext, JobDefinition, JobResult, JobRun
from openbb_core.app.jobs.schedules import IntervalSchedule
from openbb_core.app.jobs.sqlite_store import SqliteJobStore
from openbb_core.app.jobs.store import JobScheduleRecord

UTC = timezone.utc


class ExampleParams(BaseModel):
    """Example parameter model."""

    symbol: str = "SPY"


def example_handler(context: JobContext, params: ExampleParams) -> JobResult:
    """Return a structured result."""
    return JobResult(summary={"job": context.job_name, "symbol": params.symbol})


def make_definition(
    *,
    name: str = "example.job",
    schedule: IntervalSchedule | None = None,
    default_params: dict[str, object] | None = None,
    overlap_policy: str = "forbid",
    max_attempts: int = 3,
    retry_backoff_seconds: int = 30,
) -> JobDefinition:
    """Create an example job definition."""
    return JobDefinition(
        name=name,
        description=f"Definition for {name}",
        params_model=ExampleParams,
        handler=example_handler,
        schedule=schedule,
        default_params=default_params or {},
        overlap_policy=overlap_policy,  # type: ignore[arg-type]
        max_attempts=max_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
    )


def make_store(path: Path) -> SqliteJobStore:
    """Create and initialize a store for a test database."""
    store = SqliteJobStore(path)
    store.initialize()
    return store


def make_run(
    *,
    run_id: str = "run-1",
    job_name: str = "example.job",
    source: str = "manual",
    status: str = "queued",
    attempt: int = 1,
    max_attempts: int = 3,
    dedupe_key: str | None = None,
    scheduled_for: datetime | None = None,
    available_at: datetime | None = None,
) -> JobRun:
    """Create a queueable job run."""
    timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    return JobRun(
        run_id=run_id,
        job_name=job_name,
        source=source,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        params={"symbol": "SPY"},
        attempt=attempt,
        max_attempts=max_attempts,
        dedupe_key=dedupe_key,
        scheduled_for=scheduled_for,
        available_at=available_at or scheduled_for or timestamp,
        created_at=timestamp,
        updated_at=timestamp,
    )


def test_initialize_is_idempotent_and_uses_wal(tmp_path: Path):
    """Schema creation is idempotent and enables WAL mode."""
    database_path = tmp_path / "jobs.db"
    store = SqliteJobStore(database_path)

    store.initialize()
    store.initialize()
    busy_timeout = store._connection.execute("PRAGMA busy_timeout").fetchone()[0]  # pylint: disable=protected-access
    store.close()

    with sqlite3.connect(database_path) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert journal_mode.lower() == "wal"
    assert {"job_schedule", "job_run", "job_worker"} <= tables
    assert busy_timeout == 5_000


def test_store_persists_reconciled_state_across_reopen(tmp_path: Path):
    """Schedules and runs survive closing and reopening the database."""
    database_path = tmp_path / "jobs.db"
    schedule = IntervalSchedule(
        every_seconds=300,
        start_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    definition = make_definition(
        schedule=schedule,
        default_params={"symbol": "QQQ"},
    )

    store = make_store(database_path)
    store.reconcile_definitions(
        [definition],
        now=datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    )
    expected_run = store.enqueue_run(make_run(run_id="persisted-run"))
    store.close()

    reopened = make_store(database_path)
    schedules = reopened.list_schedules()
    actual_run = reopened.get_run(expected_run.run_id)

    assert schedules == [
        JobScheduleRecord(
            job_name="example.job",
            handler_version=1,
            enabled=True,
            schedule=schedule,
            default_params={"symbol": "QQQ"},
            max_attempts=3,
            retry_backoff_seconds=30,
            overlap_policy="forbid",
            next_run_at=datetime(2026, 1, 1, 12, 5, tzinfo=UTC),
            last_scheduled_at=None,
            updated_at=schedules[0].updated_at,
        )
    ]
    assert actual_run == expected_run


def test_enqueue_run_uses_manual_idempotency_keys(tmp_path: Path):
    """Manual dedupe keys return the existing run instead of creating another."""
    store = make_store(tmp_path / "jobs.db")
    store.reconcile_definitions([make_definition()], now=datetime(2026, 1, 1, tzinfo=UTC))

    first = store.enqueue_run(make_run(run_id="run-1", dedupe_key="manual:1"))
    second = store.enqueue_run(make_run(run_id="run-2", dedupe_key="manual:1"))

    assert first.run_id == second.run_id == "run-1"
    assert store.health_snapshot().total_runs == 1


def test_schedule_occurrences_are_deduplicated(tmp_path: Path):
    """The same scheduled instant is only enqueued once."""
    store = make_store(tmp_path / "jobs.db")
    schedule = IntervalSchedule(
        every_seconds=300,
        start_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    store.reconcile_definitions(
        [make_definition(schedule=schedule)],
        now=datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    )

    first = store.enqueue_due_schedules(now=datetime(2026, 1, 1, 12, 5, tzinfo=UTC))
    second = store.enqueue_due_schedules(now=datetime(2026, 1, 1, 12, 5, tzinfo=UTC))

    assert [run.dedupe_key for run in first] == [
        "schedule:example.job:2026-01-01T12:05:00+00:00"
    ]
    assert second == []
    assert store.health_snapshot().queued_runs == 1


def test_claim_next_is_atomic_for_competing_workers(tmp_path: Path):
    """Only one worker can claim a queued run."""
    database_path = tmp_path / "jobs.db"
    writer = make_store(database_path)
    writer.reconcile_definitions([make_definition()], now=datetime(2026, 1, 1, tzinfo=UTC))
    writer.enqueue_run(make_run())
    now = datetime(2026, 1, 1, 12, 5, tzinfo=UTC)
    barrier = threading.Barrier(3)

    def claim(worker_id: str) -> JobRun | None:
        store = make_store(database_path)
        try:
            barrier.wait(timeout=5)
            return store.claim_next(worker_id=worker_id, now=now)
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(claim, "worker-1"),
            executor.submit(claim, "worker-2"),
        ]
        barrier.wait(timeout=5)
        claims = [future.result(timeout=5) for future in futures]

    successful_claims = [claim for claim in claims if claim is not None]

    assert len(successful_claims) == 1
    claimed = successful_claims[0]
    assert claimed.status == "running"
    assert claimed.worker_id in {"worker-1", "worker-2"}
    assert writer.get_run("run-1").worker_id == claimed.worker_id


def test_claim_next_prevents_overlapping_forbidden_runs(tmp_path: Path):
    """A second run waits while another forbid-overlap run is active."""
    store = make_store(tmp_path / "jobs.db")
    store.reconcile_definitions([make_definition()], now=datetime(2026, 1, 1, tzinfo=UTC))
    store.enqueue_run(make_run(run_id="run-1"))
    store.enqueue_run(make_run(run_id="run-2"))

    first = store.claim_next(
        worker_id="worker-1",
        now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    blocked = store.claim_next(
        worker_id="worker-2",
        now=datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    )

    assert first is not None
    assert blocked is None

    store.complete_run(
        first.run_id,
        JobResult(summary={"ok": True}),
        finished_at=datetime(2026, 1, 1, 12, 2, tzinfo=UTC),
    )

    second = store.claim_next(
        worker_id="worker-2",
        now=datetime(2026, 1, 1, 12, 3, tzinfo=UTC),
    )

    assert second is not None
    assert second.run_id == "run-2"


def test_fail_run_requeues_retries_with_backoff(tmp_path: Path):
    """Retryable failures are re-queued for another attempt."""
    store = make_store(tmp_path / "jobs.db")
    store.reconcile_definitions([make_definition()], now=datetime(2026, 1, 1, tzinfo=UTC))
    store.enqueue_run(make_run())
    claimed = store.claim_next(
        worker_id="worker-1",
        now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert claimed is not None

    retried = store.fail_run(
        claimed.run_id,
        RuntimeError("retry later"),
        finished_at=datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
        retry_at=datetime(2026, 1, 1, 12, 1, 30, tzinfo=UTC),
    )

    assert retried.status == "queued"
    assert retried.source == "retry"
    assert retried.attempt == 2
    assert retried.available_at == datetime(2026, 1, 1, 12, 1, 30, tzinfo=UTC)
    assert retried.error_type is None


def test_cancel_run_marks_a_queued_run_cancelled(tmp_path: Path):
    """Queued runs can be cancelled before a worker claims them."""
    store = make_store(tmp_path / "jobs.db")
    store.reconcile_definitions([make_definition()], now=datetime(2026, 1, 1, tzinfo=UTC))
    store.enqueue_run(make_run())

    cancelled = store.cancel_run(
        "run-1",
        finished_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert cancelled.status == "cancelled"
    assert (
        store.claim_next(
            worker_id="worker-1",
            now=datetime(2026, 1, 1, 12, 11, tzinfo=UTC),
        )
        is None
    )


def test_recover_abandoned_running_runs(tmp_path: Path):
    """Stale running runs are re-queued as the next retry attempt."""
    store = make_store(tmp_path / "jobs.db")
    store.reconcile_definitions([make_definition()], now=datetime(2026, 1, 1, tzinfo=UTC))
    store.enqueue_run(make_run())
    claimed = store.claim_next(
        worker_id="worker-1",
        now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert claimed is not None

    recovered = store.recover_abandoned_runs(
        now=datetime(2026, 1, 1, 12, 6, tzinfo=UTC),
        lease_timeout=timedelta(minutes=5),
    )

    assert [run.run_id for run in recovered] == [claimed.run_id]
    assert recovered[0].status == "queued"
    assert recovered[0].source == "retry"
    assert recovered[0].attempt == 2
    assert recovered[0].worker_id is None

    reclaimed = store.claim_next(
        worker_id="worker-2",
        now=datetime(2026, 1, 1, 12, 7, tzinfo=UTC),
    )
    assert reclaimed is not None
    assert reclaimed.run_id == claimed.run_id
    assert reclaimed.attempt == 2


def test_recover_abandoned_run_fails_when_attempt_budget_is_exhausted(tmp_path: Path):
    """Abandoned runs fail terminally when recovery would exceed max_attempts."""
    store = make_store(tmp_path / "jobs.db")
    store.reconcile_definitions(
        [make_definition(max_attempts=1)],
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store.enqueue_run(make_run(max_attempts=1))
    claimed = store.claim_next(
        worker_id="worker-1",
        now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert claimed is not None

    recovered = store.recover_abandoned_runs(
        now=datetime(2026, 1, 1, 12, 6, tzinfo=UTC),
        lease_timeout=timedelta(minutes=5),
    )

    assert [run.run_id for run in recovered] == [claimed.run_id]
    assert recovered[0].status == "failed"
    assert recovered[0].attempt == 1
    assert recovered[0].error_type == "AbandonedRunRecoveryError"
    assert "abandoned-run recovery would exceed max_attempts=1" in (
        recovered[0].error_message or ""
    )
    assert store.get_run(claimed.run_id).status == "failed"
    assert (
        store.claim_next(
            worker_id="worker-2",
            now=datetime(2026, 1, 1, 12, 7, tzinfo=UTC),
        )
        is None
    )


def test_recover_skips_live_run_when_worker_heartbeat_is_fresh(tmp_path: Path):
    """Fresh worker heartbeats prevent recovery even after the run lease age passes."""
    store = make_store(tmp_path / "jobs.db")
    store.reconcile_definitions([make_definition()], now=datetime(2026, 1, 1, tzinfo=UTC))
    store.enqueue_run(make_run())
    claimed = store.claim_next(
        worker_id="worker-1",
        now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert claimed is not None

    store.heartbeat_worker(
        "worker-1",
        now=datetime(2026, 1, 1, 12, 4, tzinfo=UTC),
    )
    recovered = store.recover_abandoned_runs(
        now=datetime(2026, 1, 1, 12, 6, tzinfo=UTC),
        lease_timeout=timedelta(minutes=5),
    )

    assert recovered == []
    assert store.get_run(claimed.run_id).status == "running"


def test_reconcile_definitions_updates_default_params(tmp_path: Path):
    """Reconcile overwrites persisted default params with the latest definition values."""
    store = make_store(tmp_path / "jobs.db")

    store.reconcile_definitions(
        [make_definition(default_params={"symbol": "SPY"})],
        now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    store.reconcile_definitions(
        [make_definition(default_params={"symbol": "MSFT"})],
        now=datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    )

    assert store.get_schedule("example.job").default_params == {"symbol": "MSFT"}
