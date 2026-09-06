"""EOD snapshot store — public contract and SQLite backend (#1963 Task 1-2).

This module owns the shared value types, the ``canonical_key`` normalizer,
the baseline ``default_validator`` gate, the ``SnapshotStore`` Protocol, and
(#1963 Task 2) the concrete ``SqliteSnapshotStore`` lifecycle backend. The
MySQL backend (#1963 Task 4) implements the same Protocol in its own
module. See the approved design spec for the full contract this mirrors:
``docs/superpowers/specs/2026-08-09-asof-snapshot-cache-and-alignment-design.md``
§3-4.

Design invariants this module encodes (see the spec for the full list):

- **Keep-last-good ranking.** ``_STATUS_RANK`` orders
  ``FAILED < STALE < PARTIAL < OK`` so a promote can refuse to let a worse
  run displace a better LIVE row (enforced in Task 2's ``promote()``).
- **Canonicalization is a shared-store obligation.** Every caller — writer
  and reader alike — must run ``dataset``/``entity_key`` through
  ``canonical_key`` before it touches the store, or two writers using
  differently-cased labels (``Information Technology`` vs.
  ``information_technology``) would produce split-brain LIVE rows.
- **``as_of_session`` vs. ``created_at``.** The former is the trading day
  the payload is *about* (a ``date``); the latter is the wall-clock UTC
  instant of the write (a tz-aware ``datetime``). The two concepts must
  never collapse into a single timestamp.

Read path is compute-free: nothing in this module calls a provider or
performs a live computation. That remains true for every concrete backend
built on top of this contract.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class SnapshotStatus(str, Enum):
    """Outcome of a single snapshot write, also the keep-last-good rank key."""

    OK = "ok"
    PARTIAL = "partial"
    STALE = "stale"
    FAILED = "failed"


class SnapshotState(str, Enum):
    """Lifecycle of a row: staged, promoted to LIVE, or superseded by promote."""

    STAGING = "staging"
    LIVE = "live"
    SUPERSEDED = "superseded"


# Keep-last-good ranking: a candidate may only promote over the current LIVE
# row if its status ranks the same or higher. FAILED never displaces
# anything; OK may displace everything below it. See design spec §4.1/§5#2.
_STATUS_RANK = {
    SnapshotStatus.FAILED: 0,
    SnapshotStatus.STALE: 1,
    SnapshotStatus.PARTIAL: 2,
    SnapshotStatus.OK: 3,
}


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of running a validator against a staged row."""

    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class RetentionPolicy:
    """Retention hook (design spec §3.3). ``None`` = keep-all, the v1 default."""

    keep_sessions: int | None = None


@dataclass(frozen=True)
class SnapshotRow:  # pylint: disable=too-many-instance-attributes
    """A single persisted (or staged) snapshot row.

    ``as_of_session`` is the trading day the payload is about; ``created_at``
    is the tz-aware UTC wall-clock instant of the write. Every concrete
    backend must return these two as ``date`` / ``datetime`` respectively
    regardless of how the dialect stores them on disk. The field count
    (14) is a binding part of the approved design spec §4.1, not an
    accidental design smell — every field maps to a required schema
    column (see spec §3.1).
    """

    dataset: str
    entity_key: str
    as_of_session: date
    created_at: datetime
    job_run_id: str
    status: SnapshotStatus
    state: SnapshotState
    payload: dict = field(default_factory=dict)
    input_hash: str | None = None
    row_count: int | None = None
    validated: bool = False
    validation_reason: str = ""
    engine_version: str | None = None
    payload_schema_version: str | None = None


def canonical_key(raw: str) -> str:
    """Normalize a ``dataset`` or ``entity_key`` to a single canonical form.

    Both writer and reader MUST call this before any store operation — see
    design spec §4.2 (review item #4). Rules: strip surrounding whitespace;
    treat underscores as word separators; collapse internal whitespace to
    single spaces; for ``field=Label`` pairs, keep the field name verbatim
    but casefold the label half; a bare value (no ``=``) is casefolded in
    full. Deterministic and idempotent:
    ``canonical_key(canonical_key(x)) == canonical_key(x)``.
    """
    value = " ".join(raw.strip().replace("_", " ").split())
    if "=" not in value:
        return value.casefold()
    field_name, label = value.split("=", 1)
    return f"{field_name.strip()}={label.strip().casefold()}"


def default_validator(row: SnapshotRow) -> ValidationResult:
    """Baseline sanity gate: reject empty payload; reject negative row_count.

    Callers pass a stricter ``validator=`` for dataset-specific bounds
    (row_count within X% of last run, no all-null columns, prices > 0,
    ...). This baseline only guards against the two universally-invalid
    shapes any dataset would agree are broken.
    """
    if not row.payload:
        return ValidationResult(ok=False, reason="payload is empty")
    if row.row_count is not None and row.row_count < 0:
        return ValidationResult(ok=False, reason="row_count is negative")
    return ValidationResult(ok=True)


class SnapshotStore(Protocol):
    """Structural contract for any EOD snapshot backend.

    The Terminal reader and the techtrade writer depend on this Protocol,
    not on a concrete class — mirroring the repo's ``PaperEngine`` /
    ``MysqlPaperEngine`` + ``SqlitePaperEngine`` seam. Signatures are
    binding per the approved design spec §4.4; concrete backends (#1963
    Task 2 SQLite, Task 4 MySQL) own the bodies.
    """

    def stage(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
        payload: dict,
        *,
        status: SnapshotStatus = SnapshotStatus.OK,
        input_hash: str | None = None,
        row_count: int | None = None,
        engine_version: str | None = None,
        payload_schema_version: str | None = None,
    ) -> None:
        """Write a run to STAGING; NEVER touches the LIVE view."""
        ...  # pylint: disable=unnecessary-ellipsis

    def validate(  # pylint: disable=too-many-positional-arguments
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
        validator: Callable[[SnapshotRow], ValidationResult] | None = None,
    ) -> ValidationResult:
        """Run the gate on the staged row; persist validated flag + reason."""
        ...  # pylint: disable=unnecessary-ellipsis

    def promote(
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
    ) -> bool:
        """Atomically promote a validated staged row to LIVE.

        Refuses if not validated; refuses if the staged rank is lower than
        the current LIVE rank (keep-last-good); else flips the prior LIVE
        row to superseded and this row to LIVE. Returns ``True`` on
        success, ``False`` on any refusal (logs a WARNING).
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def get_live(self, dataset: str, entity_key: str) -> SnapshotRow | None:
        """Compute-free single-row read of ``state='live'``; ``None`` if absent."""
        ...  # pylint: disable=unnecessary-ellipsis

    def get_as_of(
        self, dataset: str, entity_key: str, as_of_session: date
    ) -> SnapshotRow | None:
        """Promoted row for a specific session (replay/compare-to-yesterday)."""
        ...  # pylint: disable=unnecessary-ellipsis

    def list_history(
        self, dataset: str, entity_key: str, limit: int = 50
    ) -> list[SnapshotRow]:
        """Newest-first rows for a key, retained for audit/replay/diffing."""
        ...  # pylint: disable=unnecessary-ellipsis

    def should_skip(self, dataset: str, entity_key: str, input_hash: str) -> bool:
        """Report whether the LIVE row already carries this ``input_hash``.

        A skip must not strand the staleness badge — see design spec §4.5;
        callers should follow a skip with ``restamp_live`` on a new session.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def restamp_live(
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
    ) -> bool:
        """Advance the LIVE pointer's ``as_of_session`` without recomputing.

        Writes a superseded history row for audit; returns ``True`` on
        success.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def prune(self, policy: RetentionPolicy | None = None) -> int:
        """Apply retention; return the number of rows removed.

        The default policy (``None``) keeps everything and returns ``0``.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def close(self) -> None:
        """Release any held resources (connections, file handles, ...)."""
        ...  # pylint: disable=unnecessary-ellipsis


# --- SQLite backend (#1963 Task 2) -----------------------------------------
#
# Schema per design spec §3.1. SQLite has no native DATE/DATETIME type, so
# ``as_of_session``/``created_at`` are stored as ISO-8601 text (a SQLite
# workaround, not a cross-dialect mandate — MySQL uses native DATE/DATETIME,
# see Task 4). The partial unique index is the DB-level half of the
# "exactly one LIVE row per key" invariant; ``promote()``'s validated+rank
# guard is the application-level half (spec §3.1 "LIVE resolution").
_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS pi_snapshot (
    dataset            TEXT NOT NULL,
    entity_key         TEXT NOT NULL,
    as_of_session      TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    job_run_id         TEXT NOT NULL,
    status             TEXT NOT NULL,
    state              TEXT NOT NULL,
    validated          INTEGER NOT NULL DEFAULT 0,
    validation_reason  TEXT NOT NULL DEFAULT '',
    payload_json       TEXT NOT NULL,
    input_hash         TEXT,
    row_count          INTEGER,
    engine_version         TEXT,
    payload_schema_version TEXT,
    PRIMARY KEY (dataset, entity_key, as_of_session, job_run_id)
);
CREATE INDEX IF NOT EXISTS ix_pi_snapshot_live
    ON pi_snapshot(dataset, entity_key, state);
CREATE INDEX IF NOT EXISTS ix_pi_snapshot_latest
    ON pi_snapshot(dataset, entity_key, as_of_session DESC, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pi_snapshot_live
    ON pi_snapshot(dataset, entity_key) WHERE state = 'live';
"""


def _now_iso() -> str:
    """Wall-clock UTC instant of the write, ISO-8601 (spec §3, 12.3 #8)."""
    return datetime.now(timezone.utc).isoformat()


def _row_from_record(record: sqlite3.Row) -> SnapshotRow:
    """Parse a raw ``pi_snapshot`` row back into a typed ``SnapshotRow``.

    Reverses the ISO-text storage workaround: ``as_of_session`` becomes a
    plain ``date``, ``created_at`` a tz-aware UTC ``datetime`` — the split
    the design spec (§3, 12.3 #8) requires regardless of on-disk dialect.
    """
    return SnapshotRow(
        dataset=record["dataset"],
        entity_key=record["entity_key"],
        as_of_session=date.fromisoformat(record["as_of_session"]),
        created_at=datetime.fromisoformat(record["created_at"]),
        job_run_id=record["job_run_id"],
        status=SnapshotStatus(record["status"]),
        state=SnapshotState(record["state"]),
        payload=json.loads(record["payload_json"]),
        input_hash=record["input_hash"],
        row_count=record["row_count"],
        validated=bool(record["validated"]),
        validation_reason=record["validation_reason"],
        engine_version=record["engine_version"],
        payload_schema_version=record["payload_schema_version"],
    )


class SqliteSnapshotStore:
    """SQLite-backed EOD snapshot store implementing the ``SnapshotStore`` Protocol.

    Task 2 scope only: ``stage``/``validate``/``promote``/``get_live``/
    ``get_as_of``/``list_history``/``close``. ``should_skip``/
    ``restamp_live``/``prune`` land in Task 3 on the same class.

    Threading: mirrors ``SqlitePaperEngine`` — ``check_same_thread=False``
    with ``isolation_level=None`` (autocommit) so every multi-statement
    write goes through :meth:`_tx` for all-or-nothing semantics. Rows come
    back as ``sqlite3.Row`` for name-based column access.

    Read path is compute-free: every read method here only ever issues a
    ``SELECT`` against ``pi_snapshot`` — none of them calls a provider or
    a compute/scan function.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path).resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SQLITE_SCHEMA)

    @contextmanager
    def _tx(self) -> Iterator[None]:
        """Transaction scope — all-or-nothing for multi-statement writes."""
        try:
            self._conn.execute("BEGIN")
            yield
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def _get_row(
        self, dataset: str, entity_key: str, as_of_session: date, job_run_id: str
    ) -> SnapshotRow | None:
        """Fetch the exact row identified by the full primary key.

        Callers must pass already-canonicalized ``dataset``/``entity_key``.
        """
        record = self._conn.execute(
            "SELECT dataset, entity_key, as_of_session, created_at, "
            "job_run_id, status, state, validated, validation_reason, "
            "payload_json, input_hash, row_count, engine_version, "
            "payload_schema_version FROM pi_snapshot "
            "WHERE dataset = ? AND entity_key = ? AND as_of_session = ? "
            "AND job_run_id = ?",
            (dataset, entity_key, as_of_session.isoformat(), job_run_id),
        ).fetchone()
        return _row_from_record(record) if record is not None else None

    # --- Protocol methods ---------------------------------------------

    def stage(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
        payload: dict,
        *,
        status: SnapshotStatus = SnapshotStatus.OK,
        input_hash: str | None = None,
        row_count: int | None = None,
        engine_version: str | None = None,
        payload_schema_version: str | None = None,
    ) -> None:
        """Write a run to STAGING; never touches the LIVE view."""
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        with self._tx():
            self._conn.execute(
                "INSERT INTO pi_snapshot ("
                "dataset, entity_key, as_of_session, created_at, job_run_id, "
                "status, state, validated, validation_reason, payload_json, "
                "input_hash, row_count, engine_version, payload_schema_version"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?, ?, ?, ?)",
                (
                    dataset,
                    entity_key,
                    as_of_session.isoformat(),
                    _now_iso(),
                    job_run_id,
                    status.value,
                    SnapshotState.STAGING.value,
                    json.dumps(payload, sort_keys=True, default=str),
                    input_hash,
                    row_count,
                    engine_version,
                    payload_schema_version,
                ),
            )

    def validate(  # pylint: disable=too-many-positional-arguments
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
        validator: Callable[[SnapshotRow], ValidationResult] | None = None,
    ) -> ValidationResult:
        """Run the gate on the staged row; persist validated flag + reason."""
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        row = self._get_row(dataset, entity_key, as_of_session, job_run_id)
        if row is None:
            return ValidationResult(ok=False, reason="staged snapshot not found")
        gate = validator or default_validator
        result = gate(row)
        with self._tx():
            self._conn.execute(
                "UPDATE pi_snapshot SET validated = ?, validation_reason = ? "
                "WHERE dataset = ? AND entity_key = ? AND as_of_session = ? "
                "AND job_run_id = ?",
                (
                    1 if result.ok else 0,
                    result.reason,
                    dataset,
                    entity_key,
                    as_of_session.isoformat(),
                    job_run_id,
                ),
            )
        return result

    def promote(
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
    ) -> bool:
        """Atomically promote a validated staged row to LIVE.

        Refuses if not validated; refuses if the staged rank is lower than
        the current LIVE rank (keep-last-good); else flips the prior LIVE
        row to superseded and this row to LIVE. Returns ``True`` on
        success, ``False`` on any refusal (logs a WARNING).
        """
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        candidate = self._get_row(dataset, entity_key, as_of_session, job_run_id)
        if candidate is None or not candidate.validated:
            logger.warning("snapshot promotion refused: candidate is not validated")
            return False
        live = self.get_live(dataset, entity_key)
        if live and _STATUS_RANK[candidate.status] < _STATUS_RANK[live.status]:
            logger.warning(
                "snapshot promotion refused: candidate status is worse than LIVE"
            )
            return False
        with self._tx():
            if live is not None:
                self._conn.execute(
                    "UPDATE pi_snapshot SET state = ? "
                    "WHERE dataset = ? AND entity_key = ? AND state = ?",
                    (
                        SnapshotState.SUPERSEDED.value,
                        dataset,
                        entity_key,
                        SnapshotState.LIVE.value,
                    ),
                )
            self._conn.execute(
                "UPDATE pi_snapshot SET state = ? "
                "WHERE dataset = ? AND entity_key = ? AND as_of_session = ? "
                "AND job_run_id = ?",
                (
                    SnapshotState.LIVE.value,
                    dataset,
                    entity_key,
                    as_of_session.isoformat(),
                    job_run_id,
                ),
            )
        return True

    def get_live(self, dataset: str, entity_key: str) -> SnapshotRow | None:
        """Compute-free single-row read of ``state='live'``; ``None`` if absent."""
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        record = self._conn.execute(
            "SELECT dataset, entity_key, as_of_session, created_at, "
            "job_run_id, status, state, validated, validation_reason, "
            "payload_json, input_hash, row_count, engine_version, "
            "payload_schema_version FROM pi_snapshot "
            "WHERE dataset = ? AND entity_key = ? AND state = ?",
            (dataset, entity_key, SnapshotState.LIVE.value),
        ).fetchone()
        return _row_from_record(record) if record is not None else None

    def get_as_of(
        self, dataset: str, entity_key: str, as_of_session: date
    ) -> SnapshotRow | None:
        """Promoted row for a specific session (replay/compare-to-yesterday)."""
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        record = self._conn.execute(
            "SELECT dataset, entity_key, as_of_session, created_at, "
            "job_run_id, status, state, validated, validation_reason, "
            "payload_json, input_hash, row_count, engine_version, "
            "payload_schema_version FROM pi_snapshot "
            "WHERE dataset = ? AND entity_key = ? AND as_of_session = ? "
            "AND state != ? ORDER BY created_at DESC LIMIT 1",
            (
                dataset,
                entity_key,
                as_of_session.isoformat(),
                SnapshotState.STAGING.value,
            ),
        ).fetchone()
        return _row_from_record(record) if record is not None else None

    def list_history(
        self, dataset: str, entity_key: str, limit: int = 50
    ) -> list[SnapshotRow]:
        """Newest-first rows for a key, retained for audit/replay/diffing."""
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        records = self._conn.execute(
            "SELECT dataset, entity_key, as_of_session, created_at, "
            "job_run_id, status, state, validated, validation_reason, "
            "payload_json, input_hash, row_count, engine_version, "
            "payload_schema_version FROM pi_snapshot "
            "WHERE dataset = ? AND entity_key = ? "
            "ORDER BY as_of_session DESC, created_at DESC LIMIT ?",
            (dataset, entity_key, limit),
        ).fetchall()
        return [_row_from_record(record) for record in records]

    def close(self) -> None:
        """Release the SQLite connection."""
        self._conn.close()
