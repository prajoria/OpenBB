"""techtrade EOD snapshot store — public contract + backends (#1963).

Re-exports the public contract surface from :mod:`.store` plus both
concrete backends: :class:`~.store.SqliteSnapshotStore` (#1963 Task 2-3)
and :class:`~.mysql_store.MysqlSnapshotStore` (#1963 Task 4). Both
satisfy the :class:`~.store.SnapshotStore` Protocol, so callers depend on
the Protocol and let the backend selector pick the implementation.
"""

from .mysql_store import MysqlSnapshotStore
from .store import (
    FIELD_MAX_LENGTHS,
    SNAPSHOT_SCHEMA_VERSION,
    RetentionPolicy,
    SnapshotFieldTooLong,
    SnapshotRow,
    SnapshotSchemaMismatch,
    SnapshotState,
    SnapshotStatus,
    SnapshotStore,
    SqliteSnapshotStore,
    ValidationResult,
    canonical_key,
    default_validator,
    get_default_snapshot_store,
)

__all__ = [
    "FIELD_MAX_LENGTHS",
    "SNAPSHOT_SCHEMA_VERSION",
    "MysqlSnapshotStore",
    "RetentionPolicy",
    "SnapshotFieldTooLong",
    "SnapshotRow",
    "SnapshotSchemaMismatch",
    "SnapshotState",
    "SnapshotStatus",
    "SnapshotStore",
    "SqliteSnapshotStore",
    "ValidationResult",
    "canonical_key",
    "default_validator",
    "get_default_snapshot_store",
]
