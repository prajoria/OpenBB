"""Allowlisted story job kinds for the durable jobs worker (#2218, N08).

The MCP routes in :mod:`.jobs` only enqueue; the existing
``openbb_core.app.jobs`` worker runs these handlers out of process. They are
registered through the ``openbb_job_extension`` entry point like every other
job. Each kind takes a typed payload and calls the engine the notebooks use:

- ``story.single_name``: the seven-phase ``Analysis`` pipeline.
- ``story.backtest``: ``openbb_backtest`` with a ``BacktestConfig``.
- ``story.validate``: TechTrade walk-forward validation of a ``TradePlan``.
- ``story.tune``: TechTrade per-segment tuning, never persisted.
- ``story.replay``: forward-bar replay of recommendations.

A handler runs only for a submission the MCP routes recorded for that
principal, operation and payload, so a job triggered directly on the jobs API
cannot write into a story run. The full result is written as a ``result``
artifact of the run; the job summary keeps the headline numbers and the
artifact's ref.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from importlib.util import find_spec
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from openbb_core.app.jobs.models import JobContext, JobDefinition, JobResult
from pydantic import BaseModel, ConfigDict, Field, field_validator

from openbb_mcp_server.story_adapters.artifacts import (
    ArtifactStore,
    default_artifact_root,
)
from openbb_mcp_server.story_adapters.registry import RunStore, default_store_path

OPERATION_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
# The routes record a submission, enqueue it, then record the job ID. A worker
# that claims the job in between waits this long for the ID, then refuses.
ATTACH_WAIT_SECONDS = 5.0
ATTACH_POLL_SECONDS = 0.05
_RUN_ID = r"^[a-f0-9]{32}$"


class KindUnavailable(RuntimeError):
    """A kind's engine is not installed in this environment."""


class UnauthorizedStoryJob(RuntimeError):
    """The run was not submitted through the story job routes."""


# --- Payloads ---------------------------------------------------------------


def _scalar_params(value: dict[str, Any]) -> dict[str, Any]:
    for key, item in value.items():
        items = item if isinstance(item, list) else [item]
        if len(items) > 500:
            raise ValueError(f"strategy parameter '{key}' has more than 500 values")
        for element in items:
            if not isinstance(element, str | int | float | bool) or (
                isinstance(element, float) and not math.isfinite(element)
            ):
                raise ValueError(
                    f"strategy parameter '{key}' must be finite scalars or lists"
                )
    return value


def _backtest_payload() -> type[BaseModel]:
    _require("openbb_backtest", "story.backtest")
    # pylint: disable=import-outside-toplevel
    # Importing the package registers the strategies.
    import openbb_backtest.strategies  # noqa: F401  # pylint: disable=unused-import
    from openbb_backtest.models import BacktestConfig
    from openbb_backtest.registry import list_strategies

    class BacktestPayload(BaseModel):
        """A frozen backtest experiment."""

        model_config = ConfigDict(extra="forbid")

        config: BacktestConfig
        engine: Literal["auto", "vector", "event"] = "auto"
        strategy_params: dict[Annotated[str, Field(max_length=64)], Any] = Field(
            default_factory=dict, max_length=20
        )

        @field_validator("config")
        @classmethod
        def _known_strategy(cls, config: BacktestConfig) -> BacktestConfig:
            known = list_strategies()
            if config.strategy.lower() not in known:
                raise ValueError(f"unknown strategy; choose one of {known}")
            return config

        @field_validator("strategy_params")
        @classmethod
        def _scalars(cls, value: dict[str, Any]) -> dict[str, Any]:
            return _scalar_params(value)

    return BacktestPayload


_THRESHOLD = Literal["pbo_robust", "pbo_overfit", "dsr_robust", "dsr_overfit"]


def _validate_payload() -> type[BaseModel]:
    _require("openbb_techtrade", "story.validate")
    _require("openbb_backtest", "story.validate")
    from openbb_techtrade.models import (  # pylint: disable=import-outside-toplevel
        TradePlan,
    )

    class ValidatePayload(BaseModel):
        """A plan to validate and how."""

        model_config = ConfigDict(extra="forbid")

        plan: TradePlan
        method: Literal["wfo", "cpcv"] = "wfo"
        horizon_years: int = Field(default=5, ge=1, le=20)
        thresholds: dict[_THRESHOLD, float] | None = None

    return ValidatePayload


def _tune_payload() -> type[BaseModel]:
    _require("openbb_techtrade", "story.tune")
    _require("openbb_backtest", "story.tune")
    _require("tuneta", "story.tune")
    # pylint: disable=import-outside-toplevel
    from openbb_techtrade.tuning.tune_router import SEGMENT_BENCHMARK_ETFS

    segments = tuple(sorted(SEGMENT_BENCHMARK_ETFS))

    class TunePayload(BaseModel):
        """One segment's tuning run. Story jobs never persist the result."""

        model_config = ConfigDict(extra="forbid")

        segment: str
        as_of: date | None = None
        horizon_years: int = Field(default=5, ge=1, le=20)
        forward_horizon_bars: int = Field(default=5, ge=1, le=60)
        trials: int = Field(default=100, ge=1, le=500)
        early_stop: int = Field(default=20, ge=1, le=500)
        method: Literal["wfo", "cpcv"] = "wfo"

        @field_validator("segment")
        @classmethod
        def _known_segment(cls, segment: str) -> str:
            if segment not in segments:
                raise ValueError(f"unknown segment; choose one of {list(segments)}")
            return segment

    return TunePayload


def _single_name_payload() -> type[BaseModel]:
    # pylint: disable=import-outside-toplevel
    from openbb_mcp_server.story_adapters.single_name import SingleNameRequest

    return SingleNameRequest


def _replay_payload() -> type[BaseModel]:
    _require("openbb_techtrade", "story.replay")
    # pylint: disable=import-outside-toplevel
    from openbb_mcp_server.story_adapters.techtrade_story import ReplayRequest

    return ReplayRequest


def _require(module: str, kind: str) -> None:
    if find_spec(module) is None:
        raise KindUnavailable(f"{kind} needs {module}, which is not installed.")


# --- Engines ----------------------------------------------------------------
# Module-level seams, looked up at call time, so tests can replace them.


def run_single_name(payload: BaseModel) -> dict[str, Any]:
    """Run the seven-phase pipeline (same code path as the MCP tool)."""
    # pylint: disable=import-outside-toplevel
    from openbb_mcp_server.story_adapters import single_name

    request = cast(single_name.SingleNameRequest, payload)
    return single_name._run(request).model_dump(  # pylint: disable=protected-access
        mode="json"
    )


def run_backtest(payload: BaseModel) -> dict[str, Any]:
    """Run one backtest through ``obb.backtest.run``'s implementation."""
    # pylint: disable=import-outside-toplevel
    from openbb_backtest.routers import run_router

    request = cast(Any, payload)
    result = asyncio.run(
        run_router.run(
            request.config,
            engine=request.engine,
            strategy_params=request.strategy_params or None,
        )
    )
    return result.results.model_dump(mode="json")


def run_validate(payload: BaseModel) -> dict[str, Any]:
    """Validate a plan with ``validate_plan`` and return the attached report."""
    # pylint: disable=import-outside-toplevel
    from openbb_techtrade.validation.backtest_bridge import validate_plan

    request = cast(Any, payload)
    plan, report = asyncio.run(
        validate_plan(
            request.plan,
            method=request.method,
            thresholds=request.thresholds,
            horizon_years=request.horizon_years,
        )
    )
    return {
        "report": report.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json"),
    }


def run_tune(payload: BaseModel) -> dict[str, Any]:
    """Tune one segment; ``persist`` is always off for a story job."""
    # pylint: disable=import-outside-toplevel
    from openbb_techtrade.tuning.tune_router import tune

    request = cast(Any, payload)
    result = asyncio.run(
        tune(
            request.segment,
            as_of=request.as_of,
            horizon_years=request.horizon_years,
            forward_horizon_bars=request.forward_horizon_bars,
            trials=request.trials,
            early_stop=request.early_stop,
            method=request.method,
            persist=False,
        )
    )
    return result.results.model_dump(mode="json")


def run_replay_job(payload: BaseModel) -> dict[str, Any]:
    """Replay recommendations (same code path as the MCP tool)."""
    # pylint: disable=import-outside-toplevel
    from openbb_mcp_server.story_adapters.techtrade_story import run_replay

    return run_replay(cast(Any, payload))


def _metrics(result: dict[str, Any]) -> dict[str, Any]:
    return dict(result.get("metrics") or {})


def _single_name_highlights(result: dict[str, Any]) -> dict[str, Any]:
    p7 = (result.get("phases") or {}).get("p7") or {}
    return {
        "action_label": p7.get("action_label"),
        "composite_score": p7.get("composite_score"),
        "phases": sorted(result.get("phases") or {}),
    }


def _backtest_highlights(result: dict[str, Any]) -> dict[str, Any]:
    keys = ("cagr", "sharpe", "sortino", "max_drawdown", "volatility", "calmar")
    metrics = _metrics(result)
    return {
        "engine_used": result.get("engine_used"),
        "metrics": {k: metrics.get(k) for k in keys},
        "equity_points": len(result.get("equity_curve") or []),
        "trades": len(result.get("trades") or []),
    }


def _validate_highlights(result: dict[str, Any]) -> dict[str, Any]:
    report = result.get("report") or {}
    return {
        "verdict": report.get("verdict"),
        "method": report.get("method"),
        "pbo": report.get("pbo"),
        "deflated_sharpe": report.get("deflated_sharpe"),
        "folds": len(report.get("folds") or []),
    }


def _tune_highlights(result: dict[str, Any]) -> dict[str, Any]:
    validation = result.get("validation") or {}
    return {
        "segment": result.get("segment"),
        "persisted": result.get("persisted"),
        "reason": result.get("reason"),
        "verdict": validation.get("verdict"),
    }


def _replay_highlights(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "outcomes": len(result.get("outcomes") or []),
        "summary": result.get("summary"),
    }


@dataclass(frozen=True)
class KindSpec:
    """One allowlisted job kind."""

    name: str
    description: str
    payload: Callable[[], type[BaseModel]]
    engine: str
    highlights: Callable[[dict[str, Any]], dict[str, Any]]


KINDS: dict[str, KindSpec] = {
    spec.name: spec
    for spec in (
        KindSpec(
            "story.single_name",
            "Seven-phase single-name analysis for a story run.",
            _single_name_payload,
            "run_single_name",
            _single_name_highlights,
        ),
        KindSpec(
            "story.backtest",
            "One openbb-backtest run for a story run.",
            _backtest_payload,
            "run_backtest",
            _backtest_highlights,
        ),
        KindSpec(
            "story.validate",
            "TechTrade walk-forward or CPCV validation of one plan.",
            _validate_payload,
            "run_validate",
            _validate_highlights,
        ),
        KindSpec(
            "story.tune",
            "TechTrade per-segment tuning; the candidate is never persisted.",
            _tune_payload,
            "run_tune",
            _tune_highlights,
        ),
        KindSpec(
            "story.replay",
            "Forward-bar replay of TechTrade recommendations.",
            _replay_payload,
            "run_replay_job",
            _replay_highlights,
        ),
    )
}
StoryJobKind = Literal[
    "story.single_name",
    "story.backtest",
    "story.validate",
    "story.tune",
    "story.replay",
]


def payload_model(kind: str) -> type[BaseModel]:
    """Return the typed payload model of ``kind``; raise if it is unavailable."""
    return KINDS[kind].payload()


# --- Submission ledger ------------------------------------------------------


def payload_digest(
    run_id: str, kind: str, stage_id: str | None, payload: dict[str, Any]
) -> str:
    """Hash of what was submitted; a reused operation must match it exactly."""
    canonical = json.dumps(
        {"run_id": run_id, "kind": kind, "stage_id": stage_id, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Submission:
    """One recorded story job submission."""

    principal: str
    operation_id: str
    run_id: str
    kind: str
    stage_id: str | None
    digest: str
    job_id: str | None
    created_at: str


class SubmissionLedger:
    """Story job submissions, in the run store's SQLite file."""

    def __init__(self, db_path: Path):
        """Bind the ledger; nothing touches disk until first use."""
        self.db_path = db_path
        self._ready = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if not self._ready:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, isolation_level=None)
        if not self._ready:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS story_jobs ("
                " principal TEXT NOT NULL, operation_id TEXT NOT NULL,"
                " run_id TEXT NOT NULL, kind TEXT NOT NULL, stage_id TEXT,"
                " digest TEXT NOT NULL, job_id TEXT, created_at TEXT NOT NULL,"
                " PRIMARY KEY (principal, operation_id))"
            )
            self._ready = True
        try:
            yield connection
        finally:
            connection.close()

    _COLUMNS = (
        "principal, operation_id, run_id, kind, stage_id, digest, job_id, created_at"
    )

    def get(self, principal: str, operation_id: str) -> Submission | None:
        """Return the submission for this operation, if recorded."""
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {self._COLUMNS} FROM story_jobs"  # noqa: S608
                " WHERE principal = ? AND operation_id = ?",
                (principal, operation_id),
            ).fetchone()
        return Submission(*row) if row else None

    def by_job(self, principal: str, run_id: str, job_id: str) -> Submission | None:
        """Return the submission behind a job, if it is this principal's run's."""
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {self._COLUMNS} FROM story_jobs"  # noqa: S608
                " WHERE principal = ? AND run_id = ? AND job_id = ?",
                (principal, run_id, job_id),
            ).fetchone()
        return Submission(*row) if row else None

    def for_run(self, principal: str, run_id: str) -> list[Submission]:
        """Every submission of one run, oldest first."""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {self._COLUMNS} FROM story_jobs"  # noqa: S608
                " WHERE principal = ? AND run_id = ? AND job_id IS NOT NULL"
                " ORDER BY created_at, operation_id",
                (principal, run_id),
            ).fetchall()
        return [Submission(*row) for row in rows]

    def open_job_ids(self, principal: str) -> list[str]:
        """Job IDs of every submission of this principal."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT job_id FROM story_jobs WHERE principal = ?"
                " AND job_id IS NOT NULL",
                (principal,),
            ).fetchall()
        return [row[0] for row in rows]

    def record(self, submission: Submission) -> Submission:
        """Record a new submission, or return the one already recorded."""
        try:
            with self._connect() as connection:
                connection.execute(
                    f"INSERT INTO story_jobs ({self._COLUMNS})"  # noqa: S608
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        submission.principal,
                        submission.operation_id,
                        submission.run_id,
                        submission.kind,
                        submission.stage_id,
                        submission.digest,
                        submission.job_id,
                        submission.created_at,
                    ),
                )
        except sqlite3.IntegrityError:
            pass
        recorded = self.get(submission.principal, submission.operation_id)
        assert recorded is not None  # noqa: S101  # inserted or already present
        return recorded

    def attach_job(self, principal: str, operation_id: str, job_id: str) -> None:
        """Record which durable run serves the submission."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE story_jobs SET job_id = ?"
                " WHERE principal = ? AND operation_id = ? AND job_id IS NULL",
                (job_id, principal, operation_id),
            )


# --- Worker side ------------------------------------------------------------


class StoryJobParams(BaseModel):
    """What the worker receives: who, which run, and the typed payload."""

    model_config = ConfigDict(extra="forbid")

    principal: str = Field(min_length=1, max_length=200)
    run_id: str = Field(pattern=_RUN_ID)
    operation_id: str = Field(pattern=OPERATION_ID)
    stage_id: str | None = Field(default=None, max_length=200)
    payload: dict[str, Any]


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    return value


def _attached_submission(
    ledger: SubmissionLedger, principal: str, operation_id: str
) -> Submission | None:
    """Return the submission once its job ID is recorded, or as it stands."""
    deadline = time.monotonic() + ATTACH_WAIT_SECONDS
    submission = ledger.get(principal, operation_id)
    while (
        submission is not None
        and submission.job_id is None
        and time.monotonic() < deadline
    ):
        time.sleep(ATTACH_POLL_SECONDS)
        submission = ledger.get(principal, operation_id)
    return submission


def _execute(kind: str, context: JobContext, params: StoryJobParams) -> JobResult:
    spec = KINDS[kind]
    db_path = default_store_path()
    digest = payload_digest(params.run_id, kind, params.stage_id, params.payload)
    submission = _attached_submission(
        SubmissionLedger(db_path), params.principal, params.operation_id
    )
    # The submission must name this exact durable run; an unattached one never
    # matches, so a run triggered outside the routes cannot borrow it.
    if (
        submission is None
        or submission.digest != digest
        or submission.kind != kind
        or submission.job_id != context.run_id
    ):
        raise UnauthorizedStoryJob(
            "No matching story job submission; story jobs are submitted through"
            " the story job routes."
        )
    run = RunStore(db_path).get(params.principal, params.run_id)
    if run is None:
        raise UnauthorizedStoryJob("The story run no longer exists.")
    payload = spec.payload().model_validate(params.payload)
    engine = globals()[spec.engine]
    result = _json_safe(engine(payload))
    data = json.dumps(
        result, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    record = ArtifactStore(default_artifact_root(), db_path).write(
        params.principal,
        params.run_id,
        story_id=run.story_id,
        name=f"{kind}-{params.operation_id}",
        kind="result",
        media_type="application/json",
        extension="json",
        payload=data,
        retention_days=30,
        stage_id=params.stage_id,
    )
    return JobResult(
        summary={
            "kind": kind,
            "artifact": record.ref.model_dump(mode="json"),
            "highlights": _json_safe(spec.highlights(result)),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _handler(kind: str) -> Callable[[JobContext, BaseModel], JobResult]:
    def handle(context: JobContext, params: BaseModel) -> JobResult:
        return _execute(kind, context, cast(StoryJobParams, params))

    handle.__name__ = f"run_{kind.replace('.', '_')}"
    return handle


def get_job_definitions() -> list[JobDefinition]:
    """Return the story job definitions for ``openbb_job_extension``."""
    return [
        JobDefinition(
            name=spec.name,
            description=spec.description,
            params_model=StoryJobParams,
            handler=_handler(spec.name),
            max_attempts=1,
            overlap_policy="allow",
        )
        for spec in KINDS.values()
    ]
