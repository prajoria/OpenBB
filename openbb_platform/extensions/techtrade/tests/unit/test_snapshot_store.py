"""Tests for the #1963 EOD snapshot store contract (Task 1).

Task 1 scope only: the shared value types, ``canonical_key`` normalization,
and the baseline ``default_validator`` gate. The concrete SQLite/MySQL
backends and the ``SnapshotStore`` Protocol's behavior are exercised by
later tasks (#1963 Task 2+); this module only proves the contract types
import cleanly and the two pure helper functions behave per the design
spec (``docs/superpowers/specs/2026-08-09-asof-snapshot-cache-and-alignment-design.md``
§4.2-4.3).
"""

# ruff: noqa: D101, D102, D103, D105

from __future__ import annotations

from datetime import date, datetime, timezone

from openbb_techtrade.snapshot.store import (
    SnapshotRow,
    SnapshotState,
    SnapshotStatus,
    canonical_key,
    default_validator,
)


def _row(*, payload: dict, row_count: int | None = 0) -> SnapshotRow:
    """Build a minimal staged ``SnapshotRow`` for validator-only tests."""
    return SnapshotRow(
        dataset="techtrade.movers",
        entity_key="sector=technology",
        as_of_session=date(2026, 9, 4),
        created_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        job_run_id="run-1",
        status=SnapshotStatus.OK,
        state=SnapshotState.STAGING,
        payload=payload,
        row_count=row_count,
    )


def test_canonical_key_is_idempotent_and_normalizes_label_pairs() -> None:
    canonical = canonical_key(" sector = Information_Technology ")
    assert canonical == "sector=information technology"
    assert canonical_key(canonical) == canonical


def test_default_validator_rejects_empty_payload_and_negative_rows() -> None:
    assert not default_validator(_row(payload={})).ok
    assert not default_validator(_row(payload={"rows": []}, row_count=-1)).ok
    assert default_validator(
        _row(payload={"rows": [{"symbol": "AAPL"}]}, row_count=1)
    ).ok
