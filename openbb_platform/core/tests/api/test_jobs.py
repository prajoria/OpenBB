"""Tests for the authenticated /jobs API routes.

These tests assert the API layer never resolves or calls a job handler --
only durable enqueue/list/lookup/cancel operations are exercised -- and
that the routes are gated behind authentication.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_core.api.auth.user import authenticate_user
from openbb_core.api.dependency.jobs import get_job_service
from openbb_core.api.router.jobs import router as router_jobs
from openbb_core.app.jobs.models import JobContext, JobDefinition, JobResult
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.sqlite_store import SqliteJobStore
from openbb_core.app.service.job_service import JobService
from pydantic import BaseModel

UTC = timezone.utc
BASE_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class WarmParams(BaseModel):
    """Params accepted by the fake warm job."""

    symbol: str = "AAPL"


def _never_call_handler(context: JobContext, params: WarmParams) -> JobResult:
    """Fail the test loudly if the API layer ever executes a handler."""
    raise AssertionError("The API must never execute a job handler directly")


@pytest.fixture
def job_service(tmp_path: Path) -> JobService:
    """Build a job service backed by a temporary SQLite store."""
    store = SqliteJobStore(tmp_path / "jobs.db")
    registry = JobRegistry(
        [
            JobDefinition(
                name="portfolio.position_history",
                description="Warm positions cache",
                params_model=WarmParams,
                handler=_never_call_handler,
                max_attempts=3,
            )
        ]
    )
    return JobService(store=store, registry=registry, reconcile_now=BASE_TIME)


@pytest.fixture
def app(job_service: JobService) -> FastAPI:
    """Build a standalone FastAPI app exposing only the jobs router."""
    fastapi_app = FastAPI()
    fastapi_app.include_router(router_jobs)
    fastapi_app.dependency_overrides[get_job_service] = lambda: job_service
    # No custom auth extension is installed in this test environment, so
    # AuthService().auth_hook resolves to authenticate_user by default;
    # overriding it directly lets tests simulate auth allow/deny without
    # depending on env-var timing.
    fastapi_app.dependency_overrides[authenticate_user] = lambda: None
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Return a TestClient bound to the jobs-only app."""
    return TestClient(app)


def test_list_definitions_returns_registered_jobs(client: TestClient):
    """GET /jobs/definitions lists registered job definitions."""
    response = client.get("/jobs/definitions")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "portfolio.position_history"


def test_trigger_enqueues_a_run_without_executing_the_handler(client: TestClient):
    """POST /jobs/{job_name}/trigger only persists a queued run."""
    response = client.post(
        "/jobs/portfolio.position_history/trigger",
        json={"params": {"symbol": "MSFT"}},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["job_name"] == "portfolio.position_history"
    assert body["status"] == "queued"
    assert body["params"] == {"symbol": "MSFT"}


def test_trigger_unknown_job_returns_404(client: TestClient):
    """Triggering an unregistered job name returns 404, not a 500."""
    response = client.post("/jobs/does.not.exist/trigger", json={"params": {}})

    assert response.status_code == 404


def test_trigger_invalid_params_returns_422(client: TestClient):
    """Triggering with parameters that fail validation returns 422."""
    response = client.post(
        "/jobs/portfolio.position_history/trigger",
        json={"params": {"symbol": 12345}},
    )

    assert response.status_code == 422


def test_get_run_returns_persisted_run(client: TestClient, job_service: JobService):
    """GET /jobs/runs/{run_id} returns a previously queued run."""
    queued = job_service.enqueue(
        "portfolio.position_history", {"symbol": "AAPL"}, now=BASE_TIME
    )

    response = client.get(f"/jobs/runs/{queued.run_id}")

    assert response.status_code == 200
    assert response.json()["run_id"] == queued.run_id


def test_get_unknown_run_returns_404(client: TestClient):
    """Looking up a run id that does not exist returns 404."""
    response = client.get("/jobs/runs/does-not-exist")

    assert response.status_code == 404


def test_cancel_queued_run_succeeds(client: TestClient, job_service: JobService):
    """POST /jobs/runs/{run_id}/cancel cancels a queued run."""
    queued = job_service.enqueue(
        "portfolio.position_history", {"symbol": "AAPL"}, now=BASE_TIME
    )

    response = client.post(f"/jobs/runs/{queued.run_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancel_already_running_run_returns_409(
    client: TestClient, job_service: JobService
):
    """Cancelling a run that a worker has already claimed returns 409."""
    queued = job_service.enqueue(
        "portfolio.position_history", {"symbol": "AAPL"}, now=BASE_TIME
    )
    job_service.claim_next(worker_id="worker-1", now=BASE_TIME)

    response = client.post(f"/jobs/runs/{queued.run_id}/cancel")

    assert response.status_code == 409


def test_cancel_unknown_run_returns_404(client: TestClient):
    """Cancelling a run id that does not exist returns 404."""
    response = client.post("/jobs/runs/does-not-exist/cancel")

    assert response.status_code == 404


def test_health_reports_queue_state(client: TestClient):
    """GET /jobs/health reports aggregate queue health."""
    response = client.get("/jobs/health")

    assert response.status_code == 200
    body = response.json()
    assert "queued_runs" in body


def test_health_reports_read_only_service_probe_payload(
    client: TestClient, job_service: JobService
):
    """Health exposes queue depth, heartbeat age, and per-job last success."""
    queued = job_service.enqueue(
        "portfolio.position_history", {"symbol": "MSFT"}, now=BASE_TIME
    )
    claimed = job_service.claim_next("worker-health", now=BASE_TIME)
    assert claimed is not None and claimed.run_id == queued.run_id
    job_service.complete(
        claimed.run_id,
        JobResult(summary={"ok": True}),
        finished_at=BASE_TIME,
    )
    pending = job_service.enqueue(
        "portfolio.position_history",
        {"symbol": "AAPL"},
        now=BASE_TIME,
    )
    job_service.heartbeat("worker-health", now=datetime.now(UTC))

    response = client.get("/jobs/health")

    assert response.status_code == 200
    body = response.json()
    assert body["queue_depth"] == 1
    assert body["worker_heartbeat_age_seconds"] is not None
    assert 0 <= body["worker_heartbeat_age_seconds"] < 5
    assert datetime.fromisoformat(
        body["last_successful_run_by_job"]["portfolio.position_history"]
    ) == BASE_TIME
    assert job_service.get_run(pending.run_id).status == "queued"


def test_routes_require_authentication(app: FastAPI, job_service: JobService):
    """Requests are rejected before touching the job service when auth fails."""
    from fastapi import HTTPException, status

    async def _deny():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    app.dependency_overrides[authenticate_user] = _deny
    client = TestClient(app)

    response = client.get("/jobs/definitions")

    assert response.status_code == 401
