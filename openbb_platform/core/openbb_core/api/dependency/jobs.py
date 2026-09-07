"""Jobs API dependency wiring."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from openbb_core.app.extension_loader import ExtensionLoader
from openbb_core.app.service.auth_service import AuthService
from openbb_core.app.service.job_service import JobService


@lru_cache
def _default_job_service() -> JobService:
    """Build a process-wide job service from discovered job extensions.

    Discovery happens once per process via ``openbb_job_extension`` entry
    points; the resulting registry is only ever used here to enqueue,
    list, look up, or cancel runs -- never to execute a handler.
    """
    registry = ExtensionLoader().build_job_registry()
    return JobService(registry=registry)


def get_job_service() -> JobService:
    """Return the job service used by API routes.

    Left as a plain callable (rather than inlining the cache) so tests can
    substitute a fixture-backed service via
    ``app.dependency_overrides[get_job_service]``.
    """
    return _default_job_service()


async def get_authenticated_job_service(
    _: Annotated[None, Depends(AuthService().auth_hook)],
    job_service: Annotated[JobService, Depends(get_job_service)],
) -> JobService:
    """Return the job service only once authentication succeeds."""
    return job_service
