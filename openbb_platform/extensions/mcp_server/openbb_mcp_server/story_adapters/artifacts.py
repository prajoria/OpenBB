"""Bounded, run-scoped story artifacts (#2217, N07).

Routes under ``/api/v1/story``:

- ``POST /runs/{run_id}/artifacts/{table,chart,report,workbook}``: render a
  typed table (CSV or JSON), chart spec, HTML report or XLSX workbook.
- ``POST /runs/{run_id}/artifacts/techtrade_workbook``: the existing six-sheet
  TechTrade export, written into the run instead of ``Analysis/exports``.
- ``GET /artifacts`` and ``GET /runs/{run_id}/artifacts/{artifact_id}``: list
  and read artifacts the principal owns.

Every artifact belongs to one run of one principal. Its ID is a server-issued
32-hex token and its name is a label, so no caller input ever becomes a path.
Files are created atomically under the store root and never overwritten; the
root and run directories must be real directories, not links. Writes are
bounded per file and per run, spreadsheet cells cannot carry formulas, and
reads re-hash the bytes before serving them. Each artifact carries a
retention period; expired ones read as ``410`` and are purged on later writes.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
import sqlite3
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status
from openbb_core.app.service.auth_service import AuthService
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
)

from openbb_mcp_server.story_adapters.artifact_render import (
    XLSX_MEDIA_TYPE,
    ArtifactKind,
    ArtifactRecord,
    ArtifactRefOut,
    ChartRequest,
    ReportRequest,
    SheetView,
    TableRequest,
    TechTradeWorkbookRequest,
    WorkbookRequest,
    WriteRequest,
    render_chart,
    render_csv,
    render_report,
    render_table_json,
    render_techtrade_workbook,
    render_workbook,
    workbook_view,
)
from openbb_mcp_server.story_adapters.registry import (
    RunStore,
    default_store_path,
)

MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_RUN_BYTES = 32 * 1024 * 1024
MAX_ARTIFACTS_PER_RUN = 50
MAX_INLINE_CHARS = 256 * 1024
MAX_PREVIEW_ROWS = 200

ARTIFACT_ROOT_ENV = "OPENBB_STORY_ARTIFACT_ROOT"

_TOKEN = re.compile(r"^[a-f0-9]{32}$")


class InvalidArtifactId(ValueError):
    """An artifact or run ID that the server could not have issued."""


class ArtifactNotFound(LookupError):
    """No such artifact for this principal and run."""


class ArtifactExpired(LookupError):
    """The artifact is past its retention period."""


class ArtifactConflict(Exception):
    """The name is taken, or the location or bytes are not what was written."""


class ArtifactTooLarge(Exception):
    """The artifact or the run would exceed its size or count limit."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token(value: str, what: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise InvalidArtifactId(f"{what} must be a server-issued 32-hex ID.")
    return value


class ArtifactContent(BaseModel):
    """An artifact's metadata and a bounded view of its content."""

    model_config = ConfigDict(extra="forbid")

    artifact: ArtifactRecord
    text: str | None = None
    truncated: bool = False
    workbook: list[SheetView] | None = None


# --- Store ------------------------------------------------------------------


class ArtifactStore:
    """Files under a root directory, metadata in the run store's SQLite file."""

    def __init__(self, root: Path, db_path: Path):
        """Bind the store; nothing touches disk until the first write or read."""
        self.root = root
        self.db_path = db_path
        self._ready = False

    @staticmethod
    def principal_key(principal: str) -> str:
        """Directory name for a principal: a digest, never the principal itself."""
        return hashlib.sha256(principal.encode("utf-8")).hexdigest()[:32]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if not self._ready:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, isolation_level=None)
        if not self._ready:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS story_artifacts ("
                " artifact_id TEXT PRIMARY KEY, principal TEXT NOT NULL,"
                " run_id TEXT NOT NULL, name TEXT NOT NULL,"
                " extension TEXT NOT NULL, size_bytes INTEGER NOT NULL,"
                " created_at TEXT NOT NULL, expires_at TEXT NOT NULL,"
                " record TEXT NOT NULL, UNIQUE (principal, run_id, name))"
            )
            self._ready = True
        try:
            yield connection
        finally:
            connection.close()

    def _run_dir(self, principal: str, run_id: str, *, create: bool) -> Path:
        """Return the run directory, refusing links and anything outside root."""
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or _is_junction(self.root):
            raise ArtifactConflict("The artifact root is a link.")
        root = self.root.resolve(strict=create)
        expected = root / self.principal_key(principal) / run_id
        directory = self.root / self.principal_key(principal) / run_id
        for part in (directory.parent, directory):
            if part.is_symlink() or _is_junction(part):
                raise ArtifactConflict("An artifact directory is a link.")
            if create:
                part.mkdir(exist_ok=True)
        if create and directory.resolve(strict=True) != expected:
            raise ArtifactConflict("An artifact directory resolves outside the root.")
        return directory

    def _purge_expired(self, principal: str) -> None:
        now = _now().isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT artifact_id, run_id, extension FROM story_artifacts"
                " WHERE principal = ? AND expires_at <= ?",
                (principal, now),
            ).fetchall()
            for artifact_id, run_id, extension in rows:
                path = (
                    self._run_dir(principal, run_id, create=False)
                    / f"{artifact_id}.{extension}"
                )
                if path.is_file() and not path.is_symlink():
                    path.unlink()
                connection.execute(
                    "DELETE FROM story_artifacts WHERE artifact_id = ?", (artifact_id,)
                )

    def write(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        principal: str,
        run_id: str,
        *,
        story_id: str,
        name: str,
        kind: str,
        media_type: str,
        extension: str,
        payload: bytes,
        retention_days: int,
        stage_id: str | None = None,
    ) -> ArtifactRecord:
        """Create one artifact atomically; never replace an existing one."""
        _token(run_id, "run_id")
        if len(payload) > MAX_ARTIFACT_BYTES:
            raise ArtifactTooLarge(
                f"Artifacts are limited to {MAX_ARTIFACT_BYTES} bytes."
            )
        self._purge_expired(principal)
        with self._connect() as connection:
            count, used = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM story_artifacts"
                " WHERE principal = ? AND run_id = ?",
                (principal, run_id),
            ).fetchone()
            taken = connection.execute(
                "SELECT 1 FROM story_artifacts"
                " WHERE principal = ? AND run_id = ? AND name = ?",
                (principal, run_id, name),
            ).fetchone()
        if taken:
            raise ArtifactConflict(f"Run already has an artifact named '{name}'.")
        if count >= MAX_ARTIFACTS_PER_RUN:
            raise ArtifactTooLarge(
                f"A run holds at most {MAX_ARTIFACTS_PER_RUN} artifacts."
            )
        if used + len(payload) > MAX_RUN_BYTES:
            raise ArtifactTooLarge(
                f"A run's artifacts are limited to {MAX_RUN_BYTES} bytes."
            )

        artifact_id = uuid.uuid4().hex
        directory = self._run_dir(principal, run_id, create=True)
        final = directory / f"{artifact_id}.{extension}"
        _create_exclusive(directory, final, payload)
        created = _now()
        record = ArtifactRecord(
            ref=ArtifactRefOut(
                run_id=run_id,
                artifact_id=artifact_id,
                media_type=media_type,
                sha256=hashlib.sha256(payload).hexdigest(),
                size_bytes=len(payload),
            ),
            name=name,
            kind=kind,  # type: ignore[arg-type]
            story_id=story_id,
            stage_id=stage_id,
            created_at=created,
            expires_at=created + timedelta(days=retention_days),
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO story_artifacts (artifact_id, principal, run_id,"
                    " name, extension, size_bytes, created_at, expires_at, record)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        artifact_id,
                        principal,
                        run_id,
                        name,
                        extension,
                        len(payload),
                        record.created_at.isoformat(),
                        record.expires_at.isoformat(),
                        record.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            final.unlink()
            raise ArtifactConflict(
                f"Run already has an artifact named '{name}'."
            ) from error
        except BaseException:
            final.unlink()
            raise
        return record

    def get(self, principal: str, run_id: str, artifact_id: str) -> ArtifactRecord:
        """Return the record, if this principal's run holds a live artifact."""
        _token(run_id, "run_id")
        _token(artifact_id, "artifact_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record FROM story_artifacts"
                " WHERE artifact_id = ? AND principal = ? AND run_id = ?",
                (artifact_id, principal, run_id),
            ).fetchone()
        if row is None:
            raise ArtifactNotFound(artifact_id)
        record = ArtifactRecord.model_validate_json(row[0])
        if record.expires_at <= _now():
            raise ArtifactExpired(artifact_id)
        return record

    def read(
        self, principal: str, run_id: str, artifact_id: str
    ) -> tuple[ArtifactRecord, bytes]:
        """Return the record and its bytes, verified against the stored hash."""
        record = self.get(principal, run_id, artifact_id)
        extension = _EXTENSIONS[record.ref.media_type]
        path = self._run_dir(principal, run_id, create=False) / (
            f"{artifact_id}.{extension}"
        )
        if path.is_symlink() or not path.is_file():
            raise ArtifactConflict(
                "The artifact file is missing or not a regular file."
            )
        if path.stat().st_size != record.ref.size_bytes:
            raise ArtifactConflict("The artifact changed on disk.")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != record.ref.sha256:
            raise ArtifactConflict("The artifact changed on disk.")
        return record, data

    def list(
        self,
        principal: str,
        *,
        run_id: str | None = None,
        story_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[ArtifactRecord]:
        """Live artifacts of this principal, oldest first."""
        query = (
            "SELECT record FROM story_artifacts WHERE principal = ? AND expires_at > ?"
        )
        params: list[Any] = [principal, _now().isoformat()]
        if run_id is not None:
            query += " AND run_id = ?"
            params.append(_token(run_id, "run_id"))
        query += " ORDER BY created_at, artifact_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        records = [ArtifactRecord.model_validate_json(row[0]) for row in rows]
        return [
            r
            for r in records
            if (story_id is None or r.story_id == story_id)
            and (kind is None or r.kind == kind)
        ][:limit]


_EXTENSIONS = {
    "text/csv": "csv",
    "application/json": "json",
    "text/html": "html",
    XLSX_MEDIA_TYPE: "xlsx",
}


def _is_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _create_exclusive(directory: Path, final: Path, payload: bytes) -> None:
    """Write ``payload`` to ``final`` atomically, failing if it already exists."""
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".partial-")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # A hard link publishes the complete file under its final name, and
        # unlike a rename it refuses to replace a file that is already there.
        os.link(temporary, final)
    except FileExistsError as error:
        raise ArtifactConflict("An artifact file already exists.") from error
    finally:
        os.unlink(temporary)


# --- Routes -----------------------------------------------------------------


def default_artifact_root() -> Path:
    """Artifact location: ``$OPENBB_STORY_ARTIFACT_ROOT`` or the user directory."""
    override = os.environ.get(ARTIFACT_ROOT_ENV)
    if override:
        return Path(override)
    return Path.home() / ".openbb_platform" / "story_artifacts"


def _http(error: Exception) -> HTTPException:
    if isinstance(error, InvalidArtifactId):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error))
    if isinstance(error, ArtifactNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Unknown artifact.")
    if isinstance(error, ArtifactExpired):
        return HTTPException(status.HTTP_410_GONE, "The artifact has expired.")
    if isinstance(error, ArtifactTooLarge):
        return HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(error))
    return HTTPException(status.HTTP_409_CONFLICT, str(error))


_ERRORS = (
    InvalidArtifactId,
    ArtifactNotFound,
    ArtifactExpired,
    ArtifactTooLarge,
    ArtifactConflict,
)


def build_router(  # pylint: disable=too-many-statements
    runs: RunStore, store: ArtifactStore, principal: str
) -> APIRouter:
    """Return the artifact routes bound to one principal."""
    router = APIRouter(prefix="/api/v1/story", tags=["story"])
    authenticated = [Depends(AuthService().auth_hook)]

    def _owned_run(run_id: str):
        try:
            _token(run_id, "run_id")
        except InvalidArtifactId as error:
            raise _http(error) from error
        record = runs.get(principal, run_id)
        if record is None:
            # Another principal's run is indistinguishable from no run.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown run.")
        return record

    def _write(
        run_id: str,
        request: WriteRequest,
        *,
        kind: str,
        media_type: str,
        render,
    ) -> ArtifactRecord:
        run = _owned_run(run_id)
        if request.stage_id is not None and request.stage_id not in run.stage_status:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Stage '{request.stage_id}' is not in {run.manifest_version}.",
            )
        try:
            payload = render()
        except (ValidationError, ValueError) as error:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)[:2000]
            ) from error
        try:
            return store.write(
                principal,
                run_id,
                story_id=run.story_id,
                name=request.name,
                kind=kind,
                media_type=media_type,
                extension=_EXTENSIONS[media_type],
                payload=payload,
                retention_days=request.retention_days,
                stage_id=request.stage_id,
            )
        except _ERRORS as error:
            raise _http(error) from error

    @router.post(
        "/runs/{run_id}/artifacts/table",
        operation_id="story_artifact_table",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_artifact_table"}},
    )
    def story_artifact_table(run_id: str, request: TableRequest) -> ArtifactRecord:
        """Write a typed table into a run as CSV or canonical JSON."""
        if request.format == "csv":
            return _write(
                run_id,
                request,
                kind="table",
                media_type="text/csv",
                render=lambda: render_csv(request.table),
            )
        return _write(
            run_id,
            request,
            kind="table",
            media_type="application/json",
            render=lambda: render_table_json(request.table),
        )

    @router.post(
        "/runs/{run_id}/artifacts/chart",
        operation_id="story_artifact_chart",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_artifact_chart"}},
    )
    def story_artifact_chart(run_id: str, request: ChartRequest) -> ArtifactRecord:
        """Store a chart as a deterministic JSON spec with its data."""
        return _write(
            run_id,
            request,
            kind="chart",
            media_type="application/json",
            render=lambda: render_chart(request.chart),
        )

    @router.post(
        "/runs/{run_id}/artifacts/report",
        operation_id="story_artifact_report",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_artifact_report"}},
    )
    def story_artifact_report(run_id: str, request: ReportRequest) -> ArtifactRecord:
        """Compose an escaped HTML report citing this run's artifacts."""
        _owned_run(run_id)
        cited: dict[str, ArtifactRecord] = {}
        for section in request.sections:
            for artifact_id in section.artifact_ids:
                try:
                    cited[artifact_id] = store.get(principal, run_id, artifact_id)
                except (InvalidArtifactId, ArtifactNotFound, ArtifactExpired) as error:
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        f"Cited artifact '{artifact_id}' is not a live artifact"
                        " of this run.",
                    ) from error
        return _write(
            run_id,
            request,
            kind="report",
            media_type="text/html",
            render=lambda: render_report(request, cited),
        )

    @router.post(
        "/runs/{run_id}/artifacts/workbook",
        operation_id="story_artifact_workbook",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_artifact_workbook"}},
    )
    def story_artifact_workbook(
        run_id: str, request: WorkbookRequest
    ) -> ArtifactRecord:
        """Write typed sheets into a run as a reproducible XLSX workbook."""
        return _write(
            run_id,
            request,
            kind="workbook",
            media_type=XLSX_MEDIA_TYPE,
            render=lambda: render_workbook(request.sheets),
        )

    @router.post(
        "/runs/{run_id}/artifacts/techtrade_workbook",
        operation_id="story_artifact_techtrade_workbook",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_artifact_techtrade_workbook"}},
    )
    def story_artifact_techtrade_workbook(
        run_id: str, request: TechTradeWorkbookRequest
    ) -> ArtifactRecord:
        """Write the TechTrade six-sheet export for these plans into a run."""
        return _write(
            run_id,
            request,
            kind="workbook",
            media_type=XLSX_MEDIA_TYPE,
            render=lambda: render_techtrade_workbook(
                request.plans, request.include_sheets
            ),
        )

    @router.get(
        "/artifacts",
        operation_id="story_artifact_list",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_artifact_list"}},
    )
    def story_artifact_list(
        run_id: Annotated[str | None, Query(description="Only this run.")] = None,
        story_id: Annotated[
            str | None, Query(description="Only runs of this story.", max_length=100)
        ] = None,
        kind: Annotated[ArtifactKind | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
    ) -> list[ArtifactRecord]:
        """List this principal's live artifacts, optionally for one run or story."""
        if run_id is not None:
            _owned_run(run_id)
        return store.list(
            principal, run_id=run_id, story_id=story_id, kind=kind, limit=limit
        )

    @router.get(
        "/runs/{run_id}/artifacts/{artifact_id}",
        operation_id="story_artifact_read",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_artifact_read"}},
    )
    def story_artifact_read(
        run_id: str,
        artifact_id: str,
        max_rows: Annotated[int, Query(ge=1, le=MAX_PREVIEW_ROWS)] = 20,
    ) -> ArtifactContent:
        """Read one artifact: text inline, workbooks as bounded sheet previews."""
        try:
            _token(artifact_id, "artifact_id")
        except InvalidArtifactId as error:
            raise _http(error) from error
        _owned_run(run_id)
        try:
            record, data = store.read(principal, run_id, artifact_id)
        except _ERRORS as error:
            raise _http(error) from error
        if record.ref.media_type == XLSX_MEDIA_TYPE:
            return ArtifactContent(
                artifact=record, workbook=workbook_view(data, max_rows)
            )
        text = data.decode("utf-8")
        return ArtifactContent(
            artifact=record,
            text=text[:MAX_INLINE_CHARS],
            truncated=len(text) > MAX_INLINE_CHARS,
        )

    return router


def compose_story_artifacts_app(
    source_app: FastAPI,
    *,
    principal: str,
    store_path: Path | None = None,
    artifact_root: Path | None = None,
) -> FastAPI:
    """Add the artifact routes, bound to ``principal``, to an isolated app copy."""
    if not principal:
        raise ValueError("Story artifacts require an authenticated principal")
    db_path = store_path if store_path is not None else default_store_path()
    runs = RunStore(db_path)
    store = ArtifactStore(
        artifact_root if artifact_root is not None else default_artifact_root(),
        db_path,
    )
    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    composed.include_router(build_router(runs, store, principal))
    composed.openapi_schema = None
    return composed
