"""Dataset contracts, payload dispatch, and strict PII-aware store routing."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from openbb_techtrade.snapshot.store import (
    SnapshotStore,
    SqliteSnapshotStore,
    canonical_key,
)

PayloadReader = Callable[[dict], Any]


class SnapshotDatasetError(ValueError):
    """Base class for dataset-registry contract violations."""


class UnknownSnapshotDataset(SnapshotDatasetError):
    """A dataset has no registered persistence/privacy contract."""


class UnsupportedPayloadSchema(SnapshotDatasetError):
    """No reader is registered for a persisted payload schema version."""


class PiiStoreRequired(SnapshotDatasetError):
    """A PII-scoped dataset has no user-local store."""


class PiiSharedStoreViolation(SnapshotDatasetError):
    """A PII-scoped dataset was sent directly to a shared store."""


@dataclass(frozen=True)
class DatasetDefinition:
    """Immutable persistence and decoding contract for one dataset."""

    name: str
    pii_scoped: bool
    payload_schema_version: str
    readers: Mapping[str, PayloadReader]

    def __post_init__(self) -> None:
        """Canonicalize and freeze the definition."""
        name = canonical_key(self.name)
        version = self.payload_schema_version.strip()
        readers = MappingProxyType(dict(self.readers))
        if not name:
            raise SnapshotDatasetError("dataset name must be non-empty")
        if not version:
            raise SnapshotDatasetError("payload_schema_version must be non-empty")
        if version not in readers:
            raise SnapshotDatasetError(
                "current payload_schema_version must have a registered reader"
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "payload_schema_version", version)
        object.__setattr__(self, "readers", readers)

    def read(self, payload: dict, schema_version: str | None) -> Any:
        """Decode a stored payload using its version, never the current default."""
        reader = self.readers.get(schema_version or "")
        if reader is None:
            raise UnsupportedPayloadSchema(
                f"{self.name}: unsupported payload schema version"
            )
        return reader(payload)


class SnapshotDatasetRegistry:
    """Canonical, duplicate-safe registry of snapshot dataset contracts."""

    def __init__(self, definitions: Iterable[DatasetDefinition] = ()) -> None:
        self._definitions: dict[str, DatasetDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: DatasetDefinition) -> None:
        """Register one definition; duplicate names are configuration errors."""
        if definition.name in self._definitions:
            raise SnapshotDatasetError(
                f"snapshot dataset {definition.name!r} is already registered"
            )
        self._definitions[definition.name] = definition

    def get(self, name: str) -> DatasetDefinition | None:
        """Return a definition by canonical name, or ``None``."""
        return self._definitions.get(canonical_key(name))

    def require(self, name: str) -> DatasetDefinition:
        """Return a definition or fail closed for an unknown dataset."""
        definition = self.get(name)
        if definition is None:
            raise UnknownSnapshotDataset("snapshot dataset is not registered")
        return definition

    @property
    def has_pii_scoped(self) -> bool:
        """Return whether any registered dataset requires local-only storage."""
        return any(definition.pii_scoped for definition in self._definitions.values())


def _identity_reader(payload: dict) -> dict:
    return payload


DEFAULT_DATASET_REGISTRY = SnapshotDatasetRegistry(
    [
        DatasetDefinition(
            name="techtrade.movers",
            pii_scoped=False,
            payload_schema_version="1",
            readers={"1": _identity_reader},
        ),
        DatasetDefinition(
            name="techtrade.scan",
            pii_scoped=False,
            payload_schema_version="1",
            readers={"1": _identity_reader},
        ),
    ]
)


class SnapshotStoreRouter:
    """Route public data to shared storage and PII only to local storage."""

    def __init__(
        self,
        shared_store: SnapshotStore,
        local_store: SnapshotStore | None,
        registry: SnapshotDatasetRegistry = DEFAULT_DATASET_REGISTRY,
    ) -> None:
        self._shared_store = shared_store
        self._local_store = local_store
        self._registry = registry

    def for_dataset(self, name: str) -> SnapshotStore:
        """Return the only store permitted for ``name``."""
        definition = self._registry.require(name)
        if not definition.pii_scoped:
            return self._shared_store
        if not isinstance(self._local_store, SqliteSnapshotStore):
            raise PiiStoreRequired(
                "PII-scoped snapshots require an explicit user-local store"
            )
        return self._local_store


def read_live_payload(
    store: SnapshotStore,
    registry: SnapshotDatasetRegistry,
    dataset: str,
    entity_key: str,
) -> Any | None:
    """Read LIVE once and dispatch its payload by the stored schema version."""
    definition = registry.require(dataset)
    row = store.get_live(definition.name, entity_key)
    if row is None:
        return None
    return definition.read(row.payload, row.payload_schema_version)
