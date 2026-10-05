"""Authenticated, allowlisted durable cache-job adapter contracts."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_core.api.auth.user import authenticate_user
from openbb_core.api.dependency.jobs import get_job_service
from openbb_core.api.router.jobs import router as core_jobs_router
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.sqlite_store import SqliteJobStore
from openbb_core.app.service.job_service import JobService
from openbb_mcp_server.adapters.cache_jobs import compose_cache_jobs_app
from openbb_mcp_server.app.app import create_mcp_server
from openbb_mcp_server.models.settings import MCPSettings
from portfolio_utils.jobs import get_job_definitions

UTC = timezone.utc
BASE_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def service(tmp_path: Path) -> JobService:
    """Return a durable fixture service with the real approved definitions."""
    return JobService(
        store=SqliteJobStore(tmp_path / "jobs.db"),
        registry=JobRegistry(get_job_definitions()),
        reconcile_now=BASE_TIME,
    )


@pytest.fixture
def app(service: JobService) -> FastAPI:
    """Compose adapter routes while preserving original auth dependencies."""
    composed = compose_cache_jobs_app(FastAPI())
    composed.dependency_overrides[get_job_service] = lambda: service
    composed.dependency_overrides[authenticate_user] = lambda: None
    return composed


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Return a client for the fixture-backed composed adapter."""
    return TestClient(app)


def test_definitions_and_health_are_bounded_to_allowlist(client: TestClient):
    """Metadata/status surface lists only the two approved definitions."""
    definitions = client.get("/api/v1/cache/jobs/definitions")
    assert definitions.status_code == 200
    assert {item["name"] for item in definitions.json()} == {
        "portfolio.position_history",
        "portfolio.etf_holdings",
    }
    health = client.get("/api/v1/cache/jobs/health")
    assert health.status_code == 200
    assert "queue_depth" in health.json()
    assert health.json()["worker_heartbeat_age_seconds"] is None


@pytest.mark.parametrize(
    ("path", "params"),
    [
        (
            "portfolio.position_history",
            {"symbols": ["SYNTH"], "years": 2},
        ),
        (
            "portfolio.etf_holdings",
            {"etfs": ["SYNTH"], "skip_portfolio": True},
        ),
    ],
)
def test_allowlisted_trigger_returns_durable_run_without_handler_execution(
    client: TestClient,
    path: str,
    params: dict,
):
    """Trigger endpoints only persist queued runs for a worker."""
    response = client.post(
        f"/api/v1/cache/jobs/{path}/trigger",
        json={"params": params, "idempotency_key": f"test-{path}"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["run_id"]
    assert body["job_name"] == path
    assert body["status"] == "queued"

    lookup = client.get(f"/api/v1/cache/jobs/runs/{body['run_id']}")
    assert lookup.status_code == 200
    assert lookup.json()["run_id"] == body["run_id"]


def test_idempotency_returns_the_same_durable_run(client: TestClient):
    """Repeated idempotency keys cannot enqueue duplicate maintenance work."""
    request = {
        "params": {"symbols": ["SYNTH"], "years": 2},
        "idempotency_key": "same-request",
    }
    first = client.post(
        "/api/v1/cache/jobs/portfolio.position_history/trigger",
        json=request,
    )
    second = client.post(
        "/api/v1/cache/jobs/portfolio.position_history/trigger",
        json=request,
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]


def test_idempotency_is_namespaced_per_allowlisted_job(client: TestClient):
    """The same caller key cannot return another job's run."""
    position = client.post(
        "/api/v1/cache/jobs/portfolio.position_history/trigger",
        json={"params": {}, "idempotency_key": "shared"},
    )
    etf = client.post(
        "/api/v1/cache/jobs/portfolio.etf_holdings/trigger",
        json={"params": {}, "idempotency_key": "shared"},
    )
    assert position.status_code == etf.status_code == 202
    assert position.json()["job_name"] == "portfolio.position_history"
    assert etf.json()["job_name"] == "portfolio.etf_holdings"
    assert position.json()["run_id"] != etf.json()["run_id"]


def test_cross_job_dedupe_collision_is_rejected(
    client: TestClient,
    service: JobService,
):
    """A pre-existing run can never escape the requested job boundary."""
    service.enqueue(
        "portfolio.position_history",
        {},
        idempotency_key="mcp:portfolio.etf_holdings:collision",
    )
    response = client.post(
        "/api/v1/cache/jobs/portfolio.etf_holdings/trigger",
        json={"params": {}, "idempotency_key": "collision"},
    )
    assert response.status_code == 409
    assert "different job" in response.json()["detail"]


def test_unknown_jobs_have_no_trigger_route(client: TestClient):
    """No generic job-name or arbitrary execution facility is mounted."""
    response = client.post(
        "/api/v1/cache/jobs/arbitrary.script/trigger",
        json={"params": {}},
    )
    assert response.status_code == 404


def test_invalid_params_and_absent_definition_fail_explicitly(
    client: TestClient,
    service: JobService,
):
    """Typed validation and absent workers never become queued success."""
    invalid = client.post(
        "/api/v1/cache/jobs/portfolio.position_history/trigger",
        json={"params": {"years": 0}},
    )
    assert invalid.status_code == 422

    service.registry._definitions.pop("portfolio.position_history")  # noqa: SLF001
    absent = client.post(
        "/api/v1/cache/jobs/portfolio.position_history/trigger",
        json={"params": {}},
    )
    assert absent.status_code == 503


def test_original_authentication_is_required(app: FastAPI):
    """Authentication rejects the request before durable state is touched."""

    async def deny():
        from fastapi import HTTPException

        raise HTTPException(status_code=401)

    app.dependency_overrides[authenticate_user] = deny
    assert TestClient(app).get("/api/v1/cache/jobs/definitions").status_code == 401


def test_status_survives_service_restart(tmp_path: Path):
    """Durable run IDs remain queryable after a service restart."""
    database = tmp_path / "restart-jobs.db"
    registry = JobRegistry(get_job_definitions())
    first_store = SqliteJobStore(database)
    first = JobService(
        store=first_store,
        registry=registry,
        reconcile_now=BASE_TIME,
    )
    queued = first.enqueue("portfolio.position_history", {})
    first_store.close()

    second_store = SqliteJobStore(database)
    second = JobService(
        store=second_store,
        registry=JobRegistry(get_job_definitions()),
        reconcile_now=BASE_TIME,
    )
    app = compose_cache_jobs_app(FastAPI())
    app.dependency_overrides[get_job_service] = lambda: second
    app.dependency_overrides[authenticate_user] = lambda: None
    response = TestClient(app).get(f"/api/v1/cache/jobs/runs/{queued.run_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    second_store.close()


def test_cancellation_and_invalidation_are_not_advertised(
    client: TestClient,
    service: JobService,
):
    """MCP cannot cancel running work or invalidate arbitrary cache tables."""
    queued = service.enqueue("portfolio.position_history", {})
    claimed = service.claim_next("worker-1")
    assert claimed is not None and claimed.run_id == queued.run_id
    assert (
        client.post(f"/api/v1/cache/jobs/runs/{queued.run_id}/cancel").status_code
        == 404
    )
    assert (
        client.post("/api/v1/cache/invalidate", json={"table": "*"}).status_code == 404
    )


def test_persisted_parameters_are_secret_free(
    client: TestClient,
    service: JobService,
):
    """Durable params contain only typed business inputs."""
    response = client.post(
        "/api/v1/cache/jobs/portfolio.position_history/trigger",
        json={"params": {"symbols": ["SYNTH"], "years": 3}},
    )
    run = service.get_run(response.json()["run_id"])
    serialized = str(run.params).lower()
    assert run.params == {
        "symbols": ["SYNTH"],
        "years": 3,
        "skip_holiday_prestep": False,
    }
    assert not any(
        token in serialized
        for token in ("api_key", "password", "credential", "database")
    )


@pytest.mark.asyncio
async def test_real_mcp_exposes_jobs_only_with_ops_and_explicit_maintenance(
    service: JobService,
):
    """Read/general profiles and non-maintenance ops cannot discover job controls."""
    source = FastAPI()
    source.include_router(core_jobs_router, prefix="/api/v1")
    source.dependency_overrides[get_job_service] = lambda: service
    source.dependency_overrides[authenticate_user] = lambda: None
    credentials = ("synthetic-user", "x" * 32)

    for profile, maintenance in (
        ("platform-standard", False),
        ("portfolio-read", False),
        ("portfolio-ops", False),
    ):
        mcp = create_mcp_server(
            MCPSettings(
                api_prefix="/api/v1",
                capability_profile=profile,
                enable_maintenance_operations=maintenance,
                default_tool_categories=["all"],
                default_skills_dir=None,
            ),
            source,
            auth=credentials if profile != "platform-standard" else None,
        )
        assert not {
            tool.name
            for tool in await mcp.list_tools()
            if tool.name.startswith("cache_jobs_")
        }

    ops = create_mcp_server(
        MCPSettings(
            api_prefix="/api/v1",
            capability_profile="portfolio-ops",
            enable_maintenance_operations=True,
            default_tool_categories=["all"],
            default_skills_dir=None,
        ),
        source,
        auth=credentials,
    )
    names = {
        tool.name
        for tool in await ops.list_tools()
        if tool.name.startswith("cache_jobs_")
    }
    assert names == {
        "cache_jobs_definitions",
        "cache_jobs_health",
        "cache_jobs_run",
        "cache_jobs_trigger_position_history",
        "cache_jobs_trigger_etf_holdings",
    }
    all_names = {tool.name for tool in await ops.list_tools()}
    assert not any(
        fragment in name
        for name in all_names
        for fragment in ("cancel", "invalidate")
    )
    assert not any(name.startswith("jobs_") for name in all_names)
