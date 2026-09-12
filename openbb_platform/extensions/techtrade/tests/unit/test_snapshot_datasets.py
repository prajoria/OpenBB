"""TechTrade snapshot dataset contracts and validation policy."""

# ruff: noqa: D103

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from openbb_techtrade.snapshot.datasets import (
    TECHTRADE_DATASETS,
    techtrade_entity_key,
    validate_techtrade_snapshot,
)
from openbb_techtrade.snapshot.job import SnapshotJobState
from openbb_techtrade.snapshot.refresh import (
    ComputedSnapshot,
    SnapshotRefreshOrchestrator,
)
from openbb_techtrade.snapshot.registry import (
    DEFAULT_DATASET_REGISTRY,
    SnapshotStoreRouter,
)
from openbb_techtrade.snapshot.store import (
    SnapshotRow,
    SnapshotState,
    SnapshotStatus,
    SqliteSnapshotStore,
)

NOW = datetime(2026, 9, 11, 22, tzinfo=timezone.utc)
SESSION = date(2026, 9, 11)
DATASET = "techtrade.movers"
KEY = "segment=Information Technology"


def _row(
    payload: dict,
    *,
    row_count: int | None = None,
    state: SnapshotState = SnapshotState.STAGING,
) -> SnapshotRow:
    return SnapshotRow(
        dataset=DATASET,
        entity_key=KEY,
        as_of_session=SESSION,
        created_at=NOW,
        job_run_id="job",
        status=SnapshotStatus.OK,
        state=state,
        payload=payload,
        row_count=row_count,
        engine_version="test",
        payload_schema_version="1",
    )


def _payload(rows: list[dict]) -> dict:
    return {
        "rows": rows,
        "segment": "Information Technology",
        "as_of_session": SESSION.isoformat(),
        "exchange_calendar": "XNYS",
        "earnings_symbols": [],
        "excluded_symbols": [],
        "survivorship": "not-applicable",
    }


def test_all_consumer_datasets_are_public_versioned_and_validated() -> None:
    assert TECHTRADE_DATASETS == (
        "techtrade.movers",
        "techtrade.scan",
        "techtrade.signals",
        "techtrade.plan",
        "techtrade.orders",
        "techtrade.simulate",
        "techtrade.validate",
        "techtrade.tune",
        "techtrade.audit",
    )
    for name in TECHTRADE_DATASETS:
        definition = DEFAULT_DATASET_REGISTRY.require(name)
        assert definition.pii_scoped is False
        assert definition.payload_schema_version == "1"
        assert definition.validator is validate_techtrade_snapshot


def test_entity_key_is_canonical_and_rejects_unknown_segments() -> None:
    assert (
        techtrade_entity_key("Information Technology")
        == "segment=information technology"
    )
    with pytest.raises(ValueError, match="unknown TechTrade segment"):
        techtrade_entity_key("Not A Sector")


def test_validator_accepts_well_formed_payload() -> None:
    verdict = validate_techtrade_snapshot(
        _row(
            _payload(
                [
                    {"symbol": "AAPL", "close": 100.0, "date": "2026-09-10"},
                    {"symbol": "MSFT", "close": 200.0, "date": "2026-09-11"},
                ]
            ),
            row_count=2,
        )
    )
    assert verdict.ok


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"rows": []}, "missing metadata"),
        (_payload([{"symbol": "AAPL", "close": None}]), "all-null column"),
        (_payload([{"symbol": "AAPL", "close": 0.0}]), "positive"),
        (
            _payload(
                [
                    {"symbol": "AAPL", "date": "2026-09-11"},
                    {"symbol": "MSFT", "date": "2026-09-10"},
                ]
            ),
            "monotonic",
        ),
    ],
)
def test_validator_rejects_malformed_rows(payload: dict, reason: str) -> None:
    verdict = validate_techtrade_snapshot(_row(payload, row_count=len(payload["rows"])))
    assert not verdict.ok
    assert reason in verdict.reason


def test_validator_rejects_implausible_row_count_drop() -> None:
    previous = _row(
        _payload([{"symbol": f"S{i}", "close": float(i + 1)} for i in range(10)]),
        row_count=10,
        state=SnapshotState.LIVE,
    )
    candidate = _row(
        _payload([{"symbol": f"S{i}", "close": float(i + 1)} for i in range(6)]),
        row_count=6,
    )

    verdict = validate_techtrade_snapshot(candidate, previous)

    assert not verdict.ok
    assert "70%" in verdict.reason


def test_validator_rejects_unknown_exchange_calendar() -> None:
    payload = _payload([])
    payload["exchange_calendar"] = "NOT-A-CALENDAR"

    verdict = validate_techtrade_snapshot(_row(payload, row_count=0))

    assert not verdict.ok
    assert "unknown exchange calendar" in verdict.reason


def test_validator_accounts_for_explicitly_excluded_rows() -> None:
    previous = _row(
        _payload([{"symbol": f"S{i}", "close": float(i + 1)} for i in range(10)]),
        row_count=10,
        state=SnapshotState.LIVE,
    )
    payload = _payload([{"symbol": f"S{i}", "close": float(i + 1)} for i in range(6)])
    payload["excluded_symbols"] = ["S6", "S7", "S8", "S9"]

    assert validate_techtrade_snapshot(_row(payload, row_count=6), previous).ok


def test_validator_rejects_non_session_as_of_date() -> None:
    saturday = date(2026, 9, 12)
    payload = _payload([])
    payload["as_of_session"] = saturday.isoformat()

    verdict = validate_techtrade_snapshot(
        replace(_row(payload, row_count=0), as_of_session=saturday)
    )

    assert not verdict.ok
    assert "exchange session" in verdict.reason


class _InvalidAdapter:
    name = DATASET

    def entity_keys(self) -> list[str]:
        return [KEY]

    def compute(self, entity_key: str, as_of_session: date) -> ComputedSnapshot:
        return ComputedSnapshot(
            payload=_payload([{"symbol": "AAPL", "close": None}]),
            inputs={"entity_key": entity_key, "as_of": str(as_of_session)},
            engine_version="test",
            payload_schema_version="1",
            row_count=1,
        )


def test_orchestrator_uses_registered_dataset_validator(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    orchestrator = SnapshotRefreshOrchestrator(
        SnapshotStoreRouter(store, None, DEFAULT_DATASET_REGISTRY),
        DEFAULT_DATASET_REGISTRY,
        {DATASET: _InvalidAdapter()},
        clock=lambda: NOW,
        job_id_factory=lambda: "invalid-job",
    )

    job = orchestrator.run(DATASET)

    assert job.state is SnapshotJobState.FAILED
    assert store.get_live(DATASET, KEY) is None
    assert store.retry_entity_keys(job.job_run_id) == ["segment=information technology"]
    store.close()
