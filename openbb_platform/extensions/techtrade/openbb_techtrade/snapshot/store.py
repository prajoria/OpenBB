"""EOD snapshot store — public contract and SQLite backend (#1963 Task 1-2).

This module owns the shared value types, the ``canonical_key`` normalizer,
the baseline ``default_validator`` gate, the ``SnapshotStore`` Protocol, the
dialect-agnostic row conversion + lifecycle *policy* helpers every backend
reuses, and (#1963 Task 2) the concrete ``SqliteSnapshotStore`` lifecycle
backend. The MySQL backend (#1963 Task 4) implements the same Protocol in
its own module and imports the policy helpers from here rather than
restating them — one place decides what "validated", "promotable", and
"retained" mean. See the approved design spec for the full contract this
mirrors:
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

# pylint: disable=too-many-lines
# #1963 Task 5 added the `get_default_snapshot_store` factory (~75 lines),
# pushing the module past pylint's 1000-line threshold. Splitting the
# factory out feels premature — it is one cohesive selector next to the
# backend it defaults to. Reconsider if a later task grows this further.

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

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


# --- Bounded identifier/provenance fields (#1963 Task 4) ------------------
#
# The MySQL table declares finite widths for the identity and provenance
# columns; SQLite ignores widths entirely. Enforcing them here — once, in
# shared Python, before any statement is issued — is what keeps the two
# backends interchangeable: a call one accepts is a call the other
# accepts. The alternative is silent divergence, and on a MySQL server
# without strict mode a truncated ``job_run_id`` or ``input_hash`` is
# corrupted provenance that no later read can detect.
#
# The values mirror ``_PI_SNAPSHOT_DDL`` exactly (a test asserts the two
# cannot drift apart). ``entity_key`` stops at 191 because 191 * 4 bytes
# of utf8mb4 is the widest value InnoDB can put under the historical
# 767-byte index prefix limit.

FIELD_MAX_LENGTHS: dict[str, int] = {
    "dataset": 128,
    "entity_key": 191,
    "job_run_id": 128,
    "input_hash": 128,
    "engine_version": 64,
    "payload_schema_version": 64,
}

_PREVIEW_CHARS = 32


class SnapshotFieldTooLong(ValueError):
    """A bounded identifier/provenance value exceeds its column width.

    Raised *before* the write, identically on every backend, so the
    caller learns which field is too long instead of discovering a
    truncated identifier weeks later in an audit.
    """

    def __init__(self, field_name: str, value: str, limit: int) -> None:
        self.field_name = field_name
        self.limit = limit
        self.length = len(value)
        preview = value[:_PREVIEW_CHARS]
        if self.length > _PREVIEW_CHARS:
            preview += "..."
        super().__init__(
            f"{field_name} is {self.length} characters; the column holds at "
            f"most {limit}. Refusing to write a value the database would "
            f"truncate: {preview!r}"
        )


def _check_field_lengths(**fields: str | None) -> None:
    """Reject any bounded field that would not fit its column.

    Call this *after* canonicalisation — canonicalising can shorten a
    value, and it is the stored form whose length matters.
    """
    for name, value in fields.items():
        if value is None:
            continue
        limit = FIELD_MAX_LENGTHS[name]
        if len(value) > limit:
            raise SnapshotFieldTooLong(name, value, limit)


# --- Dialect-agnostic row conversion (#1963 Task 4) ------------------------
#
# SQLite has no native temporal types and stores ISO-8601 text; MySQL uses
# native DATE / DATETIME(6) and its driver hands back real ``date`` /
# (naive) ``datetime`` objects. Both shapes funnel through the coercers
# below so every backend returns the *same* Python types (design spec
# §3, 12.3 #8) without either one re-implementing the rule.


def _as_session_date(value: Any) -> date:
    """Coerce a stored ``as_of_session`` to a plain ``date``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _as_created_at(value: Any) -> datetime:
    """Coerce a stored ``created_at`` to a tz-aware **UTC** ``datetime``.

    MySQL ``DATETIME`` carries no offset, so the driver returns a naive
    value; every backend writes UTC, so a naive read is stamped UTC here
    rather than being handed to callers as an ambiguous wall clock.
    """
    moment = (
        value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    )
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _as_payload(value: Any) -> dict:
    """Coerce a stored payload column to a ``dict``."""
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8")
    return json.loads(value)


def _row_from_mapping(record: Any) -> SnapshotRow:
    """Parse a raw ``pi_snapshot`` record into a typed ``SnapshotRow``.

    ``record`` is anything with name-based ``__getitem__`` — a
    ``sqlite3.Row`` or a PyMySQL ``DictCursor`` mapping.
    """
    return SnapshotRow(
        dataset=record["dataset"],
        entity_key=record["entity_key"],
        as_of_session=_as_session_date(record["as_of_session"]),
        created_at=_as_created_at(record["created_at"]),
        job_run_id=record["job_run_id"],
        status=SnapshotStatus(record["status"]),
        state=SnapshotState(record["state"]),
        payload=_as_payload(record["payload_json"]),
        input_hash=record["input_hash"],
        row_count=record["row_count"],
        validated=bool(record["validated"]),
        validation_reason=record["validation_reason"] or "",
        engine_version=record["engine_version"],
        payload_schema_version=record["payload_schema_version"],
    )


def _dumps_payload(payload: dict) -> str:
    """Serialize a payload deterministically for storage."""
    return json.dumps(payload, sort_keys=True, default=str)


# --- Dialect-agnostic lifecycle policy (#1963 Task 4) ----------------------
#
# The *decisions* — may this row be validated? may it be promoted? which
# sessions survive retention? — are dialect-free and live here so the
# SQLite and MySQL backends can only ever disagree about SQL text, never
# about policy.


def _validation_refusal(row: SnapshotRow | None) -> str | None:
    """Return why ``row`` may not be validated, or ``None`` if it may be.

    A LIVE or SUPERSEDED row is immutable history: rewriting its
    ``validated``/``validation_reason`` would silently forge an audit
    trail, so validation is STAGING-only.
    """
    if row is None:
        return "staged snapshot not found"
    if row.state != SnapshotState.STAGING:
        return "row is not in STAGING state"
    return None


def _promotion_refusal(
    candidate: SnapshotRow | None, live: SnapshotRow | None
) -> str | None:
    """Return why ``candidate`` may not be promoted, or ``None`` if it may.

    Three gates, in order: the candidate must have passed validation; it
    must still be in STAGING (so a stale staged-tuple cannot resurrect a
    SUPERSEDED row back to LIVE); and it must rank at least as high as
    the incumbent LIVE row (keep-last-good, spec §4.1/§5#2).
    """
    if candidate is None or not candidate.validated:
        return "candidate is not validated"
    if candidate.state != SnapshotState.STAGING:
        return "candidate is not in STAGING state"
    if live is not None and _STATUS_RANK[candidate.status] < _STATUS_RANK[live.status]:
        return "candidate status is worse than LIVE"
    return None


# --- Optimistic-concurrency vocabulary shared by both backends -------------
#
# Every lifecycle write is a *read, decide, write* sequence, and the row
# can move in between (another worker promotes it, a replay supersedes
# it). Both backends therefore re-assert what they read in the WHERE
# clause of every write and treat "0 rows affected" as a refusal, using
# these identical reasons so the two logs are diff-able.

_VALIDATION_RACE_REASON = (
    "row changed state between read and write; verdict not persisted"
)
_LIVE_RACE_REASON = "LIVE row changed between read and write"
_CANDIDATE_RACE_REASON = "candidate row changed between read and write"
_LIVE_COLLISION_REASON = "another writer already installed a LIVE row for this key"


class _LifecycleRefused(Exception):
    """Internal signal: unwind a lifecycle write's transaction cleanly.

    Raised so the enclosing transaction context manager performs its
    ``ROLLBACK`` — returning from inside the ``with`` block would
    *commit* whatever the refusal was meant to undo.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _PromotionRefused(_LifecycleRefused):
    """``promote()`` lost a race or failed a gate; unwind without an error."""


class _ValidationRefused(_LifecycleRefused):
    """``validate()`` found the row had moved; unwind without an error."""


def _is_integrity_error(exc: BaseException) -> bool:
    """Report whether ``exc`` is a DB-API ``IntegrityError`` from any driver.

    PEP 249 mandates the class *name* but no shared base class, and
    importing ``pymysql`` here would drag a MySQL dependency into the
    SQLite backend. Matching the name across the MRO keeps the check
    dialect-agnostic (and also recognizes the test doubles' subclasses).
    """
    return any(base.__name__.endswith("IntegrityError") for base in type(exc).__mro__)


def _kept_sessions(sessions: list, keep_sessions: int) -> list | None:
    """Return the newest ``keep_sessions`` values, or ``None`` if none drop.

    ``sessions`` must already be sorted newest-first. ``None`` means the
    key has nothing outside the window, so the backend can skip its
    DELETE entirely.
    """
    if len(sessions) <= keep_sessions:
        return None
    return sessions[:keep_sessions]


def _should_skip(
    store: SnapshotStore, dataset: str, entity_key: str, input_hash: str
) -> bool:
    """Shared ``should_skip`` body — LIVE already carries this input hash."""
    live = store.get_live(dataset, entity_key)
    return live is not None and live.input_hash == input_hash


def _restamp_live(
    store: SnapshotStore,
    dataset: str,
    entity_key: str,
    as_of_session: date,
    job_run_id: str,
) -> bool:
    """Shared ``restamp_live`` body — auditable, never an in-place edit.

    Stages a *new* row carrying the current LIVE row's payload and
    provenance under the new session/run IDs, then drives it through the
    same stage -> validate -> promote path. The prior LIVE row is never
    mutated: ``promote()`` flips it to SUPERSEDED and it stays in history
    exactly like any other supersession.
    """
    live = store.get_live(dataset, entity_key)
    if live is None:
        logger.warning("snapshot restamp refused: no LIVE row to restamp")
        return False
    store.stage(
        dataset,
        entity_key,
        as_of_session,
        job_run_id,
        live.payload,
        status=live.status,
        input_hash=live.input_hash,
        row_count=live.row_count,
        engine_version=live.engine_version,
        payload_schema_version=live.payload_schema_version,
    )
    result = store.validate(dataset, entity_key, as_of_session, job_run_id)
    if not result.ok:
        logger.warning("snapshot restamp refused: validation failed: %s", result.reason)
        return False
    return store.promote(dataset, entity_key, as_of_session, job_run_id)


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


class SqliteSnapshotStore:
    """SQLite-backed EOD snapshot store implementing the ``SnapshotStore`` Protocol.

    Task 2 scope: ``stage``/``validate``/``promote``/``get_live``/
    ``get_as_of``/``list_history``/``close``. Task 3 adds ``should_skip``/
    ``restamp_live``/``prune`` on the same class.

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
    def _tx(self, *, immediate: bool = False) -> Iterator[None]:
        """Transaction scope — all-or-nothing for multi-statement writes.

        ``immediate=True`` opens with ``BEGIN IMMEDIATE``, taking SQLite's
        database-wide write lock *before* the first read. That is this
        dialect's stand-in for MySQL's ``SELECT ... FOR UPDATE``: SQLite
        has no row locks, so serializing the whole read-decide-write
        sequence is the only way to stop another connection committing
        inside it.
        """
        try:
            self._conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
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
        return _row_from_mapping(record) if record is not None else None

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
        _check_field_lengths(
            dataset=dataset,
            entity_key=entity_key,
            job_run_id=job_run_id,
            input_hash=input_hash,
            engine_version=engine_version,
            payload_schema_version=payload_schema_version,
        )
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
                    _dumps_payload(payload),
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
        """Run the gate on the staged row; persist validated flag + reason.

        Refuses (without mutating anything) if the row's state is not
        STAGING — a LIVE or SUPERSEDED row is immutable history and must
        never have its ``validated``/``validation_reason`` rewritten.

        The state check is re-asserted inside the write transaction: the
        gate runs between the read and the write, so a concurrent
        ``promote()`` can move the row in that window. The transaction
        opens with ``BEGIN IMMEDIATE`` (this dialect's stand-in for
        ``SELECT ... FOR UPDATE``), re-reads the row, and refuses if it
        is no longer STAGING; the UPDATE additionally pins ``state`` in
        its WHERE clause.

        The refusal is deliberately *not* inferred from ``rowcount``.
        sqlite3 counts rows *matched*, but the MySQL backend's PyMySQL
        driver counts rows *changed* — so a re-validate that writes the
        same verdict reports 0 there and 1 here. Deciding the race by
        re-reading instead keeps the two backends' answers identical.
        """
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        row = self._get_row(dataset, entity_key, as_of_session, job_run_id)
        refusal = _validation_refusal(row)
        if row is None or refusal is not None:
            if row is not None:
                logger.warning("snapshot validation refused: %s", refusal)
            return ValidationResult(
                ok=False, reason=refusal or "staged snapshot not found"
            )
        gate = validator or default_validator
        result = gate(row)
        try:
            with self._tx(immediate=True):
                current = self._get_row(dataset, entity_key, as_of_session, job_run_id)
                # The pre-gate read already established STAGING, so
                # anything else here means the row moved in the window.
                if _validation_refusal(current) is not None:
                    raise _ValidationRefused(_VALIDATION_RACE_REASON)
                self._conn.execute(
                    "UPDATE pi_snapshot SET validated = ?, validation_reason = ? "
                    "WHERE dataset = ? AND entity_key = ? AND as_of_session = ? "
                    "AND job_run_id = ? AND state = ?",
                    (
                        1 if result.ok else 0,
                        result.reason,
                        dataset,
                        entity_key,
                        as_of_session.isoformat(),
                        job_run_id,
                        SnapshotState.STAGING.value,
                    ),
                )
        except _ValidationRefused as refused:
            logger.warning("snapshot validation refused: %s", refused.reason)
            return ValidationResult(ok=False, reason=refused.reason)
        return result

    def promote(
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
    ) -> bool:
        """Atomically promote a validated staged row to LIVE.

        Refuses if not validated; refuses if the candidate's row state is
        not STAGING (prevents resurrecting an already-LIVE or SUPERSEDED
        row back to LIVE); refuses if the staged rank is lower than the
        current LIVE rank (keep-last-good); else flips the prior LIVE row
        to superseded and this row to LIVE. Returns ``True`` on success,
        ``False`` on any refusal (logs a WARNING).

        Concurrency: the whole read-decide-write sequence runs under
        ``BEGIN IMMEDIATE`` (SQLite's only lock granularity), and both
        writes additionally pin the exact rows that were read — the
        demotion by the incumbent's primary key, the promotion by the
        candidate's — with a ``state`` predicate. A row that moved in the
        window yields zero affected rows and a refusal instead of a
        silent clobber, and a unique-index collision from a writer that
        bypassed this method is reported as ``False`` rather than raised.
        """
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        try:
            with self._tx(immediate=True):
                candidate = self._get_row(
                    dataset, entity_key, as_of_session, job_run_id
                )
                live = self.get_live(dataset, entity_key)
                refusal = _promotion_refusal(candidate, live)
                if refusal is not None:
                    raise _PromotionRefused(refusal)
                if live is not None:
                    self._demote(dataset, entity_key, live)
                promoted = self._conn.execute(
                    "UPDATE pi_snapshot SET state = ? "
                    "WHERE dataset = ? AND entity_key = ? AND as_of_session = ? "
                    "AND job_run_id = ? AND state = ?",
                    (
                        SnapshotState.LIVE.value,
                        dataset,
                        entity_key,
                        as_of_session.isoformat(),
                        job_run_id,
                        SnapshotState.STAGING.value,
                    ),
                ).rowcount
                if promoted != 1:
                    raise _PromotionRefused(_CANDIDATE_RACE_REASON)
        except _PromotionRefused as refused:
            logger.warning("snapshot promotion refused: %s", refused.reason)
            return False
        except Exception as exc:  # noqa: BLE001
            if not _is_integrity_error(exc):
                raise
            logger.warning("snapshot promotion refused: %s", _LIVE_COLLISION_REASON)
            return False
        return True

    def _demote(self, dataset: str, entity_key: str, live: SnapshotRow) -> None:
        """Supersede the exact incumbent row that was read, or refuse."""
        demoted = self._conn.execute(
            "UPDATE pi_snapshot SET state = ? "
            "WHERE dataset = ? AND entity_key = ? AND as_of_session = ? "
            "AND job_run_id = ? AND state = ?",
            (
                SnapshotState.SUPERSEDED.value,
                dataset,
                entity_key,
                live.as_of_session.isoformat(),
                live.job_run_id,
                SnapshotState.LIVE.value,
            ),
        ).rowcount
        if demoted != 1:
            raise _PromotionRefused(_LIVE_RACE_REASON)

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
        return _row_from_mapping(record) if record is not None else None

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
        return _row_from_mapping(record) if record is not None else None

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
        return [_row_from_mapping(record) for record in records]

    def should_skip(self, dataset: str, entity_key: str, input_hash: str) -> bool:
        """Report whether the LIVE row already carries this ``input_hash``.

        A skip must not strand the staleness badge — callers should follow
        a skip with ``restamp_live`` on a new session (design spec §4.5).
        """
        return _should_skip(self, dataset, entity_key, input_hash)

    def restamp_live(
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
    ) -> bool:
        """Advance the LIVE pointer's ``as_of_session`` without recomputing.

        Inserts a *new* row carrying the current LIVE row's payload and
        provenance under the new session/run IDs, then runs it through the
        same stage -> validate -> promote atomic path. The prior LIVE row
        is never mutated in place — ``promote()`` flips it to SUPERSEDED
        and it remains in history for audit, exactly like any other
        supersession.
        """
        return _restamp_live(self, dataset, entity_key, as_of_session, job_run_id)

    def prune(self, policy: RetentionPolicy | None = None) -> int:
        """Apply retention; return the number of rows removed.

        The default policy (``None``, or an explicit ``RetentionPolicy()``
        with ``keep_sessions=None``) keeps everything and returns ``0``. A
        bounded policy deletes only non-LIVE rows outside the newest
        ``keep_sessions`` distinct ``as_of_session`` values, per
        (dataset, entity_key) key. LIVE rows are never pruned — the
        ``state != 'live'`` filter below is an unconditional safety net,
        independent of whether a LIVE row's session lands inside the kept
        window.
        """
        if policy is None or policy.keep_sessions is None:
            return 0
        keep_sessions = policy.keep_sessions
        deleted = 0
        with self._tx():
            keys = self._conn.execute(
                "SELECT DISTINCT dataset, entity_key FROM pi_snapshot"
            ).fetchall()
            for key in keys:
                dataset_key, entity_key_key = key["dataset"], key["entity_key"]
                sessions = [
                    record["as_of_session"]
                    for record in self._conn.execute(
                        "SELECT DISTINCT as_of_session FROM pi_snapshot "
                        "WHERE dataset = ? AND entity_key = ? "
                        "ORDER BY as_of_session DESC",
                        (dataset_key, entity_key_key),
                    ).fetchall()
                ]
                keep = _kept_sessions(sessions, keep_sessions)
                if keep is None:
                    continue
                # `condition` is built only from a fixed literal ("1 = 1") or
                # a placeholders string of "?" — no external input reaches
                # the SQL text itself, all values are bound via `params`.
                if keep:
                    placeholders = ", ".join("?" for _ in keep)
                    condition = f"as_of_session NOT IN ({placeholders})"
                    params = (
                        dataset_key,
                        entity_key_key,
                        SnapshotState.LIVE.value,
                        *keep,
                    )
                else:
                    condition = "1 = 1"
                    params = (dataset_key, entity_key_key, SnapshotState.LIVE.value)
                cursor = self._conn.execute(
                    "DELETE FROM pi_snapshot WHERE dataset = ? AND entity_key = ? "  # noqa: S608
                    f"AND state != ? AND {condition}",
                    params,
                )
                deleted += cursor.rowcount
        return deleted

    def close(self) -> None:
        """Release the SQLite connection."""
        self._conn.close()


# ---------------------------------------------------------------------------
# Factory — env-var driven backend selection (#1963 Task 5)
# ---------------------------------------------------------------------------
#
# Mirrors the existing `execution.paper_engine.get_default_engine` /
# `execution.order_sink.get_default_sink` seam: an env var picks the
# backend, MySQL is the default, and a MySQL-unreachable server degrades
# to SQLite with a WARNING rather than failing the caller outright. An
# unrecognized `PI_SNAPSHOT_ENGINE` value raises `ValueError` loudly
# (mirrors `get_default_sink`'s stricter convention) rather than being
# silently treated as "sqlite".

_ENV_SNAPSHOT_ENGINE = "PI_SNAPSHOT_ENGINE"
_ENV_SNAPSHOT_DB = "PI_SNAPSHOT_DB"


def _make_mysql_store() -> SnapshotStore:
    """Import indirection for constructing a ``MysqlSnapshotStore``.

    ``mysql_store`` imports the shared policy helpers from *this* module,
    so importing it back at this module's top level would be circular.
    The import is deferred to call time instead, once both modules have
    finished loading, and kept as a standalone module-level function
    (rather than inlined into :func:`get_default_snapshot_store`) so
    tests can monkeypatch ``store_module._make_mysql_store`` directly to
    simulate a MySQL-unreachable server without a real connection pool.
    """
    # pylint: disable=import-outside-toplevel,cyclic-import
    from openbb_techtrade.snapshot.mysql_store import (  # noqa: PLC0415
        _make_mysql_store as _build_mysql_store,
    )

    return _build_mysql_store()


def get_default_snapshot_store(db_path: Path | str | None = None) -> SnapshotStore:
    """Return the configured EOD snapshot store.

    Backend selection (#1963 Task 5):

    - ``PI_SNAPSHOT_ENGINE=mysql`` (default) — return a
      :class:`~openbb_techtrade.snapshot.mysql_store.MysqlSnapshotStore`
      against the shared ``fmp_cached`` connection pool. If construction
      fails (missing dependency, unreachable pool, ...) a WARNING is
      logged and the selector falls through to SQLite — mirrors the
      ``get_default_engine`` graceful-fallback pattern from #1790/#1744.
      Only the MySQL construction is guarded this way; a failure
      constructing the SQLite fallback itself is never swallowed.
    - ``PI_SNAPSHOT_ENGINE=sqlite`` — force the file-backed
      :class:`SqliteSnapshotStore` at ``db_path`` (arg),
      ``$PI_SNAPSHOT_DB`` (env), or the per-user default
      ``~/.portfolio_intel/snapshot.db``.
    - Anything else — loud :class:`ValueError`. No silent fallback to
      SQLite for a typo'd or unsupported value (mirrors
      ``execution.order_sink.get_default_sink``'s stricter convention
      rather than treating "not mysql" as "must be sqlite").

    ``db_path`` takes precedence over ``$PI_SNAPSHOT_DB`` on both the
    explicit-sqlite path and the mysql-unreachable fallback path. The
    resolved SQLite path is computed once, up front, so both the
    MySQL-unreachable WARNING and the eventual ``SqliteSnapshotStore``
    construction agree on the same path — the WARNING never claims a
    different location than the one actually opened.
    """
    backend = os.environ.get(_ENV_SNAPSHOT_ENGINE, "mysql").strip().lower()

    if backend not in ("mysql", "sqlite"):
        raise ValueError(
            f"{_ENV_SNAPSHOT_ENGINE} must be one of 'mysql' | 'sqlite'; "
            f"got {backend!r}"
        )

    resolved = (
        Path(db_path)
        if db_path is not None
        else (
            Path(os.environ[_ENV_SNAPSHOT_DB])
            if os.environ.get(_ENV_SNAPSHOT_DB)
            else Path.home() / ".portfolio_intel" / "snapshot.db"
        )
    )

    if backend == "mysql":
        try:
            return _make_mysql_store()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "get_default_snapshot_store: MySQL backend unreachable (%s); "
                "falling back to SQLite at %s",
                exc,
                resolved,
            )
            # fall through to sqlite

    return SqliteSnapshotStore(resolved)
