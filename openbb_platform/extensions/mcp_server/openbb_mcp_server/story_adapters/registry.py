"""Story catalog, run registry and typed run state (#2216, N06).

Routes under ``/api/v1/story``:

- ``GET /catalog`` and ``GET /describe``: metadata reads over the reviewed
  story manifests. They never run a notebook.
- ``POST /runs``, ``GET /runs/{run_id}`` and
  ``POST /runs/{run_id}/checkpoint``: principal-scoped run state with
  optimistic concurrency. A checkpoint names the state version it read; a
  stale version is a ``409`` and changes nothing.

Run state is JSON only and size-bounded. Nothing here reads arbitrary files or
deserializes notebook pickle state. The principal is bound when the routes are
composed: an MCP server has one effective credential, so every call it serves
belongs to that principal, and another credential cannot see its runs.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status
from openbb_core.app.service.auth_service import AuthService
from pydantic import BaseModel, ConfigDict, Field

MAX_STATE_BYTES = 64 * 1024
ProviderMode = Literal["fixture", "recorded", "live"]
StageStatus = Literal[
    "pending", "running", "succeeded", "failed", "unavailable", "approval_required"
]


class StorySummary(BaseModel):
    """Catalog entry for one reviewed story manifest."""

    model_config = ConfigDict(extra="forbid")

    story_id: str
    family: str
    variant: str
    notebook_path: str
    manifest_version: str
    stages: int
    optional_stages: int


class Provenance(BaseModel):
    """Where a checkpoint's state came from."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    tool_call_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    source_story: str | None = None


class RunCreate(BaseModel):
    """Request to start a run of one story."""

    model_config = ConfigDict(extra="forbid")

    story_id: str
    provider_mode: ProviderMode = "fixture"


class Checkpoint(BaseModel):
    """One stage's result, written only against the version it read."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    stage_id: str
    status: StageStatus
    state: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)


class RunRecord(BaseModel):
    """A run as its principal sees it."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    story_id: str
    manifest_version: str
    provider_mode: ProviderMode
    state_version: int
    stage_status: dict[str, StageStatus]
    state: dict[str, dict[str, Any]]
    provenance: dict[str, Provenance]
    created_at: datetime
    updated_at: datetime


class StaleCheckpoint(Exception):
    """The checkpoint was computed from an older state version."""


class StoryCatalog:
    """Read-only view over the reviewed story manifests."""

    def __init__(self, manifest_dir: Path | None):
        """Load every ``*__*.json`` manifest under ``manifest_dir``, if present."""
        self._manifests: dict[str, dict[str, Any]] = {}
        self.available = False
        if manifest_dir is None or not manifest_dir.is_dir():
            return
        self.available = True
        for path in sorted(manifest_dir.glob("*__*.json")):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            self._manifests[manifest["story_id"]] = manifest

    @staticmethod
    def version(manifest: dict[str, Any]) -> str:
        """Immutable manifest version: story ID plus source fingerprint."""
        return f"{manifest['story_id']}@{manifest['source_sha256'][:12]}"

    def summaries(self) -> list[StorySummary]:
        """Every story, in story order."""
        return [
            StorySummary(
                story_id=m["story_id"],
                family=m["family"],
                variant=m["variant"],
                notebook_path=m["notebook_path"],
                manifest_version=self.version(m),
                stages=len(m["stages"]),
                optional_stages=sum(bool(s["optional"]) for s in m["stages"]),
            )
            for _, m in sorted(self._manifests.items())
        ]

    def get(self, story_id: str) -> dict[str, Any] | None:
        """Return a copy of one manifest, or ``None``."""
        manifest = self._manifests.get(story_id)
        return copy.deepcopy(manifest) if manifest is not None else None


class RunStore:
    """SQLite run store with optimistic concurrency per run."""

    def __init__(self, path: Path):
        """Bind the store to ``path``; the database is created on first use."""
        # Nothing touches disk until the first run is created or read, so
        # composing the routes into a server has no filesystem side effect.
        self.path = path
        self._ready = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if not self._ready:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, isolation_level=None)
        if not self._ready:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS story_runs ("
                " run_id TEXT PRIMARY KEY, principal TEXT NOT NULL,"
                " version INTEGER NOT NULL, record TEXT NOT NULL)"
            )
            self._ready = True
        try:
            yield connection
        finally:
            connection.close()

    def create(self, principal: str, record: RunRecord) -> RunRecord:
        """Persist a new run for ``principal``."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO story_runs (run_id, principal, version, record)"
                " VALUES (?, ?, ?, ?)",
                (record.run_id, principal, 0, record.model_dump_json()),
            )
        return record

    def get(self, principal: str, run_id: str) -> RunRecord | None:
        """Return the run only if ``principal`` owns it."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record FROM story_runs WHERE run_id = ? AND principal = ?",
                (run_id, principal),
            ).fetchone()
        return RunRecord.model_validate_json(row[0]) if row else None

    def checkpoint(
        self, principal: str, run_id: str, expected_version: int, updated: RunRecord
    ) -> RunRecord:
        """Write ``updated`` only if the stored version is ``expected_version``."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    "UPDATE story_runs SET version = ?, record = ?"
                    " WHERE run_id = ? AND principal = ? AND version = ?",
                    (
                        expected_version + 1,
                        updated.model_dump_json(),
                        run_id,
                        principal,
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StaleCheckpoint(run_id)
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return updated


def default_manifest_dir() -> Path | None:
    """Locate the reviewed manifests shipped with the agents package."""
    spec = importlib.util.find_spec("openbb_agents")
    if spec is None or not spec.submodule_search_locations:
        return None
    return (
        Path(next(iter(spec.submodule_search_locations))) / "notebook_guide" / "stories"
    )


STORE_ENV = "OPENBB_STORY_RUN_STORE"


def default_store_path() -> Path:
    """Run store location: ``$OPENBB_STORY_RUN_STORE`` or the user directory."""
    override = os.environ.get(STORE_ENV)
    if override:
        return Path(override)
    return Path.home() / ".openbb_platform" / "story_runs.sqlite"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def build_router(catalog: StoryCatalog, store: RunStore, principal: str) -> APIRouter:
    """Return the story routes bound to one principal."""
    router = APIRouter(prefix="/api/v1/story", tags=["story"])
    authenticated = [Depends(AuthService().auth_hook)]

    def _available() -> None:
        if not catalog.available:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Story manifests are not installed (openbb-agents).",
            )

    def _manifest(story_id: str) -> dict[str, Any]:
        _available()
        manifest = catalog.get(story_id)
        if manifest is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Unknown story '{story_id}'."
            )
        return manifest

    @router.get(
        "/catalog",
        operation_id="story_catalog",
        openapi_extra={"mcp_config": {"name": "story_catalog"}},
    )
    def story_catalog() -> list[StorySummary]:
        """List every reviewed notebook story without running it."""
        _available()
        return catalog.summaries()

    @router.get(
        "/describe",
        operation_id="story_describe",
        openapi_extra={"mcp_config": {"name": "story_describe"}},
    )
    def story_describe(
        story_id: Annotated[str, Query(description="Story ID, e.g. portfolio/03")],
    ) -> dict[str, Any]:
        """Return one story's reviewed manifest: stages, cells and capabilities."""
        return _manifest(story_id)

    @router.post(
        "/runs",
        operation_id="story_run_create",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_run_create"}},
    )
    def story_run_create(request: RunCreate) -> RunRecord:
        """Start a run of one story; state begins empty at version 0."""
        manifest = _manifest(request.story_id)
        now = _now()
        record = RunRecord(
            run_id=uuid.uuid4().hex,
            story_id=request.story_id,
            manifest_version=catalog.version(manifest),
            provider_mode=request.provider_mode,
            state_version=0,
            stage_status={stage["id"]: "pending" for stage in manifest["stages"]},
            state={},
            provenance={},
            created_at=now,
            updated_at=now,
        )
        return store.create(principal, record)

    def _owned_run(run_id: str) -> RunRecord:
        record = store.get(principal, run_id)
        if record is None:
            # Another principal's run is indistinguishable from no run.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown run.")
        return record

    @router.get(
        "/runs/{run_id}",
        operation_id="story_run_get",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_run_get"}},
    )
    def story_run_get(run_id: str) -> RunRecord:
        """Return a run owned by this principal."""
        return _owned_run(run_id)

    @router.post(
        "/runs/{run_id}/checkpoint",
        operation_id="story_run_checkpoint",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_run_checkpoint"}},
    )
    def story_run_checkpoint(run_id: str, checkpoint: Checkpoint) -> RunRecord:
        """Record one stage's status and JSON state against the version read."""
        record = _owned_run(run_id)
        if checkpoint.stage_id not in record.stage_status:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Stage '{checkpoint.stage_id}' is not in {record.manifest_version}.",
            )
        if len(json.dumps(checkpoint.state).encode("utf-8")) > MAX_STATE_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"Stage state exceeds {MAX_STATE_BYTES} bytes.",
            )
        if checkpoint.expected_version != record.state_version:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Run is at version {record.state_version}; reload before writing.",
            )
        updated = record.model_copy(
            update={
                "state_version": record.state_version + 1,
                "stage_status": {
                    **record.stage_status,
                    checkpoint.stage_id: checkpoint.status,
                },
                "state": {**record.state, checkpoint.stage_id: checkpoint.state},
                "provenance": {
                    **record.provenance,
                    checkpoint.stage_id: checkpoint.provenance,
                },
                "updated_at": _now(),
            }
        )
        try:
            return store.checkpoint(
                principal, run_id, checkpoint.expected_version, updated
            )
        except StaleCheckpoint as error:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Run changed concurrently; reload before writing.",
            ) from error

    return router


def compose_story_registry_app(
    source_app: FastAPI,
    *,
    principal: str,
    manifest_dir: Path | None = None,
    store_path: Path | None = None,
) -> FastAPI:
    """Add the story routes, bound to ``principal``, to an isolated app copy."""
    if not principal:
        raise ValueError("The story registry requires an authenticated principal")
    catalog = StoryCatalog(
        manifest_dir if manifest_dir is not None else default_manifest_dir()
    )
    store = RunStore(store_path if store_path is not None else default_store_path())
    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    composed.include_router(build_router(catalog, store, principal))
    composed.openapi_schema = None
    return composed
