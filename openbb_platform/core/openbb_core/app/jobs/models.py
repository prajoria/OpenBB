"""Core job domain models."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Literal

from openbb_core.app.jobs.schedules import DailySchedule, IntervalSchedule, ensure_utc
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_JSON_PAYLOAD_BYTES = 16_384
MAX_WARNING_COUNT = 100
MAX_WARNING_LENGTH = 512
MAX_ERROR_TYPE_LENGTH = 255
MAX_ERROR_MESSAGE_LENGTH = 1_024

JobRunStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "succeeded_with_warnings",
    "failed",
    "cancelled",
]
JobSource = Literal["schedule", "manual", "retry"]
OverlapPolicy = Literal["forbid", "allow"]


def _utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


def _validate_json_payload(value: dict[str, Any], field_name: str) -> dict[str, Any]:
    """Require a JSON-serializable dictionary within the configured size limit."""
    try:
        serialized = json.dumps(
            value,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be JSON-serializable") from error

    payload_size = len(serialized.encode("utf-8"))
    if payload_size > MAX_JSON_PAYLOAD_BYTES:
        raise ValueError(
            f"{field_name} must serialize to at most {MAX_JSON_PAYLOAD_BYTES} bytes"
        )

    return value


class JobContext(BaseModel):
    """Runtime context supplied to a job handler."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    job_name: str
    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=1, ge=1)
    worker_id: str | None = None
    scheduled_for: datetime | None = None
    started_at: datetime | None = None

    @field_validator("scheduled_for", "started_at")
    @classmethod
    def validate_datetimes(cls, value: datetime | None) -> datetime | None:
        """Normalize optional datetimes to UTC."""
        return None if value is None else ensure_utc(value)


class JobResult(BaseModel):
    """Structured handler output persisted with a job run."""

    model_config = ConfigDict(frozen=True)

    summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Require a bounded JSON-safe summary payload."""
        return _validate_json_payload(value, "summary")

    @field_validator("warnings")
    @classmethod
    def validate_warnings(cls, value: list[str]) -> list[str]:
        """Bound warning counts and message length."""
        if len(value) > MAX_WARNING_COUNT:
            raise ValueError(f"warnings must contain at most {MAX_WARNING_COUNT} items")
        if any(len(item) > MAX_WARNING_LENGTH for item in value):
            raise ValueError(
                f"warning messages must be at most {MAX_WARNING_LENGTH} characters"
            )

        return value

    @property
    def has_warnings(self) -> bool:
        """Return whether the result contains warnings."""
        return bool(self.warnings)


JobHandler = Callable[[JobContext, BaseModel], JobResult]


class JobDefinition(BaseModel):
    """Immutable registered job definition."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    version: int = Field(default=1, ge=1)
    description: str
    params_model: type[BaseModel]
    handler: JobHandler
    schedule: DailySchedule | IntervalSchedule | None = None
    default_params: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=1, ge=1)
    retry_backoff_seconds: int = Field(default=60, ge=1)
    overlap_policy: OverlapPolicy = "forbid"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Normalize job names and reject blank values."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")

        return normalized

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        """Require a non-empty description."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("description must not be blank")

        return normalized

    @field_validator("params_model")
    @classmethod
    def validate_params_model(cls, value: type[BaseModel]) -> type[BaseModel]:
        """Require a Pydantic model class for parameter validation."""
        if not isinstance(value, type) or not issubclass(value, BaseModel):
            raise TypeError("params_model must be a BaseModel subclass")

        return value

    @field_validator("handler")
    @classmethod
    def validate_handler(cls, value: JobHandler) -> JobHandler:
        """Require a callable job handler."""
        if not callable(value):
            raise TypeError("handler must be callable")

        return value

    @field_validator("default_params")
    @classmethod
    def validate_default_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Require JSON-safe scheduled default parameters."""
        return _validate_json_payload(value, "default_params")


class JobRun(BaseModel):
    """Persisted state for a single job execution attempt."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    job_name: str
    handler_version: int = Field(default=1, ge=1)
    source: JobSource = "manual"
    status: JobRunStatus = "queued"
    params: dict[str, Any] = Field(default_factory=dict)
    scheduled_for: datetime | None = None
    available_at: datetime | None = None
    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=1, ge=1)
    dedupe_key: str | None = None
    worker_id: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: JobResult | None = None
    error_type: str | None = Field(default=None, max_length=MAX_ERROR_TYPE_LENGTH)
    error_message: str | None = Field(default=None, max_length=MAX_ERROR_MESSAGE_LENGTH)

    @field_validator(
        "scheduled_for",
        "available_at",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
    )
    @classmethod
    def validate_datetimes(cls, value: datetime | None) -> datetime | None:
        """Normalize optional datetimes to UTC."""
        return None if value is None else ensure_utc(value)

    @field_validator("params")
    @classmethod
    def validate_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Require bounded JSON-safe parameter payloads."""
        return _validate_json_payload(value, "params")

    @model_validator(mode="after")
    def validate_attempt_bounds(self) -> JobRun:
        """Require attempts to remain within the configured retry policy."""
        if self.attempt > self.max_attempts:
            raise ValueError("attempt must be less than or equal to max_attempts")

        return self

    def mark_running(self, *, worker_id: str, started_at: datetime) -> JobRun:
        """Transition a queued run into running state."""
        if self.status != "queued":
            raise ValueError("Only queued jobs can transition to running")

        started = ensure_utc(started_at, "started_at")
        return self.model_copy(
            update={
                "status": "running",
                "worker_id": worker_id,
                "started_at": started,
                "updated_at": started,
            }
        )

    def complete(self, *, result: JobResult, finished_at: datetime) -> JobRun:
        """Complete a running job."""
        if self.status != "running":
            raise ValueError("Only running jobs can be completed")

        finished = ensure_utc(finished_at, "finished_at")
        return self.model_copy(
            update={
                "status": "succeeded_with_warnings"
                if result.has_warnings
                else "succeeded",
                "result": result,
                "error_type": None,
                "error_message": None,
                "finished_at": finished,
                "updated_at": finished,
            }
        )

    def fail(self, *, error: Exception, finished_at: datetime) -> JobRun:
        """Fail a running job without scheduling a retry."""
        if self.status != "running":
            raise ValueError("Only running jobs can fail")

        finished = ensure_utc(finished_at, "finished_at")
        return self.model_copy(
            update={
                "status": "failed",
                "finished_at": finished,
                "updated_at": finished,
                "error_type": type(error).__name__[:MAX_ERROR_TYPE_LENGTH],
                "error_message": str(error)[:MAX_ERROR_MESSAGE_LENGTH],
            }
        )

    def schedule_retry(self, *, available_at: datetime) -> JobRun:
        """Return a queued retry attempt for a failed or running job."""
        if self.attempt >= self.max_attempts:
            raise ValueError("Job run has exhausted its retry attempts")
        if self.status not in {"running", "failed"}:
            raise ValueError("Only running or failed jobs can be retried")

        available = ensure_utc(available_at, "available_at")
        return self.model_copy(
            update={
                "status": "queued",
                "source": "retry",
                "attempt": self.attempt + 1,
                "available_at": available,
                "worker_id": None,
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error_type": None,
                "error_message": None,
                "updated_at": available,
            }
        )

    def cancel(self, *, finished_at: datetime) -> JobRun:
        """Cancel a queued job."""
        if self.status != "queued":
            raise ValueError("Only queued jobs can be cancelled")

        finished = ensure_utc(finished_at, "finished_at")
        return self.model_copy(
            update={
                "status": "cancelled",
                "finished_at": finished,
                "updated_at": finished,
            }
        )
