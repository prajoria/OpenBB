"""EOD snapshot store — MySQL backend (#1963 Task 4).

Implements the :class:`openbb_techtrade.snapshot.store.SnapshotStore`
Protocol against the *same* MySQL instance as the corporate FMP cache,
reusing :func:`openbb_fmp_cached.utils.database.get_connection_pool`
exactly like :class:`~openbb_techtrade.execution.mysql_paper_engine.MysqlPaperEngine`.

Only the SQL dialect lives here. Every *policy* decision — row
conversion, the STAGING-only validation gate, the keep-last-good
promotion rank, canonicalization, retention windowing, the
should-skip/restamp compositions — is imported from
:mod:`openbb_techtrade.snapshot.store`, so the two backends can disagree
about SQL text but never about behavior.

Design deltas vs. :class:`~openbb_techtrade.snapshot.store.SqliteSnapshotStore`
------------------------------------------------------------------------------
1. **Native temporal types.** SQLite has no date/time type and stores
   ISO-8601 text; MySQL uses ``DATE`` for ``as_of_session`` (the trading
   day the payload is *about*) and ``DATETIME(6)`` for ``created_at``
   (the microsecond UTC wall clock of the write). Those two concepts
   never collapse into one column. ``DATETIME`` carries no offset, so
   the backend binds a **naive UTC** value and ``_as_created_at`` stamps
   ``timezone.utc`` back on read — callers get the identical tz-aware
   instant either backend returns.
2. **Generated nullable ``live_key`` instead of a partial index.** MySQL
   has no partial (``WHERE``-filtered) unique index, so the single-LIVE
   invariant is carried by a STORED generated column that is ``NULL``
   for every non-LIVE row plus a plain ``UNIQUE KEY``. MySQL unique
   indexes ignore ``NULL``s, so unlimited STAGING/SUPERSEDED history
   coexists with at most one LIVE row per ``(dataset, entity_key)``.
   ``CHAR(31)`` (ASCII unit separator) joins the two halves so a
   ``dataset``/``entity_key`` boundary can never be forged by a value
   that merely contains the delimiter. Both halves of that mechanism —
   the column *and* its unique index — are re-read from
   ``information_schema`` at construction and refused if absent or
   malformed, then exercised with a transaction-rolled-back behavior
   probe, because ``CREATE TABLE IF NOT EXISTS`` no-ops against a
   pre-existing table and takes every index declared inside it down with
   it (PR #2062 review). See
   :func:`~openbb_techtrade.snapshot.store._check_mysql_live_guard`.
3. **Explicit LIVE pointer.** "Current" is the row whose ``state`` is
   ``live`` — never "the row with the newest ``as_of_session``". A
   restamp/backfill/replay can legitimately leave LIVE pointing at an
   older session, so every read and every retention decision keys off
   ``state``, and ``prune()`` refuses to delete a LIVE row regardless of
   whether its session lands inside the kept window.
4. **``%s`` bindings, pooled PyMySQL sessions, explicit transactions.**
   Placeholders are ``%s`` (PyMySQL) instead of ``?``. Connections are
   borrowed per operation from a shared pool whose ``get_connection()``
   is a ``@contextmanager`` — it *yields* the connection and closes it
   itself — so every borrow is a ``with`` block, never a bare call.
   Those sessions are ``autocommit=True``, which means a write scope has
   to open its own transaction (:meth:`transaction`, via
   ``conn.begin()``) or it is not atomic and its ``FOR UPDATE`` locks do
   not survive the statement that took them; reads
   (:meth:`_read`) need no transaction at all. The pool pins
   ``cursorclass=DictCursor``, so cursors are requested bare
   (``conn.cursor()``) and rows arrive as mappings. Finally, PyMySQL
   connects without ``CLIENT.FOUND_ROWS``, so ``cursor.rowcount`` after
   an UPDATE counts rows *changed*, not rows *matched* — see
   :meth:`validate`, which cannot use it to detect a race. Construction
   also re-reads ``information_schema.TABLES.ENGINE`` and requires
   ``InnoDB`` before the rollback-only behavior probe: a nontransactional
   engine would make that rollback a lie and persist its synthetic rows.
5. **Pinned binary collation.** MySQL resolves an unpinned string column
   to the charset's *default* collation, which is case- and
   accent-insensitive; SQLite's default is BINARY. Every key column and
   the table itself therefore pin ``utf8mb4_bin``, or the primary key
   and the single-LIVE unique key would mean different things on the two
   backends (see the DDL comment below). The pin is also **re-read from
   ``information_schema.COLUMNS`` at construction and refused when the
   server reports anything else**, because ``CREATE TABLE IF NOT
   EXISTS`` no-ops against a pre-existing table and its collation is
   whatever that table already had (PR #2062 review). See
   :func:`~openbb_techtrade.snapshot.store._check_mysql_collations`.
6. **Schema version stamped in the table ``COMMENT``.** MySQL has no
   ``PRAGMA user_version``, so :data:`~openbb_techtrade.snapshot.store.SNAPSHOT_SCHEMA_VERSION`
   is written into ``pi_eod_snapshot``'s own comment and read back from
   ``information_schema.TABLES``. It is checked at construction in both
   directions — a table stamped by a newer build and a table stamped by
   an older one are both refused — because a column-shape check cannot
   see either case: a newer schema is a *superset* of this build's
   columns. See :meth:`MysqlSnapshotStore._ensure_schema`.

Read path is compute-free: every read method only ever issues a
``SELECT`` against ``pi_eod_snapshot``; none of them calls a provider or
a compute/scan function.

Table naming: ``pi_eod_snapshot``, **not** ``pi_snapshot`` — the latter
is already taken, in this same database, by the account-scoped positions
history of ``portfolio_snapshot_importer`` (#1744). See the C1 note in
:mod:`openbb_techtrade.snapshot.store`.
"""

# ruff: noqa: S608
# S608 (hardcoded SQL): the only f-string interpolation below builds a
# retention `NOT IN (...)` fragment out of module-owned literals and "%s"
# placeholder tokens. Every user value is bound as a parameter. Ruff
# cannot prove that, so it is suppressed at file scope.

# pylint: disable=too-many-lines
# The module is one backend of a two-backend contract; splitting it would
# put the DDL, the `information_schema` probes that verify that DDL, and
# the lifecycle methods that depend on both into separate files whose only
# reader is each other. `store.py` carries the same disable for the same
# reason.

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4
from weakref import WeakKeyDictionary

from openbb_techtrade.snapshot.store import (
    _CANDIDATE_RACE_REASON,
    _LIVE_COLLISION_REASON,
    _LIVE_GUARD_PROBE_PREFIX,
    _LIVE_RACE_REASON,
    _PRUNE_BATCH,
    _SNAPSHOT_TABLE,
    _VALIDATION_RACE_REASON,
    RetentionPolicy,
    SnapshotRow,
    SnapshotSchemaMismatch,
    SnapshotState,
    SnapshotStatus,
    ValidationResult,
    _batched,
    _check_field_lengths,
    _check_limit,
    _check_mysql_collations,
    _check_mysql_live_guard,
    _check_schema_shape,
    _check_schema_version,
    _doomed_triples,
    _dumps_payload,
    _IndexShape,
    _is_integrity_error,
    _LifecycleRefused,
    _live_guard_refusal,
    _parse_schema_version_comment,
    _promotion_refusal,
    _PromotionRefused,
    _prune_scope,
    _restamp_live,
    _restamp_race_refusal,
    _row_from_mapping,
    _schema_version_comment,
    _scope_clause,
    _should_skip,
    _validation_refusal,
    _ValidationRefused,
    canonical_key,
    default_validator,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DDL — additive; never touches the corporate FMP cache tables.
# ---------------------------------------------------------------------------

_PI_EOD_SNAPSHOT_DDL = """
CREATE TABLE IF NOT EXISTS pi_eod_snapshot (
    dataset                VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    entity_key             VARCHAR(191) COLLATE utf8mb4_bin NOT NULL,
    as_of_session          DATE NOT NULL,
    created_at             DATETIME(6) NOT NULL,
    job_run_id             VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    status                 VARCHAR(16) COLLATE utf8mb4_bin NOT NULL,
    state                  VARCHAR(16) COLLATE utf8mb4_bin NOT NULL,
    validated              TINYINT(1) NOT NULL DEFAULT 0,
    validation_reason      TEXT NOT NULL,
    payload_json           LONGTEXT NOT NULL,
    input_hash             VARCHAR(128) COLLATE utf8mb4_bin,
    row_count              INT,
    engine_version         VARCHAR(64) COLLATE utf8mb4_bin,
    payload_schema_version VARCHAR(64) COLLATE utf8mb4_bin,
    live_key               VARCHAR(512) COLLATE utf8mb4_bin
        GENERATED ALWAYS AS (
            IF(state = 'live',
               CONCAT(dataset, CHAR(31 USING utf8mb4), entity_key),
               NULL)
        ) STORED,
    PRIMARY KEY (dataset, entity_key, as_of_session, job_run_id),
    UNIQUE KEY ux_pi_eod_snapshot_live (live_key),
    INDEX ix_pi_eod_snapshot_live (dataset, entity_key, state),
    INDEX ix_pi_eod_snapshot_latest (dataset, entity_key, as_of_session, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
"""
# Collation is pinned, not inherited (#1963 security review, Alert 2).
# ``DEFAULT CHARSET=utf8mb4`` alone would take the charset's *default*
# collation — ``utf8mb4_0900_ai_ci`` on MySQL 8, ``utf8mb4_general_ci``
# on 5.7 — both case- **and** accent-insensitive. Two consequences, both
# fatal to this table's contract:
#
# 1. ``ux_pi_eod_snapshot_live`` is the only DB-level enforcement of the
#    single-LIVE invariant on MySQL. Under an ``_ai_ci`` collation two
#    genuinely distinct canonical keys that differ only by an accent
#    (``sector=cafe`` vs ``sector=café``) share one index entry, so once
#    one is LIVE the other can *never* be promoted — and the refusal is
#    logged as the routine "another writer already installed a LIVE row",
#    misattributing the cause. ``canonical_key`` casefolds, so case is
#    moot, but it does not normalize Unicode.
# 2. ``job_run_id`` is never canonicalized at all. Under ``_ci`` the
#    primary key treats ``Run-1`` and ``run-1`` as the same row: SQLite
#    inserts two rows, MySQL raises a duplicate-key ``IntegrityError``.
#    That breaks the binding parity claim below ("a call one accepts is
#    a call the other accepts") in the one place ``_check_field_lengths``
#    cannot see.
#
# Both the table default and every key column carry the collation
# explicitly, so changing one without the other is visible in review —
# and `_check_mysql_collations` re-reads what the *server* resolved, so a
# pre-existing table that the `IF NOT EXISTS` above quietly adopted
# cannot smuggle an `_ai_ci` key column past construction.

# The bounded VARCHAR widths above are mirrored by
# ``store.FIELD_MAX_LENGTHS`` and enforced in Python before any write, so
# the SQLite backend (which ignores widths) refuses exactly what MySQL
# would. ``validation_reason`` is deliberately *not* bounded: it is a
# validator's free-text explanation, not an identifier, and a
# ``VARCHAR(512)`` would silently truncate it on a non-strict server
# while SQLite kept it whole. TEXT has no literal DEFAULT before MySQL
# 8.0.13, so ``_INSERT_STAGED`` binds the empty string explicitly. (TEXT
# still tops out at 64 KiB; a validator needing more should write a
# pointer, not a novel.)

_ALL_DDLS = (_PI_EOD_SNAPSHOT_DDL,)

_COLUMNS = (
    "dataset, entity_key, as_of_session, created_at, job_run_id, status, "
    "state, validated, validation_reason, payload_json, input_hash, "
    "row_count, engine_version, payload_schema_version"
)

_SELECT_BY_PK = (
    f"SELECT {_COLUMNS} FROM pi_eod_snapshot "
    "WHERE dataset = %s AND entity_key = %s AND as_of_session = %s "
    "AND job_run_id = %s"
)

_SELECT_LIVE = (
    f"SELECT {_COLUMNS} FROM pi_eod_snapshot "
    "WHERE dataset = %s AND entity_key = %s AND state = %s"
)

# Locking variants. InnoDB takes an exclusive row lock for the rest of the
# transaction, so the candidate and the incumbent LIVE row cannot move
# between promote()'s read and its write. They are only ever issued on the
# same connection that performs the writes — a lock taken on a different
# pooled session would be released the moment that session went back.
_SELECT_BY_PK_FOR_UPDATE = _SELECT_BY_PK + " FOR UPDATE"
_SELECT_LIVE_FOR_UPDATE = _SELECT_LIVE + " FOR UPDATE"

_SELECT_AS_OF = (
    f"SELECT {_COLUMNS} FROM pi_eod_snapshot "
    "WHERE dataset = %s AND entity_key = %s AND as_of_session = %s "
    "AND state != %s ORDER BY created_at DESC LIMIT 1"
)

_SELECT_HISTORY = (
    f"SELECT {_COLUMNS} FROM pi_eod_snapshot "
    "WHERE dataset = %s AND entity_key = %s "
    "ORDER BY as_of_session DESC, created_at DESC LIMIT %s"
)

_INSERT_STAGED = (
    "INSERT INTO pi_eod_snapshot ("
    "dataset, entity_key, as_of_session, created_at, job_run_id, "
    "status, state, validated, validation_reason, payload_json, "
    "input_hash, row_count, engine_version, payload_schema_version"
    ") VALUES (%s, %s, %s, %s, %s, %s, %s, 0, '', %s, %s, %s, %s, %s)"
)

_INSERT_LIVE_GUARD_PROBE = (
    "INSERT INTO pi_eod_snapshot ("
    "dataset, entity_key, as_of_session, created_at, job_run_id, status, state, "
    "validated, validation_reason, payload_json, input_hash, row_count, "
    "engine_version, payload_schema_version"
    ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_SELECT_LIVE_GUARD_PROBE = (
    "SELECT job_run_id, state, live_key FROM pi_eod_snapshot "
    "WHERE dataset = %s AND entity_key = %s ORDER BY job_run_id"
)

_SELECT_SCHEMA_COLUMNS = (
    "SELECT COLUMN_NAME, GENERATION_EXPRESSION, COLLATION_NAME "
    "FROM information_schema.COLUMNS "
    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s"
)
# `COLLATION_NAME` is the third thing this one probe answers, and it is
# not decoration: a `CREATE TABLE IF NOT EXISTS` that no-ops leaves a
# pre-existing table's collation in place, and an `_ai_ci` key column
# turns both the primary key and `ux_pi_eod_snapshot_live` into weaker
# constraints than SQLite's BINARY ones without changing a single column
# name. It is `NULL` for a non-character column, which is itself a
# refusal — see `_check_mysql_collations` (PR #2062 review).

# The single-LIVE guard, read back from the server rather than assumed.
# `GENERATION_EXPRESSION` above distinguishes the generated `live_key`
# column from an ordinary column of the same name (which would be NULL on
# every row, so its UNIQUE index would constrain nothing); `STATISTICS`
# below is MySQL's index catalogue — one row per (index, column), ordered
# by `SEQ_IN_INDEX`, with `NON_UNIQUE = 0` for a unique index. Both
# together are what `_check_mysql_live_guard` needs to prove the invariant
# is actually enforced (PR #2062 review).
_SELECT_SCHEMA_INDEXES = (
    "SELECT INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME "
    "FROM information_schema.STATISTICS "
    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
    "ORDER BY INDEX_NAME, SEQ_IN_INDEX"
)

# MySQL's answer to `PRAGMA user_version`. The version this build speaks is
# stamped into the table's own COMMENT and read back out of the data
# dictionary — see the rationale above `_SCHEMA_VERSION_MARKER` in
# `openbb_techtrade.snapshot.store` for why the comment, and not a
# companion version table, carries the stamp.
_SELECT_SCHEMA_COMMENT = (
    "SELECT TABLE_COMMENT, ENGINE FROM information_schema.TABLES "
    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s"
)

# `ALTER TABLE ... COMMENT` is a metadata-only change (INSTANT on MySQL 8),
# not a table rebuild. PyMySQL interpolates `%s` client-side, so the
# placeholder is a real bind even though DDL cannot be server-prepared.
_STAMP_SCHEMA_COMMENT = f"ALTER TABLE {_SNAPSHOT_TABLE} COMMENT = %s"

# Pools whose database has already had the DDL + shape and behavior checks applied
# (#1963 review I3). ``ConnectionPool.get_connection()`` opens a *fresh*
# ``pymysql.connect`` per borrow — it is not a pool in the pooling sense
# — so a per-request widget store paid a full connect + DDL round trip
# on every construction. The pool object *is* the database identity here
# (`get_connection_pool()` returns a process-wide singleton built from
# one `DatabaseConfig`), so keying on it skips the redundant DDL without
# ever skipping it for a *different* database: a store built on another
# pool, another config, or a test double gets its own entry. The map is
# weak so a discarded pool cannot pin its entry — or the schema decision
# taken against it — for the life of the process.
_SCHEMA_READY: WeakKeyDictionary = WeakKeyDictionary()
_MISSING_TABLE_METADATA = object()
_TRANSACTIONAL_ENGINE = "InnoDB"


def _check_storage_engine(engine: object) -> None:
    """Require the transaction semantics the rollback-only probe depends on."""
    if (
        isinstance(engine, str)
        and engine.casefold() == _TRANSACTIONAL_ENGINE.casefold()
    ):
        return
    if engine is _MISSING_TABLE_METADATA:
        reported = "missing metadata"
    elif engine is None:
        reported = "NULL"
    else:
        reported = repr(engine)
    raise SnapshotSchemaMismatch(
        f"mysql: table {_SNAPSHOT_TABLE!r} must use {_TRANSACTIONAL_ENGINE}; "
        f"information_schema.TABLES reported ENGINE {reported}. The schema "
        "behavior probe relies on transactional rollback, so refusing to "
        "probe, stamp, or use this table."
    )


def _index_shapes(records: Iterable[Mapping[str, Any]]) -> list[_IndexShape]:
    """Fold ``information_schema.STATISTICS`` rows into one shape per index.

    ``STATISTICS`` is one row per *(index, column)* pair, so the columns
    of a composite index arrive spread over several rows and must be
    re-assembled in ``SEQ_IN_INDEX`` order — which the query already
    sorts by, so insertion order into the ``dict`` is the index order.
    ``NON_UNIQUE`` is 0 for a unique index (MySQL names the column for
    the negative). A functional index reports ``COLUMN_NAME = NULL``;
    such an entry can never be the ``(live_key)`` guard, so it is dropped
    rather than being folded in as a phantom column.
    """
    columns: dict[str, list[str]] = {}
    unique: dict[str, bool] = {}
    for record in records:
        name = record["INDEX_NAME"]
        column = record["COLUMN_NAME"]
        unique[name] = not int(record["NON_UNIQUE"])
        if column is not None:
            columns.setdefault(name, []).append(column)
    return [
        _IndexShape(name=name, unique=is_unique, columns=tuple(columns.get(name, ())))
        for name, is_unique in unique.items()
    ]


def _now_utc_naive() -> datetime:
    """UTC wall-clock instant of the write, naive for a ``DATETIME(6)`` bind.

    MySQL ``DATETIME`` stores no offset and strict mode rejects a literal
    that carries one, so the tz-aware "now" is converted to UTC and then
    stripped. :func:`~openbb_techtrade.snapshot.store._as_created_at`
    re-attaches ``timezone.utc`` on the way out.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _mysql_live_guard_probe_values(
    dataset: str, job_run_id: str, state: SnapshotState
) -> tuple[Any, ...]:
    """Build one complete synthetic row for the rolled-back engine probe."""
    return (
        dataset,
        "same-entity",
        date(2000, 1, 1),
        datetime(2000, 1, 1),
        job_run_id,
        SnapshotStatus.OK.value,
        state.value,
        0,
        "",
        "{}",
        None,
        None,
        None,
        None,
    )


def _probe_mysql_live_guard(conn: Any) -> None:
    """Prove the generated key and unique index, then roll back all rows."""
    dataset = f"{_LIVE_GUARD_PROBE_PREFIX}{uuid4().hex}"
    conn.begin()
    try:
        with conn.cursor() as cur:
            try:
                for job_run_id, state in (
                    ("staged-1", SnapshotState.STAGING),
                    ("staged-2", SnapshotState.STAGING),
                    ("live-1", SnapshotState.LIVE),
                ):
                    cur.execute(
                        _INSERT_LIVE_GUARD_PROBE,
                        _mysql_live_guard_probe_values(dataset, job_run_id, state),
                    )
            except Exception as exc:
                if not _is_integrity_error(exc):
                    raise
                raise _live_guard_refusal(
                    "mysql",
                    "an empirical, rolled-back probe could not store two STAGING "
                    "rows and one LIVE row for the same key",
                ) from exc

            cur.execute(_SELECT_LIVE_GUARD_PROBE, (dataset, "same-entity"))
            expected_live_key = f"{dataset}\x1fsame-entity"
            observed = {row["job_run_id"]: row["live_key"] for row in cur.fetchall()}
            expected = {
                "staged-1": None,
                "staged-2": None,
                "live-1": expected_live_key,
            }
            if observed != expected:
                raise _live_guard_refusal(
                    "mysql",
                    "an empirical, rolled-back probe found that live_key is not "
                    "NULL for STAGING rows and the exact dataset/entity key for "
                    "a LIVE row",
                )

            try:
                cur.execute(
                    _INSERT_LIVE_GUARD_PROBE,
                    _mysql_live_guard_probe_values(
                        dataset, "live-2", SnapshotState.LIVE
                    ),
                )
            except Exception as exc:
                if not _is_integrity_error(exc):
                    raise
            else:
                raise _live_guard_refusal(
                    "mysql",
                    "an empirical, rolled-back probe accepted two LIVE rows for "
                    "the same key",
                )
    finally:
        conn.rollback()


class MysqlSnapshotStore:
    """MySQL-backed EOD snapshot store implementing ``SnapshotStore``.

    ``connection_pool`` is injectable so the contract suite can run
    against a PyMySQL-shaped double without a live server; in production
    it defaults to the shared FMP-cache pool.
    """

    def __init__(self, connection_pool: Any = None) -> None:
        if connection_pool is None:
            # pylint: disable=import-outside-toplevel
            from openbb_fmp_cached.utils.database import (  # noqa: PLC0415
                get_connection_pool,
            )

            connection_pool = get_connection_pool()
        self._pool = connection_pool
        self._ensure_schema()

    # --- lifecycle / connection handling -------------------------------

    def __enter__(self) -> MysqlSnapshotStore:
        """Enter a ``with`` block; the store is already usable on construction."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Release this store's hold on the shared pool (the pool survives)."""
        self.close()

    @contextmanager
    def _borrow(self) -> Iterator[Any]:
        """Borrow a pooled connection.

        ``ConnectionPool.get_connection()`` is itself a
        ``@contextmanager``: it yields the live PyMySQL connection and
        closes it in its own ``finally``. Calling it bare would hand back
        a ``_GeneratorContextManager`` — an object with no ``cursor()``
        and no ``close()`` — so the ``with`` is load-bearing, not
        stylistic.
        """
        with self._pool.get_connection() as conn:
            yield conn

    @contextmanager
    def _read(self) -> Iterator[Any]:
        """Read scope: a bare, autocommitted ``SELECT``.

        Pool sessions are ``autocommit=True``, so a lone ``SELECT`` opens
        no transaction and leaves no read view behind. Nothing to commit,
        nothing to roll back — issuing either here would only be a
        round-trip that ends a transaction that was never started.
        """
        with self._borrow() as conn:
            yield conn

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """Write scope: an explicit transaction on an autocommit session.

        The pool hands out ``autocommit=True`` connections, so without an
        explicit ``begin()`` every statement is its own transaction: a
        multi-statement write is no longer atomic and every
        ``SELECT ... FOR UPDATE`` releases its row lock the instant the
        statement finishes. ``conn.begin()`` issues a plain ``BEGIN``,
        which suspends autocommit until the next ``COMMIT``/``ROLLBACK``;
        it is preferred over toggling ``conn.autocommit(False)`` because
        the pool's own writers document that mid-connection toggle as a
        PyMySQL footgun (see ``openbb_fmp_cached.utils.database``).

        The connection is shared with the FMP cache, so it must go back
        in the state it arrived in — no transaction open. The ``finally``
        therefore rolls back whatever did not commit, including the path
        where ``commit()`` itself raises, and swallows only a *failing
        rollback* (logged), which would otherwise mask the original
        error.

        **Refusals are held back until the borrow has closed.**
        ``ConnectionPool.get_connection`` is not transparent to
        exceptions: it logs ``ERROR MySQL connection error: ...`` for
        anything that unwinds across it. A :class:`_LifecycleRefused` is
        a *policy* signal — "this candidate ranks below LIVE", "the row
        moved, retry" — raised on a perfectly healthy connection, so it
        is caught here, rolled back like any other unwind, and re-raised
        only once the borrow's ``with`` block has exited. Callers see the
        identical exception at the identical place; the pool shared with
        the FMP cache simply stops reporting routine lifecycle outcomes
        as database faults.

        **An ``IntegrityError`` is held back the same way, and for the
        same reason.** A constraint violation is a *statement* outcome on
        a healthy session, not a connection fault: the clearest case is
        ``stage()`` called twice with one ``job_run_id`` for the same
        ``(dataset, entity_key, as_of_session)``, which is a caller bug
        that would otherwise page an operator about the FMP cache's
        database connection. It is held, not handled — the original
        exception is re-raised unchanged to the caller, so ``stage()``
        still fails loudly and ``promote()``'s existing safety net still
        sees the COMMIT-time collision it converts to ``False``.

        Genuine driver errors are *not* intercepted: those really are
        faults and the pool should log them.
        """
        held: BaseException | None = None
        with self._borrow() as conn:
            conn.begin()
            committed = False
            try:
                yield conn
                conn.commit()
                committed = True
            except _LifecycleRefused as refusal:
                held = refusal
            except Exception as exc:  # pylint: disable=broad-except
                if not _is_integrity_error(exc):
                    raise
                held = exc
            finally:
                if not committed:
                    self._restore(conn)
        if held is not None:
            raise held

    @staticmethod
    def _restore(conn: Any) -> None:
        """Best-effort ``ROLLBACK`` so the pooled session is reusable."""
        try:
            conn.rollback()
        except Exception:  # pylint: disable=broad-except
            # Never mask the error that caused the unwind. A connection
            # that cannot roll back is broken; the pool closes it anyway.
            logger.warning("snapshot rollback failed", exc_info=True)

    def _ensure_schema(self) -> None:
        """Create the table if absent, then verify the one that is there.

        ``CREATE TABLE IF NOT EXISTS`` succeeds as a **no-op** against a
        pre-existing table of any shape. That is what made the original
        ``pi_snapshot`` name a silent merge blocker: the account-scoped
        ``portfolio_snapshot_importer`` table of the same name in the
        same database would have absorbed the CREATE, left this store
        constructing cleanly, and failed every later call with "Unknown
        column 'dataset'". The rename fixes today's collision; the shape
        **and version** checks are what make tomorrow's loud — including
        the one #1964 / #1967 will create when they add columns.

        The version half matters in a direction the shape check
        structurally cannot see. A table written by a *newer* build is a
        column superset of what this build expects, so every expected
        column is present and the shape check passes; a table written by
        an *older* build whose columns were re-typed or re-keyed rather
        than removed passes it too. Both are refused here by comparing
        the stamp in the table's ``COMMENT`` against
        :data:`~openbb_techtrade.snapshot.store.SNAPSHOT_SCHEMA_VERSION`.

        An unstamped table of the right shape (version ``0``) is adopted
        and stamped, which is the same adopt-and-stamp SQLite performs
        with ``PRAGMA user_version``. The stamp *replaces* any existing
        comment: the shape check has already established that the table
        is this store's, and a self-describing marker is worth more than
        a hand-written annotation that no code reads.

        Neither check can see the third failure, which is why
        :meth:`_verify_schema` re-reads the single-LIVE guard and
        :func:`_probe_mysql_live_guard` exercises it on the real engine: a
        pre-existing table with all fourteen shared columns but no
        generated ``live_key`` (or no UNIQUE index over it) passes shape
        *and* version and then lets two concurrent promotions install two
        LIVE rows for one key. ``CREATE TABLE IF NOT EXISTS`` no-ops
        against such a table, and because MySQL declares its indexes
        *inside* ``CREATE TABLE``, the no-op silently skips them too.

        Nor can any of them see the fourth, which is why
        :meth:`_verify_schema` also re-reads the key columns' collation.
        The same no-op leaves a pre-existing table's collation alone, and
        an ``_ai_ci`` ``dataset``/``entity_key``/``job_run_id``/
        ``live_key`` keeps every column name, every index and every stamp
        while quietly making the primary key and the single-LIVE key
        case- and accent-blind — a strictly weaker invariant than the one
        SQLite's BINARY comparison enforces for the same calls.

        Finally, the rollback-only empirical probe is safe only on InnoDB.
        :meth:`_verify_schema` therefore requires the table's reported
        ``ENGINE`` before the probe, an adoption stamp, or the ready-cache
        mark. ``MyISAM``, any other engine, ``NULL``, and missing table
        metadata all fail closed.

        The checks run once per pool (see :data:`_SCHEMA_READY`), and the
        refusal is raised *outside* the borrow so a schema fault is not
        logged by the shared pool as ``MySQL connection error``.

        DDL is implicitly committed by MySQL, so it deliberately runs on
        the autocommit session rather than inside ``transaction()``,
        where a rollback would be a lie.
        """
        if _SCHEMA_READY.get(self._pool):
            return
        refusal: SnapshotSchemaMismatch | None = None
        with self._borrow() as conn, conn.cursor() as cur:
            for ddl in _ALL_DDLS:
                cur.execute(ddl)
            try:
                needs_stamp = self._verify_schema(cur)
                _probe_mysql_live_guard(conn)
                if needs_stamp:
                    cur.execute(_STAMP_SCHEMA_COMMENT, (_schema_version_comment(),))
            except SnapshotSchemaMismatch as mismatch:
                refusal = mismatch
        if refusal is not None:
            raise refusal
        _SCHEMA_READY[self._pool] = True

    @staticmethod
    def _verify_schema(cur: Any) -> bool:
        """Check schema metadata and report whether it needs a version stamp.

        Every probe asks the *server* (``information_schema``) rather than
        re-reading this module's own DDL text, so the answer describes
        the table that exists, not the table this build would have
        created.

        The table's storage engine is checked before the caller runs the
        empirical guard probe or acts on the returned ``True``. A
        nontransactional table is never probed, and a structurally plausible
        guard that behaves incorrectly remains unstamped when construction
        refuses it.

        The guard runs before the collation check only so its message
        wins when ``live_key`` is absent entirely — a missing column has
        no collation to report, and "the generated column is missing" is
        the more useful sentence than "live_key -> NULL".
        """
        cur.execute(_SELECT_SCHEMA_COLUMNS, (_SNAPSHOT_TABLE,))
        records = cur.fetchall()
        generation = {
            record["COLUMN_NAME"]: record["GENERATION_EXPRESSION"] or ""
            for record in records
        }
        collations = {
            record["COLUMN_NAME"]: record["COLLATION_NAME"] for record in records
        }
        _check_schema_shape(generation.keys(), backend="mysql")
        cur.execute(_SELECT_SCHEMA_INDEXES, (_SNAPSHOT_TABLE,))
        _check_mysql_live_guard(generation, _index_shapes(cur.fetchall()))
        _check_mysql_collations(collations)
        cur.execute(_SELECT_SCHEMA_COMMENT, (_SNAPSHOT_TABLE,))
        record = cur.fetchone()
        engine = (
            _MISSING_TABLE_METADATA
            if record is None
            else record.get("ENGINE", _MISSING_TABLE_METADATA)
        )
        _check_storage_engine(engine)
        stamped = _parse_schema_version_comment(
            record["TABLE_COMMENT"] if record is not None else None
        )
        _check_schema_version(stamped, backend="mysql")
        # `_check_schema_version` narrowed this to the current version or 0.
        return stamped == 0

    # --- private query helpers -----------------------------------------

    @staticmethod
    def _fetch_row(conn: Any, sql: str, params: tuple) -> SnapshotRow | None:
        # No `dictionary=`/`buffered=` keyword: PyMySQL's signature is
        # `cursor(self, cursor=None)` and the pool already pins
        # `cursorclass=DictCursor`, so a bare cursor yields dict rows.
        with conn.cursor() as cur:
            cur.execute(sql, params)
            record = cur.fetchone()
        return _row_from_mapping(record) if record is not None else None

    @classmethod
    def _get_row(  # pylint: disable=too-many-positional-arguments
        cls,
        conn: Any,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
        *,
        for_update: bool = False,
    ) -> SnapshotRow | None:
        """Fetch the exact row identified by the full primary key."""
        return cls._fetch_row(
            conn,
            _SELECT_BY_PK_FOR_UPDATE if for_update else _SELECT_BY_PK,
            (dataset, entity_key, as_of_session, job_run_id),
        )

    @classmethod
    def _get_live(
        cls, conn: Any, dataset: str, entity_key: str, *, for_update: bool = False
    ) -> SnapshotRow | None:
        """Follow the explicit LIVE pointer — never "newest session wins"."""
        return cls._fetch_row(
            conn,
            _SELECT_LIVE_FOR_UPDATE if for_update else _SELECT_LIVE,
            (dataset, entity_key, SnapshotState.LIVE.value),
        )

    # --- Protocol methods ----------------------------------------------

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
        # a non-dict payload raises without ever taking the connection's
        # write lock -- matching the bounded-field guard just above and
        # the SQLite backend (#2062 review).
        payload_text = _dumps_payload(payload)
        with self.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                _INSERT_STAGED,
                (
                    dataset,
                    entity_key,
                    as_of_session,
                    _now_utc_naive(),
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
        STAGING — a LIVE or SUPERSEDED row is immutable history.

        The gate runs *between* the read and the write, so the row can
        move in that window (a concurrent ``promote()``). The write
        transaction therefore re-reads the row ``FOR UPDATE`` and
        re-applies the STAGING gate before writing, holding the row until
        COMMIT; the UPDATE additionally pins ``state = 'staging'`` as a
        belt-and-braces predicate.

        What it deliberately does *not* do is infer the race from
        ``rowcount``. PyMySQL connects without ``CLIENT.FOUND_ROWS``, so
        an UPDATE reports rows *changed*, not rows *matched*: re-running
        the same gate over the same row legitimately affects **0** rows.
        Reading that as "someone moved the row" would turn every replayed
        job into a phantom race.
        """
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        with self._read() as conn:
            row = self._get_row(conn, dataset, entity_key, as_of_session, job_run_id)
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
            with self.transaction() as conn:
                self._write_verdict(
                    conn, dataset, entity_key, as_of_session, job_run_id, result
                )
        except _ValidationRefused as refused:
            logger.warning("snapshot validation refused: %s", refused.reason)
            return ValidationResult(ok=False, reason=refused.reason)
        return result

    @classmethod
    def _write_verdict(  # pylint: disable=too-many-positional-arguments
        cls,
        conn: Any,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
        result: ValidationResult,
    ) -> None:
        """Re-check STAGING under a row lock, then persist the verdict."""
        current = cls._get_row(
            conn, dataset, entity_key, as_of_session, job_run_id, for_update=True
        )
        # The pre-gate read already established STAGING, so anything else
        # here means the row moved inside the gate's window.
        if _validation_refusal(current) is not None:
            raise _ValidationRefused(_VALIDATION_RACE_REASON)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pi_eod_snapshot SET validated = %s, validation_reason = %s "
                "WHERE dataset = %s AND entity_key = %s AND as_of_session = %s "
                "AND job_run_id = %s AND state = %s",
                (
                    1 if result.ok else 0,
                    result.reason,
                    dataset,
                    entity_key,
                    as_of_session,
                    job_run_id,
                    SnapshotState.STAGING.value,
                ),
            )

    def promote(
        self,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
    ) -> bool:
        """Atomically promote a validated staged row to LIVE.

        Everything runs in one transaction on one pooled connection: the
        candidate and the incumbent LIVE row are read ``FOR UPDATE`` (so
        InnoDB holds exclusive row locks on them for the rest of the
        transaction), then the demotion and the promotion are pinned to
        the exact rows that were read, each with a ``state`` predicate.
        A row that moved anyway yields zero affected rows and a refusal
        instead of a silent clobber; a ``live_key`` collision caused by a
        writer that bypassed this method is reported as ``False`` rather
        than leaking a driver ``IntegrityError`` to the caller.

        Returns ``True`` on success, ``False`` on any refusal (WARNING).
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
        LIVE row read ``FOR UPDATE`` *inside* the transaction must be the
        same row the caller copied its payload from. See
        :func:`~openbb_techtrade.snapshot.store._restamp_live`.
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
            with self.transaction() as conn:
                self._promote_locked(
                    conn,
                    dataset,
                    entity_key,
                    as_of_session,
                    job_run_id,
                    expected_live=expected_live,
                    expectation=expectation,
                )
        except _PromotionRefused as refused:
            logger.warning("snapshot promotion refused: %s", refused.reason)
            return False
        except Exception as exc:  # noqa: BLE001
            # `_promote_locked` already converts a collision on its own
            # statements into a refusal; this stays as the safety net for
            # a constraint that only fires at COMMIT.
            if not _is_integrity_error(exc):
                raise
            logger.warning("snapshot promotion refused: %s", _LIVE_COLLISION_REASON)
            return False
        return True

    @classmethod
    def _promote_locked(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        cls,
        conn: Any,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
        *,
        expected_live: SnapshotRow | None = None,
        expectation: bool = False,
    ) -> None:
        """Locking read + guarded writes; raises :class:`_PromotionRefused`.

        Unlike ``validate()``, ``rowcount`` *is* trustworthy here: both
        writes are state transitions (``staging -> live``,
        ``live -> superseded``), so a matched row is always a changed
        row and PyMySQL's changed-row count cannot be ambiguous.

        A ``live_key`` collision (a writer that bypassed this method
        installed a LIVE row in the window) is translated into the same
        ``_PromotionRefused`` the other gates raise, rather than being
        left to unwind as a driver ``IntegrityError``. It means the same
        thing to the caller — ``promote()`` returns ``False`` — and
        keeping it inside the transaction scope stops a routine refusal
        being logged as a connection fault by the shared pool.

        ``expectation=True`` adds the restamp gate: the locked LIVE row
        must still be the row whose payload the caller copied (#1963 I2).
        """
        candidate = cls._get_row(
            conn, dataset, entity_key, as_of_session, job_run_id, for_update=True
        )
        live = cls._get_live(conn, dataset, entity_key, for_update=True)
        if expectation:
            moved = _restamp_race_refusal(expected_live, live)
            if moved is not None:
                raise _PromotionRefused(moved)
        refusal = _promotion_refusal(candidate, live)
        if refusal is not None:
            raise _PromotionRefused(refusal)
        try:
            cls._apply_promotion(
                conn, dataset, entity_key, as_of_session, job_run_id, live
            )
        except Exception as exc:  # noqa: BLE001
            if not _is_integrity_error(exc):
                raise
            raise _PromotionRefused(_LIVE_COLLISION_REASON) from exc

    @classmethod
    def _apply_promotion(  # pylint: disable=too-many-positional-arguments
        cls,
        conn: Any,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
        live: SnapshotRow | None,
    ) -> None:
        """Demote the incumbent (if any) and install the candidate as LIVE."""
        with conn.cursor() as cur:
            if live is not None:
                cur.execute(
                    "UPDATE pi_eod_snapshot SET state = %s "
                    "WHERE dataset = %s AND entity_key = %s AND as_of_session = %s "
                    "AND job_run_id = %s AND state = %s",
                    (
                        SnapshotState.SUPERSEDED.value,
                        dataset,
                        entity_key,
                        live.as_of_session,
                        live.job_run_id,
                        SnapshotState.LIVE.value,
                    ),
                )
                if cur.rowcount != 1:
                    raise _PromotionRefused(_LIVE_RACE_REASON)
            cur.execute(
                "UPDATE pi_eod_snapshot SET state = %s "
                "WHERE dataset = %s AND entity_key = %s AND as_of_session = %s "
                "AND job_run_id = %s AND state = %s",
                (
                    SnapshotState.LIVE.value,
                    dataset,
                    entity_key,
                    as_of_session,
                    job_run_id,
                    SnapshotState.STAGING.value,
                ),
            )
            if cur.rowcount != 1:
                raise _PromotionRefused(_CANDIDATE_RACE_REASON)

    def get_live(self, dataset: str, entity_key: str) -> SnapshotRow | None:
        """Compute-free single-row read of ``state='live'``; ``None`` if absent."""
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        with self._read() as conn:
            return self._get_live(conn, dataset, entity_key)

    def get_as_of(
        self, dataset: str, entity_key: str, as_of_session: date
    ) -> SnapshotRow | None:
        """Promoted row for a specific session (replay/compare-to-yesterday)."""
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        with self._read() as conn:
            return self._fetch_row(
                conn,
                _SELECT_AS_OF,
                (
                    dataset,
                    entity_key,
                    as_of_session,
                    SnapshotState.STAGING.value,
                ),
            )

    def list_history(
        self, dataset: str, entity_key: str, limit: int = 50
    ) -> list[SnapshotRow]:
        """Newest-first rows for a key, retained for audit/replay/diffing."""
        _check_limit(limit)
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        with self._read() as conn, conn.cursor() as cur:
            cur.execute(_SELECT_HISTORY, (dataset, entity_key, limit))
            records = cur.fetchall()
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

        Delegates to the shared composition so MySQL and SQLite produce
        byte-identical audit trails: a new staged row is validated and
        promoted, and the prior LIVE row is superseded rather than edited.
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

        The default policy (``None``, or ``RetentionPolicy()`` with
        ``keep_sessions=None``) keeps everything and returns ``0``. A
        bounded policy deletes only non-LIVE rows outside the newest
        ``keep_sessions`` distinct sessions per ``(dataset, entity_key)``.
        The ``state != 'live'`` filter is an unconditional safety net,
        independent of whether the LIVE row's session lands inside the
        kept window.

        ``dataset``/``entity_key`` scope the sweep (#1963 review I4) —
        this table lives in the database the FMP cache uses, so an
        unscoped bounded policy both applies one caller's window to every
        other dataset and holds a write transaction for the whole sweep.
        Scoped or not, the shape is one ``SELECT DISTINCT`` plus bounded
        set-based ``DELETE``s of at most :data:`_PRUNE_BATCH` sessions,
        rather than a SELECT+DELETE pair per key.
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
        scope_sql, scope_params = _scope_clause(dataset, entity_key, "%s")
        deleted = 0
        with self.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT dataset, entity_key, as_of_session "
                f"FROM pi_eod_snapshot{scope_sql} "
                "ORDER BY dataset, entity_key, as_of_session DESC",
                scope_params,
            )
            doomed = _doomed_triples(cur.fetchall(), policy.keep_sessions)
            for batch in _batched(doomed, _PRUNE_BATCH):
                deleted += self._delete_batch(cur, batch)
        return deleted

    @staticmethod
    def _delete_batch(cur: Any, batch: Any) -> int:
        """Delete one bounded batch of doomed ``(key, session)`` triples."""
        # The only interpolation is a run of module-owned "(%s, %s, %s)"
        # placeholder tokens; every value is bound via `params`.
        tuples = ", ".join("(%s, %s, %s)" for _ in batch)
        params: list = [SnapshotState.LIVE.value]
        for triple in batch:
            params.extend(triple)
        cur.execute(
            "DELETE FROM pi_eod_snapshot WHERE state != %s "
            f"AND (dataset, entity_key, as_of_session) IN ({tuples})",
            params,
        )
        return int(cur.rowcount)

    def close(self) -> None:
        """Shared pool — nothing to close per-store."""


def _make_mysql_store() -> MysqlSnapshotStore:
    """Backend-selector hook: build a store over the shared fmp_cached pool."""
    return MysqlSnapshotStore()
