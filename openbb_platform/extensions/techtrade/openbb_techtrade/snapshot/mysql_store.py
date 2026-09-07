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
4. **``%s`` bindings and pooled connections.** Placeholders are ``%s``
   (mysql-connector) instead of ``?``; connections are borrowed per
   operation and returned to the shared pool. Writes go through
   :meth:`transaction` (commit on success, rollback on any exception);
   reads go through :meth:`_read`, which rolls back on exit so an
   InnoDB read view is never leaked back into the pool.

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
    _dumps_payload,
    _is_integrity_error,
    _kept_sessions,
    _promotion_refusal,
    _PromotionRefused,
    _restamp_live,
    _row_from_mapping,
    _should_skip,
    _validation_refusal,
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
    validation_reason      VARCHAR(512) NOT NULL DEFAULT '',
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
    against a mysql-connector-shaped double without a live server; in
    production it defaults to the shared FMP-cache pool.
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
    def _acquire(self) -> Iterator[Any]:
        """Borrow a pooled connection and always hand it back."""
        conn = self._pool.get_connection()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _read(self) -> Iterator[Any]:
        """Read scope: end the InnoDB read view before returning the conn."""
        with self._acquire() as conn:
            try:
                yield conn
            finally:
                conn.rollback()

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """Write scope: commit on success, rollback on any exception."""
        with self._acquire() as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _ensure_schema(self) -> None:
        with self.transaction() as conn:
            cur = conn.cursor()
            try:
                for ddl in _ALL_DDLS:
                    cur.execute(ddl)
            finally:
                cur.close()

    # --- private query helpers -----------------------------------------

    @staticmethod
    def _fetch_row(conn: Any, sql: str, params: tuple) -> SnapshotRow | None:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(sql, params)
            record = cur.fetchone()
        finally:
            cur.close()
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
        with self.transaction() as conn:
            cur = conn.cursor()
            try:
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
            finally:
                cur.close()

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

        The gate runs *between* the read and the write, so the UPDATE
        re-asserts ``state = 'staging'`` in its WHERE clause. If a
        concurrent ``promote()`` moved the row in that window, zero rows
        are affected and the verdict is refused rather than forged onto
        a row that is no longer staged.
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
        with self.transaction() as conn:
            cur = conn.cursor()
            try:
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
                changed = cur.rowcount
            finally:
                cur.close()
        if changed != 1:
            logger.warning("snapshot validation refused: %s", _VALIDATION_RACE_REASON)
            return ValidationResult(ok=False, reason=_VALIDATION_RACE_REASON)
        return result

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
        """Locking read + guarded writes; raises :class:`_PromotionRefused`."""
        candidate = cls._get_row(
            conn, dataset, entity_key, as_of_session, job_run_id, for_update=True
        )
        live = cls._get_live(conn, dataset, entity_key, for_update=True)
        refusal = _promotion_refusal(candidate, live)
        if refusal is not None:
            raise _PromotionRefused(refusal)
        cur = conn.cursor()
        try:
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
        finally:
            cur.close()

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
        with self._read() as conn:
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute(_SELECT_HISTORY, (dataset, entity_key, limit))
                records = cur.fetchall()
            finally:
                cur.close()
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
        with self.transaction() as conn:
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute("SELECT DISTINCT dataset, entity_key FROM pi_snapshot", ())
                keys = cur.fetchall()
                for key in keys:
                    deleted += self._prune_key(
                        cur, key["dataset"], key["entity_key"], keep_sessions
                    )
            finally:
                cur.close()
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
