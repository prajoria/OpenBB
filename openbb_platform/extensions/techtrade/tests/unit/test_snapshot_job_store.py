"""Snapshot job single-flight, bookkeeping, and retry contracts (#1967)."""

# ruff: noqa: D103

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest
from openbb_techtrade.snapshot.job import (
    SnapshotJobAlreadyRunning,
    SnapshotJobState,
    SnapshotJobTransitionError,
)
from openbb_techtrade.snapshot.store import (
    SnapshotSchemaMismatch,
    SnapshotStatus,
    SqliteSnapshotStore,
)

DATASET = "techtrade.movers"
T0 = datetime(2026, 9, 11, 21, 0, tzinfo=timezone.utc)


def test_second_fresh_job_is_refused(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    store.start_job(DATASET, "run-1", started_at=T0)

    with pytest.raises(SnapshotJobAlreadyRunning):
        store.start_job(DATASET, "run-2", started_at=T0 + timedelta(minutes=5))

    assert store.get_job("run-2") is None
    store.close()


def test_stale_job_is_failed_before_replacement_starts(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    store.start_job(DATASET, "run-1", started_at=T0)

    replacement = store.start_job(
        DATASET,
        "run-2",
        started_at=T0 + timedelta(hours=2, seconds=1),
    )

    stale = store.get_job("run-1")
    assert stale is not None
    assert stale.state is SnapshotJobState.FAILED
    assert stale.error == "stale_reclaimed"
    assert replacement.state is SnapshotJobState.RUNNING
    store.close()


def test_job_errors_are_sanitized_and_drive_targeted_retry(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    store.start_job(DATASET, "run-1", started_at=T0)

    store.record_job_errors(
        "run-1",
        {
            " Symbol = AAPL ": RuntimeError("sensitive provider response"),
            "symbol=MSFT": "provider_timeout",
        },
    )
    job = store.finish_job(
        "run-1",
        SnapshotJobState.PARTIAL,
        n_ok=3,
        n_failed=2,
        error="partial_failure",
        finished_at=T0 + timedelta(minutes=10),
    )

    assert job.state is SnapshotJobState.PARTIAL
    assert job.n_ok == 3
    assert job.n_failed == 2
    assert store.retry_entity_keys("run-1") == ["symbol=aapl", "symbol=msft"]
    stored_errors = {
        row[0]
        for row in store._conn.execute(  # noqa: SLF001
            "SELECT error FROM snapshot_job_error WHERE job_run_id = ?",
            ("run-1",),
        )
    }
    assert stored_errors == {"RuntimeError", "provider_timeout"}
    assert "sensitive provider response" not in repr(stored_errors)
    store.close()


def test_replacing_job_errors_removes_recovered_keys(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    store.start_job(DATASET, "run-1", started_at=T0)
    store.record_job_errors(
        "run-1",
        {"symbol=AAPL": "timeout", "symbol=MSFT": "timeout"},
    )

    store.record_job_errors("run-1", {"symbol=MSFT": "timeout"})

    assert store.retry_entity_keys("run-1") == ["symbol=msft"]
    store.close()


@pytest.mark.parametrize(
    "drop_sql",
    [
        "DROP TABLE snapshot_job_error",
        "DROP INDEX ux_snapshot_job_running",
    ],
)
def test_current_schema_refuses_missing_job_guards(tmp_path, drop_sql: str) -> None:
    path = tmp_path / "snapshot.db"
    SqliteSnapshotStore(path).close()
    connection = sqlite3.connect(str(path))
    connection.execute(drop_sql)
    connection.commit()
    connection.close()

    with pytest.raises(SnapshotSchemaMismatch, match="job"):
        SqliteSnapshotStore(path)


def test_reclaimed_worker_cannot_publish_after_losing_lease(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    store.start_job(DATASET, "stale-run", started_at=T0)
    store.stage(
        DATASET,
        "symbol=AAPL",
        date(2026, 9, 11),
        "stale-run",
        {"rows": [{"symbol": "AAPL"}]},
        status=SnapshotStatus.OK,
    )
    assert store.validate(DATASET, "symbol=AAPL", date(2026, 9, 11), "stale-run").ok
    store.start_job(
        DATASET,
        "replacement",
        started_at=T0 + timedelta(hours=2, seconds=1),
    )

    with pytest.raises(SnapshotJobTransitionError, match="lease"):
        store.publish_job(
            "stale-run",
            [(DATASET, "symbol=AAPL", date(2026, 9, 11), "stale-run")],
            finished_at=T0 + timedelta(hours=2, minutes=5),
        )

    assert store.get_live(DATASET, "symbol=AAPL") is None
    with pytest.raises(SnapshotJobTransitionError, match="running"):
        store.record_job_errors("stale-run", {"symbol=AAPL": "late_failure"})
    assert store.retry_entity_keys("stale-run") == []
    store.close()


def test_current_schema_refuses_job_error_table_without_primary_key(
    tmp_path,
) -> None:
    path = tmp_path / "snapshot.db"
    SqliteSnapshotStore(path).close()
    connection = sqlite3.connect(str(path))
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("DROP TABLE snapshot_job_error")
    connection.execute("""
        CREATE TABLE snapshot_job_error (
            job_run_id TEXT NOT NULL,
            entity_key TEXT NOT NULL,
            error TEXT NOT NULL,
            FOREIGN KEY (job_run_id)
                REFERENCES snapshot_job(job_run_id) ON DELETE CASCADE
        )
        """)
    connection.commit()
    connection.close()

    with pytest.raises(SnapshotSchemaMismatch, match="primary key"):
        SqliteSnapshotStore(path)


def test_sqlite_transaction_rolls_back_keyboard_interrupt(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")

    with pytest.raises(KeyboardInterrupt), store._tx(immediate=True):  # noqa: SLF001
        store._conn.execute(  # noqa: SLF001
            "INSERT INTO snapshot_job ("
            "job_run_id, dataset, started_at, state, n_ok, n_failed"
            ") VALUES (?, ?, ?, ?, 0, 0)",
            ("interrupted", DATASET, T0.isoformat(), "running"),
        )
        raise KeyboardInterrupt

    assert not store._conn.in_transaction  # noqa: SLF001
    assert store.get_job("interrupted") is None
    store.start_job(DATASET, "next", started_at=T0)
    store.close()
