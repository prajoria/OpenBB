"""techtrade EOD snapshot store — public contract (#1963).

Re-exports only the public contract surface from :mod:`.store`. Concrete
backends (SQLite, MySQL) and the backend selector are added by later tasks
in the same issue; import them from their own modules once they land.
"""

from .store import (
    RetentionPolicy,
    SnapshotRow,
    SnapshotState,
    SnapshotStatus,
    SnapshotStore,
    ValidationResult,
    canonical_key,
    default_validator,
)

__all__ = [
    "RetentionPolicy",
    "SnapshotRow",
    "SnapshotState",
    "SnapshotStatus",
    "SnapshotStore",
    "ValidationResult",
    "canonical_key",
    "default_validator",
]
