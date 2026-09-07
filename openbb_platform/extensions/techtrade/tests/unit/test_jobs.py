"""Tests for the TechTrade job definitions (issue #1934).

Fully offline. Asserts the two registered jobs, their schedules and default params,
that handlers return a core ``JobResult`` (with warnings), parameter validation through
the definition's Pydantic model, and that the pyproject advertises the
``openbb_job_extension`` entry point.
"""

from __future__ import annotations

from pathlib import Path

import openbb_techtrade.jobs as jobs_module
import pytest
from openbb_core.app.jobs.models import JobContext, JobDefinition, JobResult
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.schedules import DailySchedule
from openbb_techtrade.jobs import (
    DailyScanParams,
    PruneSnapshotsParams,
    get_job_definitions,
)
from openbb_techtrade.snapshots import ScanSnapshot, SqliteScanSnapshotStore


def _by_name() -> dict[str, JobDefinition]:
    return {d.name: d for d in get_job_definitions()}


def _context(job_name: str) -> JobContext:
    return JobContext(run_id="r1", job_name=job_name)


def test_get_job_definitions_returns_both_jobs():
    """Both TechTrade jobs are defined with the expected names."""
    names = {d.name for d in get_job_definitions()}
    assert names == {"techtrade.daily_scan", "techtrade.prune_snapshots"}


def test_definitions_register_without_duplicates():
    """The definitions load cleanly into a JobRegistry (allowlist discovery)."""
    registry = JobRegistry.discover([get_job_definitions])
    assert "techtrade.daily_scan" in registry
    assert "techtrade.prune_snapshots" in registry


def test_daily_scan_schedule_is_weekday_0300_local():
    """Daily scan runs weekdays at 03:00 in the resolved local zone."""
    definition = _by_name()["techtrade.daily_scan"]
    schedule = definition.schedule
    assert isinstance(schedule, DailySchedule)
    assert (schedule.hour, schedule.minute) == (3, 0)
    assert schedule.weekdays == (0, 1, 2, 3, 4)
    assert definition.default_params == {"top_n": 3, "preset": "trend_follow"}
    assert definition.overlap_policy == "forbid"


def test_prune_schedule_is_daily_0400_local():
    """Prune runs every day at 04:00 in the resolved local zone."""
    definition = _by_name()["techtrade.prune_snapshots"]
    schedule = definition.schedule
    assert isinstance(schedule, DailySchedule)
    assert (schedule.hour, schedule.minute) == (4, 0)
    assert schedule.weekdays == (0, 1, 2, 3, 4, 5, 6)
    assert definition.default_params == {"keep": 10}


def test_timezone_env_override(monkeypatch):
    """OPENBB_JOBS_TIMEZONE overrides the schedule timezone."""
    monkeypatch.setenv("OPENBB_JOBS_TIMEZONE", "Europe/London")
    definition = _by_name()["techtrade.daily_scan"]
    assert definition.schedule.timezone == "Europe/London"


def test_default_params_validate_against_models():
    """Default params validate against each job's Pydantic model."""
    definitions = _by_name()
    DailyScanParams.model_validate(definitions["techtrade.daily_scan"].default_params)
    PruneSnapshotsParams.model_validate(
        definitions["techtrade.prune_snapshots"].default_params
    )


@pytest.mark.parametrize(
    ("model", "params"),
    [
        (DailyScanParams, {"top_n": 3, "typo": True}),
        (PruneSnapshotsParams, {"unknown_keep": 10}),
    ],
)
def test_job_params_reject_unknown_fields(model, params):
    """Operator parameter typos fail instead of silently using defaults."""
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        model.model_validate(params)


def test_daily_scan_handler_returns_job_result(monkeypatch, tmp_path):
    """The scan handler wraps run_scan and returns a JobResult with a summary."""
    captured = {}

    def _fake_run_scan(**kwargs):
        from datetime import date, datetime, timezone

        from openbb_techtrade.engine.scan_runner import ScanRunResult

        captured.update(kwargs)
        return ScanRunResult(
            as_of_session=date(2024, 1, 12),
            computed_at=datetime(2024, 1, 12, 8, 0, tzinfo=timezone.utc),
            requested_segments=["Energy"],
            processed_segments=["Energy"],
            segment_counts={"Energy": 2},
            snapshot_ids={"Energy": "abc"},
            total_rows=2,
            warnings=["scan: skipped fills for 'AAA': boom"],
        )

    monkeypatch.setattr(jobs_module, "run_scan", _fake_run_scan)
    definition = _by_name()["techtrade.daily_scan"]
    params = DailyScanParams(top_n=5, preset="trend_follow")
    result = definition.handler(_context(definition.name), params)

    assert isinstance(result, JobResult)
    assert result.summary["total_rows"] == 2
    assert result.warnings == ["scan: skipped fills for 'AAA': boom"]
    assert result.has_warnings
    # Params were threaded through to run_scan.
    assert captured["top_n"] == 5
    assert captured["preset"] == "trend_follow"


def test_prune_handler_deletes_and_reports(monkeypatch, tmp_path):
    """The prune handler prunes the default store and reports the delete count."""
    from datetime import date

    db = tmp_path / "scan.db"
    monkeypatch.setenv("OPENBB_TECHTRADE_SCAN_DB", str(db))

    seed = SqliteScanSnapshotStore(db)
    for i in range(5):
        seed.write_snapshot(
            ScanSnapshot(
                kind="daily_scan",
                segment="Energy",
                as_of_session=date(2024, 1, 12),
                rows=[{"symbol": f"E{i}"}],
            )
        )
    seed.close()

    definition = _by_name()["techtrade.prune_snapshots"]
    result = definition.handler(_context(definition.name), PruneSnapshotsParams(keep=2))

    assert isinstance(result, JobResult)
    assert result.summary == {"deleted": 3, "keep": 2}
    assert not result.has_warnings


def test_pyproject_advertises_job_entry_point():
    """The techtrade pyproject registers the openbb_job_extension entry point."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "openbb_job_extension" in text
    assert "openbb_techtrade.jobs:get_job_definitions" in text
