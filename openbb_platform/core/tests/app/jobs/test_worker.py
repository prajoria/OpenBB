"""Tests for the dedicated jobs worker and CLI."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from openbb_core.app.jobs.models import JobContext, JobDefinition, JobResult
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.sqlite_store import SqliteJobStore
from openbb_core.app.jobs.worker import JobWorker
from openbb_core.app.service.job_service import JobService, RetryableJobError
from pydantic import BaseModel

UTC = timezone.utc
BASE_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class FastParams(BaseModel):
    """Params for a fast handler."""

    symbol: str = "AAPL"


class SlowParams(BaseModel):
    """Params for a slow handler."""

    pass


class LegacyParams(BaseModel):
    """Older persisted params schema."""

    symbol: str


class ChangedParams(BaseModel):
    """Newer incompatible params schema."""

    symbols: list[str]


def fast_handler(context: JobContext, params: FastParams) -> JobResult:
    """Complete immediately."""
    return JobResult(summary={"job": context.job_name, "symbol": params.symbol})


def failing_retryable_handler(context: JobContext, params: FastParams) -> JobResult:
    """Raise a retryable error."""
    raise RetryableJobError("upstream timeout")


def legacy_handler(context: JobContext, params: LegacyParams) -> JobResult:
    """Handle the legacy schema."""
    return JobResult(summary={"job": context.job_name, "symbol": params.symbol})


def changed_handler(context: JobContext, params: ChangedParams) -> JobResult:
    """Handle the changed schema."""
    return JobResult(summary={"job": context.job_name, "symbols": params.symbols})


@pytest.fixture
def fast_service(tmp_path: Path) -> JobService:
    """Build a job service with a fast, deterministic handler."""
    store = SqliteJobStore(tmp_path / "jobs.db")
    registry = JobRegistry(
        [
            JobDefinition(
                name="fast.job",
                description="Fast job",
                params_model=FastParams,
                handler=fast_handler,
                max_attempts=1,
            )
        ]
    )
    return JobService(store=store, registry=registry, reconcile_now=BASE_TIME)


def test_run_once_returns_none_when_queue_is_empty(fast_service: JobService):
    """run_once returns None when there is no due or queued work."""
    worker = JobWorker(service=fast_service, worker_id="worker-1")

    outcome = worker.run_once(now=BASE_TIME)

    assert outcome is None


def test_run_once_claims_executes_and_completes_a_queued_run(fast_service: JobService):
    """run_once claims exactly one queued run and records its success."""
    queued = fast_service.enqueue("fast.job", {"symbol": "MSFT"}, now=BASE_TIME)
    worker = JobWorker(service=fast_service, worker_id="worker-1")

    outcome = worker.run_once(now=BASE_TIME)

    assert outcome is not None
    assert outcome.run_id == queued.run_id
    assert outcome.job_name == "fast.job"
    assert outcome.status == "succeeded"
    assert fast_service.get_run(queued.run_id).result == JobResult(
        summary={"job": "fast.job", "symbol": "MSFT"}
    )


def test_run_once_retries_retryable_handler_failures(tmp_path: Path):
    """A retryable handler failure requeues the run instead of failing it."""
    store = SqliteJobStore(tmp_path / "jobs.db")
    registry = JobRegistry(
        [
            JobDefinition(
                name="retryable.job",
                description="Retryable job",
                params_model=FastParams,
                handler=failing_retryable_handler,
                max_attempts=3,
                retry_backoff_seconds=30,
            )
        ]
    )
    service = JobService(store=store, registry=registry, reconcile_now=BASE_TIME)
    queued = service.enqueue("retryable.job", {}, now=BASE_TIME)
    worker = JobWorker(service=service, worker_id="worker-1")

    outcome = worker.run_once(now=BASE_TIME)

    assert outcome is not None
    assert outcome.run_id == queued.run_id
    assert outcome.status == "queued"
    retried = service.get_run(queued.run_id)
    assert retried.source == "retry"
    assert retried.attempt == 2


def test_run_once_marks_removed_job_definition_failed_and_continues(tmp_path: Path):
    """A removed persisted job fails terminally without blocking later valid work."""
    store = SqliteJobStore(tmp_path / "jobs.db")
    initial_registry = JobRegistry(
        [
            JobDefinition(
                name="removed.job",
                description="Removed job",
                params_model=FastParams,
                handler=fast_handler,
                max_attempts=3,
            ),
            JobDefinition(
                name="fast.job",
                description="Fast job",
                params_model=FastParams,
                handler=fast_handler,
                max_attempts=1,
            ),
        ]
    )
    initial_service = JobService(
        store=store,
        registry=initial_registry,
        reconcile_now=BASE_TIME,
    )
    removed = initial_service.enqueue("removed.job", {"symbol": "AAPL"}, now=BASE_TIME)

    active_registry = JobRegistry(
        [
            JobDefinition(
                name="fast.job",
                description="Fast job",
                params_model=FastParams,
                handler=fast_handler,
                max_attempts=1,
            )
        ]
    )
    service = JobService(
        store=store,
        registry=active_registry,
        reconcile_now=BASE_TIME + timedelta(seconds=2),
    )
    queued = service.enqueue(
        "fast.job",
        {"symbol": "MSFT"},
        now=BASE_TIME + timedelta(seconds=3),
    )
    worker = JobWorker(service=service, worker_id="worker-1")

    failed = worker.run_once(now=BASE_TIME + timedelta(seconds=4))
    completed = worker.run_once(now=BASE_TIME + timedelta(seconds=5))

    assert failed is not None
    assert failed.run_id == removed.run_id
    assert failed.status == "failed"
    failed_run = service.get_run(removed.run_id)
    assert failed_run.error_type == "UnknownJobDefinitionError"
    assert "removed.job" in (failed_run.error_message or "")

    assert completed is not None
    assert completed.run_id == queued.run_id
    assert completed.status == "succeeded"
    assert service.get_run(queued.run_id).result == JobResult(
        summary={"job": "fast.job", "symbol": "MSFT"}
    )


def test_run_once_marks_incompatible_persisted_params_failed_and_continues(tmp_path: Path):
    """Persisted params that no longer match the schema fail without stopping the worker."""
    store = SqliteJobStore(tmp_path / "jobs.db")
    initial_registry = JobRegistry(
        [
            JobDefinition(
                name="schema.job",
                description="Schema job",
                params_model=LegacyParams,
                handler=legacy_handler,
                max_attempts=3,
            ),
            JobDefinition(
                name="fast.job",
                description="Fast job",
                params_model=FastParams,
                handler=fast_handler,
                max_attempts=1,
            ),
        ]
    )
    initial_service = JobService(
        store=store,
        registry=initial_registry,
        reconcile_now=BASE_TIME,
    )
    incompatible = initial_service.enqueue("schema.job", {"symbol": "AAPL"}, now=BASE_TIME)

    active_registry = JobRegistry(
        [
            JobDefinition(
                name="schema.job",
                description="Schema job",
                params_model=ChangedParams,
                handler=changed_handler,
                max_attempts=3,
            ),
            JobDefinition(
                name="fast.job",
                description="Fast job",
                params_model=FastParams,
                handler=fast_handler,
                max_attempts=1,
            ),
        ]
    )
    service = JobService(
        store=store,
        registry=active_registry,
        reconcile_now=BASE_TIME + timedelta(seconds=2),
    )
    queued = service.enqueue(
        "fast.job",
        {"symbol": "MSFT"},
        now=BASE_TIME + timedelta(seconds=3),
    )
    worker = JobWorker(service=service, worker_id="worker-1")

    failed = worker.run_once(now=BASE_TIME + timedelta(seconds=4))
    completed = worker.run_once(now=BASE_TIME + timedelta(seconds=5))

    assert failed is not None
    assert failed.run_id == incompatible.run_id
    assert failed.status == "failed"
    failed_run = service.get_run(incompatible.run_id)
    assert failed_run.error_type == "ValidationError"
    assert "symbols" in (failed_run.error_message or "")

    assert completed is not None
    assert completed.run_id == queued.run_id
    assert completed.status == "succeeded"
    assert service.get_run(queued.run_id).result == JobResult(
        summary={"job": "fast.job", "symbol": "MSFT"}
    )


def test_run_once_recovers_abandoned_runs_from_crashed_workers(tmp_path: Path):
    """A stale running run from a vanished worker is recovered and re-claimed."""
    store = SqliteJobStore(tmp_path / "jobs.db")
    registry = JobRegistry(
        [
            JobDefinition(
                name="fast.job",
                description="Fast job",
                params_model=FastParams,
                handler=fast_handler,
                max_attempts=2,
            )
        ]
    )
    lease_timeout = timedelta(minutes=5)
    service = JobService(
        store=store,
        registry=registry,
        run_lease_timeout=lease_timeout,
        reconcile_now=BASE_TIME,
    )
    queued = service.enqueue("fast.job", {"symbol": "AAPL"}, now=BASE_TIME)

    # Simulate a worker that claimed the run and then crashed without ever
    # heartbeating again.
    claimed = service.claim_next(worker_id="ghost-worker", now=BASE_TIME)
    assert claimed is not None
    assert claimed.run_id == queued.run_id

    worker = JobWorker(service=service, worker_id="worker-2")
    later = BASE_TIME + lease_timeout + timedelta(seconds=1)

    outcome = worker.run_once(now=later)

    assert outcome is not None
    assert outcome.run_id == queued.run_id
    assert outcome.status == "succeeded"
    recovered_run = service.get_run(queued.run_id)
    assert recovered_run.attempt == 2
    assert recovered_run.worker_id == "worker-2"


def test_worker_heartbeat_prevents_recovery_of_a_live_slow_handler(tmp_path: Path):
    """A slow synchronous handler's run survives concurrent recovery sweeps.

    Two independent store connections to the same database simulate a
    worker process executing a slow handler and a second monitor/worker
    process concurrently sweeping for abandoned runs (each production
    worker owns its own SQLite connection). The executing worker heartbeats
    far more frequently than the lease timeout while the handler blocks, so
    repeated recover_abandoned_runs sweeps from the other connection during
    execution must never reclaim the live run.
    """
    db_path = tmp_path / "jobs.db"
    started = threading.Event()
    release = threading.Event()

    def slow_handler(context: JobContext, params: SlowParams) -> JobResult:
        started.set()
        release.wait(timeout=5)
        return JobResult(summary={"ok": True})

    def build_registry() -> JobRegistry:
        return JobRegistry(
            [
                JobDefinition(
                    name="slow.job",
                    description="Slow job",
                    params_model=SlowParams,
                    handler=slow_handler,
                    max_attempts=1,
                )
            ]
        )

    lease_timeout = timedelta(seconds=0.15)
    worker_service = JobService(
        store=SqliteJobStore(db_path), registry=build_registry(), run_lease_timeout=lease_timeout
    )
    queued = worker_service.enqueue("slow.job", {})

    # A second connection/service to the same database stands in for
    # another worker process independently sweeping for abandoned runs.
    monitor_service = JobService(
        store=SqliteJobStore(db_path), registry=build_registry(), run_lease_timeout=lease_timeout
    )

    # Heartbeat much faster than the lease timeout, as production sizing does.
    worker = JobWorker(service=worker_service, worker_id="worker-1", heartbeat_seconds=0.03)

    outcomes: dict[str, object] = {}

    def _run_worker() -> None:
        outcomes["outcome"] = worker.run_once()

    worker_thread = threading.Thread(target=_run_worker)
    worker_thread.start()
    assert started.wait(timeout=5), "handler never started"

    recovered_while_running: list = []
    for _ in range(6):
        time.sleep(0.05)
        recovered_while_running.extend(monitor_service.recover_abandoned_runs())

    release.set()
    worker_thread.join(timeout=5)
    assert not worker_thread.is_alive()

    assert recovered_while_running == []
    final_run = monitor_service.get_run(queued.run_id)
    assert final_run.status == "succeeded"
    assert final_run.result == JobResult(summary={"ok": True})
    assert outcomes["outcome"].status == "succeeded"  # type: ignore[union-attr]


def test_without_continuous_heartbeat_a_slow_handler_run_gets_recovered(tmp_path: Path):
    """Negative control: disabling the heartbeat thread allows recovery mid-run.

    This proves the positive heartbeat test above is not vacuous: without
    continuous heartbeating, a handler that outlives the lease timeout is
    reclaimed by another monitor/worker while still executing.
    """
    db_path = tmp_path / "jobs.db"
    started = threading.Event()
    release = threading.Event()

    def slow_handler(context: JobContext, params: SlowParams) -> JobResult:
        started.set()
        release.wait(timeout=5)
        return JobResult(summary={"ok": True})

    def build_registry() -> JobRegistry:
        return JobRegistry(
            [
                JobDefinition(
                    name="slow.job",
                    description="Slow job",
                    params_model=SlowParams,
                    handler=slow_handler,
                    max_attempts=2,
                )
            ]
        )

    lease_timeout = timedelta(seconds=0.1)
    worker_service = JobService(
        store=SqliteJobStore(db_path), registry=build_registry(), run_lease_timeout=lease_timeout
    )
    queued = worker_service.enqueue("slow.job", {})

    monitor_service = JobService(
        store=SqliteJobStore(db_path), registry=build_registry(), run_lease_timeout=lease_timeout
    )

    # heartbeat_seconds=None disables the continuous background heartbeat;
    # only the one-time heartbeat recorded at claim time is written.
    worker = JobWorker(service=worker_service, worker_id="worker-1", heartbeat_seconds=None)

    def _run_worker() -> None:
        worker.run_once()

    worker_thread = threading.Thread(target=_run_worker)
    worker_thread.start()
    assert started.wait(timeout=5), "handler never started"

    recovered = []
    deadline = time.monotonic() + 5
    while not recovered and time.monotonic() < deadline:
        time.sleep(0.05)
        recovered.extend(monitor_service.recover_abandoned_runs())

    release.set()
    worker_thread.join(timeout=5)

    assert recovered, "expected the abandoned run to be recovered mid-execution"
    assert recovered[0].run_id == queued.run_id
    assert recovered[0].status == "queued"


def test_run_forever_stops_promptly_on_stop_event(fast_service: JobService):
    """run_forever exits quickly once stop_event is set, without killing work."""
    worker = JobWorker(service=fast_service, worker_id="worker-1")
    stop_event = threading.Event()

    thread = threading.Thread(
        target=worker.run_forever, kwargs={"poll_seconds": 0.05, "stop_event": stop_event}
    )
    thread.start()
    time.sleep(0.1)
    stop_event.set()
    thread.join(timeout=2)

    assert not thread.is_alive()


def test_run_forever_processes_queued_work_before_next_poll(fast_service: JobService):
    """A queued run is drained promptly by the continuous polling loop."""
    queued = fast_service.enqueue("fast.job", {"symbol": "AAPL"}, now=BASE_TIME)
    worker = JobWorker(service=fast_service, worker_id="worker-1")
    stop_event = threading.Event()

    thread = threading.Thread(
        target=worker.run_forever, kwargs={"poll_seconds": 0.05, "stop_event": stop_event}
    )
    thread.start()

    deadline = time.monotonic() + 5
    run = fast_service.get_run(queued.run_id)
    while run.status == "queued" and time.monotonic() < deadline:
        time.sleep(0.05)
        run = fast_service.get_run(queued.run_id)

    stop_event.set()
    thread.join(timeout=2)

    assert run.status == "succeeded"


def test_stop_requested_during_cycle_prevents_a_new_claim():
    """A stop observed before claim closes the check-then-claim shutdown race."""
    stop_event = threading.Event()

    class StopBeforeClaimService:
        run_lease_timeout = timedelta(minutes=5)

        def reconcile_definitions(self, now=None):
            stop_event.set()

        def heartbeat(self, worker_id, now=None, *, hostname=None):
            pass

        def recover_abandoned_runs(self, now=None):
            return []

        def enqueue_due(self, now=None):
            return []

        def claim_next(self, worker_id, now=None):
            raise AssertionError("worker claimed new work after shutdown was requested")

    worker = JobWorker(
        service=StopBeforeClaimService(),  # type: ignore[arg-type]
        worker_id="worker-1",
    )

    assert worker.run_once(now=BASE_TIME, stop_event=stop_event) is None


def test_shutdown_finishes_active_job_but_does_not_claim_the_next(tmp_path: Path):
    """Stop grants the active handler time to finish, then exits before another claim."""
    started = threading.Event()
    release = threading.Event()

    def slow_handler(context: JobContext, params: SlowParams) -> JobResult:
        started.set()
        release.wait(timeout=5)
        return JobResult(summary={"ok": True})

    registry = JobRegistry(
        [
            JobDefinition(
                name="slow.job",
                description="Slow job",
                params_model=SlowParams,
                handler=slow_handler,
                max_attempts=1,
            )
        ]
    )
    service = JobService(
        store=SqliteJobStore(tmp_path / "jobs.db"),
        registry=registry,
        reconcile_now=BASE_TIME,
    )
    active = service.enqueue("slow.job", {}, now=BASE_TIME)
    waiting = service.enqueue("slow.job", {}, now=BASE_TIME + timedelta(seconds=1))
    worker = JobWorker(service=service, worker_id="worker-1")
    stop_event = threading.Event()
    thread = threading.Thread(
        target=worker.run_forever,
        kwargs={"poll_seconds": 0.01, "stop_event": stop_event},
    )

    thread.start()
    assert started.wait(timeout=5)
    stop_event.set()
    thread.join(timeout=0.05)
    assert thread.is_alive(), "active handler was not given its shutdown grace period"

    release.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert service.get_run(active.run_id).status == "succeeded"
    assert service.get_run(waiting.run_id).status == "queued"
