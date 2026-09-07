"""Tests for the job service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from openbb_core.app.jobs.models import JobContext, JobDefinition, JobResult
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.schedules import IntervalSchedule
from openbb_core.app.jobs.sqlite_store import SqliteJobStore
from openbb_core.app.service.job_service import JobService, RetryableJobError

UTC = timezone.utc
BASE_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class ScanParams(BaseModel):
    """Example scan parameters."""

    symbol: str
    limit: int = 10


class WarmParams(BaseModel):
    """Example warming parameters."""

    dry_run: bool = False


def scan_handler(context: JobContext, params: ScanParams) -> JobResult:
    """Return a structured scan result."""
    return JobResult(summary={"job": context.job_name, "symbol": params.symbol})


def warm_handler(context: JobContext, params: WarmParams) -> JobResult:
    """Return a structured warm result."""
    return JobResult(summary={"job": context.job_name, "dry_run": params.dry_run})


@pytest.fixture
def service(tmp_path: Path) -> JobService:
    """Build a job service with a durable SQLite backend."""
    store = SqliteJobStore(tmp_path / "jobs.db")
    registry = JobRegistry(
        [
            JobDefinition(
                name="techtrade.daily_scan",
                description="Daily scan",
                params_model=ScanParams,
                handler=scan_handler,
                schedule=IntervalSchedule(
                    every_seconds=300,
                    start_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                ),
                default_params={"symbol": "MSFT"},
                max_attempts=3,
                retry_backoff_seconds=30,
            ),
            JobDefinition(
                name="portfolio.position_history",
                description="Warm positions",
                params_model=WarmParams,
                handler=warm_handler,
                max_attempts=1,
            ),
        ]
    )
    return JobService(store=store, registry=registry, reconcile_now=BASE_TIME)


def test_service_reconciles_definitions_on_startup(service: JobService):
    """Registered definitions are reflected in the durable schedule store."""
    definitions = service.list_definitions()

    assert [definition.name for definition in definitions] == [
        "portfolio.position_history",
        "techtrade.daily_scan",
    ]
    assert definitions[0].enabled is False
    assert definitions[1].enabled is True
    assert definitions[1].default_params == {"symbol": "MSFT"}
    assert definitions[1].next_run_at == datetime(2026, 1, 1, 12, 5, tzinfo=UTC)


def test_enqueue_validates_params_and_manual_idempotency(service: JobService):
    """Manual queue requests are typed and idempotent."""
    first = service.enqueue(
        "techtrade.daily_scan",
        {"symbol": "AAPL", "limit": "5"},
        idempotency_key="trigger:1",
        now=BASE_TIME,
    )
    second = service.enqueue(
        "techtrade.daily_scan",
        {"symbol": "AAPL", "limit": 5},
        idempotency_key="trigger:1",
        now=BASE_TIME,
    )

    assert first.run_id == second.run_id
    assert first.params == {"symbol": "AAPL", "limit": 5}


def test_enqueue_rejects_invalid_params(service: JobService):
    """Invalid parameters fail fast through the registry model."""
    with pytest.raises(ValidationError, match="symbol"):
        service.enqueue("techtrade.daily_scan", {"limit": 5})


def test_enqueue_due_advances_schedule_without_duplicates(service: JobService):
    """Due schedules enqueue once and advance to the next instant."""
    first = service.enqueue_due(now=datetime(2026, 1, 1, 12, 5, tzinfo=UTC))
    second = service.enqueue_due(now=datetime(2026, 1, 1, 12, 5, tzinfo=UTC))
    definitions = service.list_definitions()

    assert len(first) == 1
    assert first[0].source == "schedule"
    assert first[0].params == {"symbol": "MSFT", "limit": 10}
    assert first[0].scheduled_for == datetime(2026, 1, 1, 12, 5, tzinfo=UTC)
    assert second == []
    assert definitions[1].last_scheduled_at == datetime(2026, 1, 1, 12, 5, tzinfo=UTC)
    assert definitions[1].next_run_at == datetime(2026, 1, 1, 12, 10, tzinfo=UTC)


def test_enqueue_due_records_invalid_scheduled_params_as_failed_run(tmp_path: Path):
    """Invalid scheduled params are persisted as failed runs instead of raising."""
    store = SqliteJobStore(tmp_path / "jobs.db")
    registry = JobRegistry(
        [
            JobDefinition(
                name="techtrade.daily_scan",
                description="Daily scan",
                params_model=ScanParams,
                handler=scan_handler,
                schedule=IntervalSchedule(
                    every_seconds=300,
                    start_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                ),
            )
        ]
    )
    service = JobService(store=store, registry=registry, reconcile_now=BASE_TIME)

    queued = service.enqueue_due(now=datetime(2026, 1, 1, 12, 5, tzinfo=UTC))
    definitions = service.list_definitions()
    failed_row = store._connection.execute(  # pylint: disable=protected-access
        "SELECT status, error_type, error_message FROM job_run"
    ).fetchone()

    assert queued == []
    assert failed_row is not None
    assert failed_row["status"] == "failed"
    assert failed_row["error_type"] == "ValidationError"
    assert "Invalid scheduled configuration for techtrade.daily_scan" in (
        failed_row["error_message"] or ""
    )
    assert "symbol" in (failed_row["error_message"] or "")
    assert service.health(now=datetime(2026, 1, 1, 12, 5, tzinfo=UTC)).failed_runs == 1
    assert definitions[0].last_scheduled_at == datetime(2026, 1, 1, 12, 5, tzinfo=UTC)
    assert definitions[0].next_run_at == datetime(2026, 1, 1, 12, 10, tzinfo=UTC)


def test_enqueue_due_keeps_valid_schedules_when_another_due_schedule_is_invalid(
    tmp_path: Path,
):
    """One invalid due schedule does not roll back another valid scheduled run."""
    store = SqliteJobStore(tmp_path / "jobs.db")
    registry = JobRegistry(
        [
            JobDefinition(
                name="broken.daily_scan",
                description="Broken scan",
                params_model=ScanParams,
                handler=scan_handler,
                schedule=IntervalSchedule(
                    every_seconds=300,
                    start_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                ),
            ),
            JobDefinition(
                name="valid.daily_scan",
                description="Valid scan",
                params_model=ScanParams,
                handler=scan_handler,
                schedule=IntervalSchedule(
                    every_seconds=300,
                    start_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                ),
                default_params={"symbol": "MSFT"},
            ),
        ]
    )
    service = JobService(store=store, registry=registry, reconcile_now=BASE_TIME)

    queued = service.enqueue_due(now=datetime(2026, 1, 1, 12, 5, tzinfo=UTC))
    health = service.health(now=datetime(2026, 1, 1, 12, 5, tzinfo=UTC))
    rows = store._connection.execute(  # pylint: disable=protected-access
        """
        SELECT job_name, status, error_type, error_message
        FROM job_run
        ORDER BY job_name
        """
    ).fetchall()

    assert len(queued) == 1
    assert queued[0].job_name == "valid.daily_scan"
    assert queued[0].status == "queued"
    assert queued[0].params == {"symbol": "MSFT", "limit": 10}
    assert health.total_runs == 2
    assert health.queued_runs == 1
    assert health.failed_runs == 1
    assert [(row["job_name"], row["status"]) for row in rows] == [
        ("broken.daily_scan", "failed"),
        ("valid.daily_scan", "queued"),
    ]
    assert rows[0]["error_type"] == "ValidationError"
    assert "Invalid scheduled configuration for broken.daily_scan" in (
        rows[0]["error_message"] or ""
    )


def test_service_claims_and_completes_runs(service: JobService):
    """Workers can claim queued runs and complete them."""
    queued = service.enqueue("portfolio.position_history", {"dry_run": True}, now=BASE_TIME)

    claimed = service.claim_next(
        worker_id="worker-1",
        now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert claimed is not None
    assert claimed.run_id == queued.run_id

    completed = service.complete(
        claimed.run_id,
        JobResult(summary={"warmed": 12}),
        finished_at=datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    )

    assert completed.status == "succeeded"
    assert completed.result == JobResult(summary={"warmed": 12})


def test_service_fail_retries_retryable_errors(service: JobService):
    """Retryable failures are requeued with exponential backoff."""
    queued = service.enqueue("techtrade.daily_scan", {"symbol": "AAPL"}, now=BASE_TIME)
    claimed = service.claim_next(
        worker_id="worker-1",
        now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert claimed is not None
    assert claimed.run_id == queued.run_id

    retried = service.fail(
        claimed.run_id,
        RetryableJobError("upstream timeout"),
        finished_at=datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    )

    assert retried.status == "queued"
    assert retried.source == "retry"
    assert retried.attempt == 2
    assert retried.available_at == datetime(2026, 1, 1, 12, 1, 30, tzinfo=UTC)


def test_service_fail_marks_terminal_failures(service: JobService):
    """Non-retryable failures finish the run as failed."""
    service.enqueue("portfolio.position_history", {"dry_run": False}, now=BASE_TIME)
    claimed = service.claim_next(
        worker_id="worker-1",
        now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert claimed is not None

    failed = service.fail(
        claimed.run_id,
        RuntimeError("bad config"),
        finished_at=datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    )

    assert failed.status == "failed"
    assert failed.error_type == "RuntimeError"
    assert failed.error_message == "bad config"


def test_service_cancels_queued_runs(service: JobService):
    """Queued runs can be cancelled before claim."""
    queued = service.enqueue("portfolio.position_history", {"dry_run": True}, now=BASE_TIME)

    cancelled = service.cancel(
        queued.run_id,
        finished_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert cancelled.status == "cancelled"
    assert (
        service.claim_next(
            worker_id="worker-1",
            now=datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
        )
        is None
    )


def test_service_health_reports_queue_state(service: JobService):
    """Health summarizes definitions, workers, and queue counts."""
    service.enqueue("portfolio.position_history", {"dry_run": True}, now=BASE_TIME)
    service.enqueue_due(now=datetime(2026, 1, 1, 12, 5, tzinfo=UTC))
    claimed = service.claim_next(
        worker_id="worker-1",
        now=datetime(2026, 1, 1, 12, 6, tzinfo=UTC),
    )
    assert claimed is not None

    health = service.health(now=datetime(2026, 1, 1, 12, 6, tzinfo=UTC))

    assert health.definition_count == 2
    assert health.total_runs == 2
    assert health.queued_runs == 1
    assert health.running_runs == 1
    assert health.active_workers == 1


def test_service_exposes_run_lease_timeout_for_worker_heartbeat_sizing(
    tmp_path: Path,
):
    """The worker needs the lease timeout to size its heartbeat interval."""
    store = SqliteJobStore(tmp_path / "jobs.db")
    registry = JobRegistry(
        [
            JobDefinition(
                name="portfolio.position_history",
                description="Warm positions",
                params_model=WarmParams,
                handler=warm_handler,
            )
        ]
    )
    lease_timeout = timedelta(seconds=42)
    service = JobService(
        store=store,
        registry=registry,
        run_lease_timeout=lease_timeout,
        reconcile_now=BASE_TIME,
    )

    assert service.run_lease_timeout == lease_timeout


def test_service_exposes_registry_for_worker_handler_resolution(service: JobService):
    """The worker resolves handlers through the service's registry."""
    definition = service.registry.get("techtrade.daily_scan")

    assert definition.handler is scan_handler


def test_service_heartbeat_refreshes_worker_and_prevents_recovery(
    service: JobService,
):
    """A manual heartbeat call keeps a claimed run's worker lease alive."""
    queued = service.enqueue("portfolio.position_history", {"dry_run": True}, now=BASE_TIME)
    claimed = service.claim_next(
        worker_id="worker-1",
        now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert claimed is not None

    service.heartbeat("worker-1", now=datetime(2026, 1, 1, 12, 4, tzinfo=UTC))
    recovered = service.recover_abandoned_runs(
        now=datetime(2026, 1, 1, 12, 4, 30, tzinfo=UTC)
    )

    assert recovered == []
    assert service.get_run(queued.run_id).status == "running"


def test_service_get_run_returns_persisted_run(service: JobService):
    """get_run exposes a single persisted run by identifier for API/CLI lookups."""
    queued = service.enqueue("portfolio.position_history", {"dry_run": True}, now=BASE_TIME)

    fetched = service.get_run(queued.run_id)

    assert fetched.run_id == queued.run_id
    assert fetched.status == "queued"


def test_service_get_run_raises_for_unknown_run(service: JobService):
    """get_run surfaces a KeyError for an unknown run id."""
    with pytest.raises(KeyError):
        service.get_run("does-not-exist")
