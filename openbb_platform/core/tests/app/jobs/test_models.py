"""Tests for the jobs domain models."""

from datetime import datetime, timezone

import pytest
from pydantic import BaseModel, ValidationError

from openbb_core.app.jobs.models import (
    MAX_JSON_PAYLOAD_BYTES,
    JobContext,
    JobDefinition,
    JobResult,
    JobRun,
)


class ExampleParams(BaseModel):
    """Example job parameters."""

    symbol: str


def example_handler(context: JobContext, params: ExampleParams) -> JobResult:
    """Return a structured example result."""
    return JobResult(summary={"job": context.job_name, "symbol": params.symbol})


@pytest.mark.parametrize(
    "status",
    [
        "queued",
        "running",
        "succeeded",
        "succeeded_with_warnings",
        "failed",
        "cancelled",
    ],
)
def test_job_run_accepts_valid_statuses(status: str):
    """JobRun accepts the supported status values."""
    run = JobRun(run_id="run-1", job_name="example.job", status=status)

    assert run.status == status


def test_job_run_rejects_invalid_status():
    """JobRun rejects unsupported status values."""
    with pytest.raises(ValidationError, match="status"):
        JobRun(  # type: ignore[arg-type]
            run_id="run-1",
            job_name="example.job",
            status="pending",
        )


def test_job_models_reject_oversized_json_payloads():
    """JobResult and JobRun reject JSON payloads over the configured bound."""
    oversized_payload = {"blob": "x" * (MAX_JSON_PAYLOAD_BYTES + 128)}

    with pytest.raises(ValidationError, match="must serialize to at most"):
        JobResult(summary=oversized_payload)

    with pytest.raises(ValidationError, match="must serialize to at most"):
        JobRun(run_id="run-1", job_name="example.job", params=oversized_payload)


def test_job_definition_is_immutable():
    """Registered job definitions are frozen."""
    definition = JobDefinition(
        name="example.job",
        description="Example job",
        params_model=ExampleParams,
        handler=example_handler,
    )

    with pytest.raises(ValidationError, match="frozen"):
        definition.name = "other.job"  # type: ignore[misc]


def test_job_definition_accepts_json_default_params():
    """JobDefinition stores JSON-safe default params for scheduled runs."""
    definition = JobDefinition(
        name="example.job",
        description="Example job",
        params_model=ExampleParams,
        handler=example_handler,
        default_params={"symbol": "AAPL"},
    )

    assert definition.default_params == {"symbol": "AAPL"}


def test_job_definition_rejects_non_json_default_params():
    """JobDefinition rejects default params that cannot be serialized."""
    with pytest.raises(ValidationError, match="default_params"):
        JobDefinition(
            name="example.job",
            description="Example job",
            params_model=ExampleParams,
            handler=example_handler,
            default_params={"value": datetime.now(timezone.utc)},
        )


def test_job_run_complete_sets_warning_status():
    """Completing a run with warnings returns a warning status."""
    run = JobRun(run_id="run-1", job_name="example.job", status="running")
    result = JobResult(summary={"rows": 10}, warnings=["one warning"])

    completed = run.complete(
        result=result,
        finished_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    assert completed.status == "succeeded_with_warnings"
    assert completed.result == result


def test_job_run_complete_requires_running_state():
    """Only running jobs can be completed."""
    run = JobRun(run_id="run-1", job_name="example.job", status="queued")

    with pytest.raises(ValueError, match="running"):
        run.complete(
            result=JobResult(summary={"rows": 10}),
            finished_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )


def test_job_run_mark_running_updates_worker_and_timestamps():
    """Queued runs transition to running with the worker and start time."""
    started_at = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)
    run = JobRun(run_id="run-1", job_name="example.job", status="queued")

    running = run.mark_running(worker_id="worker-1", started_at=started_at)

    assert running.status == "running"
    assert running.worker_id == "worker-1"
    assert running.started_at == started_at
    assert running.updated_at == started_at


def test_job_run_mark_running_requires_queued_state():
    """Only queued jobs can be marked running."""
    run = JobRun(run_id="run-1", job_name="example.job", status="running")

    with pytest.raises(ValueError, match="queued"):
        run.mark_running(
            worker_id="worker-1",
            started_at=datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc),
        )


def test_job_run_fail_records_error_details():
    """Running runs transition to failed with normalized error details."""
    finished_at = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    run = JobRun(run_id="run-1", job_name="example.job", status="running")

    failed = run.fail(
        error=RuntimeError("something went wrong"),
        finished_at=finished_at,
    )

    assert failed.status == "failed"
    assert failed.finished_at == finished_at
    assert failed.updated_at == finished_at
    assert failed.error_type == "RuntimeError"
    assert failed.error_message == "something went wrong"


def test_job_run_fail_requires_running_state():
    """Only running jobs can fail."""
    run = JobRun(run_id="run-1", job_name="example.job", status="queued")

    with pytest.raises(ValueError, match="running"):
        run.fail(
            error=RuntimeError("something went wrong"),
            finished_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        )


def test_job_run_schedule_retry_resets_runtime_state_and_increments_attempt():
    """Retry scheduling clears runtime fields and advances the attempt counter."""
    available_at = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)
    run = JobRun(
        run_id="run-1",
        job_name="example.job",
        status="failed",
        source="manual",
        attempt=1,
        max_attempts=3,
        worker_id="worker-1",
        started_at=datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc),
        finished_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        result=JobResult(summary={"rows": 10}),
        error_type="RuntimeError",
        error_message="something went wrong",
    )

    retried = run.schedule_retry(available_at=available_at)

    assert retried.status == "queued"
    assert retried.source == "retry"
    assert retried.attempt == 2
    assert retried.available_at == available_at
    assert retried.worker_id is None
    assert retried.started_at is None
    assert retried.finished_at is None
    assert retried.result is None
    assert retried.error_type is None
    assert retried.error_message is None
    assert retried.updated_at == available_at


def test_job_run_schedule_retry_requires_retryable_state():
    """Only running or failed jobs can be retried."""
    run = JobRun(
        run_id="run-1",
        job_name="example.job",
        status="queued",
        attempt=1,
        max_attempts=2,
    )

    with pytest.raises(ValueError, match="running or failed"):
        run.schedule_retry(available_at=datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc))


def test_job_run_schedule_retry_rejects_exhausted_attempts():
    """Retry attempts stop once the max attempt budget is exhausted."""
    run = JobRun(
        run_id="run-1",
        job_name="example.job",
        status="failed",
        attempt=2,
        max_attempts=2,
    )

    with pytest.raises(ValueError, match="exhausted"):
        run.schedule_retry(available_at=datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc))


def test_job_run_cancel_transitions_to_cancelled():
    """Queued runs can be cancelled with a finish timestamp."""
    finished_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    run = JobRun(run_id="run-1", job_name="example.job", status="queued")

    cancelled = run.cancel(finished_at=finished_at)

    assert cancelled.status == "cancelled"
    assert cancelled.finished_at == finished_at
    assert cancelled.updated_at == finished_at


def test_job_run_cancel_requires_queued_state():
    """Only queued jobs can be cancelled."""
    run = JobRun(run_id="run-1", job_name="example.job", status="running")

    with pytest.raises(ValueError, match="queued"):
        run.cancel(finished_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
