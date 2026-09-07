"""Persistence contract for TechTrade scan snapshots (issue #1934).

``ScanSnapshotStore`` is a ``Protocol`` so neither ``run_scan`` nor the Morning
Scan widgets depend on SQLite. The initial implementation is
:class:`~openbb_techtrade.snapshots.sqlite.SqliteScanSnapshotStore`, but the seam
leaves room for a MySQL/Postgres adapter when multi-host reads are required --
exactly the same discipline the core ``JobStore`` protocol uses.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from openbb_techtrade.snapshots.models import ScanSnapshot

#: Default number of snapshots retained per ``(kind, segment)`` by pruning.
DEFAULT_RETENTION = 10


@runtime_checkable
class ScanSnapshotStore(Protocol):
    """Durable, append-only store for widget-ready scan snapshots."""

    def initialize(self) -> None:
        """Create or migrate the underlying schema."""

    def close(self) -> None:
        """Release any resources held by the store."""

    def write_snapshot(self, snapshot: ScanSnapshot) -> ScanSnapshot:
        """Append one immutable snapshot and return the persisted record."""

    def read_latest(self, *, kind: str, segment: str) -> ScanSnapshot | None:
        """Return the most recent snapshot for a ``(kind, segment)`` or ``None``."""

    def read_by_id(self, snapshot_id: str) -> ScanSnapshot | None:
        """Return a snapshot by identifier or ``None`` when absent."""

    def list_snapshots(
        self,
        *,
        kind: str | None = None,
        segment: str | None = None,
        limit: int | None = None,
    ) -> list[ScanSnapshot]:
        """Return snapshots newest-first, optionally filtered and capped."""

    def prune_snapshots(self, *, keep: int = DEFAULT_RETENTION) -> int:
        """Retain the newest ``keep`` snapshots per ``(kind, segment)``.

        Returns the number of snapshots deleted.
        """
