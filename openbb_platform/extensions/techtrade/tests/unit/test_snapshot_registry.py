"""Dataset schema dispatch and PII routing contracts (#1964/#1965)."""

# ruff: noqa: D103

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from openbb_techtrade.snapshot.registry import (
    DatasetDefinition,
    PiiStoreRequired,
    SnapshotDatasetRegistry,
    SnapshotStoreRouter,
    UnsupportedPayloadSchema,
    read_live_payload,
)
from openbb_techtrade.snapshot.store import (
    SnapshotRow,
    SnapshotState,
    SnapshotStatus,
    SqliteSnapshotStore,
)


class _ReadableStore:
    def __init__(self, row: SnapshotRow | None = None) -> None:
        self.row = row

    def get_live(self, dataset: str, entity_key: str) -> SnapshotRow | None:
        del dataset, entity_key
        return self.row


def _definition(*, name: str, pii_scoped: bool = False) -> DatasetDefinition:
    return DatasetDefinition(
        name=name,
        pii_scoped=pii_scoped,
        payload_schema_version="2",
        readers={
            "1": lambda payload: ("v1", payload["value"]),
            "2": lambda payload: ("v2", payload["value"]),
        },
    )


def _row(*, schema_version: str) -> SnapshotRow:
    return SnapshotRow(
        dataset="techtrade.movers",
        entity_key="market=us",
        as_of_session=date(2026, 9, 11),
        created_at=datetime(2026, 9, 11, 22, tzinfo=timezone.utc),
        job_run_id="run-1",
        status=SnapshotStatus.OK,
        state=SnapshotState.LIVE,
        payload={"value": 7},
        validated=True,
        engine_version="engine-1",
        payload_schema_version=schema_version,
    )


def test_reader_dispatches_by_stored_schema_version() -> None:
    registry = SnapshotDatasetRegistry([_definition(name="techtrade.movers")])

    decoded = read_live_payload(
        _ReadableStore(_row(schema_version="1")),
        registry,
        "techtrade.movers",
        "market=us",
    )

    assert decoded == ("v1", 7)


def test_reader_fails_closed_on_unknown_schema_version() -> None:
    registry = SnapshotDatasetRegistry([_definition(name="techtrade.movers")])

    with pytest.raises(UnsupportedPayloadSchema, match="schema version"):
        read_live_payload(
            _ReadableStore(_row(schema_version="99")),
            registry,
            "techtrade.movers",
            "market=us",
        )


def test_router_sends_pii_only_to_explicit_local_store(tmp_path) -> None:
    shared = object()
    local = SqliteSnapshotStore(tmp_path / "snapshot.db")
    registry = SnapshotDatasetRegistry(
        [
            _definition(name="techtrade.movers"),
            _definition(name="pi.account.weights", pii_scoped=True),
        ]
    )
    router = SnapshotStoreRouter(shared, local, registry)

    assert router.for_dataset("techtrade.movers") is shared
    assert router.for_dataset("pi.account.weights") is local
    local.close()


def test_router_refuses_pii_without_local_store() -> None:
    registry = SnapshotDatasetRegistry(
        [_definition(name="pi.account.weights", pii_scoped=True)]
    )

    with pytest.raises(PiiStoreRequired):
        SnapshotStoreRouter(object(), None, registry).for_dataset("pi.account.weights")


def test_router_rejects_arbitrary_store_as_pii_local_destination() -> None:
    registry = SnapshotDatasetRegistry(
        [_definition(name="pi.account.weights", pii_scoped=True)]
    )

    with pytest.raises(PiiStoreRequired):
        SnapshotStoreRouter(object(), object(), registry).for_dataset(
            "pi.account.weights"
        )


def test_default_registry_marks_public_class_b_datasets_pii_free() -> None:
    from openbb_techtrade.snapshot.registry import DEFAULT_DATASET_REGISTRY

    assert not DEFAULT_DATASET_REGISTRY.require("techtrade.movers").pii_scoped
    assert not DEFAULT_DATASET_REGISTRY.require("techtrade.scan").pii_scoped
