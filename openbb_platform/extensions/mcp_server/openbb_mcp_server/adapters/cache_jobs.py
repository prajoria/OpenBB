"""Authenticated durable cache-job MCP adapter."""

import copy
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from openbb_core.api.dependency.jobs import get_authenticated_job_service
from openbb_core.app.jobs.models import JobRun
from openbb_core.app.jobs.registry import UnknownJobDefinitionError
from openbb_core.app.service.job_service import JobDefinitionView, JobHealth, JobService
from portfolio_utils.jobs import EtfHoldingsJobParams, PositionHistoryJobParams
from pydantic import BaseModel, Field, ValidationError

_ALLOWED_JOBS = {
    "portfolio.position_history",
    "portfolio.etf_holdings",
}


class PositionHistoryTrigger(BaseModel):
    """Typed manual position-history request."""

    params: PositionHistoryJobParams = Field(default_factory=PositionHistoryJobParams)
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class EtfHoldingsTrigger(BaseModel):
    """Typed manual ETF-holdings request."""

    params: EtfHoldingsJobParams = Field(default_factory=EtfHoldingsJobParams)
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


router = APIRouter(prefix="/api/v1/cache/jobs", tags=["cache", "jobs"])


@router.get(
    "/definitions",
    operation_id="cache_jobs_definitions",
    openapi_extra={"mcp_config": {"name": "cache_jobs_definitions"}},
)
async def definitions(
    service: Annotated[JobService, Depends(get_authenticated_job_service)],
) -> list[JobDefinitionView]:
    """List only the two approved cache warmer definitions."""
    return [
        definition
        for definition in service.list_definitions()
        if definition.name in _ALLOWED_JOBS
    ]


@router.get(
    "/health",
    operation_id="cache_jobs_health",
    openapi_extra={"mcp_config": {"name": "cache_jobs_health"}},
)
async def health(
    service: Annotated[JobService, Depends(get_authenticated_job_service)],
) -> JobHealth:
    """Return durable queue and worker health."""
    return service.health()


@router.get(
    "/runs/{run_id}",
    operation_id="cache_jobs_run",
    openapi_extra={"mcp_config": {"name": "cache_jobs_run"}},
)
async def run_status(
    run_id: str,
    service: Annotated[JobService, Depends(get_authenticated_job_service)],
) -> JobRun:
    """Return one durable run by identifier."""
    try:
        run = service.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job run not found") from exc
    if run.job_name not in _ALLOWED_JOBS:
        raise HTTPException(status_code=404, detail="Job run not found")
    return run


def _enqueue(
    service: JobService,
    name: str,
    params: BaseModel,
    idempotency_key: str | None,
) -> JobRun:
    dedupe_key = f"mcp:{name}:{idempotency_key}" if idempotency_key else None
    try:
        run = service.enqueue(
            name,
            params.model_dump(mode="json"),
            idempotency_key=dedupe_key,
        )
    except UnknownJobDefinitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Approved job worker definition is unavailable",
        ) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    if run.job_name != name or run.job_name not in _ALLOWED_JOBS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key belongs to a different job",
        )
    return run


@router.post(
    "/portfolio.position_history/trigger",
    operation_id="cache_jobs_trigger_position_history",
    openapi_extra={"mcp_config": {"name": "cache_jobs_trigger_position_history"}},
    status_code=202,
)
async def trigger_position_history(
    request: PositionHistoryTrigger,
    service: Annotated[JobService, Depends(get_authenticated_job_service)],
) -> JobRun:
    """Durably enqueue a position-history cache warmer run."""
    return _enqueue(
        service,
        "portfolio.position_history",
        request.params,
        request.idempotency_key,
    )


@router.post(
    "/portfolio.etf_holdings/trigger",
    operation_id="cache_jobs_trigger_etf_holdings",
    openapi_extra={"mcp_config": {"name": "cache_jobs_trigger_etf_holdings"}},
    status_code=202,
)
async def trigger_etf_holdings(
    request: EtfHoldingsTrigger,
    service: Annotated[JobService, Depends(get_authenticated_job_service)],
) -> JobRun:
    """Durably enqueue an ETF-holdings cache warmer run."""
    return _enqueue(
        service,
        "portfolio.etf_holdings",
        request.params,
        request.idempotency_key,
    )


def compose_cache_jobs_app(source_app: FastAPI) -> FastAPI:
    """Add allowlisted job controls to an isolated application."""
    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    composed.include_router(router)
    composed.openapi_schema = None
    return composed
