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
own ``_PI_EOD_SNAPSHOT_DDL``, so a ``DATE``/``DATETIME(6)`` column really is
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
import os
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
    _PI_EOD_SNAPSHOT_DDL,
    MysqlSnapshotStore,
    _make_mysql_store,
)
from openbb_techtrade.snapshot.store import (
    FIELD_MAX_LENGTHS,
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


_COLUMN_TYPES = _column_types(_PI_EOD_SNAPSHOT_DDL)

_VARCHAR_RE = re.compile(r"^\s+(\w+)\s+VARCHAR\((\d+)\)", re.M)

# `live_key` is a generated column: its width is derived from the columns it
# concatenates, so it is not a bound the *writer* can violate.
_GENERATED_COLUMNS = frozenset({"live_key"})

# Every string column the DDL declares, with the collation it pins (or
# `None` when it pins none). The double translates that into SQLite's
# `COLLATE` so an unpinned column behaves like MySQL's *default* —
# case-insensitive — instead of silently inheriting SQLite's BINARY. That
# is what makes the collation tests discriminating rather than a reading
# of the DDL text back to itself.
_TEXTUAL_COLUMN_RE = re.compile(
    r"^\s+(?P<name>\w+)\s+(?P<type>VARCHAR\(\d+\)|CHAR\(\d+\)|LONGTEXT|TEXT)"
    r"(?P<collate>\s+COLLATE\s+(?P<collation>\w+))?",
    re.M,
)


def _column_collations(ddl: str) -> dict[str, str | None]:
    """Map ``column -> pinned collation`` (``None`` when unpinned)."""
    return {
        match.group("name"): match.group("collation")
        for match in _TEXTUAL_COLUMN_RE.finditer(ddl)
        if match.group("name").upper() not in _NON_COLUMN_TOKENS
    }


def _column_widths(ddl: str) -> dict[str, int]:
    """Map ``column -> declared VARCHAR width`` from a ``CREATE TABLE`` body."""
    return {
        match.group(1): int(match.group(2))
        for match in _VARCHAR_RE.finditer(ddl)
        if match.group(1).upper() not in _NON_COLUMN_TOKENS
    }


_COLUMN_WIDTHS = _column_widths(_PI_EOD_SNAPSHOT_DDL)


def _ddl_to_sqlite(ddl: str) -> tuple[str, list[str]]:
    """Translate the MySQL ``CREATE TABLE`` into an equivalent SQLite one.

    Semantics are preserved, not erased: the generated ``live_key``
    column and its unique constraint survive the translation (SQLite
    3.31+ supports ``GENERATED ALWAYS AS ... STORED``), so the
    single-LIVE-row invariant is genuinely enforced by the double.

    SQLite ignores declared ``VARCHAR(n)`` widths entirely, while MySQL
    in its default strict mode raises ``DataError`` (1406, "Data too
    long"). Translating each declared width into a table-level ``CHECK``
    restores that difference, so a test that stages an over-long value
    fails here exactly as it would against a real server — which is what
    makes the length-guard tests discriminating rather than ceremonial.

    Collation gets the same treatment, and for the same reason. MySQL
    resolves an unpinned string column to the *charset's default*
    collation, which is case- and accent-insensitive on every supported
    server; SQLite would resolve it to BINARY. Left untranslated, a DDL
    that dropped its ``COLLATE utf8mb4_bin`` would keep passing here
    while silently changing key semantics on the real server. So a
    pinned ``utf8mb4_bin`` becomes ``COLLATE BINARY`` and an *unpinned*
    column becomes ``COLLATE NOCASE`` — the double's stand-in for
    ``_ci``.
    """
    body = ddl.strip()
    body = re.sub(
        r"\)\s*ENGINE=\w+\s+DEFAULT\s+CHARSET=\w+(\s+COLLATE=\w+)?\s*$", ")", body
    )
    indexes: list[str] = []

    def _hoist_index(match: re.Match[str]) -> str:
        indexes.append(
            f"CREATE INDEX IF NOT EXISTS {match.group(1)} "
            f"ON {_table_name(ddl)} ({match.group(2)})"
        )
        return ""

    body = re.sub(r"\n\s*INDEX (\w+) \(([^)]*)\),?", _hoist_index, body)
    body = re.sub(r"UNIQUE KEY \w+ \(([^)]*)\)", r"UNIQUE (\1)", body)
    body = _apply_collations(body)
    body = body.replace("IF(state", "IIF(state")  # codespell:ignore
    body = body.replace("CHAR(31 USING utf8mb4)", "char(31)")
    body = body.replace("CONCAT(", "concat(")
    body = re.sub(r",(\s*)\)\s*$", r"\1)", body)
    checks = ",\n".join(
        f"    CHECK ({column} IS NULL OR length({column}) <= {width})"
        for column, width in _column_widths(ddl).items()
        if column not in _GENERATED_COLUMNS
    )
    body = re.sub(r"\)\s*$", f",\n{checks}\n)", body) if checks else body
    return body, indexes


def _apply_collations(body: str) -> str:
    """Rewrite each string column's collation into SQLite's vocabulary."""

    def _rewrite(match: re.Match[str]) -> str:
        if match.group("name").upper() in _NON_COLUMN_TOKENS:
            return match.group(0)
        head = f"{match.group(0)[: match.end('type') - match.start(0)]}"
        collation = match.group("collation")
        if collation is None:
            # MySQL's utf8mb4 default collation is case-insensitive.
            return f"{head} COLLATE NOCASE"
        return f"{head} COLLATE {'BINARY' if collation.endswith('_bin') else 'NOCASE'}"

    return _TEXTUAL_COLUMN_RE.sub(_rewrite, body)


_TABLE_NAME_RE = re.compile(r"CREATE TABLE (?:IF NOT EXISTS )?(?P<name>\w+)\s*\(", re.I)


def _table_name(ddl: str) -> str:
    """Extract the table a ``CREATE TABLE`` statement declares."""
    match = _TABLE_NAME_RE.search(ddl)
    assert match is not None, f"not a CREATE TABLE statement: {ddl[:80]!r}"
    return match.group("name")


# ---------------------------------------------------------------------------
# PyMySQL-shaped test double
# ---------------------------------------------------------------------------

# The production pool logs on its own module logger; the doubles reuse that
# name deliberately so a `caplog` assertion reads the same whether the test
# runs against `_FakePool`/`_RealisticPool` or the real `ConnectionPool`.
_POOL_LOGGER = "openbb_fmp_cached.utils.database"
_MYSQL_LOGGER = "openbb_techtrade.snapshot.mysql_store"


class _FakeMysqlError(Exception):
    """Stand-in for ``pymysql.err.Error``."""


class _FakeProgrammingError(_FakeMysqlError):
    """Stand-in for ``pymysql.err.ProgrammingError``."""


class _FakeIntegrityError(_FakeMysqlError):
    """Stand-in for ``pymysql.err.IntegrityError``."""


class _FakeDataError(_FakeMysqlError):
    """Stand-in for ``pymysql.err.DataError`` (1406, "Data too long").

    Deliberately *not* an ``IntegrityError``: the store downgrades
    integrity errors to lifecycle refusals, so mis-classifying an
    over-long write would silently turn lost data into a routine
    ``promote() -> False``.
    """


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
            self._create_table(sql)
            return
        bound = tuple(params or ())
        if sql.count("%s") != len(bound):
            raise _FakeProgrammingError(
                f"Not all parameters were used in the SQL statement: "
                f"{sql.count('%s')} placeholders vs {len(bound)} params"
            )
        if "information_schema" in sql.lower():
            self._describe_table(sql, bound)
            return
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
            # The width CHECKs injected by `_ddl_to_sqlite` stand in for
            # MySQL strict mode, which reports 1406 as a *data* error.
            if "CHECK constraint failed" in str(exc):
                raise _FakeDataError(f"Data too long for column: {exc}") from exc
            raise _FakeIntegrityError(str(exc)) from exc
        self._executed = (sql, bound)

    def _create_table(self, sql: str) -> None:
        """Apply a ``CREATE TABLE`` the way MySQL would, indexes included.

        MySQL declares the indexes *inside* ``CREATE TABLE``, so an
        ``IF NOT EXISTS`` that finds an existing table creates nothing at
        all — not the table, not its indexes. SQLite needs the indexes
        hoisted into separate statements, so the double has to reproduce
        that all-or-nothing behavior explicitly; otherwise a no-op'd
        CREATE would still try to index columns a foreign table does not
        have, and a name collision would surface as a driver error
        instead of the silent no-op it really is.
        """
        table_sql, indexes = _ddl_to_sqlite(sql)
        existed = (
            self._cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (_table_name(sql),),
            ).fetchone()
            is not None
        )
        self._cursor.execute(table_sql)
        if existed:
            return
        for index_sql in indexes:
            self._cursor.execute(index_sql)

    def _describe_table(self, sql: str, bound: tuple) -> None:
        """Answer the production ``information_schema.COLUMNS`` shape probe.

        The store asks a real MySQL question (``SELECT COLUMN_NAME FROM
        information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND
        TABLE_NAME = %s``) — the double answers it from SQLite's own
        catalogue rather than the store softening its query into
        something portable. A table that does not exist yields no rows,
        exactly as ``information_schema`` does.
        """
        assert "COLUMN_NAME" in sql, f"unexpected information_schema query: {sql!r}"
        self._cursor.execute(
            "SELECT name AS COLUMN_NAME FROM pragma_table_info(?)", bound
        )
        self._executed = None

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
        self.errors: list[BaseException] = []
        self.after_execute: Any = None
        self.fail_on: Any = None
        self._ids = itertools.count(1)
        self._in_hook = False

    @contextmanager
    def get_connection(self) -> Iterator[_FakeConnection]:
        """``ConnectionPool.get_connection`` is a context manager, not a getter.

        It is also *not* transparent to exceptions: the production body is
        ``yield`` / ``except Exception: logger.error("MySQL connection
        error: %s"); raise`` / ``finally: close()``. Anything a store lets
        unwind across this boundary is therefore reported to operators as
        a **connection fault**, whatever it actually was. The double
        records every such exception in ``errors`` and logs it under the
        production logger name so a test can assert that a routine
        lifecycle refusal never reaches it.
        """
        self.handed_out += 1
        conn = self._open()
        try:
            yield conn
        except Exception as exc:  # noqa: BLE001 - mirrors the production pool
            self.errors.append(exc)
            logging.getLogger(_POOL_LOGGER).error("MySQL connection error: %s", exc)
            raise
        finally:
            conn.close()

    def _open(self) -> _FakeConnection:
        """Open one pooled session (subclasses decide how independent it is)."""
        raise NotImplementedError

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

    def _open(self) -> _FakeConnection:
        return _FakeConnection(self, self.raw, next(self._ids), owns_raw=False)


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

    def _open(self) -> _FakeConnection:
        raw = sqlite3.connect(self.path, timeout=1.0, isolation_level=None)
        return _FakeConnection(self, raw, next(self._ids), owns_raw=True)

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
                "SELECT job_run_id FROM pi_eod_snapshot WHERE state = ? "
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
    engine_version: str | None = None,
    payload_schema_version: str | None = None,
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
        engine_version=engine_version,
        payload_schema_version=payload_schema_version,
    )
    return (dataset, entity_key, as_of_session, job_run_id)


def _direct_insert(pool: _BasePool, *, job_run_id: str, state: str) -> None:
    """Bypass the store to test the DB-level constraint directly."""
    with pool.get_connection() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO pi_eod_snapshot ("
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
    assert re.search(r"\bas_of_session\s+DATE NOT NULL", _PI_EOD_SNAPSHOT_DDL)
    assert re.search(r"\bcreated_at\s+DATETIME\(6\) NOT NULL", _PI_EOD_SNAPSHOT_DDL)
    assert _COLUMN_TYPES["as_of_session"] == "DATE"
    assert _COLUMN_TYPES["created_at"] == "DATETIME"


def test_ddl_declares_generated_nullable_live_key_and_unique_key() -> None:
    """Invariant: single-LIVE-row is enforced by a generated nullable key.

    ``live_key`` is NULL for every non-LIVE row (MySQL unique indexes
    ignore NULLs), so unlimited STAGING/SUPERSEDED history coexists with
    at most one LIVE row per ``(dataset, entity_key)``.
    """
    assert re.search(r"\blive_key\s+VARCHAR\(512\)", _PI_EOD_SNAPSHOT_DDL)
    assert "GENERATED ALWAYS AS" in _PI_EOD_SNAPSHOT_DDL
    assert "IF(state = 'live'" in _PI_EOD_SNAPSHOT_DDL
    assert "STORED" in _PI_EOD_SNAPSHOT_DDL
    assert "UNIQUE KEY ux_pi_eod_snapshot_live (live_key)" in _PI_EOD_SNAPSHOT_DDL
    # The generated expression must key on BOTH parts of the identity, or
    # two datasets sharing an entity_key would collide. The CHAR(31) unit
    # separator keeps the boundary unforgeable.
    assert re.search(
        r"CONCAT\(\s*dataset,\s*CHAR\(31[^)]*\),\s*entity_key\s*\)",
        _PI_EOD_SNAPSHOT_DDL,
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
        "SELECT state, live_key FROM pi_eod_snapshot ORDER BY job_run_id"
    ).fetchall()
    assert len(rows) == 3
    assert all(live_key is None for _, live_key in rows)


# ---------------------------------------------------------------------------
# Bounded identifier/provenance fields (review finding 2)
# ---------------------------------------------------------------------------
#
# MySQL declares finite widths for the identity and provenance columns;
# SQLite ignores widths entirely. Left alone, the same `stage()` call is
# accepted by one backend and rejected (or, on a non-strict server,
# silently truncated) by the other -- and a truncated `job_run_id` or
# `input_hash` is corrupted provenance that no later read can detect.
# The limits therefore live in one shared table that is asserted against
# the DDL, and are enforced in Python before any statement is issued.

_LONG_TEXT = "x" * 600


def test_ddl_widths_match_the_shared_length_limits() -> None:
    """Drift guard: the declared widths *are* the enforced limits.

    If the DDL is widened (or the shared table edited) without the other
    following, the guard would reject values the column accepts, or --
    far worse -- admit values the column truncates.
    """
    declared = {
        column: width
        for column, width in _COLUMN_WIDTHS.items()
        if column in FIELD_MAX_LENGTHS
    }
    assert declared == FIELD_MAX_LENGTHS
    # Every bounded field the guard knows about must exist in the table.
    assert set(FIELD_MAX_LENGTHS) <= set(_COLUMN_WIDTHS)


def test_ddl_stores_validation_reason_as_unbounded_text() -> None:
    """A validator's explanation is diagnostics, not an identifier.

    Bounding it to ``VARCHAR(512)`` puts the two backends in permanent
    disagreement -- SQLite keeps the whole reason, MySQL truncates it --
    and the truncation is silent on a non-strict server, so the operator
    reading the row cannot tell a short reason from a cut-off one.
    """
    assert _COLUMN_TYPES["validation_reason"] == "TEXT"
    assert "validation_reason" not in _COLUMN_WIDTHS


def test_live_key_is_wide_enough_for_the_widest_possible_identity() -> None:
    """The generated column must hold ``dataset + SEP + entity_key``.

    A narrower ``live_key`` would truncate the concatenation, and two
    distinct identities sharing a prefix would then collide on the unique
    index -- a spurious "another writer installed a LIVE row" refusal.
    """
    widest = FIELD_MAX_LENGTHS["dataset"] + 1 + FIELD_MAX_LENGTHS["entity_key"]
    assert _COLUMN_WIDTHS["live_key"] >= widest


def test_status_and_state_columns_fit_every_enum_value() -> None:
    """The lifecycle vocabularies are persisted verbatim, not truncated."""
    vocabulary = [member.value for member in SnapshotStatus] + [
        member.value for member in SnapshotState
    ]
    for column in ("status", "state"):
        assert _COLUMN_WIDTHS[column] >= max(len(value) for value in vocabulary)


def test_the_double_enforces_declared_widths_like_strict_mode(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    """Guards the guard: without this, the length tests prove nothing.

    SQLite ignores ``VARCHAR(n)``. If the double did too, a test that
    stages an over-long value would pass whether or not the production
    guard existed. Here the double is made to reject the write the way a
    strict-mode MySQL server does -- as a *data* error, not an integrity
    error (the store downgrades integrity errors to refusals).
    """
    _stage(store, payload={"rows": [{"symbol": "AAPL"}]})  # creates the table
    with pytest.raises(_FakeDataError) as excinfo:
        _direct_insert(pool, job_run_id="run-" + _LONG_TEXT, state="staging")
    assert not isinstance(excinfo.value, _FakeIntegrityError)


@pytest.mark.parametrize("field", sorted(FIELD_MAX_LENGTHS))
def test_stage_refuses_an_over_long_bounded_field(
    store: MysqlSnapshotStore, pool: _FakePool, field: str
) -> None:
    """Every bounded field is checked, and nothing is written."""
    limit = FIELD_MAX_LENGTHS[field]
    begins_before = pool.begins
    with pytest.raises(SnapshotFieldTooLong) as excinfo:
        _stage(
            store,
            payload={"rows": [{"symbol": "AAPL"}]},
            **{field: "y" * (limit + 1)},
        )

    message = str(excinfo.value)
    assert field in message
    assert str(limit) in message
    assert str(limit + 1) in message
    assert excinfo.value.field_name == field
    assert excinfo.value.limit == limit
    assert excinfo.value.length == limit + 1
    # The refusal lands before the driver is touched at all: no write
    # transaction is opened and no INSERT is issued, so a server without
    # strict mode never gets the chance to truncate the value. This is
    # asserted independently of the exception type above, because a guard
    # placed *inside* the transaction would still raise -- after a
    # pointless BEGIN/ROLLBACK round-trip on the shared pool.
    assert pool.begins == begins_before
    inserts = [
        sql for sql, _ in pool.statements if sql.lstrip().upper().startswith("INSERT")
    ]
    assert inserts == []


@pytest.mark.parametrize("field", sorted(FIELD_MAX_LENGTHS))
def test_stage_accepts_a_bounded_field_at_exactly_the_limit(
    store: MysqlSnapshotStore, field: str
) -> None:
    """The boundary is inclusive, and the full value round-trips.

    An off-by-one in either direction is a real defect: one rejects legal
    identifiers, the other hands the column a value it must truncate.
    """
    value = "z" * FIELD_MAX_LENGTHS[field]
    dataset, entity_key, _, _ = _stage(
        store, payload={"rows": [{"symbol": "AAPL"}]}, **{field: value}
    )
    history = store.list_history(dataset, entity_key)
    assert len(history) == 1
    assert getattr(history[0], field) == value


def test_bounded_lengths_are_measured_after_canonicalization(
    store: MysqlSnapshotStore,
) -> None:
    """The stored value is the canonical one, so that is what is measured.

    Checking the raw argument would reject a key whose canonical form
    fits the column -- a false refusal caused by whitespace the store
    itself strips.
    """
    padded = "  " + "k" * FIELD_MAX_LENGTHS["entity_key"] + "  "
    assert len(padded) > FIELD_MAX_LENGTHS["entity_key"]
    dataset, entity_key, _, _ = _stage(
        store, payload={"rows": [{"symbol": "AAPL"}]}, entity_key=padded
    )
    history = store.list_history(dataset, entity_key)
    assert len(history) == 1
    assert history[0].entity_key == canonical_key(padded)


def test_a_long_validation_reason_is_persisted_whole(
    store: MysqlSnapshotStore,
) -> None:
    """A validator may say as much as it needs to; nothing is cut off."""
    reason = "row-level mismatch: " + ", ".join(f"AAPL{n}" for n in range(300))
    assert len(reason) > 512

    def _reject(row: SnapshotRow) -> ValidationResult:
        del row
        return ValidationResult(ok=False, reason=reason)

    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    result = store.validate(*staged, validator=_reject)

    assert result.ok is False
    assert result.reason == reason
    history = store.list_history(staged[0], staged[1])
    assert history[0].validation_reason == reason


def test_both_backends_refuse_the_same_over_long_value(
    store: MysqlSnapshotStore, tmp_path: Path
) -> None:
    """Cross-backend parity, asserted in one place.

    This is the finding itself: the same call must not be accepted by
    SQLite and rejected by MySQL. Both raise the identical error, from
    the identical shared limit, before either dialect is reached.
    """
    sqlite_store = SqliteSnapshotStore(tmp_path / "parity.db")
    try:
        too_long = "w" * (FIELD_MAX_LENGTHS["job_run_id"] + 1)
        payload = {"rows": [{"symbol": "AAPL"}]}
        with pytest.raises(SnapshotFieldTooLong) as mysql_error:
            _stage(store, payload=payload, job_run_id=too_long)
        with pytest.raises(SnapshotFieldTooLong) as sqlite_error:
            sqlite_store.stage(
                "techtrade.movers",
                "sector=technology",
                date(2026, 9, 4),
                too_long,
                payload,
            )
        assert str(mysql_error.value) == str(sqlite_error.value)
        assert sqlite_store.get_live("techtrade.movers", "sector=technology") is None
    finally:
        sqlite_store.close()


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
        job_run_id="run-injection'; DROP TABLE pi_eod_snapshot; --",
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
    assert pool.raw.execute("SELECT COUNT(*) FROM pi_eod_snapshot").fetchone()[0] >= 1


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
        sql.startswith("UPDATE pi_eod_snapshot SET state")
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
            "SELECT dataset, state FROM pi_eod_snapshot WHERE state = %s", ("live",)
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


class _SeamHarness:
    """The **production** ``ConnectionPool`` driven over SQLite.

    Only ``pymysql.connect`` is stubbed — no server, no socket — so the
    borrow protocol (``@contextmanager``, log-and-reraise, close-in-
    ``finally``), the pinned ``DictCursor`` and ``autocommit=True`` are
    the real ones, and so is the ``logger.error("MySQL connection error:
    ...")`` any exception crossing the borrow triggers.
    """

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from openbb_fmp_cached.utils import database  # noqa: PLC0415

        self.database = database
        self.book = _BasePool()
        self.path = tmp_path / "seam.db"
        self.connect_kwargs: list[dict[str, Any]] = []
        self.opened: list[_FakeConnection] = []
        monkeypatch.setattr(database.pymysql, "connect", self._connect)
        self.pool = database.ConnectionPool(_StubDatabaseConfig())

    def _connect(self, **kwargs: Any) -> _FakeConnection:
        self.connect_kwargs.append(kwargs)
        conn = _FakeConnection(
            self.book,
            sqlite3.connect(str(self.path), isolation_level=None),
            len(self.opened) + 1,
            owns_raw=True,
        )
        self.opened.append(conn)
        return conn


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
    seam = _SeamHarness(tmp_path, monkeypatch)

    borrowed = seam.pool.get_connection()
    assert hasattr(borrowed, "__enter__") and hasattr(borrowed, "__exit__")
    assert not hasattr(borrowed, "cursor"), (
        "get_connection() returns a context manager; a store that treats it "
        "as a connection breaks against the real pool"
    )
    with borrowed as conn:
        assert conn is seam.opened[-1]
    assert seam.connect_kwargs[-1]["autocommit"] is True
    assert (
        seam.connect_kwargs[-1]["cursorclass"]
        is seam.database.pymysql.cursors.DictCursor
    )
    assert seam.connect_kwargs[-1]["database"] == "seam_contract_test"

    store = MysqlSnapshotStore(connection_pool=seam.pool)
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.job_run_id == staged[3]
    assert live.state == SnapshotState.LIVE

    assert seam.book.begins >= 2, "writes must open an explicit transaction"
    assert seam.book.closed_with_open_txn == 0
    assert seam.book.returned == len(
        seam.opened
    ), "the pool closes every connection it opens"


# ---------------------------------------------------------------------------
# Lifecycle refusals must not be reported as pool faults (review finding 1)
# ---------------------------------------------------------------------------
#
# `ConnectionPool.get_connection` logs `ERROR MySQL connection error: ...`
# for *anything* that unwinds across the borrow. `_PromotionRefused` /
# `_ValidationRefused` are healthy, expected outcomes of the lifecycle —
# "this candidate ranks below LIVE", "the row moved, retry" — so letting
# them cross that boundary turns every routine refusal into an operator
# page about a database connection that is in fact perfectly healthy, on a
# pool shared with the FMP cache. The refusal must therefore be rolled
# back *inside* the borrow and re-raised only after it has closed.


def _pool_errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Every ``MySQL connection error`` the pool logged, as messages."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == _POOL_LOGGER
        and record.levelno >= logging.ERROR
        and "MySQL connection error" in record.getMessage()
    ]


def test_a_refused_promotion_is_not_reported_to_the_pool_as_an_error(
    store: MysqlSnapshotStore, pool: _FakePool, caplog: pytest.LogCaptureFixture
) -> None:
    """Invariant: a gate refusal never unwinds across ``get_connection``.

    Promoting an unvalidated row is the most routine refusal there is.
    It must still roll back (nothing is written) *and* leave the shared
    pool's error path untouched.
    """
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})

    with caplog.at_level(logging.DEBUG):
        promoted = store.promote(*staged)

    assert promoted is False
    assert [r for r in caplog.records if "promotion refused" in r.getMessage()]
    assert pool.errors == [], (
        "a lifecycle refusal unwound across ConnectionPool.get_connection; "
        "the shared pool logs that as `ERROR MySQL connection error`"
    )
    assert _pool_errors(caplog) == []
    assert pool.rollbacks >= 1, "the refusal must still roll back its transaction"
    assert pool.closed_with_open_txn == 0


def test_a_keep_last_good_refusal_is_not_reported_to_the_pool_as_an_error(
    store: MysqlSnapshotStore, pool: _FakePool, caplog: pytest.LogCaptureFixture
) -> None:
    """Same invariant for the rank gate, which refuses *after* a read."""
    incumbent = _stage(
        store, payload={"rows": [{"symbol": "AAPL"}]}, as_of_session=date(2026, 9, 3)
    )
    assert store.validate(*incumbent).ok
    assert store.promote(*incumbent)

    worse = _stage(
        store,
        payload={"rows": [{"symbol": "MSFT"}]},
        as_of_session=date(2026, 9, 4),
        status=SnapshotStatus.PARTIAL,
    )
    assert store.validate(*worse).ok

    with caplog.at_level(logging.DEBUG):
        promoted = store.promote(*worse)

    assert promoted is False
    assert pool.errors == []
    assert _pool_errors(caplog) == []
    assert store.get_live("techtrade.movers", "sector=technology") is not None


def test_a_refused_validation_is_not_reported_to_the_pool_as_an_error(
    real_store: MysqlSnapshotStore,
    real_pool: _RealisticPool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Invariant: the ``validate()`` race refusal is a refusal, not a fault.

    The row is promoted out of STAGING between the gate's read and its
    write, so ``_ValidationRefused`` unwinds the write transaction. That
    is the store working exactly as designed.
    """
    staged = _stage(real_store, payload={"rows": [{"symbol": "AAPL"}]})
    other = MysqlSnapshotStore(connection_pool=real_pool)

    def _forge(row: SnapshotRow) -> ValidationResult:
        del row
        # Play the concurrent worker from inside the gate: promote the
        # row out of STAGING before our verdict is written.
        assert other.validate(*staged).ok
        assert other.promote(*staged)
        return ValidationResult(ok=True, reason="")

    with caplog.at_level(logging.DEBUG):
        result = real_store.validate(*staged, _forge)

    assert result.ok is False
    assert "changed state between read and write" in result.reason
    assert real_pool.errors == [], (
        "a validation refusal unwound across ConnectionPool.get_connection; "
        "the shared pool logs that as `ERROR MySQL connection error`"
    )
    assert _pool_errors(caplog) == []


def test_refusals_are_invisible_to_the_real_pool_but_driver_faults_are_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Seam contract, both directions, against the production pool class.

    The first half proves the fix: a routine refusal produces no
    ``MySQL connection error`` record from
    ``openbb_fmp_cached.utils.database``. The second half proves the fix
    is not a blanket suppression: a genuine driver failure inside the
    same transaction still reaches the pool and is still logged, because
    that one really is a database fault.
    """
    seam = _SeamHarness(tmp_path, monkeypatch)
    store = MysqlSnapshotStore(connection_pool=seam.pool)
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})

    with caplog.at_level(logging.DEBUG):
        assert store.promote(*staged) is False  # unvalidated -> refusal
    assert _pool_errors(caplog) == []
    assert seam.book.rollbacks >= 1

    caplog.clear()
    seam.book.fail_on = lambda sql, params: sql.startswith("UPDATE pi_eod_snapshot SET")
    with caplog.at_level(logging.DEBUG), pytest.raises(_FakeMysqlError):
        store.validate(*staged)
    assert _pool_errors(caplog), (
        "a real driver failure must still reach the pool's error log — the "
        "refusal fix must not swallow genuine faults"
    )


# ---------------------------------------------------------------------------
# Concurrency: the read -> write window (review findings 1 and 2)
# ---------------------------------------------------------------------------
#
# The single-connection `_FakePool` above cannot express a race: every
# borrow is the same session, so nothing can commit "in between". These
# tests therefore run on `_RealisticPool`, whose `get_connection()`
# returns an independent PyMySQL-shaped session exactly like the real
# pool's, and drive a second actor from the double's `after_execute` hook
# so the interleaving is deterministic rather than timing-dependent.


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
        if sql.lstrip().upper().startswith("UPDATE PI_EOD_SNAPSHOT SET VALIDATED")
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
        if sql.lstrip().upper().startswith("UPDATE PI_EOD_SNAPSHOT SET VALIDATED")
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
    assert real_pool.errors == [], (
        "the collision is a lifecycle refusal the store already downgrades to "
        "False; it must not also unwind across ConnectionPool.get_connection, "
        "which would log it as `ERROR MySQL connection error`"
    )

    rolled_back = real_pool.query(
        "SELECT state FROM pi_eod_snapshot WHERE job_run_id = ?", (mine[3],)
    )
    assert rolled_back == [(SnapshotState.STAGING.value,)]


def _direct_supersede(pool: _RealisticPool, job_run_id: str) -> None:
    """Out-of-band demotion, committed on its own connection."""
    with pool.get_connection() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE pi_eod_snapshot SET state = %s WHERE job_run_id = %s",
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


# ---------------------------------------------------------------------------
# Table identity: no collision with the positions importer (#1963 review C1)
# ---------------------------------------------------------------------------
#
# `portfolio_snapshot_importer` (#1744) ships its own `pi_snapshot` - a
# completely different, account-scoped schema (`snapshot_id`,
# `source_sha256`, `user_id`, plus a `pi_position` FK) - into the *same*
# `openbb_fmp_cache_test` database through the *same* `get_connection_pool()`.
# `CREATE TABLE IF NOT EXISTS` succeeds as a no-op against it, so a shared
# name meant this store constructed healthy and then failed every operation
# with "Unknown column 'dataset'" - while colliding a compute-free shared
# cache with the PII-bearing table design spec 8 / #1965 says it must never
# share.


def _importer_snapshot_ddl() -> str:
    from portfolio_snapshot_importer.mysql_store import (  # noqa: PLC0415
        _PI_SNAPSHOT_DDL as _IMPORTER_DDL,
    )

    return _IMPORTER_DDL


def test_snapshot_table_name_does_not_collide_with_the_positions_importer() -> None:
    """Name regression: the two tables must never share an identifier."""
    ours = _table_name(_PI_EOD_SNAPSHOT_DDL)
    theirs = _table_name(_importer_snapshot_ddl())

    assert ours == "pi_eod_snapshot"
    assert theirs == "pi_snapshot"
    assert ours != theirs, (
        "the EOD snapshot store and the account-scoped positions importer "
        "would share one table in one database"
    )
    # Indexes live in the same namespace on MySQL's information_schema and
    # must not collide either.
    ours_indexes = set(re.findall(r"(?:UNIQUE KEY|INDEX) (\w+)", _PI_EOD_SNAPSHOT_DDL))
    theirs_indexes = set(
        re.findall(r"(?:UNIQUE KEY|INDEX) (\w+)", _importer_snapshot_ddl())
    )
    assert ours_indexes and not (ours_indexes & theirs_indexes)


def test_store_coexists_with_the_positions_importer_table_in_one_database(
    tmp_path: Path,
) -> None:
    """Discriminating: the importer's table is already there, ours still works.

    Reverse-verified: renaming `pi_eod_snapshot` back to `pi_snapshot`
    makes construction raise `SnapshotSchemaMismatch` here (and, without
    the shape check, makes every lifecycle call fail on a missing column).
    """
    pool = _FakePool(tmp_path / "shared.db")
    importer_sql, importer_indexes = _ddl_to_sqlite(_importer_snapshot_ddl())
    pool.raw.execute(importer_sql)
    for index_sql in importer_indexes:
        pool.raw.execute(index_sql)
    pool.raw.execute(
        "INSERT INTO pi_snapshot (snapshot_id, snapshot_date, user_id, "
        "source_filename, source_sha256, imported_at, row_count_raw, "
        "row_count_kept, row_count_skipped, schema_version) VALUES "
        "('snap-1', '2026-09-04', 'user-1', 'positions.csv', 'a' , "
        "'2026-09-04 12:00:00', 3, 3, 0, 1)"
    )

    store = MysqlSnapshotStore(connection_pool=pool)
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.payload["rows"][0]["symbol"] == "AAPL"

    # The importer's row and shape survive untouched.
    assert pool.raw.execute("SELECT COUNT(*) FROM pi_snapshot").fetchone()[0] == 1
    importer_columns = {
        row[1] for row in pool.raw.execute("PRAGMA table_info(pi_snapshot)").fetchall()
    }
    assert "snapshot_id" in importer_columns
    assert "dataset" not in importer_columns


# ---------------------------------------------------------------------------
# Schema shape validation (#1963 review I1)
# ---------------------------------------------------------------------------


def test_mysql_refuses_a_foreign_table_of_the_same_name(tmp_path: Path) -> None:
    """A `pi_eod_snapshot` that is not ours must fail at construction."""
    pool = _FakePool(tmp_path / "foreign.db")
    pool.raw.execute(
        "CREATE TABLE pi_eod_snapshot (snapshot_id TEXT PRIMARY KEY, user_id TEXT)"
    )

    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        MysqlSnapshotStore(connection_pool=pool)

    assert "pi_eod_snapshot" in str(excinfo.value)
    assert "dataset" in str(excinfo.value)


def test_a_schema_refusal_is_not_reported_to_the_pool_as_a_connection_fault(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A misconfigured schema is not a database fault.

    `ConnectionPool.get_connection` logs `ERROR MySQL connection error`
    for anything unwinding across it. The shape refusal is raised after
    the borrow has closed, so the pool the FMP cache shares stays quiet.
    """
    pool = _FakePool(tmp_path / "foreign.db")
    pool.raw.execute(
        "CREATE TABLE pi_eod_snapshot (snapshot_id TEXT PRIMARY KEY, user_id TEXT)"
    )

    with caplog.at_level(logging.ERROR, logger=_POOL_LOGGER), pytest.raises(
        SnapshotSchemaMismatch
    ):
        MysqlSnapshotStore(connection_pool=pool)

    assert pool.errors == []
    assert _pool_errors(caplog) == []


def test_schema_probe_asks_information_schema_for_the_real_table(
    tmp_path: Path,
) -> None:
    """The shape check must interrogate the server, not trust the DDL text."""
    pool = _FakePool(tmp_path / "probe.db")
    MysqlSnapshotStore(connection_pool=pool)

    assert "information_schema" in mysql_store_module._SELECT_SCHEMA_COLUMNS.lower()
    assert "DATABASE()" in mysql_store_module._SELECT_SCHEMA_COLUMNS


# ---------------------------------------------------------------------------
# Schema DDL runs once per pool (#1963 review I3)
# ---------------------------------------------------------------------------


def _create_table_statements(pool: _BasePool) -> list[str]:
    return [
        sql for sql, _ in pool.statements if sql.lstrip().upper().startswith("CREATE")
    ]


def test_repeated_store_construction_does_not_repeat_the_schema_ddl(
    tmp_path: Path,
) -> None:
    """A per-request widget store must not pay a connect + DDL round trip.

    `ConnectionPool.get_connection()` opens a *fresh* `pymysql.connect`
    per borrow, so `_ensure_schema()` on every construction is a real
    handshake, not a cached one.
    """
    pool = _RealisticPool(tmp_path / "once.db")
    MysqlSnapshotStore(connection_pool=pool)
    borrows_after_first = pool.handed_out

    for _ in range(5):
        MysqlSnapshotStore(connection_pool=pool)

    assert pool.handed_out == borrows_after_first, (
        "constructing a store against an already-prepared pool borrowed a "
        "connection again"
    )


def test_a_different_pool_gets_its_own_schema_check(tmp_path: Path) -> None:
    """Discriminating: the once-guard must never span two databases.

    A process-wide boolean would skip the DDL for a *different* config -
    the store would then run against a database with no table at all.
    """
    first = _FakePool(tmp_path / "first.db")
    MysqlSnapshotStore(connection_pool=first)

    second = _FakePool(tmp_path / "second.db")
    store = MysqlSnapshotStore(connection_pool=second)

    assert second.handed_out >= 1, "the second pool was never asked for a connection"
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    assert second.raw.execute("SELECT COUNT(*) FROM pi_eod_snapshot").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Collation is pinned, not inherited (#1963 security review, Alert 2)
# ---------------------------------------------------------------------------
#
# `DEFAULT CHARSET=utf8mb4` with no `COLLATE` resolves to the charset's
# default collation - `utf8mb4_0900_ai_ci` on MySQL 8, `utf8mb4_general_ci`
# on 5.7 - both case- AND accent-insensitive. That silently changes the
# semantics of the only two DB-level guarantees this table has: the
# `ux_pi_eod_snapshot_live` unique key (single LIVE row) and the primary
# key (`job_run_id` identity). The double translates a pinned
# `utf8mb4_bin` to SQLite's BINARY and an *unpinned* column to NOCASE, so
# these assertions fail if the DDL ever loses its COLLATE.

_KEY_COLUMNS = ("dataset", "entity_key", "job_run_id", "status", "state", "live_key")


def test_ddl_pins_binary_collation_on_every_key_column() -> None:
    collations = _column_collations(_PI_EOD_SNAPSHOT_DDL)
    for column in _KEY_COLUMNS:
        assert collations.get(column) == "utf8mb4_bin", (
            f"{column} inherits the charset default collation, which is "
            "case- and accent-insensitive on every supported MySQL version"
        )


def test_ddl_pins_binary_collation_on_the_table_itself() -> None:
    """Belt and braces: a column added later must not silently be _ci."""
    assert re.search(
        r"ENGINE=InnoDB\s+DEFAULT\s+CHARSET=utf8mb4\s+COLLATE=utf8mb4_bin",
        _PI_EOD_SNAPSHOT_DDL,
    )


def test_job_run_id_case_is_significant_on_mysql(store: MysqlSnapshotStore) -> None:
    """Parity: `Run-1` and `run-1` are two rows, not a duplicate-key error.

    `job_run_id` is never canonicalized. Under an `_ci` collation the
    primary key folds the two together: SQLite inserts both, MySQL raises
    `IntegrityError`. That breaks the module's binding parity claim in
    the one place `_check_field_lengths` cannot see.

    Reverse-verified: dropping `COLLATE utf8mb4_bin` from `job_run_id`
    makes the double fold the two ids and this staging call raises.
    """
    _stage(store, payload={"rows": [{"symbol": "AAPL"}]}, job_run_id="run-case")
    _stage(store, payload={"rows": [{"symbol": "AAPL"}]}, job_run_id="Run-Case")

    history = store.list_history("techtrade.movers", "sector=technology")
    assert {row.job_run_id for row in history} == {"run-case", "Run-Case"}


def test_job_run_id_case_is_significant_on_both_backends(
    store: MysqlSnapshotStore, tmp_path: Path
) -> None:
    """The same call must be accepted by both backends, identically."""
    sqlite_store = SqliteSnapshotStore(tmp_path / "parity.db")
    for target in (store, sqlite_store):
        _stage(target, payload={"rows": [{"symbol": "AAPL"}]}, job_run_id="run-parity")
        _stage(target, payload={"rows": [{"symbol": "AAPL"}]}, job_run_id="RUN-PARITY")
        assert len(target.list_history("techtrade.movers", "sector=technology")) == 2
    sqlite_store.close()


def test_the_double_folds_case_when_a_column_is_unpinned(tmp_path: Path) -> None:
    """Guards the guard: without this, the collation tests prove nothing.

    Strips the ``COLLATE`` clauses out of the real DDL and shows the
    double then behaves like MySQL's ``_ci`` default - the two
    ``job_run_id`` values collide on the primary key. If this test ever
    passes *without* raising, the double stopped modelling collation and
    every assertion above became ceremonial.

    Scope note: SQLite's ``NOCASE`` folds ASCII case only, so it models
    the ``_ci`` half of ``utf8mb4_0900_ai_ci``. The accent-insensitive
    half (the ``live_key`` collision path) is pinned statically by
    ``test_ddl_pins_binary_collation_on_every_key_column``; no local
    engine can reproduce MySQL's accent folding.
    """
    unpinned = _PI_EOD_SNAPSHOT_DDL.replace(" COLLATE utf8mb4_bin", "").replace(
        " COLLATE=utf8mb4_bin", ""
    )
    assert "COLLATE" not in unpinned
    table_sql, _ = _ddl_to_sqlite(unpinned)
    conn = sqlite3.connect(str(tmp_path / "unpinned.db"), isolation_level=None)
    conn.execute(table_sql)

    insert = (
        "INSERT INTO pi_eod_snapshot (dataset, entity_key, as_of_session, "
        "created_at, job_run_id, status, state, validated, validation_reason, "
        "payload_json) VALUES (?, ?, '2026-09-04', '2026-09-04 00:00:00', ?, "
        "'ok', 'staging', 0, '', '{}')"
    )
    conn.execute(insert, ("techtrade.movers", "sector=technology", "run-1"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("techtrade.movers", "sector=technology", "Run-1"))
    conn.close()


# ---------------------------------------------------------------------------
# restamp_live is pinned to the row it copied (#1963 review I2)
# ---------------------------------------------------------------------------


def test_restamp_refuses_when_a_real_recompute_wins_the_race(
    real_store: MysqlSnapshotStore,
    real_pool: _RealisticPool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Invariant: a stale copy never supersedes newer content.

    `restamp_live` reads LIVE, then stages / validates / promotes in
    separate transactions - on MySQL, separate pooled borrows. A genuine
    recompute promoting inside that window would be superseded by the
    copy of the *older* payload under a *newer* session date.

    Reverse-verified: with `_promote_expecting_live` reduced to a plain
    `promote()`, the restamp succeeds and LIVE reverts to AAPL.
    """
    original = _stage(
        real_store,
        payload={"rows": [{"symbol": "AAPL"}]},
        as_of_session=date(2026, 9, 3),
    )
    assert real_store.validate(*original).ok
    assert real_store.promote(*original)

    competitor = MysqlSnapshotStore(connection_pool=real_pool)
    fired: list[str] = []
    real_stage = real_store.stage

    def _stage_then_recompute(*args, **kwargs):
        real_stage(*args, **kwargs)
        if fired:
            return
        recompute = _stage(
            competitor,
            payload={"rows": [{"symbol": "NVDA"}]},
            as_of_session=date(2026, 9, 4),
        )
        assert competitor.validate(*recompute).ok
        assert competitor.promote(*recompute)
        fired.append(recompute[3])

    real_store.stage = _stage_then_recompute  # type: ignore[method-assign]

    with caplog.at_level(logging.WARNING, logger=_MYSQL_LOGGER):
        restamped = real_store.restamp_live(
            "techtrade.movers", "sector=technology", date(2026, 9, 5), "run-restamp"
        )

    assert fired, "the interleaving hook never ran - test is inert"
    assert restamped is False
    assert [
        record
        for record in caplog.records
        if "promotion refused" in record.getMessage()
        and "real recompute" in record.getMessage()
    ]

    real_store.stage = real_stage  # type: ignore[method-assign]
    live = real_store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.job_run_id == fired[0]
    assert live.payload["rows"][0]["symbol"] == "NVDA"
    assert real_pool.live_job_run_ids() == [fired[0]]


def test_restamp_still_succeeds_when_live_does_not_move(
    store: MysqlSnapshotStore,
) -> None:
    """Guards the guard: the new gate must not refuse the ordinary path."""
    _live_store(store, input_hash="same-input")
    assert store.restamp_live(
        "techtrade.movers", "sector=technology", date(2026, 9, 6), "run-restamp"
    )
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.as_of_session == date(2026, 9, 6)
    assert live.job_run_id == "run-restamp"


# ---------------------------------------------------------------------------
# prune scoping and statement shape (#1963 review I4)
# ---------------------------------------------------------------------------


def _store_with_two_datasets(store: MysqlSnapshotStore) -> None:
    for dataset in ("techtrade.movers", "techtrade.segments"):
        for symbol, as_of_session in (
            ("AAPL", date(2026, 9, 2)),
            ("MSFT", date(2026, 9, 3)),
            ("GOOG", date(2026, 9, 4)),
        ):
            staged = _stage(
                store,
                payload={"rows": [{"symbol": symbol}]},
                dataset=dataset,
                as_of_session=as_of_session,
            )
            assert store.validate(*staged).ok
            assert store.promote(*staged)


def test_scoped_prune_leaves_a_neighbouring_dataset_untouched(
    store: MysqlSnapshotStore,
) -> None:
    """The table is shared with the FMP cache; a job scopes its own sweep."""
    _store_with_two_datasets(store)

    assert (
        store.prune(RetentionPolicy(keep_sessions=1), dataset="techtrade.movers") == 2
    )

    assert len(store.list_history("techtrade.movers", "sector=technology")) == 1
    assert len(store.list_history("techtrade.segments", "sector=technology")) == 3


def test_unscoped_prune_still_sweeps_every_dataset(store: MysqlSnapshotStore) -> None:
    _store_with_two_datasets(store)
    assert store.prune(RetentionPolicy(keep_sessions=1)) == 4
    assert len(store.list_history("techtrade.movers", "sector=technology")) == 1
    assert len(store.list_history("techtrade.segments", "sector=technology")) == 1


def test_entity_scoped_prune_requires_its_dataset(store: MysqlSnapshotStore) -> None:
    with pytest.raises(ValueError, match="requires dataset"):
        store.prune(RetentionPolicy(keep_sessions=1), entity_key="sector=technology")


def test_prune_is_set_based_not_a_round_trip_per_key(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    """The write transaction is held for a bounded number of statements."""
    for index in range(8):
        for as_of_session in (date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4)):
            staged = _stage(
                store,
                payload={"rows": [{"symbol": "AAPL"}]},
                entity_key=f"sector=sector{index}",
                as_of_session=as_of_session,
            )
            assert store.validate(*staged).ok
            assert store.promote(*staged)

    before = len(pool.statements)
    assert store.prune(RetentionPolicy(keep_sessions=1)) == 16
    issued = [sql for sql, _ in pool.statements[before:]]

    selects = [sql for sql in issued if sql.lstrip().upper().startswith("SELECT")]
    deletes = [sql for sql in issued if sql.lstrip().upper().startswith("DELETE")]
    assert len(selects) == 1, f"one SELECT for the whole sweep, saw {len(selects)}"
    assert len(deletes) == 1, f"one batched DELETE for 8 keys, saw {len(deletes)}"
    assert all("%s" in sql for sql in deletes)


def test_prune_binds_every_scope_and_session_value(
    store: MysqlSnapshotStore, pool: _FakePool
) -> None:
    """No prune value is ever interpolated into SQL text."""
    _store_with_two_datasets(store)
    before = len(pool.statements)
    store.prune(RetentionPolicy(keep_sessions=1), dataset="techtrade.movers")

    for sql, params in pool.statements[before:]:
        assert sql.count("%s") == len(params)
        assert "techtrade.movers" not in sql


@pytest.mark.parametrize("limit", [0, -1])
def test_a_non_positive_history_limit_is_refused(
    store: MysqlSnapshotStore, limit: int
) -> None:
    """`LIMIT -1` is unlimited on SQLite and a syntax error on MySQL."""
    with pytest.raises(ValueError, match="limit"):
        store.list_history("techtrade.movers", "sector=technology", limit=limit)


def test_both_backends_support_the_same_context_manager_protocol(
    store: MysqlSnapshotStore, tmp_path: Path
) -> None:
    """Parity: `with get_default_snapshot_store() as s:` works on either.

    Without `__enter__`/`__exit__` on both, the selector hands back an
    object that supports `with` on one backend and raises `TypeError` on
    the other - which defeats the point of choosing behind a Protocol.
    """
    with store as entered:
        assert entered is store
    with SqliteSnapshotStore(tmp_path / "ctx.db") as sqlite_store:
        assert sqlite_store.get_live("techtrade.movers", "sector=technology") is None


def test_schema_mismatch_and_version_are_public(store: MysqlSnapshotStore) -> None:
    """Callers need to catch the refusal and report the version they speak."""
    from openbb_techtrade import snapshot  # noqa: PLC0415

    del store
    assert snapshot.SnapshotSchemaMismatch is SnapshotSchemaMismatch
    assert "SnapshotSchemaMismatch" in snapshot.__all__
    assert "SNAPSHOT_SCHEMA_VERSION" in snapshot.__all__
    assert snapshot.SNAPSHOT_SCHEMA_VERSION >= 1


# ---------------------------------------------------------------------------
# Live-MySQL smoke coverage (#1963 review I5)
# ---------------------------------------------------------------------------
#
# Everything above runs against a PyMySQL-shaped double over SQLite. The
# double is deliberately strict, but it is still not a MySQL server: nothing
# in this suite has ever asked a real server to parse
# `CHAR(31 USING utf8mb4)` inside a STORED generated column, to accept
# `TINYINT(1)`, or to build a unique key on `live_key VARCHAR(512)` (2048
# bytes under utf8mb4 - fine on InnoDB's modern 3072-byte limit with
# DYNAMIC row format, over the historical 767-byte one) alongside a
# 1791-byte primary key.
#
# These tests are the documented gap. They are skipped by default - stock CI
# has no MySQL - and are the one place the DDL is validated by the engine
# that will actually run it:
#
#     $env:PI_SNAPSHOT_MYSQL_SMOKE = "1"
#     .venv_portfolio\Scripts\python.exe -m pytest `
#         openbb_platform\extensions\techtrade\tests\unit\test_mysql_snapshot_store.py `
#         -m "integration and requires_mysql" -v
#
# Connection parameters come from the shared `fmp_cached` DatabaseConfig
# (`~/.openbb_platform/user_settings.json` or `DB_*` env vars), exactly like
# production. The tests write and then remove rows under a dedicated
# `techtrade.snapshot.smoke` dataset and never touch any other dataset.

_LIVE_SMOKE_ENV = "PI_SNAPSHOT_MYSQL_SMOKE"
_SMOKE_DATASET = "techtrade.snapshot.smoke"

_requires_live_mysql = pytest.mark.skipif(
    os.environ.get(_LIVE_SMOKE_ENV, "").strip().lower() not in ("1", "true", "yes"),
    reason=(
        f"live MySQL smoke test: set {_LIVE_SMOKE_ENV}=1 with a reachable "
        "fmp_cached MySQL to exercise the real server. Skipped by default so "
        "stock CI (no MySQL) stays green - see #1963 review I5."
    ),
)


@contextmanager
def _live_mysql_store() -> Iterator[MysqlSnapshotStore]:
    """Build a store on the real shared pool and clean up its rows after."""
    from openbb_fmp_cached.utils.database import (  # noqa: PLC0415
        get_connection_pool,
    )

    pool = get_connection_pool()
    store = MysqlSnapshotStore(connection_pool=pool)
    try:
        yield store
    finally:
        with pool.get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM pi_eod_snapshot WHERE dataset = %s", (_SMOKE_DATASET,)
            )


@pytest.mark.integration
@pytest.mark.requires_mysql
@_requires_live_mysql
def test_live_mysql_accepts_the_ddl_and_enforces_the_generated_live_key() -> None:
    """The real server parses the DDL and honours the single-LIVE key."""
    with _live_mysql_store() as store:
        staged = _stage(
            store,
            payload={"rows": [{"symbol": "AAPL"}]},
            dataset=_SMOKE_DATASET,
            entity_key="sector=technology",
        )
        assert store.validate(*staged).ok
        assert store.promote(*staged)

        from openbb_fmp_cached.utils.database import (  # noqa: PLC0415
            get_connection_pool,
        )

        with get_connection_pool().get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT live_key FROM pi_eod_snapshot WHERE dataset = %s "
                "AND state = 'live'",
                (_SMOKE_DATASET,),
            )
            live_key = cur.fetchone()["live_key"]
            cur.execute(
                "SELECT COUNT(*) AS n FROM pi_eod_snapshot WHERE dataset = %s "
                "AND state != 'live' AND live_key IS NOT NULL",
                (_SMOKE_DATASET,),
            )
            assert cur.fetchone()["n"] == 0

        assert live_key == f"{_SMOKE_DATASET}\x1fsector=technology"


@pytest.mark.integration
@pytest.mark.requires_mysql
@_requires_live_mysql
def test_live_mysql_round_trips_every_protocol_entry_point() -> None:
    """One smoke pass over all ten Protocol methods on a real server."""
    with _live_mysql_store() as store:
        first = _stage(
            store,
            payload={"rows": [{"symbol": "AAPL"}]},
            dataset=_SMOKE_DATASET,
            entity_key="sector=technology",
            as_of_session=date(2026, 9, 3),
            input_hash="smoke-hash",
            engine_version="smoke-1",
            payload_schema_version="v1",
        )
        assert store.validate(*first).ok
        assert store.promote(*first)

        live = store.get_live(_SMOKE_DATASET, "sector=technology")
        assert live is not None
        assert live.as_of_session == date(2026, 9, 3)
        assert live.created_at.tzinfo is not None
        assert live.created_at.utcoffset().total_seconds() == 0
        assert live.payload == {"rows": [{"symbol": "AAPL"}]}
        assert live.state == SnapshotState.LIVE

        assert store.should_skip(_SMOKE_DATASET, "sector=technology", "smoke-hash")
        assert not store.should_skip(_SMOKE_DATASET, "sector=technology", "other")

        assert store.restamp_live(
            _SMOKE_DATASET, "sector=technology", date(2026, 9, 4), "run-smoke-restamp"
        )
        restamped = store.get_live(_SMOKE_DATASET, "sector=technology")
        assert restamped is not None
        assert restamped.as_of_session == date(2026, 9, 4)
        assert restamped.payload == {"rows": [{"symbol": "AAPL"}]}

        as_of = store.get_as_of(_SMOKE_DATASET, "sector=technology", date(2026, 9, 3))
        assert as_of is not None
        assert as_of.state == SnapshotState.SUPERSEDED

        history = store.list_history(_SMOKE_DATASET, "sector=technology", limit=10)
        assert len(history) == 2

        removed = store.prune(RetentionPolicy(keep_sessions=1), dataset=_SMOKE_DATASET)
        assert removed == 1
        assert store.get_live(_SMOKE_DATASET, "sector=technology") is not None
        store.close()


@pytest.mark.integration
@pytest.mark.requires_mysql
@_requires_live_mysql
def test_live_mysql_pins_binary_collation_on_the_key_columns() -> None:
    """The server reports the collation the DDL asked for, not the default."""
    with _live_mysql_store() as store:
        del store
        from openbb_fmp_cached.utils.database import (  # noqa: PLC0415
            get_connection_pool,
        )

        with get_connection_pool().get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COLUMN_NAME, COLLATION_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                ("pi_eod_snapshot",),
            )
            collations = {
                record["COLUMN_NAME"]: record["COLLATION_NAME"]
                for record in cur.fetchall()
            }

    for column in _KEY_COLUMNS:
        assert (
            collations[column] == "utf8mb4_bin"
        ), f"{column} resolved to {collations[column]!r} on the live server"
