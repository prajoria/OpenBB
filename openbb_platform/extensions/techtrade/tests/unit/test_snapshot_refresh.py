"""Standalone post-close snapshot orchestration contracts (#1967)."""

# ruff: noqa: D103

from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from openbb_techtrade.snapshot import refresh as refresh_module
from openbb_techtrade.snapshot.job import (
    SnapshotJobAlreadyRunning,
    SnapshotJobState,
    SnapshotJobTransitionError,
)
from openbb_techtrade.snapshot.refresh import (
    ComputedSnapshot,
    SnapshotRefreshOrchestrator,
    main,
)
from openbb_techtrade.snapshot.registry import (
    DatasetDefinition,
    SnapshotDatasetRegistry,
    SnapshotStoreRouter,
    UnsupportedPayloadSchema,
)
from openbb_techtrade.snapshot.store import (
    RetentionPolicy,
    SnapshotStatus,
    SqliteSnapshotStore,
)

NOW = datetime(2026, 9, 11, 22, tzinfo=timezone.utc)
DATASET = "techtrade.movers"


class _Adapter:
    name = DATASET

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail: set[str] = set()
        self.threads: list[threading.Thread] = []
        self.schema_version = "1"

    def entity_keys(self) -> list[str]:
        return ["symbol=AAPL", "symbol=MSFT"]

    def compute(self, entity_key: str, as_of_session: date) -> ComputedSnapshot:
        self.calls.append(entity_key)
        self.threads.append(threading.current_thread())
        if entity_key in self.fail:
            raise RuntimeError("provider response must not persist")
        return ComputedSnapshot(
            payload={
                "symbol": entity_key.split("=", 1)[1],
                "session": str(as_of_session),
            },
            inputs={"entity_key": entity_key, "session": str(as_of_session)},
            engine_version="engine-1",
            payload_schema_version=self.schema_version,
            row_count=1,
        )


def _registry() -> SnapshotDatasetRegistry:
    return SnapshotDatasetRegistry(
        [
            DatasetDefinition(
                name=DATASET,
                pii_scoped=False,
                payload_schema_version="1",
                readers={"1": lambda payload: payload},
            )
        ]
    )


def _orchestrator(
    store: SqliteSnapshotStore,
    adapter: _Adapter,
    ids: list[str],
) -> SnapshotRefreshOrchestrator:
    registry = _registry()
    return SnapshotRefreshOrchestrator(
        SnapshotStoreRouter(store, None, registry),
        registry,
        {DATASET: adapter},
        clock=lambda: NOW,
        job_id_factory=lambda: ids.pop(0),
    )


def _seed_live(store: SqliteSnapshotStore, entity_key: str, job_run_id: str) -> None:
    store.stage(
        DATASET,
        entity_key,
        date(2026, 9, 10),
        job_run_id,
        {"symbol": entity_key.split("=", 1)[1], "session": "old"},
        status=SnapshotStatus.OK,
        engine_version="engine-0",
        payload_schema_version="1",
    )
    assert store.validate(DATASET, entity_key, date(2026, 9, 10), job_run_id).ok
    assert store.promote(DATASET, entity_key, date(2026, 9, 10), job_run_id)


def test_complete_run_promotes_and_records_success(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    adapter = _Adapter()
    orchestrator = _orchestrator(store, adapter, ["job-1"])

    job = orchestrator.run(DATASET)

    assert job.state is SnapshotJobState.SUCCEEDED
    assert (job.n_ok, job.n_failed) == (2, 0)
    assert store.get_live(DATASET, "symbol=AAPL").job_run_id == "job-1"
    assert store.get_live(DATASET, "symbol=MSFT").job_run_id == "job-1"
    assert adapter.threads == [threading.main_thread(), threading.main_thread()]
    store.close()


def test_fresh_single_flight_refuses_before_compute(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    store.start_job(DATASET, "existing", started_at=NOW)
    adapter = _Adapter()
    orchestrator = _orchestrator(store, adapter, ["job-2"])

    with pytest.raises(SnapshotJobAlreadyRunning):
        orchestrator.run(DATASET)

    assert adapter.calls == []
    store.close()


def test_partial_then_targeted_retry_promotes_only_after_recovery(
    tmp_path: Path,
) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    _seed_live(store, "symbol=AAPL", "old-a")
    _seed_live(store, "symbol=MSFT", "old-b")
    adapter = _Adapter()
    adapter.fail = {"symbol=msft"}
    orchestrator = _orchestrator(store, adapter, ["job-partial", "job-retry"])

    partial = orchestrator.run(DATASET)

    assert partial.state is SnapshotJobState.PARTIAL
    assert store.retry_entity_keys(partial.job_run_id) == ["symbol=msft"]
    assert store.get_live(DATASET, "symbol=AAPL").job_run_id == "old-a"
    assert store.get_live(DATASET, "symbol=MSFT").job_run_id == "old-b"

    adapter.calls.clear()
    adapter.fail.clear()
    recovered = orchestrator.run(DATASET, retry_job_run_id=partial.job_run_id)

    assert recovered.state is SnapshotJobState.SUCCEEDED
    assert recovered.n_ok == 2
    assert adapter.calls == ["symbol=msft"]
    assert store.get_live(DATASET, "symbol=AAPL").job_run_id == "job-retry"
    assert store.get_live(DATASET, "symbol=MSFT").job_run_id == "job-retry"
    store.close()


def test_still_partial_retry_keeps_last_good_pointers(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    _seed_live(store, "symbol=AAPL", "old-a")
    _seed_live(store, "symbol=MSFT", "old-b")
    adapter = _Adapter()
    adapter.fail = {"symbol=msft"}
    orchestrator = _orchestrator(store, adapter, ["job-partial", "job-retry"])
    partial = orchestrator.run(DATASET)

    retry = orchestrator.run(DATASET, retry_job_run_id=partial.job_run_id)

    assert retry.state is SnapshotJobState.PARTIAL
    assert store.get_live(DATASET, "symbol=AAPL").job_run_id == "old-a"
    assert store.get_live(DATASET, "symbol=MSFT").job_run_id == "old-b"
    store.close()


def test_chained_retries_preserve_all_prior_successes(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    adapter = _Adapter()
    adapter.entity_keys = lambda: [  # type: ignore[method-assign]
        "symbol=AAPL",
        "symbol=MSFT",
        "symbol=NVDA",
    ]
    adapter.fail = {"symbol=msft", "symbol=nvda"}
    orchestrator = _orchestrator(store, adapter, ["job-1", "job-2", "job-3"])

    first = orchestrator.run(DATASET)
    adapter.fail = {"symbol=nvda"}
    second = orchestrator.run(DATASET, retry_job_run_id=first.job_run_id)
    adapter.fail.clear()
    third = orchestrator.run(DATASET, retry_job_run_id=second.job_run_id)

    assert first.state is SnapshotJobState.PARTIAL
    assert second.state is SnapshotJobState.PARTIAL
    assert third.state is SnapshotJobState.SUCCEEDED
    assert third.n_ok == 3
    assert {
        store.get_live(DATASET, key).job_run_id
        for key in ("symbol=AAPL", "symbol=MSFT", "symbol=NVDA")
    } == {"job-3"}
    store.close()


def test_retry_refuses_when_prior_success_lineage_was_pruned(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    adapter = _Adapter()
    adapter.fail = {"symbol=msft"}
    orchestrator = _orchestrator(store, adapter, ["job-1", "job-2"])
    partial = orchestrator.run(DATASET)
    assert partial.n_ok == 1
    assert store.prune(RetentionPolicy(keep_sessions=0), dataset=DATASET) == 1
    adapter.fail.clear()

    with pytest.raises(ValueError, match="lineage is incomplete"):
        orchestrator.run(DATASET, retry_job_run_id=partial.job_run_id)

    assert store.get_live(DATASET, "symbol=AAPL") is None
    assert store.get_live(DATASET, "symbol=MSFT") is None
    store.close()


def test_retry_cannot_replace_a_newer_successful_session(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    adapter = _Adapter()
    registry = _registry()
    times = [NOW]
    ids = iter(["day-1-partial", "day-2-full", "obsolete-retry"])
    orchestrator = SnapshotRefreshOrchestrator(
        SnapshotStoreRouter(store, None, registry),
        registry,
        {DATASET: adapter},
        clock=lambda: times[0],
        job_id_factory=lambda: next(ids),
    )
    adapter.fail = {"symbol=msft"}
    partial = orchestrator.run(DATASET)
    adapter.fail.clear()
    times[0] = datetime(2026, 9, 14, 22, tzinfo=timezone.utc)
    latest = orchestrator.run(DATASET)
    assert latest.state is SnapshotJobState.SUCCEEDED

    with pytest.raises(SnapshotJobTransitionError, match="older"):
        orchestrator.run(DATASET, retry_job_run_id=partial.job_run_id)

    assert {
        store.get_live(DATASET, key).job_run_id
        for key in ("symbol=AAPL", "symbol=MSFT")
    } == {"day-2-full"}
    store.close()


def test_retry_cannot_replace_newer_refresh_from_same_session(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    adapter = _Adapter()
    registry = _registry()
    ids = iter(["first-partial", "newer-full", "obsolete-retry"])
    orchestrator = SnapshotRefreshOrchestrator(
        SnapshotStoreRouter(store, None, registry),
        registry,
        {DATASET: adapter},
        clock=lambda: NOW,
        job_id_factory=lambda: next(ids),
    )
    adapter.fail = {"symbol=msft"}
    partial = orchestrator.run(DATASET)
    adapter.fail.clear()
    assert orchestrator.run(DATASET).state is SnapshotJobState.SUCCEEDED

    with pytest.raises(SnapshotJobTransitionError, match="newer than LIVE"):
        orchestrator.run(DATASET, retry_job_run_id=partial.job_run_id)

    assert {
        store.get_live(DATASET, key).job_run_id
        for key in ("symbol=AAPL", "symbol=MSFT")
    } == {"newer-full"}
    store.close()


def test_retry_refuses_prior_payload_without_registered_schema_reader(
    tmp_path: Path,
) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    adapter = _Adapter()
    adapter.fail = {"symbol=msft"}
    first = _orchestrator(store, adapter, ["partial"]).run(DATASET)
    upgraded_registry = SnapshotDatasetRegistry(
        [
            DatasetDefinition(
                name=DATASET,
                pii_scoped=False,
                payload_schema_version="2",
                readers={"2": lambda payload: payload},
            )
        ]
    )
    adapter.schema_version = "2"
    adapter.fail.clear()
    retry = SnapshotRefreshOrchestrator(
        SnapshotStoreRouter(store, None, upgraded_registry),
        upgraded_registry,
        {DATASET: adapter},
        clock=lambda: NOW,
        job_id_factory=lambda: "retry",
    )

    with pytest.raises(UnsupportedPayloadSchema):
        retry.run(DATASET, retry_job_run_id=first.job_run_id)

    assert store.get_live(DATASET, "symbol=AAPL") is None
    store.close()


def test_keyboard_interrupt_terminalizes_accepted_job(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    adapter = _Adapter()
    adapter.compute = lambda *_args: (_ for _ in ()).throw(  # type: ignore[method-assign]
        KeyboardInterrupt()
    )
    orchestrator = _orchestrator(store, adapter, ["interrupted"])

    with pytest.raises(KeyboardInterrupt):
        orchestrator.run(DATASET)

    job = store.get_job("interrupted")
    assert job is not None
    assert job.state is SnapshotJobState.FAILED
    store.close()


def test_module_entrypoint_computes_on_calling_main_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    adapter = _Adapter()
    monkeypatch.setattr(refresh_module, "_load_adapters", lambda: {DATASET: adapter})
    monkeypatch.setattr(
        refresh_module, "get_default_snapshot_store", lambda **_kwargs: store
    )

    assert main(["--dataset", DATASET]) == 0
    assert adapter.threads == [threading.main_thread(), threading.main_thread()]


@pytest.mark.parametrize(
    ("failed_keys", "expected_code"),
    [
        ({"symbol=msft"}, 3),
        ({"symbol=aapl", "symbol=msft"}, 1),
    ],
)
def test_module_entrypoint_returns_nonzero_for_incomplete_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_keys: set[str],
    expected_code: int,
) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    adapter = _Adapter()
    adapter.fail = failed_keys
    monkeypatch.setattr(refresh_module, "_load_adapters", lambda: {DATASET: adapter})
    monkeypatch.setattr(
        refresh_module, "get_default_snapshot_store", lambda **_kwargs: store
    )

    assert main(["--dataset", DATASET]) == expected_code
