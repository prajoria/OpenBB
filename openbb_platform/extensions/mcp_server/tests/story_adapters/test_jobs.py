"""Story jobs over the durable jobs service (#2218, N08)."""

# pylint: disable=redefined-outer-name,protected-access,import-outside-toplevel
# pylint: disable=too-many-positional-arguments

import json
import os
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_core.api.dependency.jobs import get_job_service
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.sqlite_store import SqliteJobStore
from openbb_core.app.jobs.worker import JobWorker
from openbb_core.app.service.job_service import JobService
from openbb_mcp_server.story_adapters import jobs, story_job_kinds
from openbb_mcp_server.story_adapters.artifacts import compose_story_artifacts_app
from openbb_mcp_server.story_adapters.jobs import compose_story_jobs_app
from openbb_mcp_server.story_adapters.registry import compose_story_registry_app
from openbb_mcp_server.story_adapters.story_job_kinds import (
    KINDS,
    StoryJobParams,
    get_job_definitions,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
MANIFESTS = (
    REPO_ROOT
    / "openbb_platform"
    / "extensions"
    / "agents"
    / "openbb_agents"
    / "notebook_guide"
    / "stories"
)
BACKTEST = {
    "config": {
        "strategy": "buy_and_hold",
        "universe": ["AAA", "BBB"],
        "start": "2023-01-03",
        "end": "2024-12-31",
    },
    "strategy_params": {"symbols": ["AAA", "BBB"]},
}
FAKE_BACKTEST = {
    "engine_used": "vector",
    "equity_curve": [{"value": 100.0}, {"value": 104.0}],
    "trades": [],
    "metrics": {"cagr": 0.04, "sharpe": 1.25, "max_drawdown": -0.1, "sortino": None},
}


def _app(principal, store, root, service):
    app = compose_story_registry_app(
        FastAPI(), principal=principal, manifest_dir=MANIFESTS, store_path=store
    )
    app = compose_story_artifacts_app(
        app, principal=principal, store_path=store, artifact_root=root
    )
    app = compose_story_jobs_app(app, principal=principal, store_path=store)
    app.dependency_overrides[get_job_service] = lambda: service
    return TestClient(app)


@pytest.fixture
def job_harness(tmp_path, monkeypatch):
    """Two principals, one run store, one durable job store and a worker."""
    store = tmp_path / "runs.sqlite"
    root = tmp_path / "artifacts"
    jobs_db = tmp_path / "jobs.db"
    # The worker resolves the story stores from the environment.
    monkeypatch.setenv("OPENBB_STORY_RUN_STORE", str(store))
    monkeypatch.setenv("OPENBB_STORY_ARTIFACT_ROOT", str(root))
    calls = []

    def fake_backtest(payload):
        calls.append(payload)
        return FAKE_BACKTEST

    monkeypatch.setattr(story_job_kinds, "run_backtest", fake_backtest)
    service = JobService(
        store=SqliteJobStore(jobs_db), registry=JobRegistry(get_job_definitions())
    )
    alice = _app("alice", store, root, service)
    bob = _app("bob", store, root, service)

    def run(story_id="portfolio/08", client=alice):
        response = client.post("/api/v1/story/runs", json={"story_id": story_id})
        assert response.status_code == 200, response.text
        return response.json()["run_id"]

    state = SimpleNamespace(run_id=None)

    def submit(
        operation_id,
        *,
        kind="story.backtest",
        payload=None,
        run_id=None,
        client=alice,
        raw=False,
        **extra,
    ):
        run_id = run_id or state.run_id or run()
        state.run_id = state.run_id or run_id
        response = client.post(
            f"/api/v1/story/runs/{run_id}/jobs",
            json={
                "operation_id": operation_id,
                "kind": kind,
                "payload": BACKTEST if payload is None else payload,
                **extra,
            },
        )
        if raw:
            return response
        assert response.status_code == 202, response.text
        return SimpleNamespace(**response.json())

    def get(job_id, run_id=None, client=alice):
        return client.get(f"/api/v1/story/runs/{run_id or state.run_id}/jobs/{job_id}")

    class Harness(SimpleNamespace):
        """Fixture namespace; ``worker_submission_count`` reads the job store."""

        @property
        def worker_submission_count(self):
            with sqlite3.connect(jobs_db) as connection:
                return connection.execute("SELECT COUNT(*) FROM job_run").fetchone()[0]

    return Harness(
        alice=alice,
        bob=bob,
        service=service,
        worker=JobWorker(service=service, worker_id="test-worker"),
        run=run,
        submit=submit,
        get=get,
        state=state,
        calls=calls,
        root=root,
        jobs_db=jobs_db,
        store=store,
    )


def test_uncertain_submission_is_not_duplicated(job_harness):
    """The plan's anchor case: a lost response, retried, is still one job."""
    first = job_harness.submit(operation_id="synthetic-op-1")
    second = job_harness.submit(operation_id="synthetic-op-1")
    assert first.job_id == second.job_id
    assert job_harness.worker_submission_count == 1


def test_a_crash_before_the_job_id_was_recorded_still_yields_one_job(job_harness):
    """If the ledger never learned the job ID, a retry finds the same run."""
    first = job_harness.submit(operation_id="op-crash")
    with sqlite3.connect(job_harness.store) as connection:
        connection.execute("UPDATE story_jobs SET job_id = NULL")
    second = job_harness.submit(operation_id="op-crash")
    assert second.job_id == first.job_id
    assert job_harness.worker_submission_count == 1


def test_reusing_an_operation_for_a_different_payload_conflicts(job_harness):
    """An operation ID names one job; a different payload under it is a 409."""
    job_harness.submit(operation_id="op-1")
    other = {**BACKTEST, "strategy_params": {"symbols": ["AAA"]}}
    response = job_harness.submit(operation_id="op-1", payload=other, raw=True)
    assert response.status_code == 409
    assert job_harness.worker_submission_count == 1


def _crash_after_recording(harness, operation_id, run_id):
    """Leave a recorded submission whose job was never enqueued."""
    harness.submit(operation_id=operation_id, run_id=run_id)
    with sqlite3.connect(harness.jobs_db) as connection:
        connection.execute("DELETE FROM job_run")
    with sqlite3.connect(harness.store) as connection:
        connection.execute("UPDATE story_jobs SET job_id = NULL")


def test_a_recorded_but_unqueued_operation_keeps_its_payload(job_harness):
    """After a crash before enqueueing, the operation still names its payload."""
    run_id = job_harness.run()
    _crash_after_recording(job_harness, "op-1", run_id)
    other = {**BACKTEST, "strategy_params": {"symbols": ["AAA"]}}
    response = job_harness.submit(
        operation_id="op-1", run_id=run_id, payload=other, raw=True
    )
    assert response.status_code == 409
    assert job_harness.worker_submission_count == 0
    retried = job_harness.submit(operation_id="op-1", run_id=run_id)
    assert retried.status == "queued"
    assert job_harness.worker_submission_count == 1


def test_a_recorded_but_unqueued_operation_keeps_its_run(job_harness):
    """The same crash cannot let the operation move to another run."""
    run_id = job_harness.run()
    _crash_after_recording(job_harness, "op-1", run_id)
    response = job_harness.submit(
        operation_id="op-1", run_id=job_harness.run(), raw=True
    )
    assert response.status_code == 409
    assert job_harness.worker_submission_count == 0


def test_a_lost_ledger_row_cannot_rebind_a_queued_job(job_harness):
    """If the submission record is gone, the queued job's params still decide."""
    run_id = job_harness.run()
    job_harness.submit(operation_id="op-1", run_id=run_id)
    with sqlite3.connect(job_harness.store) as connection:
        connection.execute("DELETE FROM story_jobs")
    other = {**BACKTEST, "strategy_params": {"symbols": ["AAA"]}}
    response = job_harness.submit(
        operation_id="op-1", run_id=run_id, payload=other, raw=True
    )
    assert response.status_code == 409
    assert job_harness.worker_submission_count == 1


def test_a_job_whose_run_was_removed_fails_explicitly(job_harness):
    """The handler refuses to write into a run that no longer exists."""
    job = job_harness.submit(operation_id="op-1")
    with sqlite3.connect(job_harness.store) as connection:
        connection.execute("DELETE FROM story_runs")
    assert job_harness.worker.run_once().status == "failed"
    with sqlite3.connect(job_harness.jobs_db) as connection:
        error_type, message = connection.execute(
            "SELECT error_type, error_message FROM job_run WHERE run_id = ?",
            (job.job_id,),
        ).fetchone()
    assert error_type == "UnauthorizedStoryJob"
    assert message == "The story run no longer exists."
    assert job_harness.calls == []


def test_reusing_an_operation_in_another_run_conflicts(job_harness):
    """The run is part of what the operation ID names."""
    job_harness.submit(operation_id="op-1")
    response = job_harness.submit(
        operation_id="op-1", run_id=job_harness.run(), raw=True
    )
    assert response.status_code == 409
    assert job_harness.worker_submission_count == 1


def test_operation_ids_and_jobs_are_per_principal(job_harness):
    """Bob's operation op-1 is not Alice's, and he cannot see her job."""
    alice_job = job_harness.submit(operation_id="op-1")
    bob_run = job_harness.run(client=job_harness.bob)
    bob_job = job_harness.submit(
        operation_id="op-1", run_id=bob_run, client=job_harness.bob
    )
    assert bob_job.job_id != alice_job.job_id
    assert job_harness.worker_submission_count == 2
    response = job_harness.bob.get(
        f"/api/v1/story/runs/{job_harness.state.run_id}/jobs/{alice_job.job_id}"
    )
    assert response.status_code == 404
    response = job_harness.bob.get(
        f"/api/v1/story/runs/{bob_run}/jobs/{alice_job.job_id}"
    )
    assert response.status_code == 404


def test_a_job_in_another_run_is_not_found(job_harness):
    """A job is reachable only through the run it was submitted for."""
    job = job_harness.submit(operation_id="op-1")
    other_run = job_harness.run()
    assert job_harness.get(job.job_id, run_id=other_run).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"operation_id": "op", "kind": "shell", "payload": {"cmd": "rm -rf /"}},
        {
            "operation_id": "op",
            "kind": "story.backtest",
            "payload": {**BACKTEST, "code": "x"},
        },
        {
            "operation_id": "op",
            "kind": "story.backtest",
            "payload": BACKTEST,
            "handler": "x",
        },
        {"operation_id": "../op", "kind": "story.backtest", "payload": BACKTEST},
    ],
)
def test_generic_or_unknown_payloads_are_rejected(job_harness, body):
    """Only allowlisted kinds with their typed payloads are accepted."""
    run_id = job_harness.run()
    response = job_harness.alice.post(f"/api/v1/story/runs/{run_id}/jobs", json=body)
    assert response.status_code == 422, response.text
    assert job_harness.worker_submission_count == 0


def test_an_unknown_strategy_is_rejected_at_submission(job_harness):
    """The backtest strategy must be a registered one."""
    payload = {**BACKTEST, "config": {**BACKTEST["config"], "strategy": "os.system"}}
    response = job_harness.submit(operation_id="op", payload=payload, raw=True)
    assert response.status_code == 422
    assert "unknown strategy" in response.text


def test_strategy_params_must_be_scalars(job_harness):
    """Strategy keyword arguments are finite scalars or lists of them."""
    payload = {**BACKTEST, "strategy_params": {"symbols": {"nested": "dict"}}}
    response = job_harness.submit(operation_id="op", payload=payload, raw=True)
    assert response.status_code == 422


def test_a_kind_without_its_worker_definition_is_unavailable(job_harness, tmp_path):
    """A server whose worker lacks the definition says so instead of queueing."""
    service = JobService(
        store=SqliteJobStore(tmp_path / "other-jobs.db"), registry=JobRegistry()
    )
    client = _app("alice", tmp_path / "runs.sqlite", job_harness.root, service)
    run_id = job_harness.run(client=client)
    response = client.post(
        f"/api/v1/story/runs/{run_id}/jobs",
        json={"operation_id": "op", "kind": "story.backtest", "payload": BACKTEST},
    )
    assert response.status_code == 503
    assert "worker definition is not registered" in response.text


def test_a_kind_whose_engine_is_missing_is_unavailable(job_harness, monkeypatch):
    """A missing optional engine is a 503 naming it, not a queued failure."""
    real = story_job_kinds.find_spec
    monkeypatch.setattr(
        story_job_kinds,
        "find_spec",
        lambda name: None if name == "tuneta" else real(name),
    )
    response = job_harness.submit(
        operation_id="op",
        kind="story.tune",
        payload={"segment": "Energy"},
        raw=True,
    )
    assert response.status_code == 503
    assert "tuneta" in response.text
    assert job_harness.worker_submission_count == 0


def test_the_worker_runs_the_job_and_writes_a_result_artifact(job_harness):
    """The worker executes the engine; the run gets its full result."""
    job = job_harness.submit(operation_id="op-1", stage_id=None)
    assert job.status == "queued"
    outcome = job_harness.worker.run_once()
    assert outcome.status == "succeeded"
    assert job_harness.calls[0].config.strategy == "buy_and_hold"
    assert job_harness.calls[0].strategy_params == {"symbols": ["AAA", "BBB"]}
    done = job_harness.get(job.job_id).json()
    assert done["status"] == "succeeded"
    assert done["error"] is None
    highlights = done["result"]["highlights"]
    assert highlights["metrics"]["sharpe"] == 1.25
    assert highlights["equity_points"] == 2
    ref = done["result"]["artifact"]
    read = job_harness.alice.get(
        f"/api/v1/story/runs/{ref['run_id']}/artifacts/{ref['artifact_id']}"
    ).json()
    assert read["artifact"]["kind"] == "result"
    assert read["artifact"]["name"] == "story.backtest-op-1"
    assert json.loads(read["text"]) == FAKE_BACKTEST


def test_non_finite_engine_output_becomes_null(job_harness, monkeypatch):
    """A NaN metric cannot make the result artifact invalid JSON."""
    monkeypatch.setattr(
        story_job_kinds,
        "run_backtest",
        lambda payload: {"metrics": {"sharpe": float("nan")}},
    )
    job = job_harness.submit(operation_id="op-nan")
    assert job_harness.worker.run_once().status == "succeeded"
    done = job_harness.get(job.job_id).json()
    assert done["result"]["highlights"]["metrics"]["sharpe"] is None


def test_an_engine_error_is_an_explicit_terminal_failure(job_harness, monkeypatch):
    """A failing engine leaves one failed job with its error, and no artifact."""

    def broken(payload):
        raise ValueError("provider returned no bars")

    monkeypatch.setattr(story_job_kinds, "run_backtest", broken)
    job = job_harness.submit(operation_id="op-fail")
    assert job_harness.worker.run_once().status == "failed"
    done = job_harness.get(job.job_id).json()
    assert done["status"] == "failed"
    assert done["error"] == {
        "type": "ValueError",
        "message": "provider returned no bars",
    }
    assert done["result"] is None
    assert not list(job_harness.root.rglob("*.json"))
    assert job_harness.worker_submission_count == 1


def test_a_job_triggered_outside_the_story_routes_cannot_write(job_harness):
    """A forged run on the jobs API is refused by the handler."""
    run_id = job_harness.run()
    params = StoryJobParams(
        principal="alice",
        run_id=run_id,
        operation_id="forged",
        payload=BACKTEST,
    ).model_dump(mode="json")
    job_harness.service.enqueue("story.backtest", params)
    assert job_harness.worker.run_once().status == "failed"
    with sqlite3.connect(job_harness.jobs_db) as connection:
        error = connection.execute("SELECT error_type FROM job_run").fetchone()[0]
    assert error == "UnauthorizedStoryJob"
    assert job_harness.calls == []
    assert not list(job_harness.root.rglob("*.json"))


def test_a_tampered_queued_payload_is_refused(job_harness):
    """Editing the queued params after submission fails the digest check."""
    job = job_harness.submit(operation_id="op-1")
    with sqlite3.connect(job_harness.jobs_db) as connection:
        params = json.loads(
            connection.execute("SELECT params_json FROM job_run").fetchone()[0]
        )
        params["payload"]["strategy_params"] = {"symbols": ["EVIL"]}
        connection.execute("UPDATE job_run SET params_json = ?", (json.dumps(params),))
    assert job_harness.worker.run_once().status == "failed"
    assert job_harness.get(job.job_id).json()["error"]["type"] == "UnauthorizedStoryJob"
    assert job_harness.calls == []


def test_a_worker_lost_mid_job_ends_in_one_failed_job(job_harness):
    """Restart or timeout: lease recovery fails the run once, no duplicate."""
    job = job_harness.submit(operation_id="op-1")
    claimed = job_harness.service.claim_next("crashed-worker")
    assert claimed.run_id == job.job_id
    later = datetime.now(timezone.utc) + job_harness.service.run_lease_timeout * 2
    job_harness.service.recover_abandoned_runs(later)
    done = job_harness.get(job.job_id).json()
    assert done["status"] == "failed"
    assert done["error"]["type"] == "AbandonedRunRecoveryError"
    assert job_harness.worker.run_once(now=later) is None
    assert job_harness.worker_submission_count == 1
    again = job_harness.submit(operation_id="op-1")
    assert again.job_id == job.job_id
    assert again.status == "failed"


def test_cancel_distinguishes_queued_running_and_finished(job_harness):
    """Cancel confirms a queued job, is too late for a claimed one."""
    queued = job_harness.submit(operation_id="op-queued")
    path = f"/api/v1/story/runs/{job_harness.state.run_id}/jobs"
    cancelled = job_harness.alice.post(f"{path}/{queued.job_id}/cancel").json()
    assert cancelled["outcome"] == "cancelled"
    assert cancelled["job"]["status"] == "cancelled"
    assert job_harness.worker.run_once() is None
    assert job_harness.calls == []

    running = job_harness.submit(operation_id="op-running")
    job_harness.service.claim_next("busy-worker")
    late = job_harness.alice.post(f"{path}/{running.job_id}/cancel").json()
    assert late["outcome"] == "too_late"
    assert late["job"]["status"] == "running"

    again = job_harness.alice.post(f"{path}/{queued.job_id}/cancel").json()
    assert again["outcome"] == "already_finished"


def test_a_principal_may_have_only_a_few_active_jobs(job_harness, monkeypatch):
    """Queued and running jobs are bounded; finished ones do not count."""
    monkeypatch.setattr(jobs, "MAX_ACTIVE_JOBS", 2)
    job_harness.submit(operation_id="a")
    job_harness.submit(operation_id="b")
    assert job_harness.submit(operation_id="c", raw=True).status_code == 429
    # Retrying an existing operation is never refused by the limit.
    assert job_harness.submit(operation_id="a").status == "queued"
    job_harness.worker.run_once()
    assert job_harness.submit(operation_id="c").status == "queued"


def test_the_stage_must_belong_to_the_run(job_harness):
    """A job may name its stage, if the run's story has it."""
    run_id = job_harness.run()
    ok = job_harness.submit(
        operation_id="op-1",
        run_id=run_id,
        stage_id="8-backtest-buy-and-hold-on-the-15-etf-universe-v",
    )
    assert ok.stage_id == "8-backtest-buy-and-hold-on-the-15-etf-universe-v"
    bad = job_harness.submit(
        operation_id="op-2", run_id=run_id, stage_id="nope", raw=True
    )
    assert bad.status_code == 422


def test_unknown_runs_are_not_found(job_harness):
    """Submitting into a run that is not this principal's is a 404."""
    run_id = job_harness.run()
    response = job_harness.submit(
        operation_id="op", run_id=run_id, client=job_harness.bob, raw=True
    )
    assert response.status_code == 404
    assert job_harness.worker_submission_count == 0


def test_list_returns_this_runs_jobs(job_harness):
    """The run's jobs, oldest first, and nobody else's."""
    first = job_harness.submit(operation_id="op-1")
    second = job_harness.submit(operation_id="op-2")
    job_harness.submit(operation_id="op-3", run_id=job_harness.run())
    listed = job_harness.alice.get(
        f"/api/v1/story/runs/{job_harness.state.run_id}/jobs"
    ).json()
    assert [j["job_id"] for j in listed] == [first.job_id, second.job_id]


# --- Kinds ------------------------------------------------------------------


def _trade_plan():
    # pylint: disable=import-outside-toplevel
    from openbb_techtrade.models import (
        EntryExitRule,
        IndicatorVote,
        MoverSignal,
        Recommendation,
        TradePlan,
    )

    as_of = date(2024, 1, 12)
    price = Decimal("121.40")
    signal = MoverSignal(
        symbol="MSFT",
        segment="Information Technology",
        as_of=as_of,
        score=0.7,
        direction="long",
        votes=[IndicatorVote(family="trend", name="macd_hist", vote=1.0, weight=0.4)],
        rank_in_segment=1,
    )
    recommendation = Recommendation(
        symbol="MSFT",
        segment="Information Technology",
        as_of=as_of,
        action="BUY",
        conviction="High",
        score=0.7,
        entry_price=price,
        stop_price=Decimal("117.60"),
        target_price=Decimal("129.00"),
        stop_distance_pct=0.03,
        target_distance_pct=0.06,
        risk_reward=2.0,
        atr=1.9,
        position_size=Decimal(10),
        risk_per_share=Decimal("3.80"),
        risk_pct_of_notional=0.01,
        time_stop_bars=20,
        reasoning="Long MSFT.",
        top_factors=[],
        caveats="None.",
    )
    plan = TradePlan(
        symbol="MSFT",
        segment="Information Technology",
        as_of=as_of,
        signal=signal,
        rule=EntryExitRule(),
        position_size=Decimal(10),
        recommendation=recommendation,
    )
    return json.loads(plan.model_dump_json())


@pytest.mark.parametrize(
    ("kind", "engine", "payload", "fake", "highlights"),
    [
        (
            "story.single_name",
            "run_single_name",
            {"symbol": "MSFT"},
            {
                "phases": {
                    "p1": {},
                    "p7": {"action_label": "BUY", "composite_score": 3.9},
                }
            },
            {"action_label": "BUY", "composite_score": 3.9, "phases": ["p1", "p7"]},
        ),
        (
            "story.validate",
            "run_validate",
            "PLAN",
            {
                "report": {
                    "verdict": "robust",
                    "method": "wfo",
                    "pbo": 0.1,
                    "deflated_sharpe": 0.9,
                    "folds": [{}, {}],
                },
                "plan": {},
            },
            {
                "verdict": "robust",
                "method": "wfo",
                "pbo": 0.1,
                "deflated_sharpe": 0.9,
                "folds": 2,
            },
        ),
        (
            "story.replay",
            "run_replay_job",
            {
                "as_of": "2024-01-12",
                "recommendations": [
                    {
                        "symbol": "MSFT",
                        "action": "BUY",
                        "entry_price": 100,
                        "stop_price": 95,
                        "target_price": 110,
                        "position_size": 1,
                    }
                ],
            },
            {"outcomes": [{"status": "target"}], "summary": {"win_rate": 1.0}},
            {"outcomes": 1, "summary": {"win_rate": 1.0}},
        ),
    ],
)
def test_each_kind_runs_its_engine_with_the_typed_payload(
    job_harness, monkeypatch, kind, engine, payload, fake, highlights
):
    """Every kind validates its payload, runs its engine and keeps its headline."""
    seen = []

    def stub(typed):
        seen.append(typed)
        return fake

    monkeypatch.setattr(story_job_kinds, engine, stub)
    payload = {"plan": _trade_plan(), "method": "wfo"} if payload == "PLAN" else payload
    job = job_harness.submit(operation_id="op-k", kind=kind, payload=payload)
    assert job_harness.worker.run_once().status == "succeeded"
    assert (
        type(seen[0]).__name__
        == type(KINDS[kind].payload().model_validate(payload)).__name__
    )
    done = job_harness.get(job.job_id).json()
    assert done["result"]["highlights"] == highlights
    assert done["result"]["kind"] == kind


def test_tune_payloads_cannot_ask_to_persist():
    """A story tune never writes the operator's tuned defaults."""
    model = KINDS["story.tune"].payload
    try:
        tune_model = model()
    except story_job_kinds.KindUnavailable:
        pytest.skip("tuneta is not installed")
    with pytest.raises(ValueError):
        tune_model.model_validate({"segment": "Energy", "persist": True})
    with pytest.raises(ValueError):
        tune_model.model_validate({"segment": "Not A Sector"})


def test_the_tune_engine_always_passes_persist_false(monkeypatch):
    """The engine seam hard-codes persist=False whatever the payload says."""
    seen = {}

    async def fake_tune(segment, **kwargs):
        seen.update(kwargs, segment=segment)
        return SimpleNamespace(results=SimpleNamespace(model_dump=lambda mode: {}))

    from openbb_techtrade.tuning import (
        tune_router,
    )  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(tune_router, "tune", fake_tune)
    payload = SimpleNamespace(
        segment="Energy",
        as_of=None,
        horizon_years=5,
        forward_horizon_bars=5,
        trials=10,
        early_stop=5,
        method="wfo",
    )
    story_job_kinds.run_tune(payload)
    assert seen["persist"] is False
    assert seen["segment"] == "Energy"


def test_validate_rejects_unknown_thresholds(job_harness):
    """Threshold overrides are limited to the four verdict thresholds."""
    payload = {"plan": _trade_plan(), "thresholds": {"anything": 1.0}}
    response = job_harness.submit(
        operation_id="op", kind="story.validate", payload=payload, raw=True
    )
    assert response.status_code == 422


def test_definitions_are_the_allowlist_with_no_retries():
    """Five kinds, one attempt each, all taking the same strict params."""
    definitions = get_job_definitions()
    assert (
        {d.name for d in definitions}
        == set(KINDS)
        == {
            "story.single_name",
            "story.backtest",
            "story.validate",
            "story.tune",
            "story.replay",
        }
    )
    assert all(d.max_attempts == 1 and d.schedule is None for d in definitions)
    assert all(d.params_model is StoryJobParams for d in definitions)


def test_the_worker_discovers_the_kinds_through_the_entry_point():
    """The package registers the definitions with openbb_job_extension."""
    import tomllib

    pyproject = tomllib.loads(
        (REPO_ROOT / "openbb_platform/extensions/mcp_server/pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    plugins = pyproject["tool"]["poetry"]["plugins"]["openbb_job_extension"]
    assert plugins == {
        "story": "openbb_mcp_server.story_adapters.story_job_kinds:get_job_definitions"
    }


def test_the_job_routes_are_four_mcp_tools(tmp_path):
    """Submit, list, get and cancel; each depends on the authenticated service."""
    app = compose_story_jobs_app(
        FastAPI(), principal="alice", store_path=tmp_path / "r.sqlite"
    )
    routes = [r for r in app.routes if getattr(r, "openapi_extra", None)]
    assert {r.openapi_extra["mcp_config"]["name"] for r in routes} == {
        "story_job_submit",
        "story_job_list",
        "story_job_get",
        "story_job_cancel",
    }
    assert not (tmp_path / "r.sqlite").exists()
    with pytest.raises(ValueError):
        compose_story_jobs_app(FastAPI(), principal="")


def test_job_views_never_carry_a_filesystem_path(job_harness):
    """No submission or result names a local path."""
    job = job_harness.submit(operation_id="op-1")
    job_harness.worker.run_once()
    blob = json.dumps(job_harness.get(job.job_id).json()) + json.dumps(
        vars(job), default=str
    )
    for marker in (str(job_harness.root), job_harness.root.as_posix(), "jobs.db"):
        assert marker not in blob


def _has_fmp_cached_key() -> bool:
    """Return whether a fmp_cached key is configured where the Platform looks."""
    if os.getenv("OPENBB_FMP_CACHED_API_KEY") or os.getenv("FMP_API_KEY"):
        return True
    settings = Path.home() / ".openbb_platform" / "user_settings.json"
    try:
        credentials = json.loads(settings.read_text(encoding="utf-8")).get(
            "credentials", {}
        )
    except (OSError, ValueError):
        return False
    return bool(credentials.get("fmp_cached_api_key"))


@pytest.mark.integration
@pytest.mark.skipif(
    not _has_fmp_cached_key(),
    reason="live run needs a fmp_cached_api_key (environment or user_settings.json)",
)
def test_live_backtest_job_runs_on_the_real_engine(tmp_path, monkeypatch):
    """One honest story.backtest through the real worker and engine."""
    store = tmp_path / "runs.sqlite"
    root = tmp_path / "artifacts"
    monkeypatch.setenv("OPENBB_STORY_RUN_STORE", str(store))
    monkeypatch.setenv("OPENBB_STORY_ARTIFACT_ROOT", str(root))
    service = JobService(
        store=SqliteJobStore(tmp_path / "jobs.db"),
        registry=JobRegistry(get_job_definitions()),
    )
    client = _app("live", store, root, service)
    run_id = client.post("/api/v1/story/runs", json={"story_id": "portfolio/08"})
    run_id = run_id.json()["run_id"]
    payload = {
        "config": {
            "strategy": "buy_and_hold",
            "universe": ["SPY", "AGG"],
            "start": "2024-01-02",
            "end": "2024-06-28",
            "benchmark": "SPY",
        },
        "strategy_params": {"symbols": ["SPY", "AGG"]},
    }
    job = client.post(
        f"/api/v1/story/runs/{run_id}/jobs",
        json={"operation_id": "live-1", "kind": "story.backtest", "payload": payload},
    )
    assert job.status_code == 202, job.text
    assert JobWorker(service=service, worker_id="live").run_once().status == "succeeded"
    view = client.get(f"/api/v1/story/runs/{run_id}/jobs/{job.json()['job_id']}")
    highlights = view.json()["result"]["highlights"]
    assert highlights["equity_points"] > 100, "a half-year of daily bars"
    assert highlights["metrics"]["sharpe"] is not None


def test_an_unattached_submission_cannot_authorize_a_forged_run(
    job_harness, monkeypatch
):
    """A run with identical params but no recorded job ID is refused."""
    monkeypatch.setattr(story_job_kinds, "ATTACH_WAIT_SECONDS", 0.05)
    run_id = job_harness.run()
    _crash_after_recording(job_harness, "op-1", run_id)
    params = StoryJobParams(
        principal="alice", run_id=run_id, operation_id="op-1", payload=BACKTEST
    )
    # Normalize the payload exactly as the routes do, so only the job ID differs.
    payload = story_job_kinds.payload_model("story.backtest").model_validate(BACKTEST)
    params = params.model_copy(update={"payload": payload.model_dump(mode="json")})
    job_harness.service.enqueue("story.backtest", params.model_dump(mode="json"))
    assert job_harness.worker.run_once().status == "failed"
    with sqlite3.connect(job_harness.jobs_db) as connection:
        error = connection.execute("SELECT error_type FROM job_run").fetchone()[0]
    assert error == "UnauthorizedStoryJob"
    assert job_harness.calls == []


def test_a_job_claimed_before_its_id_is_recorded_waits_for_it(job_harness, monkeypatch):
    """The worker waits for the routes to record the job ID, then runs."""
    job = job_harness.submit(operation_id="op-1")
    with sqlite3.connect(job_harness.store) as connection:
        connection.execute("UPDATE story_jobs SET job_id = NULL")
    ledger = story_job_kinds.SubmissionLedger(job_harness.store)
    sleeps = []

    def attach_during_wait(seconds):
        sleeps.append(seconds)
        ledger.attach_job("alice", "op-1", job.job_id)

    monkeypatch.setattr(story_job_kinds.time, "sleep", attach_during_wait)
    assert job_harness.worker.run_once().status == "succeeded"
    assert sleeps, "the worker never waited for the job ID"
    assert len(job_harness.calls) == 1
