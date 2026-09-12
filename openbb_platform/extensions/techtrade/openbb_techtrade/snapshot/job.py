"""Snapshot-job value types and privacy-safe error vocabulary."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Protocol

DEFAULT_STALE_AFTER = timedelta(hours=2)
_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class SnapshotJobState(str, Enum):
    """Durable state of one post-close dataset run."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class SnapshotJob:
    """PII-free bookkeeping record for one dataset run."""

    job_run_id: str
    dataset: str
    started_at: datetime
    finished_at: datetime | None
    state: SnapshotJobState
    n_ok: int
    n_failed: int
    error: str | None


class SnapshotJobAlreadyRunning(RuntimeError):
    """A fresh single-flight lease already exists for the dataset."""


class SnapshotJobTransitionError(RuntimeError):
    """A requested job transition is not valid for the durable row."""


class SnapshotJobStore(Protocol):
    """Persistence seam required by the standalone refresh orchestrator."""

    def start_job(
        self,
        dataset: str,
        job_run_id: str,
        *,
        started_at: datetime | None = None,
        stale_after: timedelta = DEFAULT_STALE_AFTER,
    ) -> SnapshotJob:
        """Acquire the dataset's single-flight lease."""
        ...

    def finish_job(
        self,
        job_run_id: str,
        state: SnapshotJobState,
        *,
        n_ok: int,
        n_failed: int,
        error: BaseException | str | None = None,
        finished_at: datetime | None = None,
    ) -> SnapshotJob:
        """Finish a running job with exact counts."""
        ...

    def record_job_errors(
        self, job_run_id: str, errors: Mapping[str, BaseException | str]
    ) -> None:
        """Replace the failed-key set for targeted retry."""
        ...

    def retry_entity_keys(self, job_run_id: str) -> list[str]:
        """Return only failed canonical entity keys."""
        ...

    def get_job(self, job_run_id: str) -> SnapshotJob | None:
        """Read one job record."""
        ...

    def publish_job(
        self,
        job_run_id: str,
        candidates: Sequence[tuple[str, str, date, str]],
        *,
        finished_at: datetime | None = None,
        require_newer: bool = False,
    ) -> SnapshotJob:
        """Atomically verify the lease, promote all rows, and finish the job."""
        ...


def utc_datetime(value: datetime | None = None) -> datetime:
    """Normalize an aware instant to UTC, defaulting to now."""
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("job timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def sanitized_error(error: BaseException | str | None) -> str | None:
    """Return a bounded category without retaining exception-message data."""
    if error is None:
        return None
    if isinstance(error, BaseException):
        return type(error).__name__[:64]
    candidate = error.strip().casefold()
    return candidate if _ERROR_CODE_RE.fullmatch(candidate) else "error"


def job_from_mapping(record: Mapping | object) -> SnapshotJob:
    """Hydrate a job from a SQLite row or PyMySQL dictionary."""
    started = utc_datetime(_stored_datetime(record["started_at"]))  # type: ignore[index]
    raw_finished = record["finished_at"]  # type: ignore[index]
    finished = (
        None if raw_finished is None else utc_datetime(_stored_datetime(raw_finished))
    )
    return SnapshotJob(
        job_run_id=record["job_run_id"],  # type: ignore[index]
        dataset=record["dataset"],  # type: ignore[index]
        started_at=started,
        finished_at=finished,
        state=SnapshotJobState(record["state"]),  # type: ignore[index]
        n_ok=int(record["n_ok"]),  # type: ignore[index]
        n_failed=int(record["n_failed"]),  # type: ignore[index]
        error=record["error"],  # type: ignore[index]
    )


def _stored_datetime(value: object) -> datetime:
    parsed = (
        value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
