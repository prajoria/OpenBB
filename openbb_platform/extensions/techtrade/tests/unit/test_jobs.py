"""Post-close jobs for canonical TechTrade EOD snapshots."""

# ruff: noqa: D103

from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path

import openbb_techtrade.jobs as jobs_module
import pytest
from openbb_core.app.jobs.models import JobContext, JobDefinition, JobResult
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.schedules import DailySchedule
from openbb_techtrade.jobs import (
    DailyScanParams,
    EodSnapshotsParams,
    PruneSnapshotsParams,
    get_job_definitions,
)
from openbb_techtrade.snapshot.datasets import TECHTRADE_DATASETS
from openbb_techtrade.snapshot.refresh import ComputedSnapshot
from openbb_techtrade.snapshot.store import SqliteSnapshotStore


def _by_name() -> dict[str, JobDefinition]:
    return {definition.name: definition for definition in get_job_definitions()}


def _context(job_name: str) -> JobContext:
    return JobContext(run_id="r1", job_name=job_name)


def test_get_job_definitions_returns_post_close_and_prune_jobs() -> None:
    assert set(_by_name()) == {
        "techtrade.daily_scan",
        "techtrade.eod_snapshots",
        "techtrade.prune_snapshots",
    }
    registry = JobRegistry.discover([get_job_definitions])
    assert "techtrade.eod_snapshots" in registry


def test_eod_schedule_is_weekday_post_close_new_york(monkeypatch) -> None:
    monkeypatch.delenv("OPENBB_JOBS_TIMEZONE", raising=False)
    definition = _by_name()["techtrade.eod_snapshots"]
    schedule = definition.schedule
    assert isinstance(schedule, DailySchedule)
    assert (schedule.hour, schedule.minute) == (18, 5)
    assert schedule.timezone == "America/New_York"
    assert schedule.weekdays == (0, 1, 2, 3, 4)
    assert definition.default_params == {
        "datasets": jobs_module._default_eod_datasets()
    }
    assert definition.overlap_policy == "forbid"


def test_default_fanout_excludes_unavailable_optional_workloads(monkeypatch) -> None:
    monkeypatch.setattr(jobs_module, "find_spec", lambda _name: None)

    defaults = jobs_module._default_eod_datasets()

    assert "techtrade.validate" not in defaults
    assert "techtrade.tune" not in defaults
    assert "techtrade.audit" not in defaults


def test_timezone_env_override(monkeypatch) -> None:
    monkeypatch.setenv("OPENBB_JOBS_TIMEZONE", "Europe/London")
    assert _by_name()["techtrade.eod_snapshots"].schedule.timezone == "Europe/London"


def test_params_reject_unknown_or_duplicate_datasets() -> None:
    with pytest.raises(ValueError, match="unknown snapshot dataset"):
        EodSnapshotsParams(datasets=["techtrade.unknown"])
    with pytest.raises(ValueError, match="duplicate snapshot dataset"):
        EodSnapshotsParams(datasets=["techtrade.scan", "techtrade.scan"])
    with pytest.raises(ValueError, match="Extra inputs"):
        PruneSnapshotsParams(unknown_keep=10)


def test_prune_accepts_legacy_keep_alias() -> None:
    assert PruneSnapshotsParams(keep=3).keep_sessions == 3


def test_legacy_daily_scan_definition_accepts_durable_schedule_params() -> None:
    definition = _by_name()["techtrade.daily_scan"]
    assert definition.default_params["top_n"] == 10
    params = DailyScanParams(
        segments=["Information Technology"],
        top_n=5,
        preset="trend_follow",
        as_of="2026-09-11",
    )
    assert definition.params_model is DailyScanParams
    assert params.top_n == 5


def test_legacy_daily_scan_forwards_all_supported_parameters(monkeypatch) -> None:
    captured: dict = {}

    def adapters(**kwargs):
        captured["adapter_kwargs"] = kwargs
        return {"techtrade.movers": object(), "techtrade.scan": object()}

    def execute(datasets, selected_adapters, *, now=None):
        captured["datasets"] = datasets
        captured["adapters"] = selected_adapters
        captured["now"] = now
        return JobResult(summary={"datasets": {}}, warnings=[])

    monkeypatch.setattr(jobs_module, "get_snapshot_adapters", adapters)
    monkeypatch.setattr(jobs_module, "_execute_datasets", execute)
    definition = _by_name()["techtrade.daily_scan"]
    result = definition.handler(
        _context(definition.name),
        DailyScanParams(
            segments=["Energy"],
            top_n=5,
            preset="breakout",
            as_of="2026-09-11",
        ),
    )

    assert isinstance(result, JobResult)
    assert captured["adapter_kwargs"] == {
        "segments": ["Energy"],
        "movers_top_n": 5,
        "scan_top_n": 5,
        "preset": "breakout",
    }
    assert captured["now"].date() == date(2026, 9, 11)


def test_legacy_daily_scan_rejects_future_as_of() -> None:
    definition = _by_name()["techtrade.daily_scan"]

    with pytest.raises(ValueError, match="last completed XNYS session"):
        definition.handler(
            _context(definition.name),
            DailyScanParams(as_of="2099-01-01"),
        )


class _Adapter:
    name = "techtrade.movers"

    def entity_keys(self) -> list[str]:
        return ["segment=Information Technology"]

    def compute(self, entity_key: str, as_of_session: date) -> ComputedSnapshot:
        return ComputedSnapshot(
            payload={
                "rows": [{"symbol": "NVDA", "pct_change": 1.5}],
                "segment": "Information Technology",
                "as_of_session": as_of_session.isoformat(),
                "exchange_calendar": "XNYS",
            },
            inputs={"entity_key": entity_key, "session": str(as_of_session)},
            engine_version="test",
            payload_schema_version="1",
            row_count=1,
        )


class _FailingAdapter(_Adapter):
    def compute(self, entity_key: str, as_of_session: date) -> ComputedSnapshot:
        raise RuntimeError("private provider detail")


def test_eod_handler_runs_generic_orchestrator(monkeypatch, tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    monkeypatch.setattr(jobs_module, "get_default_snapshot_store", lambda: store)
    monkeypatch.setattr(
        jobs_module, "get_snapshot_adapters", lambda: {"techtrade.movers": _Adapter()}
    )
    definition = _by_name()["techtrade.eod_snapshots"]

    result = definition.handler(
        _context(definition.name),
        EodSnapshotsParams(datasets=["techtrade.movers"]),
    )

    assert isinstance(result, JobResult)
    assert result.summary["datasets"]["techtrade.movers"] == {
        "state": "succeeded",
        "n_ok": 1,
        "n_failed": 0,
    }
    reopened = SqliteSnapshotStore(tmp_path / "snapshots.db")
    assert (
        reopened.get_live("techtrade.movers", "segment=information technology").payload[
            "rows"
        ][0]["symbol"]
        == "NVDA"
    )
    reopened.close()


def test_prune_handler_uses_generic_store(monkeypatch, tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    monkeypatch.setattr(jobs_module, "get_default_snapshot_store", lambda: store)
    definition = _by_name()["techtrade.prune_snapshots"]

    result = definition.handler(
        _context(definition.name), PruneSnapshotsParams(keep_sessions=2)
    )

    assert result.summary == {"deleted": 0, "keep_sessions": 2}


def test_prune_handler_scopes_retention_to_techtrade_datasets(monkeypatch) -> None:
    class _Store:
        def __init__(self):
            self.datasets: list[str] = []

        def prune(self, _policy, *, dataset):
            self.datasets.append(dataset)
            return 1

        def close(self):
            return None

    store = _Store()
    monkeypatch.setattr(jobs_module, "get_default_snapshot_store", lambda: store)
    definition = _by_name()["techtrade.prune_snapshots"]

    result = definition.handler(
        _context(definition.name), PruneSnapshotsParams(keep_sessions=2)
    )

    assert store.datasets == list(TECHTRADE_DATASETS)
    assert result.summary["deleted"] == len(TECHTRADE_DATASETS)


def test_eod_handler_raises_when_every_dataset_fails(
    monkeypatch, tmp_path: Path
) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    monkeypatch.setattr(jobs_module, "get_default_snapshot_store", lambda: store)
    monkeypatch.setattr(
        jobs_module,
        "get_snapshot_adapters",
        lambda: {"techtrade.movers": _FailingAdapter()},
    )
    definition = _by_name()["techtrade.eod_snapshots"]

    with pytest.raises(RuntimeError, match="all selected snapshot datasets failed"):
        definition.handler(
            _context(definition.name),
            EodSnapshotsParams(datasets=["techtrade.movers"]),
        )


def test_jobs_module_has_no_legacy_snapshot_store_dependency() -> None:
    source = inspect.getsource(jobs_module)
    assert "SqliteScanSnapshotStore" not in source
    assert "run_scan" not in source


def test_pyproject_advertises_job_entry_point() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "openbb_job_extension" in text
    assert "openbb_techtrade.jobs:get_job_definitions" in text
