"""Jobs API routes.

These routes form the control plane for the durable jobs service: they can
enqueue, list, look up, and cancel job runs, and report queue health. They
never resolve or call a job handler -- execution only ever happens in the
dedicated worker process (see ``openbb_core.app.jobs.worker``).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from openbb_core.api.dependency.jobs import get_authenticated_job_service
from openbb_core.app.jobs.models import JobRun
from openbb_core.app.jobs.registry import UnknownJobDefinitionError
from openbb_core.app.service.job_service import JobDefinitionView, JobHealth, JobService
from pydantic import BaseModel, Field, ValidationError

router = APIRouter(prefix="/jobs", tags=["Jobs"])


class TriggerJobRequest(BaseModel):
    """Request body for manually triggering a job run."""

    params: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


@router.get("/definitions", response_model=list[JobDefinitionView])
async def list_job_definitions(
    job_service: Annotated[JobService, Depends(get_authenticated_job_service)],
) -> list[JobDefinitionView]:
    """List registered job definitions and their durable schedule state."""
    return job_service.list_definitions()


@router.post(
    "/{job_name}/trigger",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobRun,
)
async def trigger_job(
    job_name: str,
    request: TriggerJobRequest,
    job_service: Annotated[JobService, Depends(get_authenticated_job_service)],
) -> JobRun:
    """Enqueue a manual run for a registered job.

    This only durably persists a queued run for a worker to claim later;
    the handler is never invoked by this endpoint.
    """
    try:
        return job_service.enqueue(
            job_name, request.params, idempotency_key=request.idempotency_key
        )
    except UnknownJobDefinitionError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error.errors(),
        ) from error


@router.get("/runs/{run_id}", response_model=JobRun)
async def get_job_run(
    run_id: str,
    job_service: Annotated[JobService, Depends(get_authenticated_job_service)],
) -> JobRun:
    """Look up a single persisted job run by identifier."""
    try:
        return job_service.get_run(run_id)
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error


@router.post("/runs/{run_id}/cancel", response_model=JobRun)
async def cancel_job_run(
    run_id: str,
    job_service: Annotated[JobService, Depends(get_authenticated_job_service)],
) -> JobRun:
    """Cancel a queued job run.

    Only queued runs can be cancelled; a run already claimed by a worker
    must be left to finish or be recovered after its lease expires.
    """
    try:
        return job_service.cancel(run_id)
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error


@router.get("/health", response_model=JobHealth)
async def get_jobs_health(
    job_service: Annotated[JobService, Depends(get_authenticated_job_service)],
) -> JobHealth:
    """Report aggregate queue, schedule, and worker health."""
    return job_service.health()
