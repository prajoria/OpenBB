"""Post-close jobs for canonical TechTrade EOD snapshots."""

from __future__ import annotations

import os
from datetime import date, datetime, time, timezone
from importlib.util import find_spec
from typing import Any, cast

from openbb_core.app.jobs.models import (
    MAX_WARNING_COUNT,
    MAX_WARNING_LENGTH,
    JobContext,
    JobDefinition,
    JobResult,
)
from openbb_core.app.jobs.schedules import DailySchedule
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from openbb_techtrade.snapshot.adapters import get_snapshot_adapters
from openbb_techtrade.snapshot.datasets import TECHTRADE_DATASETS
from openbb_techtrade.snapshot.refresh import SnapshotRefreshOrchestrator
from openbb_techtrade.snapshot.registry import (
    DEFAULT_DATASET_REGISTRY,
    SnapshotStoreRouter,
)
from openbb_techtrade.snapshot.store import (
    RetentionPolicy,
    get_default_snapshot_store,
)

_TRADING_WEEKDAYS = (0, 1, 2, 3, 4)
_TIMEZONE_ENV = "OPENBB_JOBS_TIMEZONE"
_DEFAULT_TIMEZONE = "America/New_York"


def _default_timezone() -> str:
    return os.environ.get(_TIMEZONE_ENV) or _DEFAULT_TIMEZONE


def _bounded_warnings(messages: list[str]) -> list[str]:
    return [message[:MAX_WARNING_LENGTH] for message in messages[:MAX_WARNING_COUNT]]


def _default_eod_datasets() -> list[str]:
    """Return workloads supported by the currently installed optional extras."""
    available = list(TECHTRADE_DATASETS)
    if find_spec("openbb_backtest") is None:
        available.remove("techtrade.validate")
        available.remove("techtrade.tune")
    elif find_spec("tuneta") is None:
        available.remove("techtrade.tune")
    return available


class EodSnapshotsParams(BaseModel):
    """Datasets selected for one post-close refresh."""

    model_config = ConfigDict(extra="forbid")

    datasets: list[str] = Field(default_factory=_default_eod_datasets)

    @field_validator("datasets")
    @classmethod
    def _validate_datasets(cls, value: list[str]) -> list[str]:
        unknown = [name for name in value if name not in TECHTRADE_DATASETS]
        if unknown:
            raise ValueError("unknown snapshot dataset")
        if len(value) != len(set(value)):
            raise ValueError("duplicate snapshot dataset")
        if not value:
            raise ValueError("at least one snapshot dataset is required")
        return value


class PruneSnapshotsParams(BaseModel):
    """Retention settings for the canonical snapshot store."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    keep_sessions: int = Field(
        default=10,
        ge=0,
        le=1000,
        validation_alias=AliasChoices("keep_sessions", "keep"),
    )


class DailyScanParams(BaseModel):
    """Compatibility parameters accepted by the retired daily-scan job name."""

    model_config = ConfigDict(extra="forbid")

    segments: list[str] | None = None
    top_n: int = Field(default=3, ge=1, le=50)
    preset: str = "trend_follow"
    as_of: str | None = None


def _execute_datasets(
    datasets_to_run: list[str],
    adapters: dict[str, Any],
    *,
    now: datetime | None = None,
) -> JobResult:
    store = get_default_snapshot_store()
    router = SnapshotStoreRouter(store, None, DEFAULT_DATASET_REGISTRY)
    orchestrator = (
        SnapshotRefreshOrchestrator(
            router,
            DEFAULT_DATASET_REGISTRY,
            adapters,
            clock=lambda: now,
        )
        if now is not None
        else SnapshotRefreshOrchestrator(
            router,
            DEFAULT_DATASET_REGISTRY,
            adapters,
        )
    )
    datasets: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    published = 0
    try:
        for name in datasets_to_run:
            try:
                job = orchestrator.run(name)
            except Exception as exc:  # noqa: BLE001 - continue independent datasets
                datasets[name] = {"state": "failed", "n_ok": 0, "n_failed": 1}
                warnings.append(f"{name}: {type(exc).__name__}")
                continue
            datasets[name] = {
                "state": job.state.value,
                "n_ok": job.n_ok,
                "n_failed": job.n_failed,
            }
            if job.state.value == "succeeded":
                published += 1
            if job.n_failed:
                warnings.append(f"{name}: {job.n_failed} entity refresh failures")
    finally:
        store.close()
    if published == 0:
        raise RuntimeError("all selected snapshot datasets failed")
    return JobResult(
        summary={"datasets": datasets},
        warnings=_bounded_warnings(warnings),
    )


def _run_eod_snapshots(context: JobContext, params: BaseModel) -> JobResult:
    del context
    selected = cast(EodSnapshotsParams, params)
    return _execute_datasets(selected.datasets, get_snapshot_adapters())


def _run_daily_scan(context: JobContext, params: BaseModel) -> JobResult:
    del context
    legacy = cast(DailyScanParams, params)
    adapters = get_snapshot_adapters(
        segments=legacy.segments,
        movers_top_n=legacy.top_n,
        scan_top_n=legacy.top_n,
        preset=legacy.preset,
    )
    requested_date = date.fromisoformat(legacy.as_of) if legacy.as_of else None
    requested_now = (
        datetime.combine(requested_date, time(23, 59), tzinfo=timezone.utc)
        if requested_date is not None
        else None
    )
    return _execute_datasets(
        ["techtrade.movers", "techtrade.scan"],
        adapters,
        now=requested_now,
    )


def _run_prune_snapshots(context: JobContext, params: BaseModel) -> JobResult:
    del context
    params = cast(PruneSnapshotsParams, params)
    store = get_default_snapshot_store()
    try:
        deleted = sum(
            store.prune(
                RetentionPolicy(keep_sessions=params.keep_sessions),
                dataset=dataset,
            )
            for dataset in TECHTRADE_DATASETS
        )
    finally:
        store.close()
    return JobResult(
        summary={"deleted": deleted, "keep_sessions": params.keep_sessions},
        warnings=[],
    )


def get_job_definitions() -> list[JobDefinition]:
    """Return post-close refresh and retention job definitions."""
    schedule_timezone = _default_timezone()
    return [
        JobDefinition(
            name="techtrade.daily_scan",
            description="Compatibility alias for the canonical EOD movers and scan refresh.",
            params_model=DailyScanParams,
            handler=_run_daily_scan,
            default_params={"top_n": 10, "preset": "trend_follow"},
            schedule=DailySchedule(
                hour=18,
                minute=5,
                timezone=schedule_timezone,
                weekdays=_TRADING_WEEKDAYS,
            ),
            max_attempts=1,
            overlap_policy="forbid",
        ),
        JobDefinition(
            name="techtrade.eod_snapshots",
            description="Compute, validate, and atomically publish TechTrade EOD snapshots.",
            params_model=EodSnapshotsParams,
            handler=_run_eod_snapshots,
            schedule=DailySchedule(
                hour=18,
                minute=0,
                timezone=schedule_timezone,
                weekdays=_TRADING_WEEKDAYS,
            ),
            default_params={"datasets": _default_eod_datasets()},
            max_attempts=1,
            overlap_policy="forbid",
        ),
        JobDefinition(
            name="techtrade.prune_snapshots",
            description="Prune canonical TechTrade EOD snapshot history.",
            params_model=PruneSnapshotsParams,
            handler=_run_prune_snapshots,
            schedule=DailySchedule(hour=19, minute=0, timezone=schedule_timezone),
            default_params={"keep_sessions": 10},
            max_attempts=1,
            overlap_policy="forbid",
        ),
    ]
