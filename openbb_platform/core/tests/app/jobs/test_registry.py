"""Tests for the job registry."""

import pytest
from pydantic import BaseModel, ValidationError

from openbb_core.app.jobs.models import JobContext, JobDefinition, JobResult
from openbb_core.app.jobs.registry import DuplicateJobDefinitionError, JobRegistry


class ScanParams(BaseModel):
    """Example scan params."""

    symbol: str
    limit: int = 10


class WarmParams(BaseModel):
    """Example warming params."""

    dry_run: bool = False


def scan_handler(context: JobContext, params: ScanParams) -> JobResult:
    """Example scan handler."""
    return JobResult(summary={"job": context.job_name, "symbol": params.symbol})


def warm_handler(context: JobContext, params: WarmParams) -> JobResult:
    """Example cache warmer handler."""
    return JobResult(summary={"job": context.job_name, "dry_run": params.dry_run})


def test_registry_discovers_jobs_from_providers():
    """JobRegistry discovers definitions from provider callables."""

    def provider_one():
        return [
            JobDefinition(
                name="techtrade.daily_scan",
                description="Daily scan",
                params_model=ScanParams,
                handler=scan_handler,
            )
        ]

    def provider_two():
        return [
            JobDefinition(
                name="portfolio.position_history",
                description="Position history warm",
                params_model=WarmParams,
                handler=warm_handler,
            )
        ]

    registry = JobRegistry.discover([provider_one, provider_two])

    assert [definition.name for definition in registry.definitions] == [
        "portfolio.position_history",
        "techtrade.daily_scan",
    ]


def test_registry_rejects_duplicate_job_names():
    """Duplicate job names fail registry discovery."""

    def provider_one():
        return [
            JobDefinition(
                name="techtrade.daily_scan",
                description="Daily scan",
                params_model=ScanParams,
                handler=scan_handler,
            )
        ]

    def provider_two():
        return [
            JobDefinition(
                name="techtrade.daily_scan",
                description="Other daily scan",
                params_model=ScanParams,
                handler=scan_handler,
            )
        ]

    with pytest.raises(DuplicateJobDefinitionError, match="techtrade.daily_scan"):
        JobRegistry.discover([provider_one, provider_two])


def test_registry_rejects_invalid_definitions():
    """Providers must return JobDefinition instances."""

    def invalid_provider():
        return ["not-a-job-definition"]

    with pytest.raises(TypeError, match="JobDefinition"):
        JobRegistry.discover([invalid_provider])


def test_registry_validates_params_with_pydantic():
    """Registry validates input params against each job's model."""
    registry = JobRegistry(
        [
            JobDefinition(
                name="techtrade.daily_scan",
                description="Daily scan",
                params_model=ScanParams,
                handler=scan_handler,
            )
        ]
    )

    validated = registry.validate_params(
        "techtrade.daily_scan",
        {"symbol": "AAPL", "limit": "5"},
    )

    assert isinstance(validated, ScanParams)
    assert validated.limit == 5

    with pytest.raises(ValidationError, match="symbol"):
        registry.validate_params("techtrade.daily_scan", {"limit": 5})
