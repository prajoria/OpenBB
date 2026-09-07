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
   that merely contains the delimiter.
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
   :meth:`validate`, which cannot use it to detect a race.

Read path is compute-free: every read method only ever issues a
``SELECT`` against ``pi_snapshot``; none of them calls a provider or a
compute/scan function.
"""

# ruff: noqa: S608
# S608 (hardcoded SQL): the only f-string interpolation below builds a
# retention `NOT IN (...)` fragment out of module-owned literals and "%s"
# placeholder tokens. Every user value is bound as a parameter. Ruff
# cannot prove that, so it is suppressed at file scope.

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any

from openbb_techtrade.snapshot.store import (
    _CANDIDATE_RACE_REASON,
    _LIVE_COLLISION_REASON,
    _LIVE_RACE_REASON,
    _VALIDATION_RACE_REASON,
    RetentionPolicy,
    SnapshotRow,
    SnapshotState,
    SnapshotStatus,
    ValidationResult,
    _check_field_lengths,
    _dumps_payload,
    _is_integrity_error,
    _kept_sessions,
    _LifecycleRefused,
    _promotion_refusal,
    _PromotionRefused,
    _restamp_live,
    _row_from_mapping,
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

_PI_SNAPSHOT_DDL = """
CREATE TABLE IF NOT EXISTS pi_snapshot (
    dataset                VARCHAR(128) NOT NULL,
    entity_key             VARCHAR(191) NOT NULL,
    as_of_session          DATE NOT NULL,
    created_at             DATETIME(6) NOT NULL,
    job_run_id             VARCHAR(128) NOT NULL,
    status                 VARCHAR(16) NOT NULL,
    state                  VARCHAR(16) NOT NULL,
    validated              TINYINT(1) NOT NULL DEFAULT 0,
    validation_reason      TEXT NOT NULL,
    payload_json           LONGTEXT NOT NULL,
    input_hash             VARCHAR(128),
    row_count              INT,
    engine_version         VARCHAR(64),
    payload_schema_version VARCHAR(64),
    live_key               VARCHAR(512)
        GENERATED ALWAYS AS (
            IF(state = 'live',
               CONCAT(dataset, CHAR(31 USING utf8mb4), entity_key),
               NULL)
        ) STORED,
    PRIMARY KEY (dataset, entity_key, as_of_session, job_run_id),
    UNIQUE KEY ux_pi_snapshot_live (live_key),
    INDEX ix_pi_snapshot_live (dataset, entity_key, state),
    INDEX ix_pi_snapshot_latest (dataset, entity_key, as_of_session, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""
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

_ALL_DDLS = (_PI_SNAPSHOT_DDL,)

_COLUMNS = (
    "dataset, entity_key, as_of_session, created_at, job_run_id, status, "
    "state, validated, validation_reason, payload_json, input_hash, "
    "row_count, engine_version, payload_schema_version"
)

_SELECT_BY_PK = (
    f"SELECT {_COLUMNS} FROM pi_snapshot "
    "WHERE dataset = %s AND entity_key = %s AND as_of_session = %s "
    "AND job_run_id = %s"
)

_SELECT_LIVE = (
    f"SELECT {_COLUMNS} FROM pi_snapshot "
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
    f"SELECT {_COLUMNS} FROM pi_snapshot "
    "WHERE dataset = %s AND entity_key = %s AND as_of_session = %s "
    "AND state != %s ORDER BY created_at DESC LIMIT 1"
)

_SELECT_HISTORY = (
    f"SELECT {_COLUMNS} FROM pi_snapshot "
    "WHERE dataset = %s AND entity_key = %s "
    "ORDER BY as_of_session DESC, created_at DESC LIMIT %s"
)

_INSERT_STAGED = (
    "INSERT INTO pi_snapshot ("
    "dataset, entity_key, as_of_session, created_at, job_run_id, "
    "status, state, validated, validation_reason, payload_json, "
    "input_hash, row_count, engine_version, payload_schema_version"
    ") VALUES (%s, %s, %s, %s, %s, %s, %s, 0, '', %s, %s, %s, %s, %s)"
)


def _now_utc_naive() -> datetime:
    """UTC wall-clock instant of the write, naive for a ``DATETIME(6)`` bind.

    MySQL ``DATETIME`` stores no offset and strict mode rejects a literal
    that carries one, so the tz-aware "now" is converted to UTC and then
    stripped. :func:`~openbb_techtrade.snapshot.store._as_created_at`
    re-attaches ``timezone.utc`` on the way out.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
        as database faults. Genuine driver errors are *not* intercepted:
        those really are faults and the pool should log them.
        """
        refused: _LifecycleRefused | None = None
        with self._borrow() as conn:
            conn.begin()
            committed = False
            try:
                yield conn
                conn.commit()
                committed = True
            except _LifecycleRefused as refusal:
                refused = refusal
            finally:
                if not committed:
                    self._restore(conn)
        if refused is not None:
            raise refused

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
        # DDL is implicitly committed by MySQL, so it deliberately runs on
        # the autocommit session rather than inside `transaction()`, where
        # a rollback would be a lie.
        with self._borrow() as conn, conn.cursor() as cur:
            for ddl in _ALL_DDLS:
                cur.execute(ddl)

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
                "UPDATE pi_snapshot SET validated = %s, validation_reason = %s "
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
        dataset = canonical_key(dataset)
        entity_key = canonical_key(entity_key)
        try:
            with self.transaction() as conn:
                self._promote_locked(
                    conn, dataset, entity_key, as_of_session, job_run_id
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
    def _promote_locked(  # pylint: disable=too-many-positional-arguments
        cls,
        conn: Any,
        dataset: str,
        entity_key: str,
        as_of_session: date,
        job_run_id: str,
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
        """
        candidate = cls._get_row(
            conn, dataset, entity_key, as_of_session, job_run_id, for_update=True
        )
        live = cls._get_live(conn, dataset, entity_key, for_update=True)
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
                    "UPDATE pi_snapshot SET state = %s "
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
                "UPDATE pi_snapshot SET state = %s "
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

    def prune(self, policy: RetentionPolicy | None = None) -> int:
        """Apply retention; return the number of rows removed.

        The default policy (``None``, or ``RetentionPolicy()`` with
        ``keep_sessions=None``) keeps everything and returns ``0``. A
        bounded policy deletes only non-LIVE rows outside the newest
        ``keep_sessions`` distinct sessions per ``(dataset, entity_key)``.
        The ``state != 'live'`` filter is an unconditional safety net,
        independent of whether the LIVE row's session lands inside the
        kept window.
        """
        if policy is None or policy.keep_sessions is None:
            return 0
        keep_sessions = policy.keep_sessions
        deleted = 0
        with self.transaction() as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT dataset, entity_key FROM pi_snapshot", ())
            keys = cur.fetchall()
            for key in keys:
                deleted += self._prune_key(
                    cur, key["dataset"], key["entity_key"], keep_sessions
                )
        return deleted

    @staticmethod
    def _prune_key(cur: Any, dataset: str, entity_key: str, keep_sessions: int) -> int:
        """Delete this key's non-LIVE rows outside the kept-session window."""
        cur.execute(
            "SELECT DISTINCT as_of_session FROM pi_snapshot "
            "WHERE dataset = %s AND entity_key = %s "
            "ORDER BY as_of_session DESC",
            (dataset, entity_key),
        )
        sessions = [record["as_of_session"] for record in cur.fetchall()]
        keep = _kept_sessions(sessions, keep_sessions)
        if keep is None:
            return 0
        # `condition` is built only from a fixed literal ("1 = 1") or a
        # placeholders string of "%s" — no external input reaches the SQL
        # text itself, every value is bound via `params`.
        if keep:
            placeholders = ", ".join("%s" for _ in keep)
            condition = f"as_of_session NOT IN ({placeholders})"
            params: tuple = (dataset, entity_key, SnapshotState.LIVE.value, *keep)
        else:
            condition = "1 = 1"
            params = (dataset, entity_key, SnapshotState.LIVE.value)
        cur.execute(
            "DELETE FROM pi_snapshot WHERE dataset = %s AND entity_key = %s "
            f"AND state != %s AND {condition}",
            params,
        )
        return cur.rowcount

    def close(self) -> None:
        """Shared pool — nothing to close per-store."""


def _make_mysql_store() -> MysqlSnapshotStore:
    """Backend-selector hook: build a store over the shared fmp_cached pool."""
    return MysqlSnapshotStore()
