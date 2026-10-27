"""Story catalog, run registry and typed run state contracts (#2216, N06)."""

# pylint: disable=redefined-outer-name

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_mcp_server.story_adapters.registry import (
    MAX_STATE_BYTES,
    compose_story_registry_app,
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


def _client(principal: str, store: Path, manifests: Path = MANIFESTS) -> TestClient:
    app = compose_story_registry_app(
        FastAPI(), principal=principal, manifest_dir=manifests, store_path=store
    )
    return TestClient(app)


@pytest.fixture
def registry_harness(tmp_path):
    """Two principals sharing one run store, plus helpers."""
    store = tmp_path / "runs.sqlite"
    alice = _client("alice", store)
    bob = _client("bob", store)

    def create_run(story_id="portfolio/03", client=alice):
        response = client.post("/api/v1/story/runs", json={"story_id": story_id})
        assert response.status_code == 200, response.text
        return SimpleNamespace(**response.json(), id=response.json()["run_id"])

    def first_stage(run):
        return next(iter(run.stage_status))

    def checkpoint(run_id, expected_version, stage_id=None, client=alice, **body):
        run = client.get(f"/api/v1/story/runs/{run_id}")
        stage = stage_id or next(iter(run.json()["stage_status"]))
        return client.post(
            f"/api/v1/story/runs/{run_id}/checkpoint",
            json={
                "expected_version": expected_version,
                "stage_id": stage,
                "status": body.pop("status", "succeeded"),
                **body,
            },
        )

    return SimpleNamespace(
        alice=alice,
        bob=bob,
        create_run=create_run,
        first_stage=first_stage,
        checkpoint=checkpoint,
    )


def test_catalog_lists_all_25_story_variants(registry_harness):
    """The catalog covers every story and both Portfolio provider variants."""
    response = registry_harness.alice.get("/api/v1/story/catalog")
    assert response.status_code == 200
    stories = response.json()
    assert len(stories) == 25
    assert {s["variant"] for s in stories} == {
        "portfolio",
        "free-provider",
        "techtrade",
    }
    assert all("@" in s["manifest_version"] for s in stories)


def test_describe_returns_the_reviewed_manifest(registry_harness):
    """A story's stages and cells are inspectable without running it."""
    response = registry_harness.alice.get(
        "/api/v1/story/describe", params={"story_id": "portfolio/03"}
    )
    assert response.status_code == 200
    assert response.json()["story_id"] == "portfolio/03"
    assert response.json()["stages"]
    missing = registry_harness.alice.get(
        "/api/v1/story/describe", params={"story_id": "portfolio/99"}
    )
    assert missing.status_code == 404


def test_new_run_starts_at_version_zero_with_pending_stages(registry_harness):
    """A run is created empty, pinned to an immutable manifest version."""
    run = registry_harness.create_run()
    assert run.state_version == 0
    assert set(run.stage_status.values()) == {"pending"}
    assert run.manifest_version.startswith("portfolio/03@")
    assert len(run.run_id) == 32


def test_stale_checkpoint_cannot_overwrite_state(registry_harness):
    """The plan's anchor case: a second write from version 0 conflicts."""
    run = registry_harness.create_run()
    first = registry_harness.checkpoint(run.id, expected_version=0)
    assert first.status_code == 200
    assert first.json()["state_version"] == 1
    stale = registry_harness.checkpoint(run.id, expected_version=0, status="failed")
    assert stale.status_code == 409
    after = registry_harness.alice.get(f"/api/v1/story/runs/{run.id}").json()
    assert after["state_version"] == 1
    assert set(after["stage_status"].values()) >= {"succeeded"}
    assert "failed" not in after["stage_status"].values()


def test_another_principal_cannot_read_or_write_a_run(registry_harness):
    """Run IDs are principal-scoped; another principal sees no such run."""
    run = registry_harness.create_run()
    assert registry_harness.bob.get(f"/api/v1/story/runs/{run.id}").status_code == 404
    write = registry_harness.bob.post(
        f"/api/v1/story/runs/{run.id}/checkpoint",
        json={
            "expected_version": 0,
            "stage_id": registry_harness.first_stage(run),
            "status": "succeeded",
        },
    )
    assert write.status_code == 404
    owner_view = registry_harness.alice.get(f"/api/v1/story/runs/{run.id}").json()
    assert owner_view["state_version"] == 0


def test_state_handoff_retains_provenance(registry_harness):
    """Stage state keeps its provider, tool-call and artifact provenance."""
    run = registry_harness.create_run()
    stage = registry_harness.first_stage(run)
    response = registry_harness.checkpoint(
        run.id,
        expected_version=0,
        stage_id=stage,
        state={"basket": {"asset_a": 0.5, "asset_b": 0.5}},
        provenance={
            "provider": "fmp_cached",
            "tool_call_ids": ["call-1"],
            "artifact_ids": ["artifact-1"],
            "source_story": "portfolio/02",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"][stage] == {"basket": {"asset_a": 0.5, "asset_b": 0.5}}
    assert body["provenance"][stage]["source_story"] == "portfolio/02"
    assert body["provenance"][stage]["tool_call_ids"] == ["call-1"]


def test_unknown_stage_is_rejected(registry_harness):
    """A checkpoint must name a stage of the run's pinned manifest."""
    run = registry_harness.create_run()
    response = registry_harness.checkpoint(run.id, expected_version=0, stage_id="ghost")
    assert response.status_code == 422


def test_state_must_be_a_bounded_json_object(registry_harness):
    """Non-object or oversized state is refused before anything is written."""
    run = registry_harness.create_run()
    not_object = registry_harness.checkpoint(run.id, expected_version=0, state=[1, 2])
    assert not_object.status_code == 422
    huge = registry_harness.checkpoint(
        run.id, expected_version=0, state={"blob": "x" * (MAX_STATE_BYTES + 1)}
    )
    assert huge.status_code == 413
    unchanged = registry_harness.alice.get(f"/api/v1/story/runs/{run.id}").json()
    assert unchanged["state_version"] == 0


def test_unknown_story_cannot_start_a_run(registry_harness):
    """Runs exist only for reviewed stories."""
    response = registry_harness.alice.post(
        "/api/v1/story/runs", json={"story_id": "portfolio/99"}
    )
    assert response.status_code == 404


def test_missing_manifests_are_an_explicit_unavailable_error(tmp_path):
    """Without the agents package the catalog says so instead of listing nothing."""
    client = _client("alice", tmp_path / "runs.sqlite", manifests=tmp_path / "none")
    response = client.get("/api/v1/story/catalog")
    assert response.status_code == 503


def test_registry_requires_a_principal(tmp_path):
    """An unauthenticated server cannot compose principal-scoped runs."""
    with pytest.raises(ValueError, match="principal"):
        compose_story_registry_app(
            FastAPI(), principal="", manifest_dir=MANIFESTS, store_path=tmp_path / "r"
        )


def test_composing_the_routes_writes_nothing(tmp_path):
    """Building a server must not create the run store."""
    store = tmp_path / "nested" / "runs.sqlite"
    compose_story_registry_app(
        FastAPI(), principal="alice", manifest_dir=MANIFESTS, store_path=store
    )
    assert not store.exists()
    assert not store.parent.exists()


def test_store_location_can_be_overridden(tmp_path, monkeypatch):
    """Operators can move the run store without code changes."""
    # pylint: disable=import-outside-toplevel
    from openbb_mcp_server.story_adapters.registry import STORE_ENV, default_store_path

    monkeypatch.setenv(STORE_ENV, str(tmp_path / "custom.sqlite"))
    assert default_store_path() == tmp_path / "custom.sqlite"


async def _server(profile, monkeypatch, tmp_path):
    # pylint: disable=import-outside-toplevel
    from openbb_mcp_server.app.app import create_mcp_server
    from openbb_mcp_server.models.settings import MCPSettings
    from openbb_mcp_server.story_adapters import registry

    monkeypatch.setattr(registry, "default_manifest_dir", lambda: MANIFESTS)
    monkeypatch.setenv(registry.STORE_ENV, str(tmp_path / "runs.sqlite"))
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile=profile,
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    auth = ("synthetic-user", "x" * 32) if profile != "platform-standard" else None
    return create_mcp_server(settings, FastAPI(), auth=auth)


STORY_TOOLS = {
    "story_catalog",
    "story_describe",
    "story_run_create",
    "story_run_get",
    "story_run_checkpoint",
}


@pytest.mark.asyncio
async def test_portfolio_profile_exposes_story_tools(monkeypatch, tmp_path):
    """The five tools are admitted to portfolio-read by the reviewed policy."""
    mcp = await _server("portfolio-read", monkeypatch, tmp_path)
    names = {tool.name for tool in await mcp.list_tools()}
    assert names >= STORY_TOOLS


@pytest.mark.asyncio
async def test_standard_profile_has_no_story_tools(monkeypatch, tmp_path):
    """The compatibility default never composes story run state."""
    mcp = await _server("platform-standard", monkeypatch, tmp_path)
    names = {tool.name for tool in await mcp.list_tools()}
    assert not names & STORY_TOOLS


@pytest.mark.asyncio
async def test_run_lifecycle_over_mcp(monkeypatch, tmp_path):
    """Create, checkpoint and conflict through real MCP tool calls."""
    mcp = await _server("portfolio-read", monkeypatch, tmp_path)
    catalog = await mcp.call_tool("story_catalog", {})
    assert len(catalog.structured_content["result"]) == 25
    run = await mcp.call_tool("story_run_create", {"story_id": "portfolio/03"})
    record = run.structured_content
    stage = next(iter(record["stage_status"]))
    body = {
        "run_id": record["run_id"],
        "expected_version": 0,
        "stage_id": stage,
        "status": "succeeded",
        "state": {"done": True},
    }
    first = await mcp.call_tool("story_run_checkpoint", body)
    assert first.structured_content["state_version"] == 1
    with pytest.raises(Exception, match="409|version"):
        await mcp.call_tool("story_run_checkpoint", body)
    assert (tmp_path / "runs.sqlite").exists()
