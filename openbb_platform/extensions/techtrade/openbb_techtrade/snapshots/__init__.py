"""TechTrade scan snapshot persistence (issue #1934).

Public surface:

- :class:`ScanSnapshot` -- the append-only, widget-ready snapshot record;
- :func:`plan_to_row` -- narrows a ``TradePlan`` to a JSON-safe row;
- :class:`ScanSnapshotStore` -- the persistence protocol;
- :class:`SqliteScanSnapshotStore` -- the single-host SQLite implementation.
"""

from openbb_techtrade.snapshots.models import (
    DEFAULT_SCAN_KIND,
    ScanSnapshot,
    new_snapshot_id,
    plan_to_row,
)
from openbb_techtrade.snapshots.sqlite import (
    SCAN_DB_ENV,
    SqliteScanSnapshotStore,
    default_scan_db_path,
)
from openbb_techtrade.snapshots.store import DEFAULT_RETENTION, ScanSnapshotStore

__all__ = [
    "DEFAULT_RETENTION",
    "DEFAULT_SCAN_KIND",
    "SCAN_DB_ENV",
    "ScanSnapshot",
    "ScanSnapshotStore",
    "SqliteScanSnapshotStore",
    "default_scan_db_path",
    "new_snapshot_id",
    "plan_to_row",
]
