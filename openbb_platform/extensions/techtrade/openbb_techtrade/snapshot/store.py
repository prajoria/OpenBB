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
  differently-cased keys (``Information Technology`` vs.
  ``information_technology``, ``Sector=Technology`` vs.
  ``sector=technology``) would produce split-brain LIVE rows. Case is
  folded on **both** sides of a ``field=label`` pair, so a field name
  spelled two ways cannot split one logical key in two.
- **``as_of_session`` vs. ``created_at``.** The former is the trading day
  the payload is *about* (a ``date``); the latter is the wall-clock UTC
  instant of the write (a tz-aware ``datetime``). The two concepts must
  never collapse into a single timestamp.
- **Namespaced table.** The table is ``pi_eod_snapshot``. ``pi_snapshot``
  is already taken by ``portfolio_snapshot_importer``'s account-scoped
  positions history in the same MySQL database — see the C1 note above
  ``_SNAPSHOT_TABLE``.
- **Schema identity is verified, not assumed.** Both backends refuse a
  table of the right name and the wrong shape with
  :class:`SnapshotSchemaMismatch`, because ``CREATE TABLE IF NOT
  EXISTS`` cannot tell the two apart — and both also refuse a table
  stamped by a *different* schema version, in either direction, which
  the shape check structurally cannot detect (a newer schema is a
  column superset of this build's). SQLite stamps ``PRAGMA
  user_version``; MySQL stamps the table's own ``COMMENT``.
- **The single-LIVE guard is verified, not assumed.** The DB object that
  enforces "at most one LIVE row per ``(dataset, entity_key)``" differs
  by dialect — SQLite uses a *partial* unique index, MySQL (which has
  none) uses a generated nullable ``live_key`` column plus a plain
  ``UNIQUE KEY`` — so each backend checks its own, at construction. A
  pre-existing table can pass the column-shape *and* version checks
  while carrying no such guard at all (``CREATE TABLE IF NOT EXISTS``
  no-ops, and with it every index declared inside it), which would let
  concurrent promotions install two LIVE rows for one key. See
  :func:`_check_mysql_live_guard` / :func:`_check_sqlite_live_guard`.
- **The comparison semantics of the key columns are verified, not
  assumed.** On MySQL the guard above only means what it says while the
  columns it keys on compare *byte for byte*. An existing table whose
  ``dataset``/``entity_key``/``job_run_id``/``live_key`` resolved to the
  charset's case- and accent-insensitive default collation enforces a
  different — weaker — invariant than SQLite's BINARY default, so the
  reported collation is read back from ``information_schema.COLUMNS``
  and refused when it is not ``utf8mb4_bin``. See
  :func:`_check_mysql_collations`.
- **Stored timestamps are fixed-width.** SQLite has no temporal type, so
  ``created_at`` is text and every "newest row" decision is a *lexical*
  ``ORDER BY``. :func:`_iso_utc` is the single renderer, and it always
  emits UTC at microsecond precision so text order is time order by
  construction rather than by accident.

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
import re
import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
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
    """Retention hook (design spec §3.3). ``None`` = keep-all, the v1 default.

    ``keep_sessions`` is validated on construction. A negative value is
    not a smaller window — it is a Python slice bound, so
    ``sessions[:-1]`` would silently mean "delete only the *oldest*
    session", the near-inverse of what the caller asked for. ``0`` is
    legal and means "keep no session outside LIVE" (LIVE rows are never
    pruned regardless).
    """

    keep_sessions: int | None = None

    def __post_init__(self) -> None:
        """Reject a negative window before it can be read as a slice bound."""
        if self.keep_sessions is not None and self.keep_sessions < 0:
            raise ValueError(
                "RetentionPolicy.keep_sessions must be None (keep-all) or "
                f">= 0; got {self.keep_sessions!r}"
            )


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
    design spec §4.2 (review item #4). Rules: treat underscores as word
    separators; collapse all surrounding and internal whitespace; casefold
    the **whole** value, both halves of a ``field=Label`` pair included;
    then trim the whitespace that sat either side of the ``=``.
    Deterministic and idempotent:
    ``canonical_key(canonical_key(x)) == canonical_key(x)``.

    The field-name half is casefolded too (PR #2062 review): an earlier
    revision kept it verbatim, so ``Sector=Technology`` and
    ``sector=technology`` canonicalized to *different* keys. That is the
    exact split-brain this function exists to prevent — two writers
    disagreeing only about the case of a field name would each install
    their own LIVE row, and a reader spelling the field the third way
    would find neither. Casing carries no meaning in a key here, so it is
    removed everywhere rather than in one half.

    Casefolding before the ``=`` split is safe and deliberate: Unicode
    full case folding never produces ``=`` (nor whitespace) from a
    character that was not already one, so the split sees exactly the
    same boundary either way — and folding once, up front, is what makes
    the two halves provably symmetric.

    Migration: none is needed. ``pi_eod_snapshot`` is a new, unused
    foundation (#1963) with no writers in any shipped code path, so no
    persisted row carries a pre-fix key; the schema *shape* is unchanged,
    so :data:`SNAPSHOT_SCHEMA_VERSION` is deliberately **not** bumped —
    a bump would refuse existing empty development databases while
    protecting no real data. A stray development row written with a
    mixed-case field name simply stops resolving (a miss, never a
    corruption): re-stage it, or delete the development database.
    """
    value = " ".join(raw.replace("_", " ").casefold().split())
    if "=" not in value:
        return value
    field_name, label = value.split("=", 1)
    return f"{field_name.strip()}={label.strip()}"


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
        """Write a run to STAGING; NEVER touches the LIVE view.

        ``payload`` must be a JSON object (``dict``); every backend
        raises :class:`SnapshotPayloadNotAnObject` and writes nothing if
        it is not (#2062 review).
        """
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

    def prune(
        self,
        policy: RetentionPolicy | None = None,
        *,
        dataset: str | None = None,
        entity_key: str | None = None,
    ) -> int:
        """Apply retention; return the number of rows removed.

        The default policy (``None``) keeps everything and returns ``0``.

        ``dataset``/``entity_key`` scope the sweep (#1963 review I4). The
        store is *shared*, so an unscoped call applies one caller's
        window to every other dataset's history; passing ``dataset``
        keeps a job's retention policy inside its own data. ``entity_key``
        may only be given together with ``dataset`` — the same
        ``entity_key`` string is reused across datasets, so scoping by it
        alone would silently reach into a neighbour's history.
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
# The values mirror ``_PI_EOD_SNAPSHOT_DDL`` exactly (a test asserts the two
# cannot drift apart). ``entity_key`` stops at 191 because 191 * 4 bytes
# of utf8mb4 is the widest value InnoDB can put under the historical
# 767-byte index prefix limit.
#
# The target server, stated explicitly because the two limits are easy to
# confuse (#1963 review I5): **InnoDB with the DYNAMIC row format** (the
# default since MySQL 5.7.9), whose index-key limit is 3072 bytes. The 767
# figure is the rationale for *this one column's width* — the cheapest
# point at which it also stays portable to COMPACT/REDUNDANT — not a claim
# about the whole schema. The other two keys are sized against 3072:
# ``live_key VARCHAR(512)`` is 2048 bytes and the four-column primary key
# is 1791 (512 + 764 + 3 + 512). Both exceed 767 by design.

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


def _check_limit(limit: int) -> None:
    """Reject a non-positive ``list_history`` limit on both backends.

    The dialects disagree about what a non-positive ``LIMIT`` means:
    SQLite reads ``LIMIT -1`` as *unlimited*, MySQL rejects it as a
    syntax error, and ``LIMIT 0`` returns nothing on both. Left
    unvalidated, the same call is a full history dump on one backend and
    a driver traceback on the other, which breaks the module's binding
    parity claim. One shared guard, before either dialect is reached.
    """
    if limit <= 0:
        raise ValueError(f"list_history limit must be >= 1; got {limit!r}")


# --- Table identity + schema versioning (#1963 review C1/I1) --------------
#
# The table is namespaced ``pi_eod_snapshot`` rather than ``pi_snapshot``
# because ``portfolio_snapshot_importer`` (#1744) already ships a
# *different* ``pi_snapshot`` — account-scoped positions history, with a
# ``snapshot_id`` primary key and a ``pi_position`` FK — into the very
# same MySQL database through the very same ``get_connection_pool()``.
# ``CREATE TABLE IF NOT EXISTS`` would have silently no-op'd against it,
# leaving a store that constructs cleanly and then fails every operation
# with "Unknown column 'dataset'", and colliding this compute-free shared
# cache with the PII-bearing table design spec §8 / #1965 says it must
# never share.
#
# The rename removes the collision; the shape + version check below is
# what makes any *future* collision loud instead of silent, including the
# one #1964/#1967 will create when they add columns.

_SNAPSHOT_TABLE = "pi_eod_snapshot"

SNAPSHOT_SCHEMA_VERSION = 1

_EXPECTED_COLUMNS = frozenset(
    {
        "dataset",
        "entity_key",
        "as_of_session",
        "created_at",
        "job_run_id",
        "status",
        "state",
        "validated",
        "validation_reason",
        "payload_json",
        "input_hash",
        "row_count",
        "engine_version",
        "payload_schema_version",
    }
)

# The single-LIVE guard, by dialect.
#
# SQLite enforces "at most one LIVE row per (dataset, entity_key)" with a
# *partial* unique index — `... ON (dataset, entity_key) WHERE state =
# 'live'`. MySQL has no partial indexes, so it carries an extra generated
# column, `live_key`, that is the two key parts concatenated when the row
# is LIVE and NULL otherwise, plus a plain `UNIQUE KEY` over it (MySQL
# unique indexes ignore NULLs, so unlimited STAGING/SUPERSEDED history
# still coexists).
#
# `live_key` therefore belongs to *MySQL only*: it is deliberately absent
# from `_EXPECTED_COLUMNS`, which is the dialect-independent shape both
# backends share. Requiring it on SQLite would refuse every correct
# SQLite database this store has ever written.
_LIVE_UNIQUE_INDEX = "ux_pi_eod_snapshot_live"
_MYSQL_LIVE_KEY_COLUMN = "live_key"
_SQLITE_LIVE_INDEX_COLUMNS = ("dataset", "entity_key")

# --- Comparison semantics of the key columns (PR #2062 review) ------------
#
# The guards above prove that the *objects* which enforce the invariants
# exist. They cannot prove that those objects mean the same thing on both
# backends, because on MySQL an index means whatever its columns'
# collation says it means. SQLite compares TEXT byte for byte (BINARY);
# MySQL resolves an unpinned column to the charset's *default* collation
# — `utf8mb4_0900_ai_ci` on 8.x, `utf8mb4_general_ci` on 5.7 — both case-
# **and** accent-insensitive. `_PI_EOD_SNAPSHOT_DDL` therefore pins
# `utf8mb4_bin` on every column below, but `CREATE TABLE IF NOT EXISTS`
# no-ops against a pre-existing table, so the DDL's pin says nothing
# about the table that is actually there. Only the server does.
#
# Two divergences follow from a `_ci`/`_ai` column, neither visible to the
# shape, guard or version checks:
#
# 1. `ux_pi_eod_snapshot_live` over an `_ai_ci` `live_key` folds two
#    genuinely distinct canonical keys into one index entry —
#    `sector=cafe` and `sector=café` (`canonical_key` casefolds but does
#    not normalize Unicode, so both survive canonicalization intact).
#    Once one is LIVE the other can never be promoted, and the refusal is
#    logged as the routine "another writer already installed a LIVE row",
#    misattributing the cause forever.
# 2. `job_run_id` is never canonicalized at all, so under `_ci` the
#    primary key treats `Run-1` and `run-1` as one row: SQLite inserts
#    two, MySQL raises a duplicate-key `IntegrityError`. A call one
#    backend accepts is a call the other refuses.
#
# `input_hash` (`should_skip` equality), `status`/`state` (every WHERE
# clause and the `live_key` generation expression itself) and
# `engine_version`/`payload_schema_version` (provenance an operator
# filters and groups on) are held to the same rule for parity: SQLite
# compares all of them byte for byte, so MySQL must too, and a table
# built by this DDL already reports `utf8mb4_bin` for each.
#
# `validation_reason` and `payload_json` are deliberately *not* checked:
# free text and a JSON document, never compared, never indexed, never
# part of a key — their collation cannot change any decision this store
# makes, and refusing an operator who redeclared one of them would be
# pedantry.
_MYSQL_BINARY_COLLATION = "utf8mb4_bin"

_MYSQL_BINARY_COLLATED_COLUMNS = (
    "dataset",
    "entity_key",
    "job_run_id",
    "status",
    "state",
    "input_hash",
    "engine_version",
    "payload_schema_version",
    _MYSQL_LIVE_KEY_COLUMN,
)

# --- Structural comparison of the guard expressions (PR #2062 review) -----
#
# Both dialect guards used to ask only whether the server-reported text
# *mentioned* a few tokens (`state`, `live`, ...). That is satisfied by
# expressions which mean the opposite of the invariant: `state != 'live'`
# contains both `state` and `live`, and `IF(state = 'live', NULL,
# CONCAT(dataset, CHAR(31), entity_key))` contains all four — the first
# keys `live_key` on every *non*-LIVE row, the second on every non-LIVE
# row as well, and either one turns the UNIQUE index into a constraint on
# the rows nobody promotes while leaving LIVE rows unconstrained. A
# substring check cannot tell those apart from the real guard, so the
# comparison is now *structural*: the reported expression is reduced to a
# canonical token string and compared for equality against the canonical
# form of the expression this module's DDL ships.
#
# Exact text comparison is impossible — no server hands back what was
# typed. MySQL 8.4.9 rewrites
#
#     IF(state = 'live', CONCAT(dataset, CHAR(31 USING utf8mb4), entity_key), NULL)
#
# as ``if((`state` = _utf8mb4\'live\'),concat(`dataset`,char(31),
# `entity_key`),NULL)`` — 8.0 keeps the ``using utf8mb4`` inside
# ``char()``, 5.7 and MariaDB drop the introducer, and the escaping of
# the literal's delimiters is described below. The exact rewrite differs
# by server version. :func:`_canonical_sql` therefore folds away
# precisely the things a server is free to change and nothing else:
# letter case of keywords and identifiers, identifier quoting
# (`` `x` ``, ``"x"``, ``[x]``), whitespace, comments, charset
# introducers (``_utf8mb4'live'`` -> ``'live'``), ``USING <charset>``
# inside ``CHAR()``, redundant grouping parentheses, and the spelling of
# a literal's escapes. Operators, argument order, literal text and
# literal case all survive — which is what makes `!=`, `<>`, a swapped
# THEN/ELSE, a dropped `entity_key` or a `'staging'` literal a mismatch.
_LIVE_KEY_CANONICAL = "if(state='live',concat(dataset,char(31),entity_key),null)"

# `a = b` and `b = a` are the same predicate, and a server is free to
# report either; nothing else is tolerated.
_LIVE_KEY_CANONICAL_FORMS = frozenset(
    {
        _LIVE_KEY_CANONICAL,
        "if('live'=state,concat(dataset,char(31),entity_key),null)",
    }
)

# SQLite's partial-index predicate, under the same discipline. SQLite
# stores the `WHERE` clause as written, so `state='live'`, `state = 'live'`
# and `"state" = 'live'` are one index reported three ways — while
# `state != 'live'` is a different index entirely, and used to pass.
_SQLITE_LIVE_PREDICATE = "state='live'"
_SQLITE_LIVE_PREDICATE_FORMS = frozenset({_SQLITE_LIVE_PREDICATE, "'live'=state"})

# --- MySQL's two layers of literal escaping (PR #2062 review) -------------
#
# MySQL does not report a generated column's expression the way it prints
# it: `information_schema` hands back the *printed* expression with a
# further layer of backslash escaping applied on top, so the text is safe
# to paste inside a quoted string. On 8.4.9 the expression
# `_PI_EOD_SNAPSHOT_DDL` ships comes back as
#
#     if((`state` = _utf8mb4\'live\'),concat(`dataset`,char(31),`entity_key`),NULL)
#
# with the literal's own *delimiters* wearing backslashes. A token scan
# that knows only about `''` doubling therefore reads the literal as
# `'live\'` and canonicalizes the whole expression to
# `if(state='live\',...)`, which matches no accepted form — so the guard
# refused every real server it was ever pointed at (#1963 live smoke).
#
# Two escaping layers are stacked, and both have to be peeled before the
# scan can see a literal at all. Confirmed against 8.4.9 with a throwaway
# probe table: a column generated from `IF(s = 'li''ve', ...)` is
# reported as ``if((`s` = _utf8mb4\'li\\\'ve\'),...)`` and one generated
# from `IF(s = 'a\\b', ...)` as ``if((`s` = _utf8mb4\'a\\\\b\'),...)``.
# One plain unescape pass over the whole text yields the printed
# expression, whose literals then carry MySQL's own backslash escaping —
# which the token scan handles directly.
#
# Neither layer exists on SQLite. `sqlite_master.sql` stores the text as
# typed, and SQLite has no backslash escapes at all, so `'li\ve'` there
# is the five-character value `li\ve`. Peeling escapes off a SQLite
# predicate would *weaken* its guard: `state = 'li\ve'` would decode onto
# `state = 'live'` and be accepted while indexing rows nothing ever
# writes. Both layers are consequently MySQL-only, selected by the
# caller, and nothing about the SQLite scan changed.
_SQL_BACKSLASH_ESCAPE_RE = re.compile(r"\\(?s:.)")

# One escaped unit inside a MySQL string literal: a doubled quote or a
# backslash sequence.
_SQL_LITERAL_ESCAPE_RE = re.compile(r"''|\\(?s:.)")

# MySQL's backslash sequences that stand for some *other* character. Any
# other `\x` stands for `x` itself, except `\%` and `\_`, which keep the
# backslash — it is only special to `LIKE`.
_MYSQL_ESCAPE_SEQUENCES = {
    "0": "\0",
    "b": "\b",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "Z": "\x1a",
}

# One SQL token. Ordered alternation matters: the string-literal and
# comment branches come first so a `--` or a quote *inside* a literal is
# consumed with it rather than restarting the scan mid-token. The literal
# branch is the one piece that differs by dialect, so it is substituted
# in rather than written twice.
_SQL_SCAN_PATTERN = r"""
      {literal}                      # 'live'
    | --[^\n]*                       # -- line comment
    | (?s:/\*.*?\*/)                 # /* block comment */
    | `(?:[^`]|``)*`                 # `state`   MySQL-quoted identifier
    | "(?:[^"]|"")*"                 # "state"   ANSI-quoted identifier
    | \[[^\]]*\]                     # [state]   bracket-quoted identifier
    | [A-Za-z_$][A-Za-z_$0-9]*       # bare word: identifier, keyword, _utf8mb4
    | \d+(?:\.\d+)?                  # 31
    | <=>|<>|!=|>=|<=|\|\|           # multi-character operators
    | [-+*/%(),.=<>!&|^~]            # single-character operators
    """

# Doubled `''` only — a backslash is an ordinary character, which is what
# SQLite means by it.
_SQL_TOKEN_RE = re.compile(
    _SQL_SCAN_PATTERN.format(literal=r"'(?:[^']|'')*'"), re.VERBOSE
)

# Doubled `''` *and* `\x`, so `'li\'ve'` is one literal rather than a
# literal, a bare word, and a literal that runs off the end.
_SQL_TOKEN_ESCAPED_RE = re.compile(
    _SQL_SCAN_PATTERN.format(literal=r"'(?:[^'\\]|''|\\(?s:.))*'"), re.VERBOSE
)

_SQL_WORD_RE = re.compile(r"[A-Za-z_$][A-Za-z_$0-9]*")

# A charset introducer: `_utf8mb4'live'`. Only ever dropped when it sits
# immediately before a string literal, so a column actually named `_x` is
# untouched.
_SQL_INTRODUCER_RE = re.compile(r"_[a-z0-9]+")

# `IIF` is the same three-argument conditional as `IF` (SQLite and SQL  # codespell:ignore
# Server spell it that way, and this repo's SQLite-backed MySQL double
# emits it). Folding the spelling costs nothing semantically; every other
# function name is compared as reported.
_SQL_CONDITIONAL_SYNONYMS = {"iif": "if"}  # codespell:ignore


def _unquote_identifier(token: str) -> str:
    """Strip one layer of identifier quoting, undoubling any inner quote."""
    if token.startswith("`"):
        return token[1:-1].replace("``", "`")
    if token.startswith('"'):
        return token[1:-1].replace('""', '"')
    return token[1:-1]


def _decode_escape(sequence: str) -> str:
    r"""Resolve one ``''`` or ``\x`` sequence to the character it stands for."""
    if sequence == "''":
        return "'"
    escaped = sequence[1]
    if escaped in ("%", "_"):
        # `\%` and `\_` keep their backslash: it is meaningful only to
        # `LIKE`, and MySQL leaves it in place everywhere else.
        return sequence
    return _MYSQL_ESCAPE_SEQUENCES.get(escaped, escaped)


def _decode_backslash_escapes(text: str) -> str:
    """Undo ``information_schema``'s escaping of a whole expression.

    The inverse of the pass MySQL applies to a generated column's printed
    expression before reporting it (see the block comment above
    :data:`_SQL_BACKSLASH_ESCAPE_RE`). A text with no backslashes — every
    expression this repo's DDL produces, on every server that does not
    add the layer, and every SQLite predicate — is returned unchanged, so
    applying it can only ever *add* the servers that do escape.
    """
    return _SQL_BACKSLASH_ESCAPE_RE.sub(lambda m: _decode_escape(m.group(0)), text)


def _canonical_literal(token: str, *, backslash_escapes: bool) -> str:
    r"""Re-emit a string literal from its value under one escaping scheme.

    Two spellings of one literal (``'li''ve'`` and, on MySQL, ``'li\'ve'``)
    become one canonical token, and two *different* literals stay
    different: the value is decoded, then re-emitted with only ``''``
    doubling. Literal case is preserved, which is what keeps ``'live'``
    and ``'staging'`` — or ``'live'`` and ``'LIVE'`` — apart.
    """
    body = token[1:-1]
    if backslash_escapes:
        value = _SQL_LITERAL_ESCAPE_RE.sub(lambda m: _decode_escape(m.group(0)), body)
    else:
        value = body.replace("''", "'")
    return "'" + value.replace("'", "''") + "'"


def _canonical_sql(expression: str | None, *, backslash_escapes: bool = False) -> str:
    r"""Reduce a server-reported SQL expression to a comparable canonical form.

    Folds exactly the variation a server may introduce without changing
    meaning (see the block comment above :data:`_LIVE_KEY_CANONICAL`) and
    preserves everything that carries meaning. An unparseable or empty
    expression canonicalizes to ``""``, which matches no accepted form —
    an ordinary (non-generated) column reports ``""`` and must be refused.

    Grouping parentheses are dropped, call parentheses are kept: a ``(``
    is a call only when the token before it is a bare word (a function
    name). That is what folds MySQL's ``if((state = 'live'), ...)`` onto
    the shipped ``IF(state = 'live', ...)`` without also folding
    ``if(not(state = 'live'), ...)`` onto it — ``not`` survives as a
    token either way.

    ``backslash_escapes`` selects the dialect's *literal* syntax and
    nothing else. MySQL reads ``\'`` inside a literal as a quote; SQLite
    reads it as a backslash followed by the literal's closing quote, so
    the flag must stay off for a SQLite predicate or ``state = 'li\ve'``
    would be read as ``state = 'live'`` and accepted (PR #2062 review).
    """
    token_re = _SQL_TOKEN_ESCAPED_RE if backslash_escapes else _SQL_TOKEN_RE
    tokens: list[str] = []
    call_paren: list[bool] = []
    skip_charset = False
    for raw in token_re.findall(expression or ""):
        if raw.startswith("--") or raw.startswith("/*"):
            continue
        if skip_charset:
            skip_charset = False
            if _SQL_WORD_RE.fullmatch(raw):
                continue
        if raw.startswith("'"):
            if tokens and _SQL_INTRODUCER_RE.fullmatch(tokens[-1]):
                tokens.pop()
            tokens.append(_canonical_literal(raw, backslash_escapes=backslash_escapes))
        elif raw[0] in '`"[':
            tokens.append(_unquote_identifier(raw).casefold())
        elif raw == "(":
            is_call = bool(tokens) and _SQL_WORD_RE.fullmatch(tokens[-1]) is not None
            call_paren.append(is_call)
            if is_call:
                tokens.append(raw)
        elif raw == ")":
            if call_paren and call_paren.pop():
                tokens.append(raw)
        else:
            word = raw.casefold()
            if word == "using":
                # `CHAR(31 USING utf8mb4)` -> `char(31)`: the charset name
                # is the next word, and is dropped with it.
                skip_charset = True
                continue
            tokens.append(_SQL_CONDITIONAL_SYNONYMS.get(word, word))
    return "".join(tokens)


def _canonical_generation_expression(expression: str | None) -> str:
    """Canonicalize a ``GENERATION_EXPRESSION`` as MySQL reports it.

    Peels ``information_schema``'s escaping of the whole text, then scans
    the printed expression under MySQL's literal syntax — the two layers
    described above :data:`_SQL_BACKSLASH_ESCAPE_RE`. Both are no-ops on
    text a server reported without escaping (MySQL 5.7, MariaDB, and this
    suite's SQLite-backed double all do), so one code path serves every
    server.
    """
    return _canonical_sql(
        _decode_backslash_escapes(expression or ""), backslash_escapes=True
    )


# Slices a partial index's predicate out of its `CREATE INDEX` statement.
# `\bWHERE\b` cannot match inside an identifier (`somewhere`), and SQLite
# forbids subqueries in an index predicate, so at most one `WHERE` appears.
_INDEX_WHERE_RE = re.compile(r"\bWHERE\b(.*)$", re.IGNORECASE | re.DOTALL)


def _quote_identifier(name: str) -> str:
    """Double-quote an identifier for interpolation into a ``PRAGMA``.

    ``PRAGMA`` arguments cannot be bound as parameters, so a catalogue-
    derived index name has to be interpolated — and an index name is
    free-form: ``CREATE INDEX "ux live"`` and ``CREATE INDEX "a""b"`` are
    both legal. Interpolated bare, either one is a syntax error from
    ``PRAGMA index_info``, which surfaces as a raw ``OperationalError``
    from the constructor *before* the schema guard can say anything
    useful (PR #2062 review). Quoting the name is what keeps the failure
    inside the guard.
    """
    return '"' + name.replace('"', '""') + '"'


@dataclass(frozen=True)
class _IndexShape:
    """One index as the server's own catalogue describes it.

    Built from ``information_schema.STATISTICS`` on MySQL and from
    ``PRAGMA index_list`` / ``PRAGMA index_info`` on SQLite, so the check
    describes the index that *exists* rather than the one this build's
    DDL would have created. ``predicate`` is SQLite's partial-index
    ``WHERE`` text and is always empty on MySQL, which has no such thing.
    """

    name: str
    unique: bool
    columns: tuple[str, ...]
    predicate: str = ""


class SnapshotSchemaMismatch(RuntimeError):
    """An existing ``pi_eod_snapshot`` table is not the one this code expects.

    Raised at construction, before any lifecycle call, so an
    incompatible or foreign table fails loudly at the seam instead of
    surfacing later as an "Unknown column" from deep inside ``stage()``.
    """


def _check_schema_shape(columns: Iterable[str], *, backend: str) -> None:
    """Fail loudly when the existing table is missing expected columns.

    Only the *dialect-independent* columns are checked here. MySQL's
    extra ``live_key`` guard column is checked by
    :func:`_check_mysql_live_guard`, which is called by the MySQL backend
    alone — SQLite has no such column and must never be asked for one.
    """
    missing = sorted(_EXPECTED_COLUMNS - set(columns))
    if missing:
        raise SnapshotSchemaMismatch(
            f"{backend}: table {_SNAPSHOT_TABLE!r} exists but is missing "
            f"{missing} — it belongs to another component or to an "
            f"incompatible schema version. Refusing to use it. Expected "
            f"schema version {SNAPSHOT_SCHEMA_VERSION}."
        )


def _live_guard_refusal(backend: str, detail: str) -> SnapshotSchemaMismatch:
    """Build the refusal both dialect guards raise, with a shared preamble."""
    return SnapshotSchemaMismatch(
        f"{backend}: table {_SNAPSHOT_TABLE!r} does not enforce the "
        f"single-LIVE-row invariant — {detail}. Two concurrent promotions "
        f"could install two LIVE rows for one (dataset, entity_key) and "
        f"every reader would then resolve an arbitrary one. Refusing to "
        f"use it."
    )


def _check_mysql_live_guard(
    generation: dict[str, str], indexes: Iterable[_IndexShape]
) -> None:
    """Verify MySQL's half of the single-LIVE invariant (PR #2062 review).

    ``generation`` maps every existing column to its
    ``information_schema.COLUMNS.GENERATION_EXPRESSION`` (``""`` for an
    ordinary column). Three distinct failures are all silent without this
    check, and none of them is visible to :func:`_check_schema_shape` or
    :func:`_check_schema_version`:

    1. **No ``live_key`` at all.** ``CREATE TABLE IF NOT EXISTS`` no-ops
       against a pre-existing table, so a table carrying only the 14
       shared columns passes the shape check and gets stamped — while
       nothing whatsoever constrains how many rows may be LIVE.
    2. **A ``live_key`` that is an ordinary column.** Worse than absent:
       the unique index may well exist, but the column is NULL for every
       row (nobody writes it — it is never in an ``INSERT`` column list)
       and MySQL unique indexes ignore NULLs, so the index accepts
       unlimited LIVE rows while *looking* like the guard.
    3. **A unique index that is missing, non-unique, or over the wrong
       columns.** A plain ``INDEX (live_key)`` enforces nothing; a
       ``UNIQUE`` over ``(dataset, entity_key)`` would (wrongly) forbid a
       second *staged* run for the same key.

    The generation expression is matched *structurally* — canonicalized
    by :func:`_canonical_generation_expression` and compared for equality
    against :data:`_LIVE_KEY_CANONICAL_FORMS` — rather than scanned for
    tokens. A token scan accepts expressions that invert the invariant
    while mentioning every expected word: ``IF(state != 'live',
    CONCAT(dataset, CHAR(31), entity_key), NULL)`` keys ``live_key`` on
    every row that is *not* LIVE, so the UNIQUE index then permits
    unlimited LIVE rows and forbids a second staged one — the exact
    opposite of the invariant, passing a check meant to prove it
    (PR #2062 review).

    The index is matched on its *shape*, not its name: an operator who
    rebuilt an equivalent unique index under a different name has not
    broken the invariant, and refusing them would be pedantry. The
    canonical name is named in the message so the fix is obvious.
    """
    if _MYSQL_LIVE_KEY_COLUMN not in generation:
        raise _live_guard_refusal(
            "mysql",
            f"the generated column {_MYSQL_LIVE_KEY_COLUMN!r} is missing",
        )
    expression = generation[_MYSQL_LIVE_KEY_COLUMN]
    canonical = _canonical_generation_expression(expression)
    if canonical not in _LIVE_KEY_CANONICAL_FORMS:
        raise _live_guard_refusal(
            "mysql",
            f"column {_MYSQL_LIVE_KEY_COLUMN!r} is not generated from the "
            f"expected expression (its GENERATION_EXPRESSION {expression!r} "
            f"canonicalizes to {canonical!r}, not to {_LIVE_KEY_CANONICAL!r}); "
            f"an ordinary column is NULL on every row so a unique index over "
            f"it constrains nothing, and an expression that merely resembles "
            f"the expected one — an inverted comparison, a swapped "
            f"THEN/ELSE, a missing identity half — inverts or weakens the "
            f"guard while still mentioning every expected word",
        )
    if not any(
        index.unique and index.columns == (_MYSQL_LIVE_KEY_COLUMN,) for index in indexes
    ):
        raise _live_guard_refusal(
            "mysql",
            f"no UNIQUE index over exactly ({_MYSQL_LIVE_KEY_COLUMN}) exists "
            f"(expected {_LIVE_UNIQUE_INDEX!r})",
        )


def _check_mysql_collations(collations: Mapping[str, str | None]) -> None:
    """Verify MySQL compares the key columns byte for byte (PR #2062 review).

    ``collations`` maps every existing column to its
    ``information_schema.COLUMNS.COLLATION_NAME`` — ``NULL`` for a
    non-character column. Every name in
    :data:`_MYSQL_BINARY_COLLATED_COLUMNS` must report
    :data:`_MYSQL_BINARY_COLLATION`; anything else is refused, including
    ``NULL``.

    ``NULL`` is refused rather than ignored because it is not the benign
    case it looks like. A character column always reports a collation, so
    ``NULL`` here means the column is no longer a character column at
    all — someone redeclared ``entity_key`` as ``VARBINARY``/``BLOB``,
    or ``job_run_id`` as an integer. That table's comparison semantics
    are *undefined* with respect to this store's parity claim (a binary
    string column would compare byte for byte but silently change what
    the driver hands back; a numeric one would coerce), and it passes the
    shape check because ``information_schema`` still lists the column.

    An exact name match is required, not a ``_bin`` suffix test, for the
    same reason :func:`_check_mysql_live_guard` compares the generation
    expression exactly: "equivalent collation" is not a property this
    check can decide in general. ``utf8mb4_0900_bin`` orders by code
    point and would very likely behave, but it is not what the DDL asks
    for, and failing closed on a table nobody in this repo creates costs
    an operator one ``ALTER TABLE`` — which the refusal spells out.

    Every offending column is reported at once. An operator repairing a
    restored table should see the whole list, not discover the next one
    on the next construction.
    """
    wrong = [
        (column, collations.get(column))
        for column in _MYSQL_BINARY_COLLATED_COLUMNS
        if (collations.get(column) or "").casefold() != _MYSQL_BINARY_COLLATION
    ]
    if not wrong:
        return
    # `NULL` rather than `None`: the operator reading this is looking at
    # `information_schema`, where that is what the column reports.
    detail = ", ".join(
        f"{column} -> {'NULL' if reported is None else repr(reported)}"
        for column, reported in wrong
    )
    repairs = " ".join(
        f"ALTER TABLE {_SNAPSHOT_TABLE} MODIFY {column} ... "
        f"COLLATE {_MYSQL_BINARY_COLLATION};"
        for column, _ in wrong
    )
    raise SnapshotSchemaMismatch(
        f"mysql: table {_SNAPSHOT_TABLE!r} does not compare its key columns "
        f"byte for byte — {detail} (expected {_MYSQL_BINARY_COLLATION!r} on "
        f"every one of {list(_MYSQL_BINARY_COLLATED_COLUMNS)}). MySQL "
        f"resolves an unpinned column to the charset default, which is case- "
        f"AND accent-insensitive, so 'sector=cafe' and 'sector=café' "
        f"collide on {_LIVE_UNIQUE_INDEX!r} (the second key becomes "
        f"permanently unpromotable, reported as a routine LIVE-row race) and "
        f"'Run-1' and 'run-1' collide on the primary key (a stage() SQLite "
        f"accepts raises a duplicate-key error here). A NULL collation means "
        f"the column is no longer a character column at all. Refusing to use "
        f"it. Repair with: {repairs}"
    )


def _index_predicate(sql: str | None) -> str:
    """Slice the ``WHERE`` tail out of a ``CREATE INDEX`` statement.

    ``sqlite_master.sql`` is the only place a partial index's predicate
    survives, but the statement also contains the index's *name* — and
    the single-LIVE guard is named ``ux_pi_eod_snapshot_live``. Checking
    the whole statement for the token ``live`` would therefore succeed
    for any index wearing that name, including one predicated on the
    wrong state: the check would be satisfied by the very name it was
    trying to look past. Returning only the predicate is what makes the
    caller's token check discriminating.

    ``None`` (the implicit index behind a ``PRIMARY KEY``) and a
    non-partial index both yield ``""``. Slicing at the first ``WHERE``
    is unambiguous: SQLite forbids subqueries in an index predicate, so
    at most one appears.
    """
    if not sql:
        return ""
    match = _INDEX_WHERE_RE.search(sql)
    return match.group(1).strip() if match else ""


def _check_sqlite_live_guard(indexes: Iterable[_IndexShape]) -> None:
    """Verify SQLite's half of the same invariant: the *partial* unique index.

    SQLite needs no ``live_key`` — it indexes ``(dataset, entity_key)``
    directly under a ``WHERE state = 'live'`` predicate — so this check
    must never look for that column. It exists because ``CREATE UNIQUE
    INDEX IF NOT EXISTS`` is keyed on the index *name*: a pre-existing
    index that merely wears the name :data:`_LIVE_UNIQUE_INDEX` (an
    ordinary non-unique index, or a unique one without the partial
    predicate) silently no-ops the ``CREATE`` and leaves the invariant
    unenforced, exactly as MySQL's ``CREATE TABLE IF NOT EXISTS`` does.

    The predicate is required, not optional: a *total* unique index over
    ``(dataset, entity_key)`` would forbid a second staged run for one
    key, which is the store's normal daily operation.

    The predicate is matched *structurally* — canonicalized by
    :func:`_canonical_sql` and compared for equality against
    :data:`_SQLITE_LIVE_PREDICATE_FORMS` — rather than scanned for the
    tokens ``state`` and ``live``. A token scan accepts ``WHERE state !=
    'live'``, which mentions both and indexes exactly the rows that are
    *not* LIVE: unlimited LIVE rows for one key, and a second staged run
    rejected. Requiring an explicit equality is what tells the guard
    apart from its inverse (PR #2062 review).
    """
    for index in indexes:
        if (
            index.unique
            and index.columns == _SQLITE_LIVE_INDEX_COLUMNS
            and _canonical_sql(index.predicate) in _SQLITE_LIVE_PREDICATE_FORMS
        ):
            return
    raise _live_guard_refusal(
        "sqlite",
        f"no partial UNIQUE index over {_SQLITE_LIVE_INDEX_COLUMNS} whose "
        f"predicate is exactly \"state = 'live'\" exists (expected "
        f"{_LIVE_UNIQUE_INDEX!r}); a predicate that merely mentions "
        f"'state' and 'live' — \"state != 'live'\" above all — indexes the "
        f"complement of the rows the invariant is about",
    )


def _check_schema_version(version: int, *, backend: str) -> None:
    """Fail loudly on a table stamped by a different schema version.

    ``0`` means *unstamped* on both backends (SQLite's default
    ``PRAGMA user_version``; a MySQL table with no version marker in its
    ``COMMENT``) and is accepted so a table this build created before
    stamping existed can be adopted and stamped. Every other value that
    is not this build's own is refused in **both** directions: a table
    stamped by a newer build (this build is old) and a table stamped by
    an older build (this build is new) are equally unusable, and neither
    is detectable by a column-shape check — a newer schema is a superset
    of the columns this build expects, and an older one that merely
    *renamed* or re-typed a column is not.
    """
    if version not in (0, SNAPSHOT_SCHEMA_VERSION):
        raise SnapshotSchemaMismatch(
            f"{backend}: table {_SNAPSHOT_TABLE!r} is stamped schema "
            f"version {version}, but this build speaks version "
            f"{SNAPSHOT_SCHEMA_VERSION}. Refusing to read or write it."
        )


# MySQL has no `PRAGMA user_version`, so the stamp lives in the table's own
# `COMMENT` — read back from `information_schema.TABLES.TABLE_COMMENT`.
#
# Why the comment rather than a companion `pi_eod_snapshot_schema` table:
# the comment is a property *of the table*, so it cannot drift from it.
# A companion table can be dropped, restored, or replicated separately
# from the table it describes, and the failure mode of that drift is a
# fresh empty `pi_eod_snapshot` wearing a stale version row — precisely
# the silent mismatch this check exists to prevent. It also adds a second
# object to a database this store is only a guest in (the corporate FMP
# cache), which is what C1 was about in the first place.
#
# The marker is *searched for*, not compared for equality: some servers
# decorate `TABLE_COMMENT` with their own text (older InnoDB builds
# prefix `InnoDB free: ...`), and an operator may have annotated the
# table by hand. A comment with no marker at all reads as version 0 —
# "unstamped" — which is the same thing SQLite's default `user_version`
# means, so both backends adopt-and-stamp in exactly one case.
_SCHEMA_VERSION_MARKER = f"{_SNAPSHOT_TABLE} schema_version="
_SCHEMA_VERSION_RE = re.compile(rf"{re.escape(_SCHEMA_VERSION_MARKER)}(\d+)")


def _schema_version_comment() -> str:
    """Build the stamp this build writes into the table's ``COMMENT``.

    Built at call time, not import time, so the version is read from
    :data:`SNAPSHOT_SCHEMA_VERSION` rather than baked into a module
    constant — which is what lets a test stand in for "a build that
    speaks a different version" by rebinding one name.
    """
    return (
        f"{_SCHEMA_VERSION_MARKER}{SNAPSHOT_SCHEMA_VERSION} "
        "openbb_techtrade EOD snapshot store (#1963)"
    )


def _parse_schema_version_comment(comment: str | None) -> int:
    """Read the stamped schema version out of a MySQL ``TABLE_COMMENT``.

    Returns ``0`` when the comment is absent, empty, or carries no
    marker — the "unstamped" value :func:`_check_schema_version` accepts.
    """
    match = _SCHEMA_VERSION_RE.search(comment or "")
    return int(match.group(1)) if match is not None else 0


def _prune_scope(dataset: str | None, entity_key: str | None) -> tuple[str | None, ...]:
    """Canonicalize + validate a ``prune()`` scope (#1963 review I4).

    ``entity_key`` alone is refused: the same entity label ("AAPL",
    "sector=technology") is reused across datasets, so an unqualified
    entity scope would silently sweep a neighbouring dataset's history.
    """
    if entity_key is not None and dataset is None:
        raise ValueError(
            "prune(entity_key=...) requires dataset=...; an entity_key is "
            "only unique within a dataset"
        )
    return (
        canonical_key(dataset) if dataset is not None else None,
        canonical_key(entity_key) if entity_key is not None else None,
    )


def _scope_clause(
    dataset: str | None, entity_key: str | None, placeholder: str
) -> tuple[str, tuple]:
    """Build the optional ``WHERE`` fragment for a scoped ``prune()``.

    Returns SQL text assembled only from module-owned literals and the
    dialect's own placeholder token; the scope values themselves are
    returned separately, to be bound.
    """
    if dataset is None:
        return "", ()
    if entity_key is None:
        return f" WHERE dataset = {placeholder}", (dataset,)
    return (
        f" WHERE dataset = {placeholder} AND entity_key = {placeholder}",
        (dataset, entity_key),
    )


# --- Dialect-agnostic row conversion (#1963 Task 4) ------------------------
#
# SQLite has no native temporal types and stores ISO-8601 text; MySQL uses
# native DATE / DATETIME(6) and its driver hands back real ``date`` /
# (naive) ``datetime`` objects. Both shapes funnel through the coercers
# below so every backend returns the *same* Python types (design spec
# §3, 12.3 #8) without either one re-implementing the rule.


class SnapshotPayloadNotAnObject(ValueError):
    """A snapshot payload is not a JSON object, despite ``dict`` typing.

    ``SnapshotRow.payload`` is typed ``dict`` (design spec §3.1) and every
    consumer — the validator, the Terminal reader, callers merging or
    indexing the payload — relies on that being real. ``dict`` is only a
    type *hint*: a caller that stages a list/scalar/``None`` would
    otherwise serialize to valid-but-wrong JSON, and a persisted row that
    decodes to anything other than an object (a list, a scalar, ``null``,
    or JSON that fails to parse at all — a hand-edited or corrupted row)
    would otherwise be handed straight to a caller expecting ``.get``/
    membership semantics (PR #2062 review). Raised at both boundaries this
    module owns: before a non-dict payload is ever written
    (:func:`_dumps_payload`) and when a persisted ``payload_json`` fails to
    decode back to one (:func:`_as_payload`) — on both backends, since both
    funnel through these same two shared functions.
    """

    def __init__(self, *, context: str, value: Any) -> None:
        self.context = context
        self.value_type = type(value).__name__
        preview = repr(value)
        if len(preview) > _PREVIEW_CHARS:
            preview = preview[:_PREVIEW_CHARS] + "..."
        super().__init__(
            f"{context}: payload must be a JSON object (dict); got "
            f"{self.value_type} ({preview})"
        )


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
    """Coerce a stored payload column to a ``dict``.

    Read-boundary half of the #2062 review guard: a persisted
    ``payload_json`` that decodes to a list, a scalar, or ``null`` — or
    that is not valid JSON at all, e.g. a hand-edited or corrupted row —
    would otherwise be handed to :class:`SnapshotRow` (and every caller
    that trusts its ``payload: dict`` typing) as-is. Raising
    :class:`SnapshotPayloadNotAnObject` here, at the one read seam both
    backends share, turns that into a loud, attributable failure instead
    of a confusing ``AttributeError``/``TypeError`` deep inside a caller.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8")
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SnapshotPayloadNotAnObject(
            context="persisted payload_json", value=value
        ) from exc
    if not isinstance(decoded, dict):
        raise SnapshotPayloadNotAnObject(
            context="persisted payload_json", value=decoded
        )
    return decoded


def _row_from_mapping(record: Any) -> SnapshotRow:
    """Parse a raw ``pi_eod_snapshot`` record into a typed ``SnapshotRow``.

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
    """Serialize a payload deterministically for storage.

    Write-boundary half of the #2062 review guard: ``payload: dict`` is
    only a type hint, and a caller that ignores it — staging a list,
    scalar, or ``None`` — would otherwise serialize to valid-but-wrong
    JSON that violates ``SnapshotRow.payload``'s contract for every
    future reader. Checked here, at the one write seam both backends
    share and *before* either ``execute()``/``cur.execute()`` is called,
    so the refusal raises before any statement reaches the database and
    no row is written.
    """
    if not isinstance(payload, dict):
        raise SnapshotPayloadNotAnObject(context="stage() payload", value=payload)
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

    Four gates, in order: the candidate row must exist; it must have
    passed validation; it must still be in STAGING (so a stale
    staged-tuple cannot resurrect a SUPERSEDED row back to LIVE); and it
    must rank at least as high as the incumbent LIVE row (keep-last-good,
    spec §4.1/§5#2). The missing-row and not-validated cases are reported
    with distinct reasons so a caller (and the logs) can tell "there is
    no such staged snapshot" apart from "it exists but failed/hasn't
    passed validation".
    """
    if candidate is None:
        return "candidate snapshot not found"
    if not candidate.validated:
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
_RESTAMP_RACE_REASON = (
    "LIVE row was replaced by a real recompute while the restamp copy was "
    "in flight; refusing to supersede newer content with an older payload"
)


class _RestampCapable(Protocol):
    """Internal seam :func:`_restamp_live` needs beyond the public Protocol.

    ``restamp_live`` cannot go through the public ``promote()``: it has
    to pin the promotion to the exact LIVE row its payload was copied
    from (#1963 review I2), and that expectation is a *backend*
    obligation — only the backend can re-read LIVE inside the promoting
    transaction. Keeping it on this private Protocol rather than
    widening :class:`SnapshotStore` preserves the public contract's
    signature parity: callers and the Terminal reader still see exactly
    the ten spec'd methods.
    """

    def get_live(self, dataset: str, entity_key: str) -> SnapshotRow | None:
        """Compute-free single-row read of ``state='live'``."""
        ...  # pylint: disable=unnecessary-ellipsis

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
        """Write a run to STAGING."""
        ...  # pylint: disable=unnecessary-ellipsis

    def validate(  # pylint: disable=too-many-positional-arguments
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
        validator: Callable[[SnapshotRow], ValidationResult] | None = None,
    ) -> ValidationResult:
        """Run the gate on the staged row."""
        ...  # pylint: disable=unnecessary-ellipsis

    def _promote_expecting_live(  # pylint: disable=too-many-positional-arguments
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
        *,
        expected_live: SnapshotRow | None,
    ) -> bool:
        """Promote only while LIVE is still ``expected_live``."""
        ...  # pylint: disable=unnecessary-ellipsis


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


def _doomed_triples(rows: Iterable[Any], keep_sessions: int) -> list[tuple]:
    """Compute the ``(dataset, entity_key, as_of_session)`` set to delete.

    ``rows`` is the *single* ``SELECT DISTINCT dataset, entity_key,
    as_of_session ... ORDER BY dataset, entity_key, as_of_session DESC``
    both backends issue — one round trip for the whole sweep instead of
    a SELECT-then-DELETE pair per key (#1963 review I4). Deciding which
    sessions survive stays here, in shared Python, so the two backends
    can only disagree about SQL text.

    LIVE rows are excluded by the DELETE's own ``state != 'live'``
    predicate, not here: a LIVE row whose session falls outside the kept
    window must survive, and its session must still count as one of the
    key's distinct sessions.
    """
    grouped: dict[tuple, list] = {}
    for record in rows:
        key = (record["dataset"], record["entity_key"])
        grouped.setdefault(key, []).append(record["as_of_session"])
    doomed: list[tuple] = []
    for (dataset, entity_key), sessions in grouped.items():
        keep = _kept_sessions(sessions, keep_sessions)
        if keep is None:
            continue
        kept = set(keep)
        doomed.extend(
            (dataset, entity_key, session)
            for session in sessions
            if session not in kept
        )
    return doomed


# A DELETE binds three parameters per doomed session, so a batch of 500
# is 1500 placeholders — comfortably inside SQLite's default 32k limit
# and MySQL's max_allowed_packet, while keeping the write lock on a table
# shared with the FMP cache held for a bounded number of statements
# rather than one per key.
_PRUNE_BATCH = 500


def _batched(items: Sequence, size: int = _PRUNE_BATCH) -> Iterator[Sequence]:
    """Yield ``items`` in bounded chunks (no ``itertools.batched`` on 3.10)."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _should_skip(
    store: SnapshotStore, dataset: str, entity_key: str, input_hash: str
) -> bool:
    """Shared ``should_skip`` body — LIVE already carries this input hash."""
    live = store.get_live(dataset, entity_key)
    return live is not None and live.input_hash == input_hash


def _restamp_live(
    store: _RestampCapable,
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

    **The copy is pinned to the row it was taken from (#1963 review
    I2).** ``get_live`` here, ``stage``/``validate``/``promote`` each in
    their own transaction (on MySQL, several separate pooled borrows) —
    a genuine recompute can promote inside that window. Promoting the
    copy afterwards would supersede the *newer* payload with the *older*
    one under a *newer* session date: LIVE goes backwards in content
    while going forwards in freshness, and the keep-last-good rank guard
    cannot see it because the copy inherits the old row's status. The
    final promote therefore re-reads LIVE inside its own transaction and
    refuses unless it is still the exact row that was copied.
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
    return store._promote_expecting_live(  # pylint: disable=protected-access
        dataset, entity_key, as_of_session, job_run_id, expected_live=live
    )


def _live_identity(row: SnapshotRow | None) -> tuple | None:
    """Primary-key identity of a LIVE row, for cross-transaction comparison."""
    if row is None:
        return None
    return (row.dataset, row.entity_key, row.as_of_session, row.job_run_id)


def _restamp_race_refusal(
    expected: SnapshotRow | None, current: SnapshotRow | None
) -> str | None:
    """Return why a restamp may not promote, or ``None`` if it may.

    Called with the LIVE row the payload was copied from and the LIVE row
    read back inside the promoting transaction. Anything but the same
    row means a real recompute landed in the window and the copy is now
    stale.
    """
    if _live_identity(expected) != _live_identity(current):
        return _RESTAMP_RACE_REASON
    return None


# --- SQLite backend (#1963 Task 2) -----------------------------------------
#
# Schema per design spec §3.1. SQLite has no native DATE/DATETIME type, so
# ``as_of_session``/``created_at`` are stored as ISO-8601 text (a SQLite
# workaround, not a cross-dialect mandate — MySQL uses native DATE/DATETIME,
# see Task 4). The partial unique index is the DB-level half of the
# "exactly one LIVE row per key" invariant; ``promote()``'s validated+rank
# guard is the application-level half (spec §3.1 "LIVE resolution").
_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS pi_eod_snapshot (
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
CREATE INDEX IF NOT EXISTS ix_pi_eod_snapshot_live
    ON pi_eod_snapshot(dataset, entity_key, state);
CREATE INDEX IF NOT EXISTS ix_pi_eod_snapshot_latest
    ON pi_eod_snapshot(dataset, entity_key, as_of_session DESC, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pi_eod_snapshot_live
    ON pi_eod_snapshot(dataset, entity_key) WHERE state = 'live';
"""


def _iso_utc(moment: datetime) -> str:
    """Render an instant as **fixed-width** UTC ISO-8601 text.

    The single renderer for every ``created_at`` this backend persists,
    because on SQLite that column is ``TEXT`` and every "which row is
    newest" decision — :meth:`SqliteSnapshotStore.get_as_of`'s
    ``ORDER BY created_at DESC LIMIT 1``, :meth:`list_history`'s
    ``ORDER BY as_of_session DESC, created_at DESC``, and the
    ``ix_pi_eod_snapshot_latest`` index behind both — is a *lexical*
    comparison of that text. Lexical order equals temporal order only
    while every value has the same shape, and two properties of a bare
    ``datetime.isoformat()`` break that (PR #2062 review):

    * **Variable width.** ``isoformat()`` omits the fractional part
      entirely when ``microsecond == 0``, so two writes inside one second
      are stored as ``...T12:00:00+00:00`` and
      ``...T12:00:00.000001+00:00`` — 25 characters and 32. Those two
      happen to still compare correctly, but only because ``'+'`` sorts
      below ``'.'`` in ASCII: an accident of the offset spelling, not a
      property anyone declared. Rendering the offset as ``Z``, or
      widening the fraction, silently inverts the pair.
    * **Variable offset.** ``isoformat()`` keeps whatever offset the
      instant carries, and ``'2026-09-04T17:30:00+05:30'`` sorts *after*
      the later-in-time ``'2026-09-04T12:00:01+00:00'``.

    ``timespec="microseconds"`` fixes the width at 32 characters and
    ``astimezone(timezone.utc)`` fixes the offset at ``+00:00``, so the
    text sort is the time sort by construction. It also matches the
    MySQL backend's ``DATETIME(6)``, which has fixed microsecond
    precision and no offset at all.

    Compatibility: ``pi_eod_snapshot`` is unshipped foundation (#1963),
    so no deployed database holds pre-fix values. A development database
    that does needs no rewrite either — a legacy 25-character value still
    sorts correctly beside the new 32-character ones, for the ASCII
    accident above — and :func:`_as_created_at` parses both, since
    ``datetime.fromisoformat`` accepts either width. The schema *shape*
    is unchanged, so :data:`SNAPSHOT_SCHEMA_VERSION` is deliberately not
    bumped; a bump would refuse those development databases while
    protecting no real data.
    """
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _now_iso() -> str:
    """Wall-clock UTC instant of the write, ISO-8601 (spec §3, 12.3 #8)."""
    return _iso_utc(datetime.now(timezone.utc))


# Design spec §4.6 makes this binding: the SQLite backend "serializes all
# writes behind a module-level ``RLock`` inside a ``_tx()``
# BEGIN/COMMIT/ROLLBACK context manager". It is module-level rather than
# per-instance on purpose — two `SqliteSnapshotStore` objects opened on
# the same file inside one process (the selector hands out a new store
# per call; the tests do it deliberately) would otherwise serialize
# against nothing. It is an `RLock`, not a `Lock`, because the shared
# `_restamp_live` composition and the validator-gate seam re-enter the
# store from inside a scope the same thread already holds.
#
# Why a lock at all, when sqlite3 is "thread-safe": the module serializes
# individual C-API calls, but a transaction is *connection*-scoped. Two
# threads sharing one `check_same_thread=False` connection share one
# transaction, so thread B's `BEGIN IMMEDIATE` raises "cannot start a
# transaction within a transaction" and B's rollback then aborts A's
# in-flight transaction — splitting promote()'s demote/promote pair into
# separately committed statements, which is exactly the partial LIVE
# write safeguard #1 exists to prevent.
_SQLITE_LOCK = threading.RLock()

# 30s: long enough to ride out another *process*'s write transaction on
# the same file (this store's own writes are short), short enough that a
# genuinely wedged writer surfaces as an error instead of an infinite
# hang. Only reachable across processes — in-process contention is
# already serialized by `_SQLITE_LOCK`.
_SQLITE_BUSY_TIMEOUT_MS = 30_000


class SqliteSnapshotStore:
    """SQLite-backed EOD snapshot store implementing the ``SnapshotStore`` Protocol.

    Task 2 scope: ``stage``/``validate``/``promote``/``get_live``/
    ``get_as_of``/``list_history``/``close``. Task 3 adds ``should_skip``/
    ``restamp_live``/``prune`` on the same class.

    Threading: the connection is opened ``check_same_thread=False`` with
    ``isolation_level=None`` (autocommit), and **every** statement —
    write scopes via :meth:`_tx` and the bare reads alike — is issued
    under the module-level :data:`_SQLITE_LOCK`. That lock is the whole
    of the all-or-nothing guarantee on this backend: sqlite3
    transactions are connection-scoped, so without it a second thread
    entering :meth:`_tx` both fails to start its own transaction *and*
    rolls back the first thread's. Rows come back as ``sqlite3.Row`` for
    name-based column access.

    Concurrency across *processes*: the file is opened in WAL mode with
    a busy timeout, so a reader (the Terminal) never has to see
    ``database is locked`` because a writer (the EOD job) holds
    ``BEGIN IMMEDIATE``. WAL is attempted, not assumed — some network
    filesystems refuse it — and a refusal degrades to the rollback
    journal with a WARNING rather than failing construction.

    Read path is compute-free: every read method here only ever issues a
    ``SELECT`` against ``pi_eod_snapshot`` — none of them calls a provider or
    a compute/scan function.
    """

    def __init__(self, db_path: Path | str) -> None:
        # ``expanduser()`` must run before ``resolve()``: ``resolve()``
        # alone treats a leading ``~`` as an ordinary path segment, so a
        # direct caller passing e.g. ``SqliteSnapshotStore("~/x.db")`` —
        # bypassing :func:`get_default_snapshot_store`, which normalizes
        # its own ``resolved`` path before ever reaching here — would
        # otherwise get a literal ``~`` directory created under the
        # current working directory instead of the caller's real home
        # directory. Re-applying the normalization here (it is a no-op
        # for already-normalized callers) makes the constructor safe on
        # its own, not merely safe when reached through the factory.
        self._db_path = Path(db_path).expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        try:
            with _SQLITE_LOCK:
                self._configure_connection()
                self._ensure_schema()
        except BaseException:
            # A refused schema must not also leak the file handle it was
            # refused through. On Windows an open sqlite connection keeps
            # the file locked, so a caller that catches
            # `SnapshotSchemaMismatch` and repairs the database would find
            # it still held by the store that never finished constructing.
            self._conn.close()
            raise

    def __enter__(self) -> SqliteSnapshotStore:
        """Enter a ``with`` block; the store is already usable on construction.

        Present for parity with
        :class:`~openbb_techtrade.snapshot.mysql_store.MysqlSnapshotStore`:
        without it ``with get_default_snapshot_store() as store:`` works on
        one backend and raises ``TypeError`` on the other, which defeats
        the point of selecting a backend behind a Protocol.
        """
        return self

    def __exit__(self, *exc: object) -> None:
        """Release the SQLite connection."""
        self.close()

    def _configure_connection(self) -> None:
        """Set WAL + busy timeout so concurrent reads are never locked out.

        In the default rollback-journal mode a reader that arrives while
        the EOD writer holds ``BEGIN IMMEDIATE`` raises
        ``sqlite3.OperationalError: database is locked``, straight out of
        the always-available read path safeguard #9 promises. WAL lets
        readers proceed against the last committed snapshot instead.
        """
        self._conn.execute(f"PRAGMA busy_timeout = {_SQLITE_BUSY_TIMEOUT_MS}")
        mode = self._conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            logger.warning(
                "snapshot store: SQLite refused WAL at %s (journal_mode=%s); "
                "concurrent readers may see 'database is locked' under a "
                "long write",
                self._db_path,
                mode,
            )

    def _pragma(self, pragma: str, argument: str) -> list[sqlite3.Row]:
        """Run ``PRAGMA <pragma>(<argument>)`` with the argument quoted.

        ``PRAGMA`` arguments cannot be bound as parameters, so the table
        or index name has to be interpolated. Index names come out of the
        database's own catalogue and are free-form — ``CREATE INDEX "ux
        live"``, ``CREATE INDEX "order"`` and ``CREATE INDEX "a""b"`` are
        all legal — so an unquoted interpolation turns a merely
        awkwardly-named index into a raw ``sqlite3.OperationalError``
        raised from the constructor, before the schema guard can say
        anything about it. Quoting handles the awkward names; converting
        whatever is left into :class:`SnapshotSchemaMismatch` keeps the
        one remaining failure mode ("this store cannot read the
        catalogue, so it cannot prove the invariant") inside the guard's
        vocabulary rather than the driver's (PR #2062 review).
        """
        try:
            return self._conn.execute(
                f"PRAGMA {pragma}({_quote_identifier(argument)})"  # noqa: S608
            ).fetchall()
        except (sqlite3.Error, ValueError) as exc:
            raise SnapshotSchemaMismatch(
                f"sqlite: PRAGMA {pragma} failed for {argument!r} "
                f"({type(exc).__name__}: {exc}). The catalogue of table "
                f"{_SNAPSHOT_TABLE!r} cannot be read, so neither its shape "
                f"nor its single-LIVE guard can be verified. Refusing to "
                f"use it."
            ) from exc

    def _table_columns(self) -> list[str] | None:
        """Column names of an existing ``pi_eod_snapshot``, or ``None``."""
        exists = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (_SNAPSHOT_TABLE,),
        ).fetchone()
        if exists is None:
            return None
        return [
            record["name"] for record in self._pragma("table_info", _SNAPSHOT_TABLE)
        ]

    def _table_indexes(self) -> list[_IndexShape]:
        """Every index on ``pi_eod_snapshot``, as SQLite's catalogue sees it.

        ``PRAGMA index_list`` reports uniqueness and whether an index is
        partial but not *what* the partial predicate is, and ``PRAGMA
        index_info`` reports the columns; only ``sqlite_master.sql``
        carries the ``WHERE`` clause — and it is ``NULL`` for the
        implicit index behind a ``PRIMARY KEY``, which is exactly the
        index that must not be mistaken for the single-LIVE guard.

        Only the ``WHERE`` tail is kept, never the whole statement: the
        guard's own name (``ux_pi_eod_snapshot_live``) contains the token
        ``live``, so a predicate check run against the full SQL text
        would pass for *any* index wearing that name, including one
        predicated on the wrong state. Slicing at the first ``WHERE`` is
        unambiguous because SQLite forbids subqueries in an index
        predicate, so a partial index has exactly one.

        Both PRAGMAs go through :meth:`_pragma`, which quotes the
        interpolated name: ``index_list`` names a constant, but
        ``index_info`` names whatever the catalogue reports, and an index
        called ``"ux live"`` or ``"order"`` would otherwise be a raw
        ``OperationalError`` out of the constructor instead of a
        :class:`SnapshotSchemaMismatch` (PR #2062 review).
        """
        predicates = {
            record["name"]: _index_predicate(record["sql"])
            for record in self._conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'index' "
                "AND tbl_name = ?",
                (_SNAPSHOT_TABLE,),
            ).fetchall()
        }
        shapes: list[_IndexShape] = []
        for record in self._pragma("index_list", _SNAPSHOT_TABLE):
            name = record["name"]
            columns = tuple(
                column["name"] for column in self._pragma("index_info", name)
            )
            shapes.append(
                _IndexShape(
                    name=name,
                    unique=bool(record["unique"]),
                    columns=columns,
                    predicate=predicates.get(name, ""),
                )
            )
        return shapes

    def _ensure_schema(self) -> None:
        """Create the schema, or refuse an existing table that isn't ours.

        ``CREATE TABLE IF NOT EXISTS`` succeeds as a *no-op* against a
        pre-existing table of any shape, which is what would let a
        foreign ``pi_eod_snapshot`` (or a future #1964/#1967 column
        addition) produce a store that constructs cleanly and then fails
        every operation with "no such column". The shape and version are
        therefore checked before the DDL runs, and both failures are
        loud (:class:`SnapshotSchemaMismatch`).

        The single-LIVE partial unique index is checked *after* the DDL,
        because on a fresh database the DDL is what creates it. ``CREATE
        UNIQUE INDEX IF NOT EXISTS`` is keyed on the index name, so a
        pre-existing object already wearing that name — a plain index, or
        a unique one without the ``state = 'live'`` predicate — no-ops
        the statement and leaves the invariant unenforced. Reading the
        index back from the catalogue is the only way to know which of
        the two happened (PR #2062 review).

        ``PRAGMA user_version`` is per *file*: ``PI_SNAPSHOT_DB`` must
        point at a database dedicated to this store (the factory default
        ``~/.portfolio_intel/snapshot.db`` is), not one shared with
        another component that stamps its own version.
        """
        columns = self._table_columns()
        if columns is not None:
            _check_schema_shape(columns, backend="sqlite")
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            _check_schema_version(int(version), backend="sqlite")
        self._conn.executescript(_SQLITE_SCHEMA)
        _check_sqlite_live_guard(self._table_indexes())
        self._conn.execute(f"PRAGMA user_version = {SNAPSHOT_SCHEMA_VERSION}")

    @contextmanager
    def _tx(self, *, immediate: bool = False) -> Iterator[None]:
        """Transaction scope — all-or-nothing for multi-statement writes.

        ``immediate=True`` opens with ``BEGIN IMMEDIATE``, taking SQLite's
        database-wide write lock *before* the first read. That is this
        dialect's stand-in for MySQL's ``SELECT ... FOR UPDATE``: SQLite
        has no row locks, so serializing the whole read-decide-write
        sequence is the only way to stop another connection committing
        inside it.

        The whole body is held under :data:`_SQLITE_LOCK` (spec §4.6):
        `BEGIN IMMEDIATE` locks the *database against other processes*,
        but says nothing about two threads sharing this one connection —
        they would share one transaction.

        The rollback is conditional on a transaction actually being open
        and is itself guarded. When the failure *was* the ``BEGIN`` (a
        locked database, a nested transaction), an unconditional
        ``ROLLBACK`` raises a second ``OperationalError`` that replaces
        the first — and callers such as :meth:`promote` classify the
        exception they see, so a displaced ``IntegrityError`` turns a
        documented ``False`` into a raw driver traceback.
        """
        with _SQLITE_LOCK:
            try:
                self._conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield
                self._conn.execute("COMMIT")
            except Exception:
                self._rollback_quietly()
                raise

    def _rollback_quietly(self) -> None:
        """Roll back an open transaction without masking the original error."""
        if not self._conn.in_transaction:
            return
        try:
            self._conn.execute("ROLLBACK")
        except sqlite3.Error:
            logger.warning("snapshot rollback failed", exc_info=True)

    def _get_row(
        self, dataset: str, entity_key: str, as_of_session: date, job_run_id: str
    ) -> SnapshotRow | None:
        """Fetch the exact row identified by the full primary key.

        Callers must pass already-canonicalized ``dataset``/``entity_key``.
        """
        with _SQLITE_LOCK:
            record = self._conn.execute(
                "SELECT dataset, entity_key, as_of_session, created_at, "
                "job_run_id, status, state, validated, validation_reason, "
                "payload_json, input_hash, row_count, engine_version, "
                "payload_schema_version FROM pi_eod_snapshot "
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
        # Serialized (and shape-checked) *before* the transaction opens, so
        # a non-dict payload raises without ever taking the write lock --
        # matching the bounded-field guard just above (#2062 review).
        payload_text = _dumps_payload(payload)
        with self._tx():
            self._conn.execute(
                "INSERT INTO pi_eod_snapshot ("
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
                    payload_text,
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
                    "UPDATE pi_eod_snapshot SET validated = ?, validation_reason = ? "
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
        return self._promote(dataset, entity_key, as_of_session, job_run_id)

    def _promote_expecting_live(  # pylint: disable=too-many-positional-arguments
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
        *,
        expected_live: SnapshotRow | None,
    ) -> bool:
        """Promote only while LIVE is still ``expected_live`` (#1963 I2).

        The restamp seam: identical to :meth:`promote` except that the
        LIVE row read *inside* the transaction must be the same row the
        caller copied its payload from. See :func:`_restamp_live`.
        """
        return self._promote(
            dataset,
            entity_key,
            as_of_session,
            job_run_id,
            expected_live=expected_live,
            expectation=True,
        )

    def _promote(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
        *,
        expected_live: SnapshotRow | None = None,
        expectation: bool = False,
    ) -> bool:
        """Shared promote body; ``expectation`` pins the incumbent LIVE row."""
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        try:
            with self._tx(immediate=True):
                candidate = self._get_row(
                    dataset, entity_key, as_of_session, job_run_id
                )
                live = self.get_live(dataset, entity_key)
                if expectation:
                    moved = _restamp_race_refusal(expected_live, live)
                    if moved is not None:
                        raise _PromotionRefused(moved)
                refusal = _promotion_refusal(candidate, live)
                if refusal is not None:
                    raise _PromotionRefused(refusal)
                if live is not None:
                    self._demote(dataset, entity_key, live)
                promoted = self._conn.execute(
                    "UPDATE pi_eod_snapshot SET state = ? "
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
            "UPDATE pi_eod_snapshot SET state = ? "
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
        with _SQLITE_LOCK:
            record = self._conn.execute(
                "SELECT dataset, entity_key, as_of_session, created_at, "
                "job_run_id, status, state, validated, validation_reason, "
                "payload_json, input_hash, row_count, engine_version, "
                "payload_schema_version FROM pi_eod_snapshot "
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
        with _SQLITE_LOCK:
            record = self._conn.execute(
                "SELECT dataset, entity_key, as_of_session, created_at, "
                "job_run_id, status, state, validated, validation_reason, "
                "payload_json, input_hash, row_count, engine_version, "
                "payload_schema_version FROM pi_eod_snapshot "
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
        _check_limit(limit)
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        with _SQLITE_LOCK:
            records = self._conn.execute(
                "SELECT dataset, entity_key, as_of_session, created_at, "
                "job_run_id, status, state, validated, validation_reason, "
                "payload_json, input_hash, row_count, engine_version, "
                "payload_schema_version FROM pi_eod_snapshot "
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

    def prune(
        self,
        policy: RetentionPolicy | None = None,
        *,
        dataset: str | None = None,
        entity_key: str | None = None,
    ) -> int:
        """Apply retention; return the number of rows removed.

        The default policy (``None``, or an explicit ``RetentionPolicy()``
        with ``keep_sessions=None``) keeps everything and returns ``0``. A
        bounded policy deletes only non-LIVE rows outside the newest
        ``keep_sessions`` distinct ``as_of_session`` values, per
        (dataset, entity_key) key. LIVE rows are never pruned — the
        ``state != 'live'`` filter below is an unconditional safety net,
        independent of whether a LIVE row's session lands inside the kept
        window.

        ``dataset``/``entity_key`` scope the sweep (#1963 review I4). The
        store is shared, so an unscoped bounded policy applies one
        caller's window to *every* dataset's history; that is still
        supported (it is the whole-store janitor) but it is logged, and
        scoped calls are the recommended shape for a per-dataset job.

        Shape: one ``SELECT DISTINCT`` for the whole sweep, then bounded
        set-based ``DELETE``s of at most :data:`_PRUNE_BATCH` sessions
        each — not a SELECT+DELETE round trip per key, which held the
        write lock for O(#keys) statements.

        The transaction is ``BEGIN IMMEDIATE``: this is a read-decide-
        write sequence, and a *deferred* ``BEGIN`` takes only a read
        snapshot at the ``SELECT``. In WAL mode another connection is
        free to commit inside that window, and the first ``DELETE`` then
        fails to upgrade with ``SQLITE_BUSY_SNAPSHOT`` — an error the
        busy timeout deliberately does not retry, because retrying it
        cannot succeed. Taking the write lock up front is the same
        stand-in for ``FOR UPDATE`` that :meth:`promote` uses, and it
        also stops a concurrent writer's row from being ranked into the
        kept window by the ``SELECT`` and then deleted by the ``DELETE``.
        """
        if policy is None or policy.keep_sessions is None:
            return 0
        dataset, entity_key = _prune_scope(dataset, entity_key)
        if dataset is None:
            logger.info(
                "snapshot prune: applying keep_sessions=%d to every dataset in "
                "the shared store; pass dataset=... to scope it",
                policy.keep_sessions,
            )
        scope_sql, scope_params = _scope_clause(dataset, entity_key, "?")
        deleted = 0
        with self._tx(immediate=True):
            # The only interpolation is `_scope_clause`'s module-owned
            # fragment of literals and "?" tokens; values are bound.
            rows = self._conn.execute(
                "SELECT DISTINCT dataset, entity_key, as_of_session "  # noqa: S608
                f"FROM pi_eod_snapshot{scope_sql} "
                "ORDER BY dataset, entity_key, as_of_session DESC",
                scope_params,
            ).fetchall()
            doomed = _doomed_triples(rows, policy.keep_sessions)
            for batch in _batched(doomed):
                # The only interpolation is a run of module-owned "(?, ?, ?)"
                # placeholder tokens; every value is bound via `params`.
                tuples = ", ".join("(?, ?, ?)" for _ in batch)
                params = [SnapshotState.LIVE.value]
                for triple in batch:
                    params.extend(triple)
                deleted += self._conn.execute(
                    "DELETE FROM pi_eod_snapshot WHERE state != ? "  # noqa: S608
                    f"AND (dataset, entity_key, as_of_session) IN ({tuples})",
                    params,
                ).rowcount
        return deleted

    def close(self) -> None:
        """Release the SQLite connection, under the same lock every call uses.

        The lock is not ceremony here. The connection is shared across
        threads (``check_same_thread=False``), so closing it while
        another thread is inside :meth:`_tx` would abort that thread's
        open transaction and turn its next statement into
        ``sqlite3.ProgrammingError: Cannot operate on a closed
        database`` — a half-written promote reported as a programming
        bug. Taking :data:`_SQLITE_LOCK` makes ``close()`` wait for the
        in-flight write to commit, exactly like any other statement.
        """
        with _SQLITE_LOCK:
            self._conn.close()


# ---------------------------------------------------------------------------
# Factory — env-var driven backend selection (#1963 Task 5)
# ---------------------------------------------------------------------------
#
# Mirrors the existing `execution.paper_engine.get_default_engine` /
# `execution.order_sink.get_default_sink` seam: an env var picks the
# backend, MySQL is the default, and a MySQL backend that cannot be
# constructed — for any reason — degrades to SQLite with a WARNING rather
# than failing the caller outright. An unrecognized `PI_SNAPSHOT_ENGINE`
# value raises `ValueError` loudly (mirrors `get_default_sink`'s stricter
# convention) rather than being silently treated as "sqlite".

_ENV_SNAPSHOT_ENGINE = "PI_SNAPSHOT_ENGINE"
_ENV_SNAPSHOT_DB = "PI_SNAPSHOT_DB"


def _exception_label(exc: BaseException) -> str:
    """Name an exception's *type* for a log line, without its message.

    Qualified by module for anything outside ``builtins``, because
    ``OperationalError`` alone does not say whether the driver, this
    store's SQLite fallback, or something else raised it — and the three
    send an operator to three different places. The message is
    deliberately not included: driver messages routinely carry the DSN,
    the account that failed to authenticate, or a fragment of the
    failing statement (PR #2062 review).
    """
    kind = type(exc)
    module = kind.__module__
    if module in ("builtins", "__main__"):
        return kind.__qualname__
    return f"{module}.{kind.__qualname__}"


def _make_mysql_store() -> SnapshotStore:
    """Import indirection for constructing a ``MysqlSnapshotStore``.

    ``mysql_store`` imports the shared policy helpers from *this* module,
    so importing it back at this module's top level would be circular.
    The import is deferred to call time instead, once both modules have
    finished loading, and kept as a standalone module-level function
    (rather than inlined into :func:`get_default_snapshot_store`) so
    tests can monkeypatch ``store_module._make_mysql_store`` directly to
    simulate an unavailable MySQL backend without a real connection pool.
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
      fails for *any* reason — a missing optional dependency
      (``ImportError``), an unreachable or unauthenticated pool, or a
      refused schema (:class:`SnapshotSchemaMismatch`) — a WARNING
      naming the exception *type* is logged and the selector falls
      through to SQLite, mirroring the ``get_default_engine``
      graceful-fallback pattern from #1790/#1744. Only the MySQL
      construction is guarded this way; a failure constructing the
      SQLite fallback itself is never swallowed.
    - ``PI_SNAPSHOT_ENGINE=sqlite`` — force the file-backed
      :class:`SqliteSnapshotStore` at ``db_path`` (arg),
      ``$PI_SNAPSHOT_DB`` (env), or the per-user default
      ``~/.portfolio_intel/snapshot.db``.
    - Anything else — loud :class:`ValueError`. No silent fallback to
      SQLite for a typo'd or unsupported value (mirrors
      ``execution.order_sink.get_default_sink``'s stricter convention
      rather than treating "not mysql" as "must be sqlite").

    ``db_path`` takes precedence over ``$PI_SNAPSHOT_DB`` on both the
    explicit-sqlite path and the MySQL-unavailable fallback path. The
    resolved SQLite path is computed once, up front, and immediately
    normalized with ``expanduser().resolve()`` so the fallback WARNING
    and the eventual ``SqliteSnapshotStore`` construction agree
    on the same absolute path. Without the ``expanduser()`` half, a
    literal ``~`` in ``$PI_SNAPSHOT_DB``/``db_path`` would not expand to
    the caller's home directory: ``Path.resolve()`` alone treats ``~``
    as an ordinary path segment and would create it as a literal
    directory named ``~`` under the current working directory instead.
    :class:`SqliteSnapshotStore.__init__` applies the same
    ``expanduser().resolve()`` normalization independently, so this is
    belt-and-braces here rather than the only guard: a caller that
    constructs :class:`SqliteSnapshotStore` directly, bypassing this
    factory, is protected too.
    """
    backend = os.environ.get(_ENV_SNAPSHOT_ENGINE, "mysql").strip().lower()

    if backend not in ("mysql", "sqlite"):
        raise ValueError(
            f"{_ENV_SNAPSHOT_ENGINE} must be one of 'mysql' | 'sqlite'; "
            f"got {backend!r}"
        )

    # TODO(gh-1965): the resolved path is not yet checked against the
    # `_validate_outside_repo` guard the portfolio importer uses. Design
    # spec §8 requires an in-repo `PI_SNAPSHOT_DB` to raise; that guard
    # lands with #1965, deliberately out of scope for #1963.
    resolved = (
        (
            Path(db_path)
            if db_path is not None
            else (
                Path(os.environ[_ENV_SNAPSHOT_DB])
                if os.environ.get(_ENV_SNAPSHOT_DB)
                else Path.home() / ".portfolio_intel" / "snapshot.db"
            )
        )
        .expanduser()
        .resolve()
    )

    if backend == "mysql":
        try:
            return _make_mysql_store()
        except Exception as exc:  # noqa: BLE001
            # "unavailable", not "unreachable": the failure is just as
            # likely an `ImportError` (the optional MySQL dependency is
            # not installed) or a `SnapshotSchemaMismatch` (the server is
            # perfectly reachable and refused) as a network fault, and
            # naming a network fault sends the operator to the wrong
            # place. The exception *type* is what distinguishes the three,
            # so it is logged; its *message* is not, because a driver's
            # message can carry the DSN, the account it connected as, or
            # a fragment of the statement that failed. Operators who need
            # it turn on DEBUG for this module and get the whole
            # traceback below (PR #2062 review).
            logger.warning(
                "get_default_snapshot_store: MySQL backend unavailable (%s); "
                "falling back to SQLite at %s",
                _exception_label(exc),
                resolved,
            )
            logger.debug(
                "get_default_snapshot_store: MySQL backend construction failed",
                exc_info=True,
            )
            # fall through to sqlite

    return SqliteSnapshotStore(resolved)
