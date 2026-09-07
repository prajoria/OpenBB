"""techtrade EOD snapshot store — public contract + backends (#1963).

Re-exports the public contract surface from :mod:`.store` plus both
concrete backends: :class:`~.store.SqliteSnapshotStore` (#1963 Task 2-3)
and :class:`~.mysql_store.MysqlSnapshotStore` (#1963 Task 4). Both
satisfy the :class:`~.store.SnapshotStore` Protocol, so callers depend on
the Protocol and let the backend selector pick the implementation.

``MysqlSnapshotStore`` is exported lazily (PEP 562 module ``__getattr__``,
below) rather than imported at module scope: ``openbb-techtrade``'s
``pyproject.toml`` does not declare ``openbb-fmp-cached``/PyMySQL as a
hard dependency, so an eager ``from .mysql_store import MysqlSnapshotStore``
here would make a SQLite-only install fail at ``import
openbb_techtrade.snapshot`` time, before :func:`~.store.get_default_snapshot_store`
ever gets a chance to fall back to :class:`~.store.SqliteSnapshotStore`.
Deferring the import to first attribute access keeps this package's
public contract surface importable regardless of which backend's
dependencies are installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:  # pragma: no cover - type-checking only, never executed
    from .mysql_store import MysqlSnapshotStore

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


def __getattr__(name: str) -> Any:
    """Lazily import :class:`~.mysql_store.MysqlSnapshotStore` on first access.

    PEP 562: this only runs when ``name`` is not already an attribute of
    this module, so every other export above resolves through the normal,
    zero-cost path. Only ``MysqlSnapshotStore`` — the one export that
    pulls in the optional MySQL stack — is deferred. The imported class
    is cached on the module (``globals()[name] = ...``) so repeated
    access is a plain attribute lookup and ``snapshot.MysqlSnapshotStore
    is MysqlSnapshotStore`` (imported directly from ``.mysql_store``)
    still holds.
    """
    if name == "MysqlSnapshotStore":
        from .mysql_store import (  # noqa: PLC0415  pylint: disable=import-outside-toplevel
            MysqlSnapshotStore as _MysqlSnapshotStore,
        )

        globals()[name] = _MysqlSnapshotStore
        return _MysqlSnapshotStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
