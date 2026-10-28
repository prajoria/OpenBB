"""Story jobs over the existing durable jobs service (#2218, N08).

Routes under ``/api/v1/story/runs/{run_id}/jobs``:

- ``POST``: submit one allowlisted job kind with a typed payload and a
  caller-chosen operation ID. Resubmitting the same operation returns the same
  job, so a lost response can be retried safely; reusing it for a different
  payload or run is a ``409``.
- ``GET`` (list and by job ID): status, result highlights, the result
  artifact's ref and any terminal error.
- ``POST /{job_id}/cancel``: ``cancelled`` for a queued job, ``too_late``
  once a worker has claimed it (the worker never interrupts a handler), and
  ``already_finished`` for a terminal one.

Nothing here runs a handler: jobs are persisted with the core
``JobService`` and executed by the ``openbb-jobs`` worker. A kind whose engine
is not installed, or whose worker definition is not registered, is a ``503``
that says so. Every route is bound to the server's one principal.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from openbb_core.api.dependency.jobs import get_authenticated_job_service
from openbb_core.app.jobs.models import JobRun
from openbb_core.app.jobs.registry import UnknownJobDefinitionError
from openbb_core.app.service.job_service import JobService
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from openbb_mcp_server.story_adapters.artifacts import ArtifactStore
from openbb_mcp_server.story_adapters.registry import RunStore, default_store_path
from openbb_mcp_server.story_adapters.story_job_kinds import (
    OPERATION_ID,
    KindUnavailable,
    StoryJobKind,
    StoryJobParams,
    Submission,
    SubmissionLedger,
    payload_digest,
    payload_model,
)

MAX_ACTIVE_JOBS = 4
_ACTIVE = {"queued", "running"}
_TERMINAL = {"succeeded", "succeeded_with_warnings", "failed", "cancelled"}


class JobSubmit(BaseModel):
    """One story job: an allowlisted kind and its typed payload."""

    model_config = ConfigDict(extra="forbid")

    operation_id: Annotated[str, Field(pattern=OPERATION_ID)]
    kind: StoryJobKind
    payload: dict[str, Any] = Field(default_factory=dict)
    stage_id: str | None = Field(default=None, max_length=200)


class JobError(BaseModel):
    """A terminal error, as the worker recorded it."""

    model_config = ConfigDict(extra="forbid")

    type: str | None
    message: str | None


class StoryJob(BaseModel):
    """A story job as its principal sees it."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    operation_id: str
    run_id: str
    kind: str
    stage_id: str | None
    status: str
    attempt: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: dict[str, Any] | None
    warnings: list[str]
    error: JobError | None


class CancelOutcome(BaseModel):
    """What cancelling did, and the job after it."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["cancelled", "too_late", "already_finished"]
    job: StoryJob


def _view(submission: Submission, run: JobRun) -> StoryJob:
    failed = run.status == "failed"
    return StoryJob(
        job_id=run.run_id,
        operation_id=submission.operation_id,
        run_id=submission.run_id,
        kind=submission.kind,
        stage_id=submission.stage_id,
        status=run.status,
        attempt=run.attempt,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        result=run.result.summary if run.result else None,
        warnings=list(run.result.warnings) if run.result else [],
        error=(
            JobError(type=run.error_type, message=run.error_message) if failed else None
        ),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_router(  # pylint: disable=too-many-statements
    runs: RunStore, ledger: SubmissionLedger, principal: str
) -> APIRouter:
    """Return the story job routes bound to one principal."""
    router = APIRouter(prefix="/api/v1/story/runs", tags=["story"])
    dedupe_prefix = f"story:{ArtifactStore.principal_key(principal)}:"

    def _owned_run(run_id: str):
        record = runs.get(principal, run_id)
        if record is None:
            # Another principal's run is indistinguishable from no run.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown run.")
        return record

    def _job(
        service: JobService, run_id: str, job_id: str
    ) -> tuple[Submission, JobRun]:
        _owned_run(run_id)
        submission = ledger.by_job(principal, run_id, job_id)
        if submission is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job.")
        return submission, service.get_run(job_id)

    def _active_jobs(service: JobService) -> int:
        active = 0
        for job_id in ledger.open_job_ids(principal):
            try:
                active += service.get_run(job_id).status in _ACTIVE
            except KeyError:
                continue
        return active

    def _conflict(detail: str) -> HTTPException:
        return HTTPException(status.HTTP_409_CONFLICT, detail)

    @router.post(
        "/{run_id}/jobs",
        operation_id="story_job_submit",
        status_code=status.HTTP_202_ACCEPTED,
        openapi_extra={"mcp_config": {"name": "story_job_submit"}},
    )
    def story_job_submit(
        run_id: str,
        request: JobSubmit,
        service: Annotated[JobService, Depends(get_authenticated_job_service)],
    ) -> StoryJob:
        """Queue one allowlisted story job; the same operation ID returns the same job."""
        run = _owned_run(run_id)
        if request.stage_id is not None and request.stage_id not in run.stage_status:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Stage '{request.stage_id}' is not in {run.manifest_version}.",
            )
        try:
            model = payload_model(request.kind)
        except KindUnavailable as error:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, str(error)
            ) from error
        try:
            payload = model.model_validate(request.payload).model_dump(mode="json")
        except ValidationError as error:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                error.errors(
                    include_url=False, include_context=False, include_input=False
                ),
            ) from error
        digest = payload_digest(run_id, request.kind, request.stage_id, payload)
        existing = ledger.get(principal, request.operation_id)
        if existing is None and _active_jobs(service) >= MAX_ACTIVE_JOBS:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"At most {MAX_ACTIVE_JOBS} story jobs may be queued or running.",
            )
        submission = existing or ledger.record(
            Submission(
                principal=principal,
                operation_id=request.operation_id,
                run_id=run_id,
                kind=request.kind,
                stage_id=request.stage_id,
                digest=digest,
                job_id=None,
                created_at=_now(),
            )
        )
        if submission.digest != digest:
            raise _conflict(
                f"Operation '{request.operation_id}' was already used for a"
                " different job."
            )
        params = StoryJobParams(
            principal=principal,
            run_id=run_id,
            operation_id=request.operation_id,
            stage_id=request.stage_id,
            payload=payload,
        ).model_dump(mode="json")
        try:
            # The core dedupe key makes this safe to repeat: a retry after a
            # lost response, or after a crash before the job ID was recorded,
            # returns the run that already exists.
            job = service.enqueue(
                request.kind,
                params,
                idempotency_key=dedupe_prefix + request.operation_id,
            )
        except UnknownJobDefinitionError as error:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"The {request.kind} worker definition is not registered; install"
                " openbb-mcp-server where the jobs worker runs.",
            ) from error
        except ValidationError as error:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                error.errors(
                    include_url=False, include_context=False, include_input=False
                ),
            ) from error
        if job.job_name != request.kind or job.params != params:
            raise _conflict(
                f"Operation '{request.operation_id}' belongs to a different job."
            )
        ledger.attach_job(principal, request.operation_id, job.run_id)
        return _view(submission, job)

    @router.get(
        "/{run_id}/jobs",
        operation_id="story_job_list",
        openapi_extra={"mcp_config": {"name": "story_job_list"}},
    )
    def story_job_list(
        run_id: str,
        service: Annotated[JobService, Depends(get_authenticated_job_service)],
    ) -> list[StoryJob]:
        """List this run's story jobs, oldest first."""
        _owned_run(run_id)
        return [
            _view(submission, service.get_run(submission.job_id))
            for submission in ledger.for_run(principal, run_id)
            if submission.job_id is not None
        ]

    @router.get(
        "/{run_id}/jobs/{job_id}",
        operation_id="story_job_get",
        openapi_extra={"mcp_config": {"name": "story_job_get"}},
    )
    def story_job_get(
        run_id: str,
        job_id: str,
        service: Annotated[JobService, Depends(get_authenticated_job_service)],
    ) -> StoryJob:
        """Return one story job: status, highlights, result artifact or error."""
        return _view(*_job(service, run_id, job_id))

    @router.post(
        "/{run_id}/jobs/{job_id}/cancel",
        operation_id="story_job_cancel",
        openapi_extra={"mcp_config": {"name": "story_job_cancel"}},
    )
    def story_job_cancel(
        run_id: str,
        job_id: str,
        service: Annotated[JobService, Depends(get_authenticated_job_service)],
    ) -> CancelOutcome:
        """Cancel a queued job; report too_late once a worker has claimed it."""
        submission, job = _job(service, run_id, job_id)
        if job.status in _TERMINAL:
            return CancelOutcome(outcome="already_finished", job=_view(submission, job))
        if job.status == "queued":
            try:
                cancelled = service.cancel(job_id)
            except ValueError:
                # A worker claimed it between the read and the cancel.
                job = service.get_run(job_id)
            else:
                return CancelOutcome(
                    outcome="cancelled", job=_view(submission, cancelled)
                )
        return CancelOutcome(outcome="too_late", job=_view(submission, job))

    return router


def compose_story_jobs_app(
    source_app: FastAPI,
    *,
    principal: str,
    store_path: Path | None = None,
) -> FastAPI:
    """Add the story job routes, bound to ``principal``, to an isolated app copy."""
    if not principal:
        raise ValueError("Story jobs require an authenticated principal")
    db_path = store_path if store_path is not None else default_store_path()
    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    composed.include_router(
        build_router(RunStore(db_path), SubmissionLedger(db_path), principal)
    )
    composed.openapi_schema = None
    return composed
