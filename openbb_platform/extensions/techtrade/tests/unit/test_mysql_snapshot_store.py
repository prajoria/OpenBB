"""Tests for the #1963 MySQL snapshot backend (Task 4).

Every behavioral scenario in ``test_snapshot_store.py`` (Task 2-3) is
mirrored here against :class:`MysqlSnapshotStore`, plus MySQL-specific
guards for the native ``DATE``/``DATETIME(6)`` columns, the generated
nullable ``live_key`` unique constraint, ``%s`` parameter binding, and
commit/rollback discipline.

The test double
---------------
The production pool is
:class:`openbb_fmp_cached.utils.database.ConnectionPool`, which is
**PyMySQL**, not ``mysql-connector``. Its contract, read off the source:

* ``get_connection()`` is a ``@contextmanager`` — it yields a connection
  and closes it in a ``finally``. It does **not** return a connection,
  so ``conn = pool.get_connection()`` hands back a
  ``_GeneratorContextManager`` that has no ``.cursor()``/``.close()``.
* the connection is built with ``cursorclass=pymysql.cursors.DictCursor``
  and ``autocommit=True``. ``conn.cursor()`` therefore takes **no**
  ``dictionary=``/``buffered=`` keywords (PyMySQL's signature is
  ``cursor(self, cursor=None)``) and already yields ``dict`` rows.
* because the session is autocommit, a multi-statement write only becomes
  atomic — and ``SELECT ... FOR UPDATE`` only holds a lock — inside an
  explicit ``conn.begin()`` ... ``commit()``/``rollback()`` block.
* PyMySQL connects with ``client_flag=0`` (no ``CLIENT.FOUND_ROWS``), so
  ``cursor.rowcount`` after an ``UPDATE`` counts **changed** rows, not
  matched rows. Re-writing a row's existing values legitimately reports
  0 affected rows.

``_FakePool``/``_RealisticPool`` implement exactly that contract over an
on-disk SQLite database. They are deliberately *stricter* than the real
driver in four places so dialect leakage cannot pass silently:

1. ``execute`` raises when ``sql.count("%s") != len(params)`` — the real
   driver raises ``ProgrammingError`` here too.
2. Binding a **tz-aware** ``datetime`` raises, mirroring MySQL strict
   mode rejecting an offset in a ``DATETIME`` literal. The backend must
   therefore bind naive UTC and re-attach ``timezone.utc`` on read.
3. Binding a **string** that looks like an ISO date/datetime raises.
   Real MySQL would accept it; the double refuses so that a copy-pasted
   SQLite-style ``.isoformat()`` workaround fails loudly instead of
   silently round-tripping through a ``DATE`` column.
4. ``cursor(cursor=...)`` with any argument raises: the pool pins
   ``DictCursor``, so the backend must ask for a bare cursor.

Column types for the read-side conversion are parsed out of the module's
own ``_PI_SNAPSHOT_DDL``, so a ``DATE``/``DATETIME(6)`` column really is
handed back as ``datetime.date``/``datetime.datetime`` exactly like the
driver does.

Transaction fidelity, and its one deliberate simplification: SQLite has
no row locks, so a faithful ``FOR UPDATE`` is impossible. The double
therefore holds *no* read locks — it opens SQLite's write transaction
lazily, at the explicit transaction's first **write** — which keeps the
read -> write window observable, which is the whole point of the race
guards. That a lock was *requested* is asserted on the recorded SQL
text instead (``test_promote_locks_the_candidate_and_live_rows_on_one_connection``).
Statements executed without ``begin()`` are autocommitted and a later
``rollback()`` cannot undo them — exactly like the real autocommit
session, which is what makes the atomicity tests discriminating.

R7 note: every load-bearing assertion below was reverse-verified by
mutating the production code it guards (see the task report).
"""

# ruff: noqa: D101, D102, D103, D105, SLF001, S608

from __future__ import annotations

import ast
import inspect
import itertools
import logging
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from openbb_techtrade.snapshot import mysql_store as mysql_store_module
from openbb_techtrade.snapshot.mysql_store import (
    _PI_SNAPSHOT_DDL,
    MysqlSnapshotStore,
    _make_mysql_store,
)
from openbb_techtrade.snapshot.store import (
    RetentionPolicy,
    SnapshotRow,
    SnapshotState,
    SnapshotStatus,
    SnapshotStore,
    SqliteSnapshotStore,
    ValidationResult,
)

# ---------------------------------------------------------------------------
# MySQL DDL introspection (drives the double's type conversion)
# ---------------------------------------------------------------------------

_NON_COLUMN_TOKENS = frozenset(
    {"PRIMARY", "UNIQUE", "INDEX", "KEY", "CONSTRAINT", "FOREIGN", "GENERATED"}
)


def _column_types(ddl: str) -> dict[str, str]:
    """Map ``column -> base SQL type`` from a ``CREATE TABLE`` body."""
    types: dict[str, str] = {}
    for line in ddl.splitlines():
        match = re.match(r"\s+(\w+)\s+([A-Za-z]+)", line)
        if match is None:
            continue
        name, sql_type = match.group(1), match.group(2)
        if name.upper() in _NON_COLUMN_TOKENS:
            continue
        types.setdefault(name, sql_type.upper())
    return types


_COLUMN_TYPES = _column_types(_PI_SNAPSHOT_DDL)


def _ddl_to_sqlite(ddl: str) -> tuple[str, list[str]]:
    """Translate the MySQL ``CREATE TABLE`` into an equivalent SQLite one.

    Semantics are preserved, not erased: the generated ``live_key``
    column and its unique constraint survive the translation (SQLite
    3.31+ supports ``GENERATED ALWAYS AS ... STORED``), so the
    single-LIVE-row invariant is genuinely enforced by the double.
    """
    body = ddl.strip()
    body = re.sub(r"\)\s*ENGINE=\w+\s+DEFAULT\s+CHARSET=\w+\s*$", ")", body)
    indexes: list[str] = []

    def _hoist_index(match: re.Match[str]) -> str:
        indexes.append(
            f"CREATE INDEX IF NOT EXISTS {match.group(1)} "
            f"ON pi_snapshot ({match.group(2)})"
        )
        return ""

    body = re.sub(r"\n\s*INDEX (\w+) \(([^)]*)\),?", _hoist_index, body)
    body = re.sub(r"UNIQUE KEY \w+ \(([^)]*)\)", r"UNIQUE (\1)", body)
    body = body.replace("IF(state", "IIF(state")  # codespell:ignore
    body = body.replace("CHAR(31 USING utf8mb4)", "char(31)")
    body = body.replace("CONCAT(", "concat(")
    body = re.sub(r",(\s*)\)\s*$", r"\1)", body)
    return body, indexes


# ---------------------------------------------------------------------------
# PyMySQL-shaped test double
# ---------------------------------------------------------------------------


class _FakeMysqlError(Exception):
    """Stand-in for ``pymysql.err.Error``."""


class _FakeProgrammingError(_FakeMysqlError):
    """Stand-in for ``pymysql.err.ProgrammingError``."""


class _FakeIntegrityError(_FakeMysqlError):
    """Stand-in for ``pymysql.err.IntegrityError``."""


_ISO_TEMPORAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]|$)")


def _adapt(value: Any) -> Any:
    """Emulate the driver's Python -> MySQL literal conversion."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            raise _FakeMysqlError(
                "Incorrect datetime value: a tz-aware datetime cannot be "
                "bound to a DATETIME column"
            )
        return value.isoformat(sep=" ", timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and _ISO_TEMPORAL_RE.match(value):
        raise _FakeMysqlError(
            "Incorrect temporal value: bind a datetime.date/datetime, not "
            f"ISO text ({value!r})"
        )
    return value


def _convert(name: str, value: Any) -> Any:
    """Emulate the driver's MySQL -> Python conversion, driven by the DDL."""
    if value is None:
        return None
    sql_type = _COLUMN_TYPES.get(name)
    if sql_type == "DATE":
        return date.fromisoformat(value)
    if sql_type == "DATETIME":
        return datetime.fromisoformat(value)
    return value


_FOR_UPDATE_RE = re.compile(r"\s+FOR\s+UPDATE\s*$", re.I)
_WRITE_RE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.I)
_UPDATE_RE = re.compile(
    r"^\s*UPDATE\s+(?P<table>\w+)\s+SET\s+(?P<sets>.+?)\s+WHERE\s+(?P<where>.+)$",
    re.I | re.S,
)
_ASSIGNMENT_RE = re.compile(r"^\s*(\w+)\s*=\s*%s\s*$")


def _to_sqlite(sql: str) -> str:
    """Rewrite a MySQL statement for the SQLite engine behind the double.

    ``SELECT ... FOR UPDATE`` is a real InnoDB row lock; SQLite has no
    equivalent, so the clause is stripped for execution. Whether it was
    *requested* is still recorded verbatim in ``pool.statements``, which
    is what the locking tests assert on.
    """
    return _FOR_UPDATE_RE.sub("", sql).replace("%s", "?")


class _FakeCursor:
    """PyMySQL ``DictCursor`` shim: dict rows, changed-row ``rowcount``."""

    def __init__(self, conn: _FakeConnection) -> None:
        self._conn = conn
        self._cursor = conn.raw.cursor()
        self._executed: tuple[str, tuple] | None = None
        self._changed: int | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def rowcount(self) -> int:
        """Rows *changed*, as PyMySQL reports without ``CLIENT.FOUND_ROWS``."""
        return self._cursor.rowcount if self._changed is None else self._changed

    def execute(self, sql: str, params: Any = None) -> None:
        if sql.lstrip().upper().startswith("CREATE TABLE"):
            table_sql, indexes = _ddl_to_sqlite(sql)
            self._cursor.execute(table_sql)
            for index_sql in indexes:
                self._cursor.execute(index_sql)
            return
        bound = tuple(params or ())
        if sql.count("%s") != len(bound):
            raise _FakeProgrammingError(
                f"Not all parameters were used in the SQL statement: "
                f"{sql.count('%s')} placeholders vs {len(bound)} params"
            )
        self._conn.record(sql, bound)
        if _WRITE_RE.match(sql):
            # An explicit transaction only takes SQLite's write lock here,
            # at its first write — see the module docstring.
            self._conn.begin_write_if_needed()
        self._conn.maybe_fail(sql, bound)
        self._changed = self._count_changed_rows(sql, bound)
        try:
            self._cursor.execute(
                _to_sqlite(sql), tuple(_adapt(value) for value in bound)
            )
        except sqlite3.IntegrityError as exc:
            raise _FakeIntegrityError(str(exc)) from exc
        self._executed = (sql, bound)

    def _count_changed_rows(self, sql: str, bound: tuple) -> int | None:
        """Pre-compute MySQL's *changed*-row count for an ``UPDATE``.

        SQLite's ``rowcount`` counts every row the ``UPDATE`` matched,
        even when the new values equal the old ones; PyMySQL (no
        ``CLIENT.FOUND_ROWS``) reports only the rows whose values really
        changed. Emulating the driver here is what makes an *idempotent*
        write distinguishable from a lost race.
        """
        match = _UPDATE_RE.match(sql)
        if match is None:
            return None
        assignments = match.group("sets").split(",")
        columns = []
        for assignment in assignments:
            parsed = _ASSIGNMENT_RE.match(assignment)
            if parsed is None:  # pragma: no cover - keeps the double honest
                raise _FakeProgrammingError(
                    f"the double only models `col = %s` assignments: " f"{assignment!r}"
                )
            columns.append(parsed.group(1))
        set_params = bound[: len(columns)]
        where_params = bound[len(columns) :]
        unchanged = " AND ".join(f"{column} IS ?" for column in columns)
        # Not recorded in `pool.statements`: this is the double emulating
        # the driver, not the backend issuing SQL.
        row = self._cursor.execute(
            f"SELECT COUNT(*) FROM {match.group('table')} "
            f"WHERE ({_to_sqlite(match.group('where'))}) AND NOT ({unchanged})",
            tuple(_adapt(value) for value in (*where_params, *set_params)),
        ).fetchone()
        return int(row[0])

    def _shape(self, row: Any) -> Any:
        """Return dict rows, because the pool pins ``cursorclass=DictCursor``."""
        if row is None:
            return None
        names = [column[0] for column in self._cursor.description]
        return {name: _convert(name, value) for name, value in zip(names, row)}

    def fetchone(self) -> Any:
        return self._shape(self._cursor.fetchone())

    def fetchall(self) -> list[Any]:
        return [self._shape(row) for row in self._cursor.fetchall()]

    def close(self) -> None:
        self._cursor.close()
        # The interleaving hook runs here, not at execute() time: a
        # half-stepped SQLite SELECT still holds a shared lock, which
        # would make the *other* actor fail to commit instead of racing.
        # Closing first mirrors the real driver, where a completed
        # statement no longer blocks another session's write.
        executed, self._executed = self._executed, None
        if executed is not None:
            self._conn.fire(*executed)


class _FakeConnection:
    """PyMySQL ``Connection`` shim: autocommit until an explicit ``begin()``."""

    def __init__(
        self, book: _BasePool, raw: sqlite3.Connection, conn_id: int, *, owns_raw: bool
    ) -> None:
        self._book = book
        self._owns_raw = owns_raw
        self.raw = raw
        self.conn_id = conn_id
        self.in_txn = False
        self._write_txn_open = False

    def cursor(self, cursor: Any = None) -> _FakeCursor:
        """PyMySQL's signature. The pool already pins ``DictCursor``."""
        if cursor is not None:
            raise _FakeProgrammingError(
                "the pool pins cursorclass=DictCursor; ask for a bare cursor"
            )
        self._book.cursor_calls += 1
        return _FakeCursor(self)

    def record(self, sql: str, params: tuple) -> None:
        self._book.record(self.conn_id, sql, params)

    def fire(self, sql: str, params: tuple) -> None:
        self._book.fire(sql, params)

    def maybe_fail(self, sql: str, params: tuple) -> None:
        """Simulate a mid-transaction driver failure (see ``fail_on``)."""
        predicate = self._book.fail_on
        if predicate is not None and predicate(sql, params):
            self._book.fail_on = None
            raise _FakeMysqlError(f"simulated driver failure on {sql!r}")

    def begin(self) -> None:
        """``conn.begin()`` — the only way to group writes under autocommit."""
        if self.in_txn:
            raise _FakeProgrammingError("a transaction is already open")
        self.in_txn = True
        self._book.begins += 1

    def begin_write_if_needed(self) -> None:
        if self.in_txn and not self._write_txn_open:
            self.raw.execute("BEGIN IMMEDIATE")
            self._write_txn_open = True

    def commit(self) -> None:
        self._book.commits += 1
        self._end_txn("COMMIT")

    def rollback(self) -> None:
        self._book.rollbacks += 1
        self._end_txn("ROLLBACK")

    def _end_txn(self, verb: str) -> None:
        if self._write_txn_open:
            self.raw.execute(verb)
            self._write_txn_open = False
        self.in_txn = False

    def close(self) -> None:
        # Pooled connections are returned, not torn down.
        self._book.returned += 1
        if self.in_txn:
            self._book.closed_with_open_txn += 1
            self._end_txn("ROLLBACK")
        if self._owns_raw:
            self.raw.close()


class _BasePool:
    """Bookkeeping shared by both pool doubles (and the seam-test stub)."""

    def __init__(self) -> None:
        self.begins = 0
        self.commits = 0
        self.rollbacks = 0
        self.handed_out = 0
        self.returned = 0
        self.cursor_calls = 0
        self.closed_with_open_txn = 0
        self.statements: list[tuple[str, tuple]] = []
        self.calls: list[tuple[int, str, tuple]] = []
        self.after_execute: Any = None
        self.fail_on: Any = None
        self._ids = itertools.count(1)
        self._in_hook = False

    def record(self, conn_id: int, sql: str, params: tuple) -> None:
        self.statements.append((sql, params))
        self.calls.append((conn_id, sql, params))

    def fire(self, sql: str, params: tuple) -> None:
        """Run the interleaving hook, if any, after a statement executed.

        Re-entrancy is suppressed so a hook that itself drives the store
        (the whole point — it plays the *other* concurrent writer) cannot
        recursively re-trigger itself.
        """
        if self.after_execute is None or self._in_hook:
            return
        self._in_hook = True
        try:
            self.after_execute(sql, params)
        finally:
            self._in_hook = False


class _FakePool(_BasePool):
    """Single-connection pool: fast, and enough for single-actor contracts."""

    def __init__(self, path: Path | str) -> None:
        super().__init__()
        self.raw = sqlite3.connect(str(path), isolation_level=None)

    @contextmanager
    def get_connection(self) -> Iterator[_FakeConnection]:
        """``ConnectionPool.get_connection`` is a context manager, not a getter."""
        self.handed_out += 1
        conn = _FakeConnection(self, self.raw, next(self._ids), owns_raw=False)
        try:
            yield conn
        finally:
            conn.close()


class _RealisticPool(_BasePool):
    """Pool whose connections are genuinely independent, like the real driver.

    ``ConnectionPool.get_connection()`` opens a *fresh* PyMySQL session
    with its own transaction; the single-connection :class:`_FakePool`
    cannot express that, so it can never exhibit a read-then-write race.
    Here each borrow opens its own SQLite connection to the same file, so
    one actor's commit becomes visible to another actor between its read
    and its write — exactly the window ``promote()``/``validate()`` must
    defend.
    """

    def __init__(self, path: Path | str) -> None:
        super().__init__()
        self.path = str(path)

    @contextmanager
    def get_connection(self) -> Iterator[_FakeConnection]:
        self.handed_out += 1
        raw = sqlite3.connect(self.path, timeout=1.0, isolation_level=None)
        conn = _FakeConnection(self, raw, next(self._ids), owns_raw=True)
        try:
            yield conn
        finally:
            conn.close()

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Out-of-band read for assertions (its own short-lived connection)."""
        conn = sqlite3.connect(self.path, timeout=1.0)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def live_job_run_ids(self) -> list[str]:
        return [
            row[0]
            for row in self.query(
                "SELECT job_run_id FROM pi_snapshot WHERE state = ? "
                "ORDER BY job_run_id",
                (SnapshotState.LIVE.value,),
            )
        ]


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def pool(tmp_path: Path) -> _FakePool:
    return _FakePool(tmp_path / "snapshot_mysql_test.db")


@pytest.fixture
def store(pool: _FakePool) -> MysqlSnapshotStore:
    return MysqlSnapshotStore(connection_pool=pool)


@pytest.fixture
def real_pool(tmp_path: Path) -> _RealisticPool:
    return _RealisticPool(tmp_path / "snapshot_mysql_race.db")


@pytest.fixture
def real_store(real_pool: _RealisticPool) -> MysqlSnapshotStore:
    return MysqlSnapshotStore(connection_pool=real_pool)


_job_run_ids = itertools.count(1)


def _stage(  # pylint: disable=too-many-arguments
    target: Any,
    *,
    payload: dict,
    dataset: str = "techtrade.movers",
    entity_key: str = "sector=technology",
    as_of_session: date = date(2026, 9, 4),
    job_run_id: str | None = None,
    status: SnapshotStatus = SnapshotStatus.OK,
    input_hash: str | None = None,
) -> tuple[str, str, date, str]:
    job_run_id = job_run_id or f"run-{next(_job_run_ids)}"
    target.stage(
        dataset,
        entity_key,
        as_of_session,
        job_run_id,
        payload,
        status=status,
        input_hash=input_hash,
    )
    return (dataset, entity_key, as_of_session, job_run_id)


def _direct_insert(pool: _FakePool, *, job_run_id: str, state: str) -> None:
    """Bypass the store to test the DB-level constraint directly."""
    with pool.get_connection() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO pi_snapshot ("
                    "dataset, entity_key, as_of_session, created_at, job_run_id, "
                    "status, state, validated, validation_reason, payload_json, "
                    "input_hash, row_count, engine_version, payload_schema_version"
                    ") VALUES (%s, %s, %s, %s, %s, %s, %s, 1, '', %s, NULL, NULL, "
                    "NULL, NULL)",
                    (
                        "techtrade.movers",
                        "sector=technology",
                        date(2026, 9, 9),
                        datetime(2026, 9, 9, 12, 0, 0),
                        job_run_id,
                        SnapshotStatus.OK.value,
                        state,
                        '{"rows": [{"symbol": "GOOG"}]}',
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# ---------------------------------------------------------------------------
# Schema shape
# ---------------------------------------------------------------------------


def test_ddl_uses_native_date_and_datetime_columns() -> None:
    """Invariant: the trading day and the write instant keep native types.

    A ``TEXT``/``VARCHAR`` workaround (which SQLite is forced into) would
    lose index-friendly temporal ordering and server-side date math.
    """
    assert re.search(r"\bas_of_session\s+DATE NOT NULL", _PI_SNAPSHOT_DDL)
    assert re.search(r"\bcreated_at\s+DATETIME\(6\) NOT NULL", _PI_SNAPSHOT_DDL)
    assert _COLUMN_TYPES["as_of_session"] == "DATE"
    assert _COLUMN_TYPES["created_at"] == "DATETIME"


def test_ddl_declares_generated_nullable_live_key_and_unique_key() -> None:
    """Invariant: single-LIVE-row is enforced by a generated nullable key.

    ``live_key`` is NULL for every non-LIVE row (MySQL unique indexes
    ignore NULLs), so unlimited STAGING/SUPERSEDED history coexists with
    at most one LIVE row per ``(dataset, entity_key)``.
    """
    assert re.search(r"\blive_key\s+VARCHAR\(512\)", _PI_SNAPSHOT_DDL)
    assert "GENERATED ALWAYS AS" in _PI_SNAPSHOT_DDL
    assert "IF(state = 'live'" in _PI_SNAPSHOT_DDL
    assert "STORED" in _PI_SNAPSHOT_DDL
    assert "UNIQUE KEY ux_pi_snapshot_live (live_key)" in _PI_SNAPSHOT_DDL
    # The generated expression must key on BOTH parts of the identity, or
    # two datasets sharing an entity_key would collide. The CHAR(31) unit
    # separator keeps the boundary unforgeable.
    assert re.search(
        r"CONCAT\(\s*dataset,\s*CHAR\(31[^)]*\),\s*entity_key\s*\)",
        _PI_SNAPSHOT_DDL,
        re.S,
    )


def test_generated_live_key_blocks_a_second_live_row(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)

    with pytest.raises(_FakeIntegrityError):
        _direct_insert(pool, job_run_id="run-direct-live", state="live")


def test_generated_live_key_is_null_for_non_live_rows(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    """Discriminates the nullable half of the generated-column design.

    Two STAGING rows for the same key must coexist: if ``live_key`` were
    generated unconditionally (no ``IF(state='live', ...)`` guard) the
    unique key would reject the second staged run.
    """
    _stage(
        store, payload={"rows": [{"symbol": "AAPL"}]}, as_of_session=date(2026, 9, 4)
    )
    _stage(
        store, payload={"rows": [{"symbol": "MSFT"}]}, as_of_session=date(2026, 9, 5)
    )
    _direct_insert(pool, job_run_id="run-direct-staging", state="staging")

    rows = pool.raw.execute(
        "SELECT state, live_key FROM pi_snapshot ORDER BY job_run_id"
    ).fetchall()
    assert len(rows) == 3
    assert all(live_key is None for _, live_key in rows)


# ---------------------------------------------------------------------------
# Protocol parity
# ---------------------------------------------------------------------------


_PROTOCOL_METHODS = sorted(
    name
    for name, member in vars(SnapshotStore).items()
    if not name.startswith("_") and callable(member)
)


def test_protocol_surface_is_the_full_contract() -> None:
    assert _PROTOCOL_METHODS == [
        "close",
        "get_as_of",
        "get_live",
        "list_history",
        "promote",
        "prune",
        "restamp_live",
        "should_skip",
        "stage",
        "validate",
    ]


@pytest.mark.parametrize("name", _PROTOCOL_METHODS)
def test_mysql_store_signature_matches_protocol_and_sqlite(name: str) -> None:
    """Invariant: callers can swap backends without touching a call site."""
    expected = inspect.signature(getattr(SnapshotStore, name))
    assert inspect.signature(getattr(MysqlSnapshotStore, name)) == expected
    assert inspect.signature(getattr(SqliteSnapshotStore, name)) == expected


def test_snapshot_package_exports_both_backends() -> None:
    from openbb_techtrade import snapshot  # noqa: PLC0415

    assert snapshot.MysqlSnapshotStore is MysqlSnapshotStore
    assert snapshot.SqliteSnapshotStore is SqliteSnapshotStore
    assert "MysqlSnapshotStore" in snapshot.__all__
    assert "SqliteSnapshotStore" in snapshot.__all__


def test_make_mysql_store_uses_the_shared_fmp_cached_pool(
    monkeypatch: pytest.MonkeyPatch, pool: _FakePool
) -> None:
    """Invariant: production wiring goes through the shared fmp_cached pool."""
    from openbb_fmp_cached.utils import database  # noqa: PLC0415

    calls: list[int] = []

    def _fake_pool() -> _FakePool:
        calls.append(1)
        return pool

    monkeypatch.setattr(database, "get_connection_pool", _fake_pool)
    built = _make_mysql_store()
    assert isinstance(built, MysqlSnapshotStore)
    assert calls == [1]
    assert built.get_live("techtrade.movers", "sector=technology") is None


# ---------------------------------------------------------------------------
# Lifecycle parity with the SQLite backend
# ---------------------------------------------------------------------------


def test_fresh_store_has_no_live_snapshot(store: MysqlSnapshotStore) -> None:
    assert store.get_live("techtrade.movers", "sector=technology") is None
    store.close()


def test_clean_stage_validate_promote_is_atomic(store: MysqlSnapshotStore) -> None:
    staged = _stage(
        store, status=SnapshotStatus.OK, payload={"rows": [{"symbol": "AAPL"}]}
    )
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.payload["rows"][0]["symbol"] == "AAPL"
    assert live.state == SnapshotState.LIVE
    assert live.status == SnapshotStatus.OK
    assert live.validated is True
    assert live.as_of_session == date(2026, 9, 4)


def test_returned_rows_normalize_to_the_sqlite_types(
    store: MysqlSnapshotStore, tmp_path: Path
) -> None:
    """Invariant: identical Python types out of both backends.

    The MySQL driver hands back a *naive* ``datetime`` for ``DATETIME(6)``
    (MySQL has no offset); the backend must re-attach UTC so callers see
    the same tz-aware instant the SQLite backend returns.
    """
    sqlite_store = SqliteSnapshotStore(tmp_path / "parity.db")
    for backend in (store, sqlite_store):
        staged = _stage(
            backend,
            payload={"rows": [{"symbol": "AAPL"}]},
            job_run_id="run-parity",
            input_hash="hash-a",
        )
        assert backend.validate(*staged).ok
        assert backend.promote(*staged)

    mysql_live = store.get_live("techtrade.movers", "sector=technology")
    sqlite_live = sqlite_store.get_live("techtrade.movers", "sector=technology")
    assert mysql_live is not None
    assert sqlite_live is not None

    for row in (mysql_live, sqlite_live):
        assert isinstance(row, SnapshotRow)
        # `datetime` subclasses `date`, so an exact class check is required
        # here -- `isinstance` would let a datetime masquerade as a date.
        assert row.as_of_session.__class__ is date
        assert isinstance(row.created_at, datetime)
        assert row.created_at.tzinfo is not None
        assert row.created_at.utcoffset() == timezone.utc.utcoffset(None)
        assert isinstance(row.payload, dict)
        assert isinstance(row.status, SnapshotStatus)
        assert isinstance(row.state, SnapshotState)
        assert isinstance(row.validated, bool)
        assert isinstance(row.validation_reason, str)

    assert mysql_live.as_of_session == sqlite_live.as_of_session
    assert mysql_live.payload == sqlite_live.payload
    assert mysql_live.input_hash == sqlite_live.input_hash
    assert mysql_live.job_run_id == sqlite_live.job_run_id
    sqlite_store.close()


def test_unvalidated_or_empty_stage_cannot_promote(store: MysqlSnapshotStore) -> None:
    staged = _stage(store, payload={})
    assert not store.promote(*staged)
    assert not store.validate(*staged).ok
    assert store.get_live("techtrade.movers", "sector=technology") is None


def test_custom_validator_rejection_blocks_promotion(
    store: MysqlSnapshotStore,
) -> None:
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})

    def _reject(row: SnapshotRow) -> ValidationResult:
        del row
        return ValidationResult(ok=False, reason="too few rows for this caller")

    result = store.validate(*staged, validator=_reject)
    assert not result.ok
    assert result.reason == "too few rows for this caller"
    assert not store.promote(*staged)
    assert store.get_live("techtrade.movers", "sector=technology") is None


def test_partial_cannot_displace_ok(store: MysqlSnapshotStore) -> None:
    """Invariant: keep-last-good — PARTIAL never outranks a LIVE OK row."""
    ok_staged = _stage(
        store, status=SnapshotStatus.OK, payload={"rows": [{"symbol": "AAPL"}]}
    )
    assert store.validate(*ok_staged).ok
    assert store.promote(*ok_staged)

    partial_staged = _stage(
        store,
        status=SnapshotStatus.PARTIAL,
        payload={"rows": [{"symbol": "MSFT"}]},
        as_of_session=date(2026, 9, 5),
    )
    assert store.validate(*partial_staged).ok
    assert not store.promote(*partial_staged)

    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.payload["rows"][0]["symbol"] == "AAPL"
    assert live.job_run_id == ok_staged[3]


def test_newer_ok_supersedes_prior_ok_and_history_retains_both(
    store: MysqlSnapshotStore,
) -> None:
    first = _stage(
        store,
        payload={"rows": [{"symbol": "AAPL"}]},
        as_of_session=date(2026, 9, 3),
    )
    assert store.validate(*first).ok
    assert store.promote(*first)

    second = _stage(
        store,
        payload={"rows": [{"symbol": "MSFT"}]},
        as_of_session=date(2026, 9, 4),
    )
    assert store.validate(*second).ok
    assert store.promote(*second)

    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.job_run_id == second[3]

    history = store.list_history("techtrade.movers", "sector=technology")
    assert [row.job_run_id for row in history] == [second[3], first[3]]
    assert history[0].state == SnapshotState.LIVE
    assert history[1].state == SnapshotState.SUPERSEDED


def test_differently_formatted_keys_resolve_same_live_row(
    store: MysqlSnapshotStore,
) -> None:
    """Invariant: read-boundary canonicalization collapses split-brain keys."""
    staged = _stage(
        store,
        entity_key="sector = Information_Technology",
        payload={"rows": [{"symbol": "AAPL"}]},
    )
    assert store.validate(*staged).ok
    assert store.promote(*staged)

    live = store.get_live("techtrade.movers", "sector=INFORMATION_technology")
    assert live is not None
    assert live.payload["rows"][0]["symbol"] == "AAPL"
    assert (
        store.get_as_of(
            "techtrade.movers", "sector=  information   technology", date(2026, 9, 4)
        )
        is not None
    )
    assert store.list_history("TECHTRADE.MOVERS", "sector=Information Technology") != []


def test_promote_refuses_candidate_not_in_staging_state(
    store: MysqlSnapshotStore,
) -> None:
    first = _stage(
        store,
        payload={"rows": [{"symbol": "AAPL"}]},
        as_of_session=date(2026, 9, 3),
    )
    assert store.validate(*first).ok
    assert store.promote(*first)

    second = _stage(
        store,
        payload={"rows": [{"symbol": "MSFT"}]},
        as_of_session=date(2026, 9, 4),
    )
    assert store.validate(*second).ok
    assert store.promote(*second)

    assert not store.promote(*first)
    assert not store.promote(*second)

    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.job_run_id == second[3]
    states = {
        row.job_run_id: row.state
        for row in store.list_history("techtrade.movers", "sector=technology")
    }
    assert states[first[3]] == SnapshotState.SUPERSEDED
    assert states[second[3]] == SnapshotState.LIVE


def test_validate_refuses_and_does_not_mutate_non_staging_row(
    store: MysqlSnapshotStore,
) -> None:
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)

    def _reject(row: SnapshotRow) -> ValidationResult:
        del row
        return ValidationResult(ok=False, reason="should never be persisted")

    assert not store.validate(*staged, validator=_reject).ok

    live_after = store.get_live("techtrade.movers", "sector=technology")
    assert live_after is not None
    assert live_after.validated is True
    assert live_after.validation_reason == ""
    assert live_after.state == SnapshotState.LIVE


def test_get_as_of_returns_promoted_row_for_given_session(
    store: MysqlSnapshotStore,
) -> None:
    staged = _stage(
        store, payload={"rows": [{"symbol": "AAPL"}]}, as_of_session=date(2026, 9, 4)
    )
    assert store.validate(*staged).ok
    assert store.promote(*staged)

    as_of = store.get_as_of("techtrade.movers", "sector=technology", date(2026, 9, 4))
    assert as_of is not None
    assert as_of.payload["rows"][0]["symbol"] == "AAPL"
    assert as_of.as_of_session == date(2026, 9, 4)
    assert (
        store.get_as_of("techtrade.movers", "sector=technology", date(2026, 9, 1))
        is None
    )


def test_get_as_of_ignores_staging_rows(store: MysqlSnapshotStore) -> None:
    _stage(
        store, payload={"rows": [{"symbol": "AAPL"}]}, as_of_session=date(2026, 9, 4)
    )
    assert (
        store.get_as_of("techtrade.movers", "sector=technology", date(2026, 9, 4))
        is None
    )


# ---------------------------------------------------------------------------
# Idempotency, restamp, retention
# ---------------------------------------------------------------------------


def _live_store(store: MysqlSnapshotStore, *, input_hash: str) -> MysqlSnapshotStore:
    staged = _stage(
        store,
        payload={"rows": [{"symbol": "AAPL"}]},
        as_of_session=date(2026, 9, 3),
        job_run_id="run-1",
        input_hash=input_hash,
    )
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    return store


def test_should_skip_is_false_with_no_live_row_or_mismatched_hash(
    store: MysqlSnapshotStore,
) -> None:
    assert not store.should_skip("techtrade.movers", "sector=technology", "any-hash")
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]}, input_hash="hash-a")
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    assert not store.should_skip("techtrade.movers", "sector=technology", "hash-b")
    assert store.should_skip("techtrade.movers", "sector=technology", "hash-a")


def test_matching_input_hash_can_be_restamped_without_recompute(
    store: MysqlSnapshotStore,
) -> None:
    _live_store(store, input_hash="same-input")
    assert store.should_skip("techtrade.movers", "sector=technology", "same-input")
    assert store.restamp_live(
        "techtrade.movers", "sector=technology", date(2026, 9, 4), "run-2"
    )
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.as_of_session == date(2026, 9, 4)
    assert live.job_run_id == "run-2"
    assert live.payload["rows"][0]["symbol"] == "AAPL"
    assert live.input_hash == "same-input"

    history = store.list_history("techtrade.movers", "sector=technology")
    assert len(history) == 2
    superseded = next(row for row in history if row.job_run_id == "run-1")
    assert superseded.as_of_session == date(2026, 9, 3)
    assert superseded.state == SnapshotState.SUPERSEDED


def test_restamp_live_refuses_when_no_live_row_exists(
    store: MysqlSnapshotStore,
) -> None:
    assert not store.restamp_live(
        "techtrade.movers", "sector=technology", date(2026, 9, 4), "run-2"
    )
    assert store.get_live("techtrade.movers", "sector=technology") is None


def test_default_prune_keeps_all_and_bounded_policy_preserves_live(
    store: MysqlSnapshotStore,
) -> None:
    for offset, symbol in enumerate(["AAPL", "MSFT", "GOOG"]):
        staged = _stage(
            store,
            payload={"rows": [{"symbol": symbol}]},
            as_of_session=date(2026, 9, 2 + offset),
        )
        assert store.validate(*staged).ok
        assert store.promote(*staged)

    assert store.prune() == 0
    assert store.prune(RetentionPolicy()) == 0
    assert store.prune(RetentionPolicy(keep_sessions=1)) == 2
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.payload["rows"][0]["symbol"] == "GOOG"
    assert len(store.list_history("techtrade.movers", "sector=technology")) == 1


def test_bounded_prune_preserves_live_when_its_session_predates_the_window(
    store: MysqlSnapshotStore,
) -> None:
    """Discriminating regression test for the ``state != 'live'`` guard.

    Promotes out of session order (9/2, 9/4, 9/3) so LIVE's own session
    (9/3) falls outside the ``keep_sessions=1`` window ``{9/4}``. A prune
    that decided "keep" purely by session-window membership would delete
    the LIVE row.
    """
    for symbol, as_of_session in (
        ("AAPL", date(2026, 9, 2)),
        ("MSFT", date(2026, 9, 4)),
        ("GOOG", date(2026, 9, 3)),
    ):
        staged = _stage(
            store, payload={"rows": [{"symbol": symbol}]}, as_of_session=as_of_session
        )
        assert store.validate(*staged).ok
        assert store.promote(*staged)

    assert store.prune(RetentionPolicy(keep_sessions=1)) == 1

    live_after = store.get_live("techtrade.movers", "sector=technology")
    assert live_after is not None
    assert live_after.as_of_session == date(2026, 9, 3)
    assert live_after.payload["rows"][0]["symbol"] == "GOOG"

    history = store.list_history("techtrade.movers", "sector=technology")
    assert {row.payload["rows"][0]["symbol"] for row in history} == {"GOOG", "MSFT"}


# ---------------------------------------------------------------------------
# Driver discipline: bindings, transactions, pool hygiene
# ---------------------------------------------------------------------------


def test_every_user_value_is_bound_with_percent_s(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    """Invariant: no user value is ever interpolated into SQL text."""
    staged = _stage(
        store,
        dataset="techtrade.movers",
        entity_key="sector=technology",
        payload={"rows": [{"symbol": "AAPL"}]},
        input_hash="hash-a",
        job_run_id="run-injection'; DROP TABLE pi_snapshot; --",
    )
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    assert store.restamp_live(
        "techtrade.movers", "sector=technology", date(2026, 9, 6), "run-2"
    )
    store.list_history("techtrade.movers", "sector=technology")
    store.get_as_of("techtrade.movers", "sector=technology", date(2026, 9, 6))
    assert store.prune(RetentionPolicy(keep_sessions=1)) >= 0

    assert pool.statements, "no statements recorded — the double is not wired"
    poisoned = ("techtrade.movers", "sector=technology", "hash-a", "DROP TABLE")
    for sql, params in pool.statements:
        assert sql.count("%s") == len(params)
        for needle in poisoned:
            assert needle not in sql, f"user value interpolated into SQL: {sql!r}"

    # The table survived the injection-shaped job_run_id.
    assert pool.raw.execute("SELECT COUNT(*) FROM pi_snapshot").fetchone()[0] >= 1


def test_writes_commit_and_reads_do_not(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    """Invariant: writes open an explicit transaction; reads open nothing.

    The pool hands out ``autocommit=True`` sessions, so a write scope
    that never calls ``begin()`` is not a transaction at all — its
    statements land one at a time and its ``rollback()`` undoes nothing.
    A read scope, conversely, needs no transaction: a bare ``SELECT`` on
    an autocommit session leaves no read view to close, so opening one
    would only be a round-trip to throw away.
    """
    begins_before, commits_before = pool.begins, pool.commits
    _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert pool.begins == begins_before + 1
    assert pool.commits == commits_before + 1

    begins_after_write = pool.begins
    commits_after_write = pool.commits
    rollbacks_before_read = pool.rollbacks
    assert store.get_live("techtrade.movers", "sector=technology") is None
    store.list_history("techtrade.movers", "sector=technology")
    assert pool.begins == begins_after_write
    assert pool.commits == commits_after_write
    assert pool.rollbacks == rollbacks_before_read


def test_a_failed_promote_rolls_back_the_demotion_it_already_wrote(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    """Invariant: multi-statement writes are all-or-nothing.

    ``promote()`` demotes the incumbent and installs the candidate as
    two statements. On an autocommit session without an explicit
    ``begin()`` the first one is already durable when the second fails,
    leaving the key with *no* LIVE row at all — the corruption this
    store exists to prevent. The failure is injected on the promoting
    UPDATE so the demotion has definitely landed first.
    """
    incumbent = _stage(
        store, payload={"rows": [{"symbol": "AAPL"}]}, as_of_session=date(2026, 9, 3)
    )
    assert store.validate(*incumbent).ok
    assert store.promote(*incumbent)

    mine = _stage(
        store, payload={"rows": [{"symbol": "MSFT"}]}, as_of_session=date(2026, 9, 4)
    )
    assert store.validate(*mine).ok

    rollbacks_before = pool.rollbacks
    pool.fail_on = lambda sql, params: (
        sql.startswith("UPDATE pi_snapshot SET state")
        and params[0] == SnapshotState.LIVE.value
    )
    with pytest.raises(_FakeMysqlError):
        store.promote(*mine)

    assert pool.rollbacks == rollbacks_before + 1
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None, "the demotion was committed without its promotion"
    assert live.job_run_id == incumbent[3]
    states = {
        row.job_run_id: row.state
        for row in store.list_history("techtrade.movers", "sector=technology")
    }
    assert states[incumbent[3]] == SnapshotState.LIVE
    assert states[mine[3]] == SnapshotState.STAGING


def test_failed_write_rolls_back_and_leaves_the_table_untouched(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    staged = _stage(
        store, payload={"rows": [{"symbol": "AAPL"}]}, job_run_id="run-dupe"
    )
    assert store.validate(*staged).ok
    assert store.promote(*staged)

    commits_before = pool.commits
    rollbacks_before = pool.rollbacks
    with pytest.raises(_FakeIntegrityError):
        _stage(
            store,
            payload={"rows": [{"symbol": "MSFT"}]},
            job_run_id="run-dupe",
        )
    assert pool.commits == commits_before
    assert pool.rollbacks == rollbacks_before + 1

    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.payload["rows"][0]["symbol"] == "AAPL"


def test_connections_are_returned_with_no_transaction_left_open(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    """Invariant: a borrowed session goes back in a clean state.

    The pool closes whatever it handed out, but a store that leaves a
    transaction dangling on failure has already broken the contract for
    any pool that recycles sessions instead of dropping them.
    """
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]}, job_run_id="run-x")
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    with pytest.raises(_FakeIntegrityError):
        _stage(store, payload={"rows": [{"symbol": "MSFT"}]}, job_run_id="run-x")
    assert store.prune(RetentionPolicy(keep_sessions=1)) >= 0

    assert pool.closed_with_open_txn == 0
    assert pool.handed_out == pool.returned


def test_every_borrowed_connection_is_returned_to_the_pool(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    store.get_live("techtrade.movers", "sector=technology")
    store.close()
    assert pool.handed_out == pool.returned


def test_close_does_not_tear_down_the_shared_pool(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    store.close()
    # The pool is shared with the FMP cache; a second store must still work.
    second = MysqlSnapshotStore(connection_pool=pool)
    assert second.get_live("techtrade.movers", "sector=technology") is not None


# ---------------------------------------------------------------------------
# Driver seam: the store is written against PyMySQL, not mysql-connector
# ---------------------------------------------------------------------------


def _mysql_store_ast() -> ast.Module:
    return ast.parse(inspect.getsource(mysql_store_module))


def test_pool_connections_are_only_taken_inside_a_with_block() -> None:
    """Invariant: ``get_connection()`` is a context manager, not a getter.

    ``ConnectionPool.get_connection`` is decorated with
    ``@contextmanager``: calling it returns a ``_GeneratorContextManager``
    with no ``cursor()``/``close()``, and the connection is only opened
    (and, crucially, closed) by the ``with``. The AST is walked rather
    than the source text because a textual check is defeated by the
    string appearing in a comment or docstring.
    """
    tree = _mysql_store_ast()
    guarded = {
        id(item.context_expr)
        for node in ast.walk(tree)
        if isinstance(node, (ast.With, ast.AsyncWith))
        for item in node.items
    }
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get_connection"
    ]
    assert calls, "the store no longer borrows from the pool at all"
    for call in calls:
        assert id(call) in guarded, (
            "pool.get_connection() is a @contextmanager; calling it outside a "
            "`with` yields a context-manager object, not a connection"
        )


def test_cursors_are_requested_with_the_pymysql_signature() -> None:
    """Invariant: no ``dictionary=``/``buffered=`` mysql-connector kwargs.

    PyMySQL's signature is ``cursor(self, cursor=None)`` and the pool
    already pins ``cursorclass=DictCursor``, so any keyword here is a
    ``TypeError`` against the real driver.
    """
    tree = _mysql_store_ast()
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "cursor"
    ]
    assert calls, "the store no longer opens cursors at all"
    for call in calls:
        assert not call.keywords, (
            "conn.cursor() takes no keywords in PyMySQL: "
            f"{[kw.arg for kw in call.keywords]}"
        )
        assert not call.args, "the pool pins DictCursor; ask for a bare cursor"


def test_rows_come_back_as_dict_cursor_mappings(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    """Invariant: the read path consumes ``DictCursor`` rows by name.

    The pool pins ``cursorclass=DictCursor``; a backend that indexed rows
    positionally would silently transpose columns the moment the
    projection changed.
    """
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT dataset, state FROM pi_snapshot WHERE state = %s", ("live",)
        )
        record = cur.fetchone()
    assert isinstance(record, dict)
    assert record["state"] == "live"

    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.state == SnapshotState.LIVE


class _StubDatabaseConfig:
    """Minimal stand-in for ``DatabaseConfig`` — no user_settings.json read."""

    @property
    def connection_params(self) -> dict[str, Any]:
        return {"host": "127.0.0.1", "database": "seam_contract_test"}


def test_store_drives_the_real_connection_pool_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seam contract: run the store through the *real* ``ConnectionPool``.

    Every other test in this module injects a pool double, which can only
    prove the store agrees with the double. This one instantiates the
    production class from ``openbb_fmp_cached.utils.database`` and only
    stubs ``pymysql.connect`` — no server, no socket — so the borrow
    protocol (``@contextmanager``, close-in-finally), the pinned
    ``DictCursor``, and ``autocommit=True`` are the real ones.
    """
    from openbb_fmp_cached.utils import database  # noqa: PLC0415

    book = _BasePool()
    connect_kwargs: list[dict[str, Any]] = []
    opened: list[_FakeConnection] = []

    def _fake_connect(**kwargs: Any) -> _FakeConnection:
        connect_kwargs.append(kwargs)
        conn = _FakeConnection(
            book,
            sqlite3.connect(str(tmp_path / "seam.db"), isolation_level=None),
            len(opened) + 1,
            owns_raw=True,
        )
        opened.append(conn)
        return conn

    monkeypatch.setattr(database.pymysql, "connect", _fake_connect)
    pool = database.ConnectionPool(_StubDatabaseConfig())

    borrowed = pool.get_connection()
    assert hasattr(borrowed, "__enter__") and hasattr(borrowed, "__exit__")
    assert not hasattr(borrowed, "cursor"), (
        "get_connection() returns a context manager; a store that treats it "
        "as a connection breaks against the real pool"
    )
    with borrowed as conn:
        assert conn is opened[-1]
    assert connect_kwargs[-1]["autocommit"] is True
    assert connect_kwargs[-1]["cursorclass"] is database.pymysql.cursors.DictCursor
    assert connect_kwargs[-1]["database"] == "seam_contract_test"

    store = MysqlSnapshotStore(connection_pool=pool)
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.job_run_id == staged[3]
    assert live.state == SnapshotState.LIVE

    assert book.begins >= 2, "writes must open an explicit transaction"
    assert book.closed_with_open_txn == 0
    assert book.returned == len(opened), "the pool closes every connection it opens"


# ---------------------------------------------------------------------------
# Concurrency: the read -> write window (review findings 1 and 2)
# ---------------------------------------------------------------------------
#
# The single-connection `_FakePool` above cannot express a race: every
# borrow is the same session, so nothing can commit "in between". These
# tests therefore run on `_RealisticPool`, whose `get_connection()`
# returns an independent session exactly like `mysql-connector`'s, and
# drive a second actor from the double's `after_execute` hook so the
# interleaving is deterministic rather than timing-dependent.

_MYSQL_LOGGER = "openbb_techtrade.snapshot.mysql_store"


def _hook_once(pool: _RealisticPool, needle: str, action: Any) -> dict:
    """Fire `action()` exactly once, right after `needle` is executed."""
    state = {"fired": False}

    def _hook(sql: str, params: tuple) -> None:
        del params
        if state["fired"] or needle not in sql:
            return
        state["fired"] = True
        action()

    pool.after_execute = _hook
    return state


def test_validate_update_is_scoped_to_the_staging_state(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    """Invariant: the validate UPDATE re-checks STAGING in its WHERE clause.

    Reading the row and writing its verdict are two statements; without
    a `state` predicate on the write, a row promoted in between has its
    audit fields silently rewritten.
    """
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok

    updates = [
        (sql, params)
        for sql, params in pool.statements
        if sql.lstrip().upper().startswith("UPDATE PI_SNAPSHOT SET VALIDATED")
    ]
    assert len(updates) == 1
    sql, params = updates[0]
    assert "AND state = %s" in sql
    assert SnapshotState.STAGING.value in params


def test_revalidating_an_unchanged_verdict_is_not_reported_as_a_race(
    store: MysqlSnapshotStore, caplog: pytest.LogCaptureFixture
) -> None:
    """Invariant: an idempotent re-validate succeeds.

    Re-running the gate on a row that already carries the identical
    verdict rewrites nothing, and PyMySQL — which connects without
    ``CLIENT.FOUND_ROWS`` — reports **0** affected rows for that UPDATE.
    A backend that reads "0 affected" as "someone moved the row" turns a
    replayed job into a phantom race: the verdict is discarded and the
    caller is told the snapshot is unusable, while the row sits
    untouched in STAGING with the very verdict it just refused to admit.
    """
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok

    with caplog.at_level(logging.WARNING, logger=_MYSQL_LOGGER):
        again = store.validate(*staged)

    assert again.ok is True, again.reason
    assert "changed" not in again.reason.lower()
    assert not [r for r in caplog.records if "refused" in r.getMessage()]

    row = store.get_as_of("techtrade.movers", "sector=technology", staged[2])
    assert row is None  # still STAGING, never promoted
    history = store.list_history("techtrade.movers", "sector=technology")
    assert [(r.state, r.validated) for r in history] == [(SnapshotState.STAGING, True)]


def test_revalidating_a_reversed_verdict_still_persists(
    store: MysqlSnapshotStore,
) -> None:
    """The idempotency fix must not swallow a genuinely changed verdict."""
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok

    def _reject(row: SnapshotRow) -> ValidationResult:
        del row
        return ValidationResult(ok=False, reason="stale-vendor-feed")

    result = store.validate(*staged, validator=_reject)
    assert result.ok is False
    assert result.reason == "stale-vendor-feed"

    history = store.list_history("techtrade.movers", "sector=technology")
    assert history[0].validated is False
    assert history[0].validation_reason == "stale-vendor-feed"


def test_validate_re_reads_the_row_under_a_lock_in_its_write_transaction(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    """Invariant: the STAGING re-check is a *locked* read, not a rowcount.

    ``rowcount`` cannot answer "did the row move?" on PyMySQL, because 0
    affected rows is ambiguous between "someone moved it" and "nothing
    to change". The unambiguous answer is to re-read the row ``FOR
    UPDATE`` inside the same transaction as the write, which both
    resolves the ambiguity and holds the row until COMMIT.
    """
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    before = len(pool.calls)
    assert store.validate(*staged).ok

    calls = pool.calls[before:]
    update_at = next(
        index
        for index, (_, sql, _) in enumerate(calls)
        if sql.lstrip().upper().startswith("UPDATE PI_SNAPSHOT SET VALIDATED")
    )
    locked = [
        (conn_id, sql)
        for conn_id, sql, _ in calls[:update_at]
        if sql.rstrip().upper().endswith("FOR UPDATE")
    ]
    assert locked, "validate wrote its verdict without re-reading under a lock"
    assert locked[-1][0] == calls[update_at][0], (
        "the locking read must run on the same connection — and therefore the "
        "same transaction — as the write it guards"
    )


def test_validate_refuses_when_the_row_leaves_staging_between_read_and_write(
    real_store: MysqlSnapshotStore,
    real_pool: _RealisticPool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Race guard: a concurrent promotion must void an in-flight validate.

    The validator callable is the seam *between* validate's read and its
    write, so promoting from inside it reproduces the window exactly. A
    backend without the `state` predicate happily stamps the rejecting
    verdict onto the now-LIVE row, forging its audit trail.
    """
    staged = _stage(real_store, payload={"rows": [{"symbol": "AAPL"}]})
    assert real_store.validate(*staged).ok
    assert real_store.promote(*staged)

    later = _stage(
        real_store,
        payload={"rows": [{"symbol": "MSFT"}]},
        as_of_session=date(2026, 9, 5),
    )
    other = MysqlSnapshotStore(connection_pool=real_pool)

    def _forge(row: SnapshotRow) -> ValidationResult:
        del row
        # A different session promotes the row we just read.
        assert other.validate(*later).ok
        assert other.promote(*later)
        return ValidationResult(ok=False, reason="forged-verdict")

    with caplog.at_level(logging.WARNING, logger=_MYSQL_LOGGER):
        result = real_store.validate(*later, validator=_forge)

    assert result.ok is False
    assert "forged-verdict" not in result.reason
    assert "changed" in result.reason.lower()
    assert [r for r in caplog.records if "validation refused" in r.getMessage()]

    live = real_store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.job_run_id == later[3]
    assert live.state == SnapshotState.LIVE
    assert live.validated is True
    assert live.validation_reason == ""


def test_promote_locks_the_candidate_and_live_rows_on_one_connection(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    """Invariant: promote's reads take row locks on its own transaction.

    Reading the candidate and the incumbent LIVE row through a separate
    pooled connection (or without `FOR UPDATE`) leaves the whole
    lifecycle unserialised: the rows can move under the transaction that
    is about to rewrite them.
    """
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok

    before = len(pool.calls)
    assert store.promote(*staged)
    promote_calls = pool.calls[before:]

    selects = [
        call for call in promote_calls if call[1].lstrip().upper().startswith("SELECT")
    ]
    assert len(selects) == 2, "promote must read the candidate and the LIVE row"
    for _, sql, _params in selects:
        assert re.search(
            r"FOR\s+UPDATE\s*$", sql.strip(), re.I
        ), f"promote read is not a locking read: {sql!r}"

    conn_ids = {call[0] for call in promote_calls}
    assert len(conn_ids) == 1, (
        f"promote spread its statements over {len(conn_ids)} connections; "
        "the locking reads must share the writing transaction"
    )


def test_promote_refuses_when_the_incumbent_live_row_moves_mid_transaction(
    real_store: MysqlSnapshotStore,
    real_pool: _RealisticPool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Race guard: never demote a LIVE row other than the one we read.

    Without pinning the demotion to the incumbent's primary key, a
    promotion that lands between our read and our write is silently
    clobbered: we demote *its* row and install our own, losing a newer
    good snapshot with no error anywhere.
    """
    incumbent = _stage(
        real_store,
        payload={"rows": [{"symbol": "AAPL"}]},
        as_of_session=date(2026, 9, 3),
    )
    assert real_store.validate(*incumbent).ok
    assert real_store.promote(*incumbent)

    mine = _stage(
        real_store,
        payload={"rows": [{"symbol": "MSFT"}]},
        as_of_session=date(2026, 9, 4),
    )
    theirs = _stage(
        real_store,
        payload={"rows": [{"symbol": "NVDA"}]},
        as_of_session=date(2026, 9, 5),
    )
    assert real_store.validate(*mine).ok
    assert real_store.validate(*theirs).ok

    other = MysqlSnapshotStore(connection_pool=real_pool)
    fired = _hook_once(
        real_pool,
        "state = %s FOR UPDATE",
        lambda: other.promote(*theirs),
    )

    with caplog.at_level(logging.WARNING, logger=_MYSQL_LOGGER):
        promoted = real_store.promote(*mine)

    assert fired["fired"], "the interleaving hook never ran — test is inert"
    assert promoted is False
    assert [r for r in caplog.records if "promotion refused" in r.getMessage()]
    assert real_pool.live_job_run_ids() == [theirs[3]]

    states = {
        row.job_run_id: row.state
        for row in real_store.list_history("techtrade.movers", "sector=technology")
    }
    assert states[mine[3]] == SnapshotState.STAGING
    assert states[theirs[3]] == SnapshotState.LIVE
    assert states[incumbent[3]] == SnapshotState.SUPERSEDED


def test_promote_refuses_when_the_candidate_is_promoted_concurrently(
    real_store: MysqlSnapshotStore,
    real_pool: _RealisticPool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Race guard: the promoting UPDATE must re-assert STAGING.

    Two workers promoting the same staged run must not both report
    success: exactly one performed the transition, and the loser has to
    say so.
    """
    mine = _stage(real_store, payload={"rows": [{"symbol": "AAPL"}]})
    assert real_store.validate(*mine).ok

    other = MysqlSnapshotStore(connection_pool=real_pool)
    fired = _hook_once(
        real_pool,
        "state = %s FOR UPDATE",
        lambda: other.promote(*mine),
    )

    with caplog.at_level(logging.WARNING, logger=_MYSQL_LOGGER):
        promoted = real_store.promote(*mine)

    assert fired["fired"], "the interleaving hook never ran — test is inert"
    assert promoted is False
    assert [r for r in caplog.records if "promotion refused" in r.getMessage()]
    assert real_pool.live_job_run_ids() == [mine[3]]


def test_promote_converts_a_concurrent_live_key_collision_into_a_refusal(
    real_store: MysqlSnapshotStore,
    real_pool: _RealisticPool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Race guard: a unique-key collision surfaces as False, not a traceback.

    A writer that bypasses `promote()` can still install a LIVE row in
    the window; the generated `live_key` unique key then rejects ours.
    Callers of a boolean API must not have to catch a driver-specific
    IntegrityError to survive that.
    """
    mine = _stage(real_store, payload={"rows": [{"symbol": "AAPL"}]})
    assert real_store.validate(*mine).ok

    fired = _hook_once(
        real_pool,
        "state = %s FOR UPDATE",
        lambda: _direct_insert(real_pool, job_run_id="run-outsider", state="live"),
    )

    with caplog.at_level(logging.WARNING, logger=_MYSQL_LOGGER):
        promoted = real_store.promote(*mine)

    assert fired["fired"], "the interleaving hook never ran — test is inert"
    assert promoted is False
    assert [r for r in caplog.records if "promotion refused" in r.getMessage()]
    assert real_pool.live_job_run_ids() == ["run-outsider"]

    rolled_back = real_pool.query(
        "SELECT state FROM pi_snapshot WHERE job_run_id = ?", (mine[3],)
    )
    assert rolled_back == [(SnapshotState.STAGING.value,)]


def _direct_supersede(pool: _RealisticPool, job_run_id: str) -> None:
    """Out-of-band demotion, committed on its own connection."""
    with pool.get_connection() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE pi_snapshot SET state = %s WHERE job_run_id = %s",
                    (SnapshotState.SUPERSEDED.value, job_run_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def test_promote_refuses_when_the_incumbent_live_row_vanishes_mid_transaction(
    real_store: MysqlSnapshotStore,
    real_pool: _RealisticPool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Race guard: "0 rows demoted" must abort, even with nothing in the way.

    Here no competing row takes over LIVE, so the unique key never fires
    and nothing downstream would complain — the demotion's affected-row
    count is the *only* evidence that the incumbent this promotion was
    ranked against is gone. Proceeding would install our row on the
    strength of a keep-last-good comparison against a row that no longer
    exists.
    """
    incumbent = _stage(
        real_store,
        payload={"rows": [{"symbol": "AAPL"}]},
        as_of_session=date(2026, 9, 3),
    )
    assert real_store.validate(*incumbent).ok
    assert real_store.promote(*incumbent)

    mine = _stage(
        real_store,
        payload={"rows": [{"symbol": "MSFT"}]},
        as_of_session=date(2026, 9, 4),
    )
    assert real_store.validate(*mine).ok

    fired = _hook_once(
        real_pool,
        "state = %s FOR UPDATE",
        lambda: _direct_supersede(real_pool, incumbent[3]),
    )

    with caplog.at_level(logging.WARNING, logger=_MYSQL_LOGGER):
        promoted = real_store.promote(*mine)

    assert fired["fired"], "the interleaving hook never ran - test is inert"
    assert promoted is False
    assert [
        r
        for r in caplog.records
        if "promotion refused" in r.getMessage()
        and "LIVE row changed" in r.getMessage()
    ]
    assert real_pool.live_job_run_ids() == []

    states = {
        row.job_run_id: row.state
        for row in real_store.list_history("techtrade.movers", "sector=technology")
    }
    assert states[mine[3]] == SnapshotState.STAGING
    assert states[incumbent[3]] == SnapshotState.SUPERSEDED
