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
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from openbb_techtrade.snapshot import (
    mysql_store as mysql_store_module,
    store as store_module,
)
from openbb_techtrade.snapshot.mysql_store import (
    _PI_EOD_SNAPSHOT_DDL,
    MysqlSnapshotStore,
    _make_mysql_store,
)
from openbb_techtrade.snapshot.store import (
    FIELD_MAX_LENGTHS,
    RetentionPolicy,
    SnapshotFieldTooLong,
    SnapshotPayloadNotAnObject,
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
    column becomes ``COLLATE MYSQL_AI_CI`` — a collation registered on
    every connection the double opens that folds case **and** accents,
    exactly like ``utf8mb4_0900_ai_ci`` (PR #2062 review; ``NOCASE``
    modelled only the case half, so the ``sector=cafe`` /
    ``sector=café`` collision was unreachable in-process).
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

    def _hoist_unique(match: re.Match[str]) -> str:
        indexes.append(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {match.group(1)} "
            f"ON {_table_name(ddl)} ({match.group(2)})"
        )
        return ""

    body = re.sub(r"\n\s*INDEX (\w+) \(([^)]*)\),?", _hoist_index, body)
    # Hoisted rather than left inline as `UNIQUE (...)`: MySQL names its
    # unique keys, and `information_schema.STATISTICS` reports that name.
    # An inline SQLite `UNIQUE` becomes an anonymous
    # `sqlite_autoindex_pi_eod_snapshot_N`, so the double could never
    # answer the production index probe with the name the real server
    # would — and the "index was silently skipped by a no-op'd CREATE
    # TABLE" scenario (which is what `_create_table` models) would look
    # different here than in production.
    body = re.sub(r"\n\s*UNIQUE KEY (\w+) \(([^)]*)\),?", _hoist_unique, body)
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
            # MySQL's utf8mb4 default collation is case- AND
            # accent-insensitive.
            return f"{head} COLLATE {_MYSQL_AI_CI}"
        binary = collation.endswith("_bin")
        return f"{head} COLLATE {'BINARY' if binary else _MYSQL_AI_CI}"

    return _TEXTUAL_COLUMN_RE.sub(_rewrite, body)


# --- The double's stand-in for `utf8mb4_0900_ai_ci` (PR #2062 review) -----
#
# SQLite ships `NOCASE`, which folds ASCII case only. MySQL's charset
# default folds case *and* accents, and the accent half is the more
# dangerous one here: `canonical_key` casefolds, so a `_ci`-only model
# cannot reach the `sector=cafe` / `sector=café` collision on
# `ux_pi_eod_snapshot_live` that the collation guard exists to prevent.
# Registering a real collation on every connection the double opens is
# what makes that scenario reproducible in-process instead of only
# assertable against a live server.
_MYSQL_AI_CI = "MYSQL_AI_CI"

# What a server reports for an unpinned utf8mb4 column: `utf8mb4_0900_ai_ci`
# on MySQL 8, `utf8mb4_general_ci` on 5.7. Either one is case- and
# accent-insensitive; the 8.x name is used because it is what the servers
# this store runs against report.
_MYSQL_DEFAULT_COLLATION = "utf8mb4_0900_ai_ci"
_MYSQL_BINARY_COLLATION = "utf8mb4_bin"


def _ai_ci_key(value: str) -> str:
    """Fold case and strip accents, the way an ``_ai_ci`` collation compares."""
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(
        char for char in decomposed if not unicodedata.combining(char)
    ).casefold()


def _ai_ci_collation(left: str, right: str) -> int:
    """Three-way comparison over :func:`_ai_ci_key`, for ``create_collation``."""
    left_key, right_key = _ai_ci_key(left), _ai_ci_key(right)
    return (left_key > right_key) - (left_key < right_key)


def _connect(path: Path | str, **kwargs: Any) -> sqlite3.Connection:
    """Open a SQLite connection that speaks the double's collations.

    Every connection the double hands out has to know ``MYSQL_AI_CI``:
    SQLite resolves a collation name lazily, so a connection without it
    accepts the ``CREATE TABLE`` and then fails the first comparison with
    ``no such collation sequence`` — which would surface as a driver
    fault in the middle of an unrelated test.
    """
    conn = sqlite3.connect(str(path), **kwargs)
    conn.create_collation(_MYSQL_AI_CI, _ai_ci_collation)
    return conn


# Type names SQLite (and the translated MySQL DDL) uses for character
# data. A column of any other type reports `COLLATION_NAME = NULL` on a
# real server, and the double reproduces that: a `NULL` collation is not
# "unset", it means "this is no longer a character column".
_SQLITE_TEXT_TYPES = frozenset(
    {"TEXT", "VARCHAR", "CHAR", "CLOB", "LONGTEXT", "NVARCHAR", "NCHAR"}
)

_SQLITE_TO_MYSQL_COLLATION = {
    "BINARY": _MYSQL_BINARY_COLLATION,
    "NOCASE": _MYSQL_DEFAULT_COLLATION,
    _MYSQL_AI_CI: _MYSQL_DEFAULT_COLLATION,
}

# One column declaration out of a SQLite `CREATE TABLE`. `[^,\n]*` stops
# the tail at the end of the line, so a generated column's expression
# (which spans lines and contains commas) is never mistaken for part of
# the declaration that precedes it.
_SQLITE_COLUMN_DECL_RE = re.compile(
    r"^\s*(?P<name>\w+)\s+(?P<type>\w+(?:\s*\(\s*\d+\s*\))?)(?P<rest>[^,\n]*)",
    re.M,
)

_SQLITE_COLLATE_RE = re.compile(r"\bCOLLATE\s+(\w+)", re.I)

# Words that begin a line of a `CREATE TABLE` without naming a column.
_NON_COLUMN_LINE_HEADS = _NON_COLUMN_TOKENS | {"CREATE", "CHECK"}


def _declared_collations(table_sql: str) -> dict[str, str | None]:
    """Map ``column -> the collation MySQL would report`` for a SQLite table.

    SQLite exposes a column's collation nowhere in ``pragma_table_info``
    — only in ``sqlite_master.sql`` — so the declaration text is parsed
    here and translated back into MySQL's vocabulary: ``COLLATE BINARY``
    is what a pinned ``utf8mb4_bin`` becomes, ``COLLATE MYSQL_AI_CI``
    (and ``NOCASE``) is what an unpinned column becomes, and a character
    column with no ``COLLATE`` at all is BINARY, which is SQLite's own
    default and therefore what the double genuinely enforces.
    """
    collations: dict[str, str | None] = {}
    for match in _SQLITE_COLUMN_DECL_RE.finditer(table_sql or ""):
        name = match.group("name")
        if name.upper() in _NON_COLUMN_LINE_HEADS:
            continue
        base = re.sub(r"\s*\(.*", "", match.group("type")).upper()
        if base not in _SQLITE_TEXT_TYPES:
            collations[name] = None
            continue
        clause = _SQLITE_COLLATE_RE.search(match.group("rest"))
        declared = clause.group(1).upper() if clause is not None else "BINARY"
        collations[name] = _SQLITE_TO_MYSQL_COLLATION.get(declared, declared.lower())
    return collations


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
_ALTER_COMMENT_RE = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?P<table>\w+)\s+COMMENT\s*=\s*%s\s*$", re.I
)
_ENGINE_RE = re.compile(r"\bENGINE\s*=\s*(?P<engine>[A-Za-z0-9_]+)", re.I)
_INDEX_COLUMNS_RE = re.compile(r"\bON\s+\w+\s*\(", re.I)


def _index_terms(index_sql: str | None) -> tuple[str, ...]:
    """Return top-level index terms from SQLite's stored CREATE INDEX SQL."""
    if index_sql is None:
        return ()
    match = _INDEX_COLUMNS_RE.search(index_sql)
    if match is None:
        return ()
    terms: list[str] = []
    current: list[str] = []
    depth = 1
    quote: str | None = None
    index = match.end()
    while index < len(index_sql):
        char = index_sql[index]
        if quote is not None:
            current.append(char)
            if char == quote:
                if index + 1 < len(index_sql) and index_sql[index + 1] == quote:
                    current.append(index_sql[index + 1])
                    index += 1
                else:
                    quote = None
            elif char == "\\" and index + 1 < len(index_sql):
                current.append(index_sql[index + 1])
                index += 1
        elif char in ("'", '"', "`"):
            quote = char
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            if depth == 0:
                terms.append("".join(current).strip())
                return tuple(terms)
            current.append(char)
        elif char == "," and depth == 1:
            terms.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    raise AssertionError(f"unterminated CREATE INDEX column list: {index_sql!r}")


# The double's stand-in for MySQL's data dictionary. SQLite has no table
# comments or storage-engine metadata, so `information_schema.TABLES` is
# modelled by a side table *in the same database file* — see
# `_FakeCursor._alter_table` for why the file, and not the pool object, is
# the right home for it.
_DICTIONARY_TABLE = "_fake_information_schema_tables"

# `pragma_table_xinfo`'s `hidden` flag: 2 = VIRTUAL generated, 3 = STORED
# generated. Anything else is an ordinary (or hidden-for-other-reasons)
# column, which is what MySQL reports as an empty `GENERATION_EXPRESSION`.
_SQLITE_GENERATED = frozenset({2, 3})

# A generated column's expression survives only in `sqlite_master.sql`.
# `[^,]*?` covers the declaration between the column name and `GENERATED`
# (type, width, collation) — that stretch never contains a comma, while
# the expression itself does; the non-greedy tail then stops at the first
# `)` that is followed by STORED/VIRTUAL, i.e. the closing paren of the
# expression rather than of anything nested inside it.
_GENERATED_COLUMN_RE = re.compile(
    r"^\s*(?P<name>\w+)\b[^,]*?GENERATED ALWAYS AS\s*\((?P<expr>.*?)\)\s*"
    r"(?:STORED|VIRTUAL)",
    re.I | re.M | re.S,
)


def _generated_expressions(table_sql: str) -> dict[str, str]:
    """Map ``column -> generation expression`` out of a ``CREATE TABLE``."""
    return {
        match.group("name"): " ".join(match.group("expr").split())
        for match in _GENERATED_COLUMN_RE.finditer(table_sql or "")
    }


def _ensure_dictionary(cursor: sqlite3.Cursor) -> None:
    """Create the double's ``information_schema.TABLES`` stand-in once."""
    cursor.execute(
        f"CREATE TABLE IF NOT EXISTS {_DICTIONARY_TABLE} ("
        "table_name TEXT PRIMARY KEY, table_comment TEXT, table_engine TEXT)"
    )


def _record_table_metadata(
    cursor: sqlite3.Cursor,
    table: str,
    *,
    comment: str | None,
    engine: str | None,
) -> None:
    """Record the TABLES row a real MySQL server would expose."""
    _ensure_dictionary(cursor)
    cursor.execute(
        f"INSERT INTO {_DICTIONARY_TABLE} "
        "(table_name, table_comment, table_engine) VALUES (?, ?, ?) "
        "ON CONFLICT(table_name) DO UPDATE SET "
        "table_comment = excluded.table_comment, "
        "table_engine = excluded.table_engine",
        (table, comment, engine),
    )


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
        # A result set the double computed in Python because SQLite's
        # catalogue cannot express it as one query (see `_select_columns`).
        # `None` means "read from the real cursor".
        self._answered: list[dict[str, Any]] | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def rowcount(self) -> int:
        """Rows *changed*, as PyMySQL reports without ``CLIENT.FOUND_ROWS``."""
        return self._cursor.rowcount if self._changed is None else self._changed

    def execute(self, sql: str, params: Any = None) -> None:
        self._answered = None
        if sql.lstrip().upper().startswith("CREATE TABLE"):
            self._create_table(sql)
            return
        bound = tuple(params or ())
        if sql.count("%s") != len(bound):
            raise _FakeProgrammingError(
                f"Not all parameters were used in the SQL statement: "
                f"{sql.count('%s')} placeholders vs {len(bound)} params"
            )
        if sql.lstrip().upper().startswith("ALTER TABLE"):
            self._alter_table(sql, bound)
            return
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
        engine_match = _ENGINE_RE.search(sql)
        _record_table_metadata(
            self._cursor,
            _table_name(sql),
            comment="",
            engine=engine_match.group("engine") if engine_match is not None else None,
        )

    def _describe_table(self, sql: str, bound: tuple) -> None:
        """Answer the production ``information_schema`` probes.

        The store asks four real MySQL questions — ``SELECT COLUMN_NAME,
        GENERATION_EXPRESSION FROM information_schema.COLUMNS ...`` for
        the table's shape and which of its columns are *generated*,
        ``SELECT ... FROM information_schema.STATISTICS ...`` for its
        indexes, and ``SELECT TABLE_COMMENT, ENGINE FROM
        information_schema.TABLES ...`` for its schema-version stamp and
        storage engine, plus ``information_schema.TRIGGERS`` for probe
        safety — and the double answers all four from SQLite's own catalogue
        rather than the store softening its queries into something portable.
        A table that does not exist yields no rows from any of them, exactly
        as ``information_schema`` does.
        """
        if "TABLE_COMMENT" in sql or "ENGINE" in sql:
            self._select_table_metadata(bound)
            return
        if "TRIGGERS" in sql:
            self._select_triggers(bound)
            return
        if "STATISTICS" in sql:
            self._select_indexes(bound)
            return
        assert "COLUMN_NAME" in sql, f"unexpected information_schema query: {sql!r}"
        self._select_columns(bound)

    def _select_columns(self, bound: tuple) -> None:
        """Answer the shape + generated-column + collation probe from SQLite.

        ``information_schema.COLUMNS.GENERATION_EXPRESSION`` is ``''``
        for an ordinary column and the (server-normalized) expression
        text for a generated one. SQLite exposes *that a column is
        generated* through ``pragma_table_xinfo``'s ``hidden`` flag (2 =
        VIRTUAL, 3 = STORED) but never the expression itself, which only
        survives in ``sqlite_master.sql`` — so the two sources are joined
        here. Reproducing the distinction is what makes the "``live_key``
        exists but is an ordinary column" test discriminating rather than
        ceremonial: an ordinary column of that name would satisfy any
        check that merely asked whether the name is present.

        ``COLLATION_NAME`` comes from the same ``sqlite_master.sql``, for
        the same reason — no pragma reports it — translated back into
        MySQL's vocabulary by :func:`_declared_collations`. A
        non-character column reports ``NULL``, exactly as the server
        does, which is what lets the "someone redeclared ``job_run_id``
        as a BLOB" refusal be tested at all (PR #2062 review).
        """
        table = bound[0]
        record = self._cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        table_sql = record[0] if record else ""
        expressions = _generated_expressions(table_sql)
        collations = _declared_collations(table_sql)
        columns = self._cursor.execute(
            "SELECT name, hidden FROM pragma_table_xinfo(?)", (table,)
        ).fetchall()
        self._answer(
            [
                {
                    "COLUMN_NAME": name,
                    "GENERATION_EXPRESSION": (
                        expressions.get(name, "") if hidden in _SQLITE_GENERATED else ""
                    ),
                    "COLLATION_NAME": collations.get(name),
                }
                for name, hidden in columns
            ]
        )

    def _select_indexes(self, bound: tuple) -> None:
        """Answer the index probe the way ``information_schema.STATISTICS`` does.

        One row per *(index, column)* pair, ``NON_UNIQUE`` inverted from
        SQLite's ``unique`` flag, ``SEQ_IN_INDEX`` 1-based. SQLite's
        implicit ``PRIMARY KEY`` index shows up here just as MySQL's
        ``PRIMARY`` does, which is what keeps a test that hopes the
        primary key will be mistaken for the single-LIVE guard honest.
        Functional parts report ``COLUMN_NAME = NULL`` plus ``EXPRESSION``;
        ``SUB_PART`` is populated from the pool's explicit MySQL metadata
        overlay because SQLite has no prefix-index syntax.
        """
        table = bound[0]
        indexes = self._cursor.execute(
            'SELECT name, "unique" FROM pragma_index_list(?) ORDER BY name',
            (table,),
        ).fetchall()
        rows: list[dict[str, Any]] = []
        for index_name, unique in indexes:
            sql_row = self._cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
                (index_name,),
            ).fetchone()
            terms = _index_terms(sql_row[0] if sql_row is not None else None)
            parts = self._cursor.execute(
                "SELECT seqno, name, key FROM pragma_index_xinfo(?) ORDER BY seqno",
                (index_name,),
            ).fetchall()
            for seqno, column_name, is_key in parts:
                if not is_key:
                    continue
                rows.append(
                    {
                        "INDEX_NAME": index_name,
                        "NON_UNIQUE": 0 if unique else 1,
                        "SEQ_IN_INDEX": seqno + 1,
                        "COLUMN_NAME": column_name,
                        "EXPRESSION": (
                            terms[seqno]
                            if column_name is None and seqno < len(terms)
                            else None
                        ),
                        "SUB_PART": self._conn._book.mysql_index_sub_parts.get(
                            (index_name, seqno + 1)
                        ),
                    }
                )
        self._answer(rows)

    def _select_triggers(self, bound: tuple) -> None:
        """Answer the trigger probe from SQLite's actual trigger catalogue."""
        rows = self._cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'trigger' AND tbl_name = ? ORDER BY name",
            bound,
        ).fetchall()
        self._answer([{"TRIGGER_NAME": trigger_name} for (trigger_name,) in rows])

    def _select_table_metadata(self, bound: tuple) -> None:
        """Read a table's ``COMMENT`` and ``ENGINE`` from the fake dictionary.

        MySQL returns exactly one row per existing table — ``''`` when
        the table carries no comment and a canonical storage-engine name —
        and *no* row for a table that does not exist. Those distinctions
        are reproduced here because the production code treats missing,
        NULL, and non-InnoDB engine metadata as separate refusal evidence.
        """
        _ensure_dictionary(self._cursor)
        self._cursor.execute(
            "SELECT COALESCE(d.table_comment, '') AS TABLE_COMMENT, "
            "d.table_engine AS ENGINE "
            f"FROM sqlite_master AS m LEFT JOIN {_DICTIONARY_TABLE} AS d "
            "ON d.table_name = m.name "
            "WHERE m.type = 'table' AND m.name = ?",
            bound,
        )
        self._executed = None

    def _alter_table(self, sql: str, bound: tuple) -> None:
        """Apply ``ALTER TABLE <t> COMMENT = %s`` to the data dictionary.

        SQLite has no table comments, so the double keeps them in a side
        table *inside the same database file*. That placement is
        load-bearing: MySQL's comment lives in the server's data
        dictionary, so it is visible to every connection and every pool
        that opens the database, and it outlives the process that wrote
        it. A dict on the pool object would model none of that, and the
        cross-build tests (an old binary meeting a table a newer binary
        stamped) would silently degenerate into same-object bookkeeping.
        """
        self._conn.record(sql, bound)
        match = _ALTER_COMMENT_RE.match(sql)
        if match is None:  # pragma: no cover - keeps the double honest
            raise _FakeProgrammingError(
                f"the double only models `ALTER TABLE <t> COMMENT = %s`: {sql!r}"
            )
        _ensure_dictionary(self._cursor)
        self._cursor.execute(
            f"INSERT INTO {_DICTIONARY_TABLE} (table_name, table_comment) "
            "VALUES (?, ?) ON CONFLICT(table_name) DO UPDATE SET "
            "table_comment = excluded.table_comment",
            (match.group("table"), bound[0]),
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

    def _answer(self, rows: list[dict[str, Any]]) -> None:
        """Stage a result set the double assembled itself, in driver shape."""
        self._answered = rows
        self._executed = None

    def fetchone(self) -> Any:
        if self._answered is not None:
            return self._answered.pop(0) if self._answered else None
        return self._shape(self._cursor.fetchone())

    def fetchall(self) -> list[Any]:
        if self._answered is not None:
            rows, self._answered = self._answered, []
            return rows
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
        self.mysql_index_sub_parts: dict[tuple[str, int], int] = {}
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
        self.raw = _connect(str(path), isolation_level=None)

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
        raw = _connect(self.path, timeout=1.0, isolation_level=None)
        return _FakeConnection(self, raw, next(self._ids), owns_raw=True)

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Out-of-band read for assertions (its own short-lived connection)."""
        conn = _connect(self.path, timeout=1.0)
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


def _direct_insert(
    pool: _BasePool,
    *,
    job_run_id: str,
    state: str,
    payload_json: str = '{"rows": [{"symbol": "GOOG"}]}',
) -> None:
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
                        payload_json,
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
    statements_before = len(pool.statements)
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
        sql
        for sql, _ in pool.statements[statements_before:]
        if sql.lstrip().upper().startswith("INSERT")
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
# Payload must be a JSON object, not just typed as one (#2062 review)
# ---------------------------------------------------------------------------
#
# Mirrors ``test_snapshot_store.py``'s equivalent section: both backends
# fall through the same shared ``_dumps_payload``/``_as_payload`` pair, so
# the guard is exercised here against the MySQL double for parity, using
# the identical non-dict/corrupted-JSON fixtures.

_NON_DICT_PAYLOADS = [
    pytest.param(["rows", {"symbol": "AAPL"}], id="list"),
    pytest.param("just a string", id="scalar-str"),
    pytest.param(42, id="scalar-int"),
    pytest.param(None, id="null"),
]


@pytest.mark.parametrize("bad_payload", _NON_DICT_PAYLOADS)
def test_stage_refuses_a_non_dict_payload(
    store: MysqlSnapshotStore, pool: _FakePool, bad_payload: object
) -> None:
    """A list/scalar/``None`` payload is refused, and nothing is written."""
    begins_before = pool.begins
    statements_before = len(pool.statements)
    with pytest.raises(SnapshotPayloadNotAnObject) as excinfo:
        store.stage(
            "techtrade.movers",
            "sector=technology",
            date(2026, 9, 4),
            "run-1",
            bad_payload,  # type: ignore[arg-type]
        )
    assert "payload must be a JSON object" in str(excinfo.value)
    assert type(bad_payload).__name__ in str(excinfo.value)
    # The refusal lands before the driver is touched at all -- see the
    # matching field-length test above for why this is asserted
    # independently of the exception type.
    assert pool.begins == begins_before
    inserts = [
        sql
        for sql, _ in pool.statements[statements_before:]
        if sql.lstrip().upper().startswith("INSERT")
    ]
    assert inserts == []


def test_stage_accepts_and_round_trips_a_nested_dict_payload(
    store: MysqlSnapshotStore,
) -> None:
    """A dict payload -- including nested lists/dicts/``None`` values -- survives."""
    nested_payload = {
        "rows": [
            {"symbol": "AAPL", "close": 227.5, "flags": None},
            {"symbol": "MSFT", "meta": {"sector": "tech", "tags": ["a", "b"]}},
        ],
        "summary": {"count": 2, "as_of": "2026-09-04"},
    }
    staged = _stage(store, payload=nested_payload)
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.payload == nested_payload


_CORRUPTED_PAYLOAD_JSON = [
    pytest.param("[1, 2, 3]", id="list"),
    pytest.param('"just a string"', id="scalar-str"),
    pytest.param("42", id="scalar-int"),
    pytest.param("null", id="null"),
    pytest.param("{not valid json", id="invalid-syntax"),
]


@pytest.mark.parametrize("payload_json", _CORRUPTED_PAYLOAD_JSON)
def test_get_live_rejects_a_persisted_non_object_payload(
    store: MysqlSnapshotStore, pool: _FakePool, payload_json: str
) -> None:
    """A corrupted/non-object persisted payload fails loudly on read.

    Regression test for PR #2062 review: the shared decoder used to hand
    back whatever ``json.loads`` returned, so a list/scalar/``None`` (or
    invalid JSON) persisted under ``payload_json`` would silently violate
    ``SnapshotRow.payload``'s ``dict`` contract instead of raising here.
    """
    _direct_insert(
        pool, job_run_id="run-corrupt", state="live", payload_json=payload_json
    )
    with pytest.raises(SnapshotPayloadNotAnObject) as excinfo:
        store.get_live("techtrade.movers", "sector=technology")
    assert "payload must be a JSON object" in str(excinfo.value)


@pytest.mark.parametrize("payload_json", _CORRUPTED_PAYLOAD_JSON)
def test_list_history_rejects_a_persisted_non_object_payload(
    store: MysqlSnapshotStore, pool: _FakePool, payload_json: str
) -> None:
    """The same guard applies to every read path, not just ``get_live``."""
    _direct_insert(
        pool,
        job_run_id="run-corrupt-history",
        state="staging",
        payload_json=payload_json,
    )
    with pytest.raises(SnapshotPayloadNotAnObject):
        store.list_history("techtrade.movers", "sector=technology")


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
    """Both backends are reachable by explicit attribute/import.

    ``MysqlSnapshotStore`` is deliberately *not* listed in ``__all__``
    (PR #2062 review) so that ``from openbb_techtrade.snapshot import *``
    cannot trigger the deferred MySQL import on a SQLite-only install;
    see ``test_snapshot_star_import_omits_the_optional_mysql_backend``
    in ``test_snapshot_store.py`` for the discriminating regression
    test. Explicit access -- ``snapshot.MysqlSnapshotStore`` or
    ``from openbb_techtrade.snapshot import MysqlSnapshotStore`` -- is
    unaffected, because both resolve the single named attribute through
    ``__getattr__`` directly, without consulting ``__all__``.
    """
    from openbb_techtrade import snapshot  # noqa: PLC0415

    assert snapshot.MysqlSnapshotStore is MysqlSnapshotStore
    assert snapshot.SqliteSnapshotStore is SqliteSnapshotStore
    assert "MysqlSnapshotStore" not in snapshot.__all__
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
            _connect(str(self.path), isolation_level=None),
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
# A caller's duplicate key is a caller bug, not a connection fault
# (#1963 whole-branch review)
# ---------------------------------------------------------------------------
#
# `stage()` writes one row keyed `(dataset, entity_key, as_of_session,
# job_run_id)`. Reusing a `job_run_id` for the same session violates that
# primary key: a bug in the *caller* — the job scheduled two runs under one
# id. The store must surface it unchanged (never swallow it: the second
# payload really was not written) while keeping it out of the shared pool's
# `ERROR MySQL connection error` path, which pages an operator about the
# FMP cache's database. Same treatment as a lifecycle refusal: roll back
# inside the borrow, re-raise after it closes.


def test_a_duplicate_stage_is_the_callers_error_not_a_pool_fault(
    store: MysqlSnapshotStore, pool: _FakePool, caplog: pytest.LogCaptureFixture
) -> None:
    """Raised to the caller, invisible to the pool, and nothing written."""
    _stage(store, payload={"rows": [{"symbol": "AAPL"}]}, job_run_id="run-dupe")
    rollbacks_before = pool.rollbacks

    with caplog.at_level(logging.DEBUG), pytest.raises(_FakeIntegrityError):
        _stage(store, payload={"rows": [{"symbol": "MSFT"}]}, job_run_id="run-dupe")

    assert pool.errors == [], (
        "a caller's duplicate key unwound across ConnectionPool."
        "get_connection; the shared pool logs that as a connection error"
    )
    assert _pool_errors(caplog) == []
    assert pool.rollbacks == rollbacks_before + 1, "the failed write must roll back"
    assert pool.closed_with_open_txn == 0
    history = store.list_history("techtrade.movers", "sector=technology")
    assert len(history) == 1, "the duplicate must not have been written"
    assert history[0].payload["rows"][0]["symbol"] == "AAPL"


def test_a_duplicate_stage_against_the_real_pool_is_raised_but_not_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The same claim, against the production ``ConnectionPool`` class.

    The double's `errors` list only proves the store agrees with the
    double. This drives the real borrow protocol, whose
    ``logger.error("MySQL connection error: ...")`` is the thing an
    operator actually sees.
    """
    seam = _SeamHarness(tmp_path, monkeypatch)
    store = MysqlSnapshotStore(connection_pool=seam.pool)
    _stage(store, payload={"rows": [{"symbol": "AAPL"}]}, job_run_id="run-dupe")

    with caplog.at_level(logging.DEBUG), pytest.raises(_FakeIntegrityError) as excinfo:
        _stage(store, payload={"rows": [{"symbol": "MSFT"}]}, job_run_id="run-dupe")

    assert "UNIQUE" in str(excinfo.value) or "unique" in str(excinfo.value).lower()
    assert _pool_errors(caplog) == []
    assert seam.book.rollbacks >= 1
    assert seam.book.closed_with_open_txn == 0


def test_a_genuine_driver_fault_during_stage_still_reaches_the_pool(
    store: MysqlSnapshotStore, pool: _FakePool, caplog: pytest.LogCaptureFixture
) -> None:
    """Guards the guard: the hold-back is narrow, not blanket suppression.

    Only an ``IntegrityError`` is a caller bug. A connection reset, a
    lock-wait timeout or a disk-full error on the very same statement
    really is a database fault, and must still cross the borrow so the
    shared pool logs it. Reverse-verified: widening the hold-back in
    ``transaction()`` to ``except Exception`` fails this test.
    """
    pool.fail_on = lambda sql, params: sql.startswith("INSERT INTO pi_eod_snapshot")

    with caplog.at_level(logging.DEBUG), pytest.raises(_FakeMysqlError) as excinfo:
        _stage(store, payload={"rows": [{"symbol": "AAPL"}]}, job_run_id="run-fault")

    assert not isinstance(excinfo.value, _FakeIntegrityError)
    assert _pool_errors(caplog), (
        "a real driver failure must still reach the pool's error log — "
        "holding integrity errors back must not swallow genuine faults"
    )
    assert pool.rollbacks >= 1
    assert pool.closed_with_open_txn == 0


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
    _record_table_metadata(
        pool.raw.cursor(),
        "pi_eod_snapshot",
        comment=None,
        engine="InnoDB",
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
    _record_table_metadata(
        pool.raw.cursor(),
        "pi_eod_snapshot",
        comment=None,
        engine="InnoDB",
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
# Single-LIVE guard verification on MySQL (PR #2062 review)
# ---------------------------------------------------------------------------
#
# The shape check asks only "is every *shared* column present?", and the
# version check asks only "who stamped this table?". Neither can see the
# object that actually enforces "at most one LIVE row per (dataset,
# entity_key)" on MySQL: the generated `live_key` column plus its UNIQUE
# KEY. That matters because `CREATE TABLE IF NOT EXISTS` no-ops against a
# pre-existing table -- and MySQL declares its indexes *inside* CREATE
# TABLE, so the no-op silently skips them too. A table with the fourteen
# shared columns and no guard therefore used to construct cleanly, get
# stamped with this build's version, and then let two concurrent promotes
# install two LIVE rows for one key.
#
# Every test below builds a *specific* malformed table and asserts
# construction refuses it. Each one is a mutation of exactly one part of
# the guard, so together they pin all three failure modes:
# missing column / column present but not generated / index missing,
# non-unique, or over the wrong columns.

# The fourteen dialect-independent columns, in the double's SQLite
# vocabulary. Written out rather than derived from `_PI_EOD_SNAPSHOT_DDL`
# on purpose: these tests need to vary the *guard* while holding the shape
# constant, which means the shape has to be something a test can hold.
_BASE_COLUMNS_SQL = """
    dataset                TEXT NOT NULL,
    entity_key             TEXT NOT NULL,
    as_of_session          TEXT NOT NULL,
    created_at             TEXT NOT NULL,
    job_run_id             TEXT NOT NULL,
    status                 TEXT NOT NULL,
    state                  TEXT NOT NULL,
    validated              INTEGER NOT NULL DEFAULT 0,
    validation_reason      TEXT NOT NULL DEFAULT '',
    payload_json           TEXT NOT NULL,
    input_hash             TEXT,
    row_count              INTEGER,
    engine_version         TEXT,
    payload_schema_version TEXT
"""

_GOOD_LIVE_KEY_SQL = (
    "live_key TEXT GENERATED ALWAYS AS "
    "(IIF(state = 'live', concat(dataset, char(31), entity_key), NULL)) STORED"  # codespell:ignore
)


def _seed_table(
    path: Path,
    *,
    columns_sql: str = _BASE_COLUMNS_SQL,
    live_key_sql: str | None = _GOOD_LIVE_KEY_SQL,
    index_sql: str | None = (
        "CREATE UNIQUE INDEX ux_pi_eod_snapshot_live ON pi_eod_snapshot(live_key)"
    ),
    comment: str | None = None,
    engine: str | None = "InnoDB",
) -> None:
    """Pre-create a `pi_eod_snapshot` with a chosen guard (or none)."""
    columns = columns_sql.rstrip()
    if live_key_sql is not None:
        columns = f"{columns},\n    {live_key_sql}"
    conn = _connect(str(path), isolation_level=None)
    try:
        conn.execute(
            f"CREATE TABLE pi_eod_snapshot ({columns},\n"
            "    PRIMARY KEY (dataset, entity_key, as_of_session, job_run_id))"
        )
        if index_sql is not None:
            conn.execute(index_sql)
        _record_table_metadata(
            conn.cursor(),
            "pi_eod_snapshot",
            comment=comment,
            engine=engine,
        )
    finally:
        conn.close()


def _seed_table_with_columns(path: Path, columns_sql: str, **seed: Any) -> None:
    """Seed a shape-correct table whose *column declarations* were varied.

    The collation tests need to hold the guard, the index and the shape
    constant while changing exactly one column's ``COLLATE`` clause, which
    is the opposite of what the guard tests need. Naming that explicitly
    keeps the two families from quietly reaching into each other.
    """
    _seed_table(path, columns_sql=columns_sql, **seed)


def _redeclare(column: str, declaration: str) -> str:
    """Return `_BASE_COLUMNS_SQL` with one column's type clause replaced.

    Matching on the column name rather than on a fixed-width slice keeps
    these mutations working if the shared column block is ever re-aligned
    — a silently-unapplied mutation would turn every test built on it
    into a test of the *correct* table.
    """
    pattern = re.compile(rf"^(\s*{re.escape(column)}\s+)TEXT\b", re.M)
    updated, count = pattern.subn(
        lambda m: f"{m.group(1)}{declaration}", _BASE_COLUMNS_SQL
    )
    assert count == 1, f"{column} not found in the seeded column list"
    return updated


def _refusal(tmp_path: Path, name: str, **seed: Any) -> str:
    """Seed a malformed table, construct, and return the refusal message."""
    db_path = tmp_path / f"{name}.db"
    _seed_table(db_path, **seed)
    pool = _FakePool(db_path)
    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        MysqlSnapshotStore(connection_pool=pool)
    message = str(excinfo.value)
    assert "single-LIVE" in message
    assert "pi_eod_snapshot" in message
    return message


def test_mysql_accepts_the_guard_its_own_ddl_creates(tmp_path: Path) -> None:
    """Control: the positive path is not vacuous.

    The refusal tests below are only meaningful if the *correct* table
    passes, and only if the double genuinely reports the guard the
    production probe asks for. Both are asserted here, against the table
    the production DDL built.
    """
    pool = _FakePool(tmp_path / "good.db")
    MysqlSnapshotStore(connection_pool=pool)

    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            mysql_store_module._SELECT_SCHEMA_COLUMNS, (store_module._SNAPSHOT_TABLE,)
        )
        generation = {
            record["COLUMN_NAME"]: record["GENERATION_EXPRESSION"] or ""
            for record in cur.fetchall()
        }
        cur.execute(
            mysql_store_module._SELECT_SCHEMA_INDEXES, (store_module._SNAPSHOT_TABLE,)
        )
        indexes = mysql_store_module._index_shapes(cur.fetchall())

    # `live_key` is reported as a *generated* column, expression and all —
    # and its expression canonicalizes onto the one the guard demands, so
    # the structural comparison in `_check_mysql_live_guard` is satisfied
    # by the real schema rather than only by the refusal tests below.
    assert "live_key" in generation
    assert store_module._is_mysql_live_key_expression(generation["live_key"])
    # ... and its UNIQUE index is reported under the name MySQL would use.
    guard = [index for index in indexes if index.name == "ux_pi_eod_snapshot_live"]
    assert guard == [
        store_module._IndexShape(
            name="ux_pi_eod_snapshot_live",
            unique=True,
            columns=("live_key",),
            expressions=(None,),
            sub_parts=(None,),
        )
    ]
    # The primary key is visible too, and must not be mistaken for it.
    assert any(
        index.unique and index.columns[:2] == ("dataset", "entity_key")
        for index in indexes
        if index.name != "ux_pi_eod_snapshot_live"
    )


# ---------------------------------------------------------------------------
# Transactional storage-engine verification (PR #2062 final review)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("engine", "reported"),
    [
        pytest.param("MyISAM", "MyISAM", id="myisam"),
        pytest.param("MEMORY", "MEMORY", id="other-nontransactional"),
        pytest.param(None, "NULL", id="null"),
    ],
)
def test_mysql_refuses_a_non_innodb_storage_engine(
    tmp_path: Path, engine: str | None, reported: str
) -> None:
    """Rollback-only verification is valid only for an InnoDB table."""
    db_path = tmp_path / f"{reported.lower()}_engine.db"
    _seed_table(db_path, engine=engine)

    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        MysqlSnapshotStore(connection_pool=_FakePool(db_path))

    message = str(excinfo.value)
    assert "InnoDB" in message
    assert reported in message
    assert "pi_eod_snapshot" in message


@pytest.mark.parametrize(
    ("metadata", "reported"),
    [
        pytest.param(None, "missing", id="missing-row"),
        pytest.param({"TABLE_COMMENT": ""}, "missing", id="missing-engine-field"),
        pytest.param(
            {"TABLE_COMMENT": "", "ENGINE": None},
            "NULL",
            id="null-engine-field",
        ),
    ],
)
def test_mysql_refuses_missing_storage_engine_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metadata: dict[str, Any] | None,
    reported: str,
) -> None:
    """Missing dictionary evidence must not be treated as transactional."""

    def _answer_metadata(cur: _FakeCursor, _bound: tuple) -> None:
        cur._answer([] if metadata is None else [dict(metadata)])

    monkeypatch.setattr(_FakeCursor, "_select_table_metadata", _answer_metadata)
    pool = _FakePool(tmp_path / "missing_engine_metadata.db")

    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        MysqlSnapshotStore(connection_pool=pool)

    message = str(excinfo.value)
    assert "InnoDB" in message
    assert reported in message


def test_mysql_checks_engine_before_probe_stamp_or_ready_mark(tmp_path: Path) -> None:
    """A MyISAM table receives no rollback-only writes or schema adoption."""
    db_path = tmp_path / "ordering.db"
    original_comment = "operator-owned legacy table"
    _seed_table(db_path, comment=original_comment, engine="MyISAM")
    pool = _FakePool(db_path)

    with pytest.raises(SnapshotSchemaMismatch, match="MyISAM"):
        MysqlSnapshotStore(connection_pool=pool)

    assert pool.begins == 0, "the rollback-only behavior probe ran before ENGINE"
    assert pool.rollbacks == 0
    assert not any(
        any(
            isinstance(value, str)
            and value.startswith(store_module._LIVE_GUARD_PROBE_PREFIX)
            for value in params
        )
        for _, params in pool.statements
    )
    assert not any(
        sql == mysql_store_module._STAMP_SCHEMA_COMMENT for sql, _ in pool.statements
    )
    assert _table_comment(db_path) == original_comment
    assert pool not in mysql_store_module._SCHEMA_READY


def test_mysql_engine_refusal_is_not_a_pool_connection_fault(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A nontransactional table is a schema fault, not a pool failure."""
    db_path = tmp_path / "engine_quiet.db"
    _seed_table(db_path, engine="MyISAM")
    pool = _FakePool(db_path)

    with caplog.at_level(logging.ERROR, logger=_POOL_LOGGER), pytest.raises(
        SnapshotSchemaMismatch, match="MyISAM"
    ):
        MysqlSnapshotStore(connection_pool=pool)

    assert pool.errors == []
    assert _pool_errors(caplog) == []


def test_mysql_accepts_case_insensitive_innodb_engine_metadata(tmp_path: Path) -> None:
    """The server's canonical engine name may differ only in letter case."""
    db_path = tmp_path / "innodb.db"
    _seed_table(db_path, engine="iNnOdB")
    pool = _FakePool(db_path)

    MysqlSnapshotStore(connection_pool=pool)
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(mysql_store_module._SELECT_SCHEMA_COMMENT, ("pi_eod_snapshot",))
        metadata = cur.fetchone()

    assert metadata["ENGINE"] == "iNnOdB"
    assert pool.begins == 1
    assert pool.rollbacks == 1
    assert pool in mysql_store_module._SCHEMA_READY


# ---------------------------------------------------------------------------
# Trigger-free empirical probes (#2067 review follow-up)
# ---------------------------------------------------------------------------


def test_mysql_trigger_probe_asks_information_schema_for_the_real_table() -> None:
    """Trigger safety must be decided from server metadata, not DDL text."""
    probe = mysql_store_module._SELECT_SCHEMA_TRIGGERS

    assert "information_schema.TRIGGERS" in probe
    assert "DATABASE()" in probe
    assert "EVENT_OBJECT_TABLE" in probe


def test_mysql_refuses_triggers_before_probe_stamp_or_ready_mark(
    tmp_path: Path,
) -> None:
    """A rollback cannot undo external trigger effects, so no probe may run."""
    db_path = tmp_path / "trigger_ordering.db"
    original_comment = "operator-owned triggered table"
    _seed_table(db_path, comment=original_comment)
    pool = _FakePool(db_path)
    external_effects: list[str] = []
    pool.raw.create_function(
        "record_external_side_effect",
        0,
        lambda: external_effects.append("fired"),
    )
    pool.raw.execute(
        "CREATE TRIGGER pi_eod_snapshot_audit AFTER INSERT ON pi_eod_snapshot "
        "BEGIN SELECT record_external_side_effect(); END"
    )

    with pytest.raises(SnapshotSchemaMismatch, match="trigger"):
        MysqlSnapshotStore(connection_pool=pool)

    assert not external_effects, "a synthetic probe fired the production trigger"
    assert pool.begins == 0
    assert pool.rollbacks == 0
    assert not any(
        any(
            isinstance(value, str)
            and value.startswith(store_module._LIVE_GUARD_PROBE_PREFIX)
            for value in params
        )
        for _, params in pool.statements
    )
    assert not any(
        sql == mysql_store_module._STAMP_SCHEMA_COMMENT for sql, _ in pool.statements
    )
    assert _table_comment(db_path) == original_comment
    assert pool not in mysql_store_module._SCHEMA_READY


def test_mysql_trigger_refusal_is_not_a_pool_connection_fault(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A trigger is unsafe schema, not a failure of the shared connection."""
    db_path = tmp_path / "trigger_quiet.db"
    _seed_table(db_path)
    pool = _FakePool(db_path)
    pool.raw.execute(
        "CREATE TRIGGER pi_eod_snapshot_touch AFTER UPDATE ON pi_eod_snapshot "
        "BEGIN SELECT 1; END"
    )

    with caplog.at_level(logging.ERROR, logger=_POOL_LOGGER), pytest.raises(
        SnapshotSchemaMismatch, match="pi_eod_snapshot_touch"
    ):
        MysqlSnapshotStore(connection_pool=pool)

    assert not pool.errors
    assert _pool_errors(caplog) == []


def test_mysql_refuses_a_table_with_no_live_key_column(tmp_path: Path) -> None:
    """Mutation: drop the generated column. All 14 shared columns remain.

    Reverse-verified: without `_check_mysql_live_guard`, this table
    constructs cleanly (its shape is a perfect match) and nothing stops a
    second LIVE row.
    """
    message = _refusal(tmp_path, "no_live_key", live_key_sql=None, index_sql=None)

    assert "live_key" in message


def test_mysql_refuses_a_stamped_table_with_no_live_key_column(tmp_path: Path) -> None:
    """A valid version stamp must not buy a malformed table a pass.

    The stamp records *who wrote* the table, never that its keys survived
    a restore, a replication rebuild, or a hand-edited migration. And
    because construction adopts-and-stamps an unstamped table of the
    right shape, a guard-less table becomes a *stamped* guard-less table
    on its very first use — so the check has to be unconditional, not
    "only for tables we don't recognize".
    """
    message = _refusal(
        tmp_path,
        "stamped_no_live_key",
        live_key_sql=None,
        index_sql=None,
        comment=_version_stamp(store_module.SNAPSHOT_SCHEMA_VERSION),
    )

    assert "live_key" in message


def test_mysql_does_not_stamp_a_table_it_refuses(tmp_path: Path) -> None:
    """A refused table must not leave construction wearing our version marker.

    The guard is checked before the stamp is written, so an unstamped
    malformed table stays unstamped. Otherwise a single failed
    construction would relabel someone else's table as ours, and the next
    operator to look at it would be told it belongs to this build.
    """
    db_path = tmp_path / "unstamped_refusal.db"
    _seed_table(db_path, live_key_sql=None, index_sql=None)
    pool = _FakePool(db_path)

    with pytest.raises(SnapshotSchemaMismatch):
        MysqlSnapshotStore(connection_pool=pool)

    assert _table_comment(db_path) is None


def test_mysql_refuses_a_live_key_that_is_an_ordinary_column(tmp_path: Path) -> None:
    """Mutation: `live_key` exists, with its UNIQUE index, but is not generated.

    The nastiest of the three failures, because every name-only check
    passes: the column is there and so is the unique index. But nothing
    ever writes the column -- it is not in `_INSERT_STAGED`'s column list
    -- so it is NULL on every row, and MySQL unique indexes ignore NULLs.
    The guard would be decorative.
    """
    message = _refusal(tmp_path, "plain_live_key", live_key_sql="live_key TEXT")

    assert "GENERATION_EXPRESSION" in message
    assert "state" in message


def test_mysql_refuses_a_live_key_generated_from_the_wrong_expression(
    tmp_path: Path,
) -> None:
    """Mutation: generated, but keyed on identity alone -- `state` dropped.

    Such a column is non-NULL for *every* row, so the UNIQUE index would
    reject the second staged run for a key -- breaking normal daily
    operation instead of protecting anything.
    """
    message = _refusal(
        tmp_path,
        "stateless_live_key",
        live_key_sql=(
            "live_key TEXT GENERATED ALWAYS AS "
            "(concat(dataset, char(31), entity_key)) STORED"
        ),
    )

    assert "state" in message


def test_mysql_refuses_a_live_key_generated_without_the_entity_half(
    tmp_path: Path,
) -> None:
    """Mutation: generated and state-aware, but keyed on `dataset` alone.

    Two different entities in one dataset would then share a single
    `live_key`, so promoting `sector=technology` would make
    `sector=energy` unpromotable -- and the refusal would be logged as the
    routine "another writer already installed a LIVE row".
    """
    message = _refusal(
        tmp_path,
        "half_live_key",
        live_key_sql=(
            "live_key TEXT GENERATED ALWAYS AS "
            "(IIF(state = 'live', dataset, NULL)) STORED"  # codespell:ignore
        ),
    )

    assert "entity_key" in message


def test_mysql_refuses_a_correct_live_key_with_no_unique_index(tmp_path: Path) -> None:
    """Mutation: the column is perfect; the index was never created.

    This is precisely what a no-op'd `CREATE TABLE IF NOT EXISTS` leaves
    behind when someone restores the table without its keys.
    """
    message = _refusal(tmp_path, "unindexed_live_key", index_sql=None)

    assert "UNIQUE" in message
    assert "ux_pi_eod_snapshot_live" in message


def test_mysql_refuses_a_non_unique_index_over_live_key(tmp_path: Path) -> None:
    """Mutation: the index exists, under the right name, but is not UNIQUE.

    Name-only verification would pass this. A plain index constrains
    nothing at all.
    """
    message = _refusal(
        tmp_path,
        "nonunique_live_key",
        index_sql=("CREATE INDEX ux_pi_eod_snapshot_live ON pi_eod_snapshot(live_key)"),
    )

    assert "UNIQUE" in message


def test_mysql_refuses_a_unique_index_over_the_wrong_columns(tmp_path: Path) -> None:
    """Mutation: UNIQUE, right name, wrong columns -- `(dataset, entity_key)`.

    MySQL has no partial indexes, so a *total* unique index over the
    identity forbids a second staged run for one key. It is not the
    SQLite guard ported over; it is a different, wrong constraint.
    """
    message = _refusal(
        tmp_path,
        "wrong_columns",
        index_sql=(
            "CREATE UNIQUE INDEX ux_pi_eod_snapshot_live "
            "ON pi_eod_snapshot(dataset, entity_key)"
        ),
    )

    assert "live_key" in message


def test_mysql_refuses_a_composite_functional_live_guard_that_allows_cross_year_live(
    tmp_path: Path,
) -> None:
    """A hidden functional part must not disappear from the index shape.

    This is the production reproducer from #2067: both LIVE rows share one
    ``live_key``, but the extra year part makes the composite values distinct.
    The old catalogue fold dropped the ``COLUMN_NAME = NULL`` row, mistook the
    index for ``UNIQUE(live_key)``, and its same-year probe also passed.
    """
    db_path = tmp_path / "functional_composite.db"
    _seed_table(
        db_path,
        index_sql=(
            "CREATE UNIQUE INDEX ux_pi_eod_snapshot_live ON pi_eod_snapshot"
            "(live_key, strftime('%Y', as_of_session))"
        ),
    )
    pool = _FakePool(db_path)

    with pool.get_connection() as conn, conn.cursor() as cur:
        first = list(
            mysql_store_module._mysql_live_guard_probe_values(
                "same-dataset", "live-2025", SnapshotState.LIVE
            )
        )
        second = list(
            mysql_store_module._mysql_live_guard_probe_values(
                "same-dataset", "live-2026", SnapshotState.LIVE
            )
        )
        first[2] = date(2025, 12, 31)
        second[2] = date(2026, 1, 1)
        cur.execute(mysql_store_module._INSERT_LIVE_GUARD_PROBE, tuple(first))
        cur.execute(mysql_store_module._INSERT_LIVE_GUARD_PROBE, tuple(second))

    assert (
        pool.raw.execute(
            "SELECT COUNT(*) FROM pi_eod_snapshot "
            "WHERE dataset = 'same-dataset' AND state = 'live'"
        ).fetchone()[0]
        == 2
    ), "fixture does not reproduce the cross-year LIVE invariant gap"
    with pytest.raises(SnapshotSchemaMismatch, match="single-LIVE"):
        MysqlSnapshotStore(connection_pool=pool)


def test_mysql_refuses_a_unique_prefix_index_over_live_key(tmp_path: Path) -> None:
    """``UNIQUE(live_key(64))`` is not the full-column guard in the DDL."""
    db_path = tmp_path / "prefix_live_key.db"
    _seed_table(db_path)
    pool = _FakePool(db_path)
    pool.mysql_index_sub_parts[("ux_pi_eod_snapshot_live", 1)] = 64

    with pytest.raises(SnapshotSchemaMismatch, match="single-LIVE"):
        MysqlSnapshotStore(connection_pool=pool)


def test_mysql_refuses_a_live_key_generated_from_an_inverted_comparison(
    tmp_path: Path,
) -> None:
    """Mutation: `state != 'live'` -- the guard's exact inverse (PR #2062).

    This is the false positive the substring check could not see. The
    expression mentions every token the old check looked for -- `state`,
    `live`, `dataset`, `entity_key` -- and means the opposite: `live_key`
    is non-NULL on every row that is *not* LIVE, so the UNIQUE index
    rejects a second staged run for a key (normal daily operation) while
    leaving LIVE rows entirely unconstrained (the one thing it exists to
    prevent).

    Reverse-verified: restoring the old
    ``all(token in expression for token in _LIVE_KEY_EXPRESSION_TOKENS)``
    check accepts this table and construction succeeds.
    """
    message = _refusal(
        tmp_path,
        "inverted_live_key",
        live_key_sql=(
            "live_key TEXT GENERATED ALWAYS AS "
            "(IIF(state != 'live', concat(dataset, char(31), entity_key), NULL)) "  # codespell:ignore
            "STORED"
        ),
    )

    assert "GENERATION_EXPRESSION" in message
    assert store_module._LIVE_KEY_CANONICAL in message


def test_mysql_refuses_a_live_key_whose_branches_are_swapped(tmp_path: Path) -> None:
    """Mutation: right comparison, wrong branches -- THEN/ELSE exchanged.

    ``IF(state = 'live', NULL, CONCAT(...))`` is the same inversion by
    another route, and mentions the same four tokens. It is worth pinning
    separately because a swap survives any check that looks only at the
    *comparison* and never at which branch the key comes from.
    """
    message = _refusal(
        tmp_path,
        "swapped_live_key",
        live_key_sql=(
            "live_key TEXT GENERATED ALWAYS AS "
            "(IIF(state = 'live', NULL, concat(dataset, char(31), entity_key))) "  # codespell:ignore
            "STORED"
        ),
    )

    assert "GENERATION_EXPRESSION" in message


def test_mysql_refuses_a_live_key_keyed_on_the_wrong_state(tmp_path: Path) -> None:
    """Mutation: a near-match literal -- `'live'` becomes `'staging'`.

    Enforces "one STAGING row per key", which forbids the second daily
    run and permits any number of LIVE rows. The token check accepted it
    whenever the literal merely *contained* `live` too, so this pins the
    literal itself, not its neighbourhood.
    """
    message = _refusal(
        tmp_path,
        "staging_live_key",
        live_key_sql=(
            "live_key TEXT GENERATED ALWAYS AS "
            "(IIF(state = 'staging', concat(dataset, char(31), entity_key), NULL)) "  # codespell:ignore
            "STORED"
        ),
    )

    assert "GENERATION_EXPRESSION" in message


def test_mysql_refuses_an_equivalent_but_differently_shaped_live_key(
    tmp_path: Path,
) -> None:
    """The comparison is exact on purpose, and this pins that it is.

    ``CONCAT(entity_key, CHAR(31), dataset)`` would enforce the invariant
    just as well -- it is injective over the same pair -- and is refused
    anyway. "Semantically equivalent" is not a property this check can
    decide in general, so it decides the one question it can answer
    honestly: *is this the expression this build ships?* Failing closed
    on a table nobody in this repo creates costs an operator one
    ``ALTER TABLE``, and the refusal quotes the canonical form to run.
    """
    message = _refusal(
        tmp_path,
        "reversed_live_key",
        live_key_sql=(
            "live_key TEXT GENERATED ALWAYS AS "
            "(IIF(state = 'live', concat(entity_key, char(31), dataset), NULL)) "  # codespell:ignore
            "STORED"
        ),
    )

    assert store_module._LIVE_KEY_CANONICAL in message


# The forms below are what real servers hand back for the *one*
# expression `_PI_EOD_SNAPSHOT_DDL` writes. They are the false-negative
# half of the hardening: a structural check that refused any of these
# would refuse every correctly-built production table, so the guard is
# exercised against them directly rather than only against the SQLite
# double's rendering.
_SERVER_REPORTED_LIVE_KEY_EXPRESSIONS = (
    # MySQL 8.4.9, verbatim from the live server this branch's smoke
    # tests run against (`SELECT GENERATION_EXPRESSION FROM
    # information_schema.COLUMNS`, printed with `repr`). Note the
    # backslashes on the literal's own delimiters: `information_schema`
    # escapes the whole printed expression a second time, and reading
    # them as part of the literal is what made every one of the three
    # live smoke tests fail before `_decode_backslash_escapes` existed
    # (#1963). This is the single most important string in the file --
    # it is the only one taken from a real server rather than written
    # from a reading of the documentation.
    "if((`state` = _utf8mb4\\'live\\'),concat(`dataset`,"
    "char(31),`entity_key`),NULL)",
    # The same, from a server that keeps `USING utf8mb4` inside `CHAR()`
    # (MySQL 8.0) while still escaping the delimiters.
    "if((`state` = _utf8mb4\\'live\\'),concat(`dataset`,"
    "char(31 using utf8mb4),`entity_key`),NULL)",
    # MySQL 8: backticked identifiers, charset introducer on the literal,
    # `USING utf8mb4` inside CHAR(), and parentheses around the comparison.
    "if((`state` = _utf8mb4'live'),concat(`dataset`,"
    "char(31 using utf8mb4),`entity_key`),NULL)",
    # MySQL 5.7 / MariaDB: same rewrite without the introducer.
    "if((`state` = 'live'),concat(`dataset`,char(31),`entity_key`),NULL)",
    # The DDL as typed, which is what a server that stores the text
    # verbatim reports.
    "IF(state = 'live',\n   CONCAT(dataset, CHAR(31 USING utf8mb4), entity_key),\n   NULL)",
)


@pytest.mark.parametrize(
    "expression",
    _SERVER_REPORTED_LIVE_KEY_EXPRESSIONS,
    ids=(
        "mysql-8.4.9-exact-two-layer",
        "mysql-8.0-two-layer-with-char-charset",
        "mysql-8-one-layer-with-introducer",
        "mysql-5.7-mariadb-one-layer",
        "ddl-as-typed",
    ),
)
def test_mysql_live_guard_accepts_every_server_rendering_of_its_own_ddl(
    expression: str,
) -> None:
    """No false negatives: server formatting must never look like tampering.

    Reverse-verified: comparing the reported text to the DDL string
    instead of canonicalizing it fails all of them, and reverting
    `_decode_backslash_escapes` to the identity fails exactly the two
    escaped renderings -- which is the #1963 live-smoke failure.
    """
    store_module._check_mysql_live_guard(
        {"live_key": expression, "dataset": ""},
        [
            store_module._IndexShape(
                name="ux_pi_eod_snapshot_live",
                unique=True,
                columns=("live_key",),
                expressions=(None,),
                sub_parts=(None,),
            )
        ],
    )


def test_mysql_live_guard_rejects_one_layer_literal_changed_by_outer_decode() -> None:
    r"""A one-layer ``'\\live'`` literal must not be decoded as ``'live'``.

    MySQL 5.7 and MariaDB report ordinary literal delimiters without the
    extra escaping seen on MySQL 8.4.9.  In that representation ``\\`` is
    the literal's own escape for one backslash.  Applying the 8.4.9 outer
    decode anyway turns it into ``\l``; the literal decoder then drops that
    second backslash and falsely recovers the accepted ``'live'`` value.
    """
    expression = (
        r"if((`state` = _utf8mb4'\\live'),concat(`dataset`,"
        r"char(31),`entity_key`),NULL)"
    )
    guard = [
        store_module._IndexShape(
            name="ux_pi_eod_snapshot_live",
            unique=True,
            columns=("live_key",),
            expressions=(None,),
            sub_parts=(None,),
        )
    ]

    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        store_module._check_mysql_live_guard({"live_key": expression}, guard)

    assert "single-LIVE" in str(excinfo.value)


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param(
            "if((`state` := _utf8mb4'live'),concat(`dataset`,"
            "char(31),`entity_key`),NULL)",
            id="one-layer-assignment",
        ),
        pytest.param(
            "if((`state` := _utf8mb4\\'live\\'),concat(`dataset`,"
            "char(31),`entity_key`),NULL)",
            id="two-layer-assignment",
        ),
    ],
)
def test_mysql_live_guard_rejects_unconsumed_assignment_punctuation(
    expression: str,
) -> None:
    """A dropped colon must never turn MySQL assignment into equality."""
    guard = [
        store_module._IndexShape(
            name="ux_pi_eod_snapshot_live",
            unique=True,
            columns=("live_key",),
            expressions=(None,),
            sub_parts=(None,),
        )
    ]

    assert store_module._generation_expression_tokens(expression) is None
    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        store_module._check_mysql_live_guard({"live_key": expression}, guard)

    assert "single-LIVE" in str(excinfo.value)


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param(
            "if((`ſtate` = _utf8mb4'live'),concat(`dataset`,"
            "char(31),`entity_key`),NULL)",
            id="unicode-casefold-identifier",
        ),
        pytest.param(
            "if((`state`\v= _utf8mb4'live'),concat(`dataset`,"
            "char(31),`entity_key`),NULL)",
            id="vertical-tab",
        ),
        pytest.param(
            "(if((`state` = _utf8mb4'live'),concat(`dataset`,"
            "char(31),`entity_key`),NULL)",
            id="unmatched-opening-parenthesis",
        ),
        pytest.param(
            "if((`state` = _utf8mb4'live'),concat(`dataset`,"
            "char(31),`entity_key`),NULL))",
            id="unmatched-closing-parenthesis",
        ),
        pytest.param(
            "`if(state='live',concat(dataset,char(31),entity_key),null)`",
            id="whole-expression-quoted-identifier",
        ),
        pytest.param(
            "if((`state` = _utf8mb4'live'),concat(`dataset`,"
            "char(31 using utf16),`entity_key`),NULL)",
            id="unapproved-char-charset",
        ),
    ],
)
def test_mysql_live_guard_rejects_structural_token_spoofs(expression: str) -> None:
    """Only the exact typed expression and utf8mb4 decoration are accepted."""
    guard = [
        store_module._IndexShape(
            name="ux_pi_eod_snapshot_live",
            unique=True,
            columns=("live_key",),
            expressions=(None,),
            sub_parts=(None,),
        )
    ]

    with pytest.raises(SnapshotSchemaMismatch, match="single-LIVE"):
        store_module._check_mysql_live_guard({"live_key": expression}, guard)


def test_mysql_live_guard_rejects_near_matches_in_one_layer_representation() -> None:
    """Reject altered one-layer MySQL 5.7/MariaDB representations.

    Each expression differs from the shipped one by exactly one edit that
    a substring check cannot see, and every one of them mentions all four
    tokens the old check required.
    """
    near_matches = (
        # Inverted comparison.
        "if((`state` <> _utf8mb4'live'),concat(`dataset`,char(31),`entity_key`),NULL)",
        # Negated comparison.
        "if(not(`state` = 'live'),concat(`dataset`,char(31),`entity_key`),NULL)",
        # Wrong literal.
        "if((`state` = 'staging'),concat(`dataset`,char(31),`entity_key`),NULL)",
        # Swapped branches.
        "if((`state` = 'live'),NULL,concat(`dataset`,char(31),`entity_key`))",
        # An extra conjunct: one LIVE row per key *among validated rows*.
        "if((`state` = 'live' and `validated` = 1),"
        "concat(`dataset`,char(31),`entity_key`),NULL)",
        # A separator that is not the unit separator, so `a` + `b|c` and
        # `a|b` + `c` collide.
        "if((`state` = 'live'),concat(`dataset`,char(124),`entity_key`),NULL)",
        # Not generated at all: an ordinary column reports the empty string.
        "",
    )
    guard = [
        store_module._IndexShape(
            name="ux_pi_eod_snapshot_live",
            unique=True,
            columns=("live_key",),
            expressions=(None,),
            sub_parts=(None,),
        )
    ]
    for expression in near_matches:
        with pytest.raises(SnapshotSchemaMismatch) as excinfo:
            store_module._check_mysql_live_guard({"live_key": expression}, guard)
        assert "single-LIVE" in str(excinfo.value)


# The same six edits, each wearing the escaping a real MySQL applies. A
# fix for the live-smoke failure that merely deleted backslashes -- or
# that gave up and compared tokens again -- would still pass the
# unescaped list above while accepting every one of these, so this is the
# discriminating half of the regression: the peeling must recover the
# *literal*, not flatten the expression.
_ESCAPED_NEAR_MATCH_LIVE_KEY_EXPRESSIONS = (
    # Inverted comparison.
    "if((`state` <> _utf8mb4\\'live\\'),concat(`dataset`,char(31),`entity_key`),NULL)",
    # Negated comparison.
    "if(not(`state` = _utf8mb4\\'live\\'),concat(`dataset`,"
    "char(31),`entity_key`),NULL)",
    # Swapped branches.
    "if((`state` = _utf8mb4\\'live\\'),NULL,concat(`dataset`,char(31),`entity_key`))",
    # A different literal, one escaped quote away from the right one.
    "if((`state` = _utf8mb4\\'staging\\'),concat(`dataset`,"
    "char(31),`entity_key`),NULL)",
    # A literal that differs only in case: `state` is compared under
    # `utf8mb4_bin`, so `'LIVE'` never matches a row this store writes.
    "if((`state` = _utf8mb4\\'LIVE\\'),concat(`dataset`,char(31),`entity_key`),NULL)",
    # The wrong separator.
    "if((`state` = _utf8mb4\\'live\\'),concat(`dataset`,char(124),`entity_key`),NULL)",
)


@pytest.mark.parametrize("expression", _ESCAPED_NEAR_MATCH_LIVE_KEY_EXPRESSIONS)
def test_mysql_live_guard_rejects_near_matches_in_two_layer_849_representation(
    expression: str,
) -> None:
    r"""Peeling MySQL's escaping must not cost the guard its teeth.

    Reverse-verified: mutating `_generation_expression_tokens` to
    strip backslashes wholesale (``expression.replace("\\", "")``)
    keeps the accept test green and turns every case here into a false
    accept -- so these are the cases that pin the fix to *decoding* the
    literal rather than deleting characters.
    """
    guard = [
        store_module._IndexShape(
            name="ux_pi_eod_snapshot_live",
            unique=True,
            columns=("live_key",),
            expressions=(None,),
            sub_parts=(None,),
        )
    ]
    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        store_module._check_mysql_live_guard({"live_key": expression}, guard)
    assert "single-LIVE" in str(excinfo.value)


# `information_schema` escapes the *whole* printed expression, so a
# literal that itself contains a quote or a backslash comes back doubly
# escaped. These two pairs were read off MySQL 8.4.9 with a throwaway
# probe table carrying the columns
#
#     q VARCHAR(64) GENERATED ALWAYS AS (IF(s = 'li''ve', 'x', NULL)) STORED
#     b VARCHAR(64) GENERATED ALWAYS AS (IF(s = 'a\\b',   'y', NULL)) STORED
#
# and are the evidence that one unescape pass over the text, followed by
# a scan that understands MySQL's own `\'` inside a literal, is the right
# model rather than a guess that happens to work for `'live'`.
_ESCAPED_GENERATION_EXPRESSIONS = (
    (
        "if((`s` = _utf8mb4\\'li\\\\\\'ve\\'),_utf8mb4\\'x\\',NULL)",
        ("li've", "x"),
    ),
    (
        "if((`s` = _utf8mb4\\'a\\\\\\\\b\\'),_utf8mb4\\'y\\',NULL)",
        ("a\\b", "y"),
    ),
)


@pytest.mark.parametrize("reported,literal_values", _ESCAPED_GENERATION_EXPRESSIONS)
def test_generation_expression_tokenizer_recovers_the_literal_mysql_meant(
    reported: str, literal_values: tuple[str, ...]
) -> None:
    """Both escaping layers are peeled, and the literal survives intact.

    Reverse-verified: with only the outer pass the first case canonicalizes
    to ``if(s='li'...`` (the literal ends at the escaped quote and the rest
    of the expression is re-lexed as garbage); with only the inner pass
    neither case parses as a literal at all.
    """
    tokens = store_module._generation_expression_tokens(reported)
    assert tokens is not None
    assert (
        tuple(
            token.value
            for token in tokens
            if token.kind is store_module._SqlTokenKind.STRING
        )
        == literal_values
    )


def test_sqlite_predicate_is_read_without_mysql_backslash_escapes() -> None:
    r"""The peeling is MySQL's alone -- SQLite stores what was typed.

    SQLite has no backslash escapes, so ``'li\ve'`` there is the
    five-character value ``li\ve`` and an index predicated on it matches
    no row this store ever writes. Decoding it -- which is exactly what
    the MySQL path must do -- would hand that index a pass, so the two
    dialects must not share one literal syntax.

    Reverse-verified: defaulting `_sql_tokens`'s `backslash_escapes`
    to ``True`` (or peeling in `_check_sqlite_live_guard`) makes the
    refusal below stop firing.
    """
    assert not store_module._is_sqlite_live_predicate(r"state = 'li\ve'")
    with pytest.raises(SnapshotSchemaMismatch):
        store_module._check_sqlite_live_guard(
            [
                store_module._IndexShape(
                    name="ux_pi_eod_snapshot_live",
                    unique=True,
                    columns=("dataset", "entity_key"),
                    predicate=r"state = 'li\ve'",
                )
            ]
        )
    # The genuine predicate still passes, so the assertion above is not
    # vacuous.
    store_module._check_sqlite_live_guard(
        [
            store_module._IndexShape(
                name="ux_pi_eod_snapshot_live",
                unique=True,
                columns=("dataset", "entity_key"),
                predicate="state = 'live'",
            )
        ]
    )


def test_mysql_live_guard_refusal_is_not_a_pool_connection_fault(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A missing guard is a schema fault, not a database fault.

    Same contract as the shape refusal: the FMP cache shares this pool,
    and `ConnectionPool.get_connection` logs anything unwinding across it
    as `ERROR MySQL connection error`.
    """
    db_path = tmp_path / "quiet.db"
    _seed_table(db_path, live_key_sql=None, index_sql=None)
    pool = _FakePool(db_path)

    with caplog.at_level(logging.ERROR, logger=_POOL_LOGGER), pytest.raises(
        SnapshotSchemaMismatch
    ):
        MysqlSnapshotStore(connection_pool=pool)

    assert pool.errors == []
    assert _pool_errors(caplog) == []


@pytest.mark.parametrize(
    ("live_key_sql", "index_sql"),
    [
        pytest.param(_GOOD_LIVE_KEY_SQL, None, id="duplicate-live-is-allowed"),
        pytest.param(
            "live_key TEXT GENERATED ALWAYS AS "
            "(IIF(state = 'staging', concat(dataset, char(31), entity_key), NULL)) "  # codespell:ignore
            "STORED",
            "CREATE UNIQUE INDEX ux_pi_eod_snapshot_live "
            "ON pi_eod_snapshot(live_key)",
            id="second-staged-row-is-refused",
        ),
    ],
)
def test_mysql_empirical_probe_rejects_wrong_guard_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    live_key_sql: str,
    index_sql: str | None,
) -> None:
    """The engine must reject duplicate LIVE and allow duplicate STAGING."""
    db_path = tmp_path / "empirical_guard.db"
    _seed_table(db_path, live_key_sql=live_key_sql, index_sql=index_sql)
    pool = _FakePool(db_path)
    monkeypatch.setattr(mysql_store_module, "_check_mysql_live_guard", lambda *_: None)

    with pytest.raises(SnapshotSchemaMismatch, match="single-LIVE"):
        MysqlSnapshotStore(connection_pool=pool)

    assert _table_comment(db_path) is None
    assert pool.raw.execute("SELECT COUNT(*) FROM pi_eod_snapshot").fetchone()[0] == 0
    assert pool.closed_with_open_txn == 0
    assert pool.errors == []


def test_mysql_empirical_probe_rolls_back_every_probe_row(tmp_path: Path) -> None:
    """A successful construction proves the guard without persisting samples."""
    pool = _FakePool(tmp_path / "probe_rollback.db")

    MysqlSnapshotStore(connection_pool=pool)

    assert pool.begins == 1
    assert pool.commits == 0
    assert pool.rollbacks == 1
    assert pool.raw.execute("SELECT COUNT(*) FROM pi_eod_snapshot").fetchone()[0] == 0
    assert pool.closed_with_open_txn == 0
    assert pool.errors == []


def test_mysql_index_probe_asks_information_schema_for_statistics() -> None:
    """The guard check must interrogate the server, not this module's DDL."""
    probe = mysql_store_module._SELECT_SCHEMA_INDEXES

    assert "information_schema.STATISTICS" in probe
    assert "DATABASE()" in probe
    # Composite indexes arrive one row per column; the order is the
    # server's, so the query must ask for it.
    assert "SEQ_IN_INDEX" in probe
    assert "EXPRESSION" in probe
    assert "SUB_PART" in probe
    assert "ORDER BY" in probe


def test_index_shapes_reassembles_composite_indexes_in_server_order() -> None:
    """`_index_shapes` folds STATISTICS rows without inventing an order."""
    shapes = mysql_store_module._index_shapes(
        [
            {
                "INDEX_NAME": "PRIMARY",
                "NON_UNIQUE": 0,
                "SEQ_IN_INDEX": 1,
                "COLUMN_NAME": "dataset",
                "EXPRESSION": None,
                "SUB_PART": None,
            },
            {
                "INDEX_NAME": "PRIMARY",
                "NON_UNIQUE": 0,
                "SEQ_IN_INDEX": 2,
                "COLUMN_NAME": "entity_key",
                "EXPRESSION": None,
                "SUB_PART": None,
            },
            {
                "INDEX_NAME": "ix_plain",
                "NON_UNIQUE": 1,
                "SEQ_IN_INDEX": 1,
                "COLUMN_NAME": "live_key",
                "EXPRESSION": None,
                "SUB_PART": 64,
            },
            # A functional index (MySQL 8.0.13+) reports no column name.
            {
                "INDEX_NAME": "ix_functional",
                "NON_UNIQUE": 0,
                "SEQ_IN_INDEX": 1,
                "COLUMN_NAME": None,
                "EXPRESSION": "(year(`as_of_session`))",
                "SUB_PART": None,
            },
        ]
    )

    by_name = {shape.name: shape for shape in shapes}
    assert by_name["PRIMARY"].columns == ("dataset", "entity_key")
    assert getattr(by_name["PRIMARY"], "expressions", ()) == (None, None)
    assert getattr(by_name["PRIMARY"], "sub_parts", ()) == (None, None)
    assert by_name["PRIMARY"].unique
    assert not by_name["ix_plain"].unique
    assert getattr(by_name["ix_plain"], "sub_parts", ()) == (64,)
    # A NULL column is still a real key part. Dropping it lets
    # `(live_key, (YEAR(as_of_session)))` masquerade as `(live_key)`.
    assert by_name["ix_functional"].columns == (None,)
    assert getattr(by_name["ix_functional"], "expressions", ()) == (
        "(year(`as_of_session`))",
    )


def test_mysql_guard_does_not_leak_into_the_shared_column_shape() -> None:
    """`live_key` is MySQL's alone; SQLite must never be asked for it.

    SQLite enforces the same invariant with a partial unique index and has
    no such column, so requiring it in the dialect-independent
    `_EXPECTED_COLUMNS` would refuse every correct SQLite database.
    """
    assert store_module._MYSQL_LIVE_KEY_COLUMN == "live_key"
    assert "live_key" not in store_module._EXPECTED_COLUMNS
    assert "live_key" not in store_module._SQLITE_SCHEMA


# ---------------------------------------------------------------------------
# Schema *version* validation on MySQL (#1963 whole-branch review IMP-1)
# ---------------------------------------------------------------------------
#
# The shape check above is blind in one direction and half-blind in the
# other. `_check_schema_shape` only asks "is every column this build needs
# present?", so:
#
#   * a table written by a *newer* build (#1964/#1967 adding columns) is a
#     column superset — every expected column is there, the check passes,
#     and this build then writes rows a newer reader will mis-handle; and
#   * a table written by an *older* build that re-typed, re-collated or
#     re-keyed a column rather than removing it passes just as silently.
#
# SQLite closes that hole with `PRAGMA user_version`. MySQL has no
# equivalent, so the stamp lives in the table's own COMMENT and is read
# back from `information_schema.TABLES`. These tests drive both directions
# through the real production path, against a double whose comment store
# is a persistent per-*database* dictionary (not a per-pool dict), because
# "another build stamped this table" is only a meaningful scenario if the
# stamp outlives the object that wrote it.


def _table_comment(path: Path | str, table: str = "pi_eod_snapshot") -> str | None:
    """Read a table's comment out of the double's data dictionary."""
    conn = _connect(str(path))
    try:
        _ensure_dictionary(conn.cursor())
        row = conn.execute(
            f"SELECT table_comment FROM {_DICTIONARY_TABLE} WHERE table_name = ?",
            (table,),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


def _set_table_comment(
    path: Path | str, comment: str, table: str = "pi_eod_snapshot"
) -> None:
    """Stamp a table comment out-of-band, as another build's ALTER would."""
    conn = _connect(str(path))
    try:
        _ensure_dictionary(conn.cursor())
        conn.execute(
            f"INSERT INTO {_DICTIONARY_TABLE} (table_name, table_comment) "
            "VALUES (?, ?) ON CONFLICT(table_name) DO UPDATE SET "
            "table_comment = excluded.table_comment",
            (table, comment),
        )
        conn.commit()
    finally:
        conn.close()


def _version_stamp(version: int) -> str:
    """Build a comment stamping ``version`` the way the store stamps it."""
    return f"{store_module._SCHEMA_VERSION_MARKER}{version} written by another build"


def _add_column(path: Path | str, column: str) -> None:
    """Add a column out-of-band, as a newer build's migration would."""
    conn = _connect(str(path))
    try:
        conn.execute(f"ALTER TABLE pi_eod_snapshot ADD COLUMN {column}")
        conn.commit()
    finally:
        conn.close()


def test_mysql_stamps_the_schema_version_on_a_fresh_table(tmp_path: Path) -> None:
    """A table this build creates carries this build's version stamp.

    Without the stamp there is nothing for a later build to compare
    against, so every mismatch test below would pass vacuously.
    """
    db_path = tmp_path / "stamped.db"
    MysqlSnapshotStore(connection_pool=_FakePool(db_path))

    comment = _table_comment(db_path)
    assert comment is not None, "the fresh table was never stamped"
    assert (
        store_module._parse_schema_version_comment(comment)
        == store_module.SNAPSHOT_SCHEMA_VERSION
    )


def test_mysql_refuses_a_table_stamped_by_a_newer_schema_version(
    tmp_path: Path,
) -> None:
    """Old build, new schema: the column-shape check cannot see this.

    The table is a *superset* of this build's columns, so
    `_check_schema_shape` is satisfied. Only the version stamp makes it
    loud.
    """
    db_path = tmp_path / "forward.db"
    MysqlSnapshotStore(connection_pool=_FakePool(db_path))
    newer = store_module.SNAPSHOT_SCHEMA_VERSION + 7
    _set_table_comment(db_path, _version_stamp(newer))
    _add_column(db_path, "quality_score REAL")

    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        MysqlSnapshotStore(connection_pool=_FakePool(db_path))

    message = str(excinfo.value)
    assert "mysql" in message
    assert str(newer) in message
    assert str(store_module.SNAPSHOT_SCHEMA_VERSION) in message


def test_mysql_refuses_a_table_stamped_by_an_older_schema_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """New build, old schema: the other direction, equally invisible to shape.

    `SNAPSHOT_SCHEMA_VERSION` is rebound to stand in for a later build.
    That is enough to move *both* the stamp writer and the stamp checker
    because each reads the module global at call time — which is the
    property that makes a real version bump work at all.
    """
    db_path = tmp_path / "backward.db"
    MysqlSnapshotStore(connection_pool=_FakePool(db_path))
    assert _table_comment(db_path) is not None
    stamped = store_module.SNAPSHOT_SCHEMA_VERSION

    monkeypatch.setattr(store_module, "SNAPSHOT_SCHEMA_VERSION", stamped + 1)

    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        MysqlSnapshotStore(connection_pool=_FakePool(db_path))

    message = str(excinfo.value)
    assert f"stamped schema version {stamped}" in message
    assert f"speaks version {stamped + 1}" in message


def test_mysql_adopts_and_stamps_an_unstamped_table_of_the_right_shape(
    tmp_path: Path,
) -> None:
    """Parity with SQLite's `user_version = 0`: unstamped is not a mismatch.

    A table created before the stamp existed (or by a `CREATE TABLE` run
    by hand) has the right shape and no marker. Refusing it would break
    every existing deployment; the store adopts it and stamps it instead.
    """
    db_path = tmp_path / "legacy.db"
    MysqlSnapshotStore(connection_pool=_FakePool(db_path))
    _set_table_comment(db_path, "")

    store = MysqlSnapshotStore(connection_pool=_FakePool(db_path))

    assert (
        store_module._parse_schema_version_comment(_table_comment(db_path))
        == store_module.SNAPSHOT_SCHEMA_VERSION
    ), "an unstamped table was adopted but never stamped"
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)


def test_a_foreign_comment_with_no_marker_also_reads_as_unstamped(
    tmp_path: Path,
) -> None:
    """Robustness: a decorated comment must not be read as a version.

    Older InnoDB builds prepend their own text to `TABLE_COMMENT`, and
    operators annotate tables by hand. The marker is searched for, so a
    comment carrying one *is* honoured even when it carries other text
    too — and one carrying none reads as unstamped rather than blowing
    up an `int()`.
    """
    db_path = tmp_path / "decorated.db"
    MysqlSnapshotStore(connection_pool=_FakePool(db_path))
    _set_table_comment(db_path, "InnoDB free: 5120 kB; owned by portfolio-intel")

    MysqlSnapshotStore(connection_pool=_FakePool(db_path))
    assert (
        store_module._parse_schema_version_comment(_table_comment(db_path))
        == store_module.SNAPSHOT_SCHEMA_VERSION
    )
    decorated = f"InnoDB free: 5120 kB; {_version_stamp(99)}"
    assert store_module._parse_schema_version_comment(decorated) == 99


def test_a_schema_version_refusal_is_not_reported_to_the_pool_as_a_fault(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A version mismatch is a deployment error, not a connection fault."""
    db_path = tmp_path / "forward_quiet.db"
    MysqlSnapshotStore(connection_pool=_FakePool(db_path))
    _set_table_comment(
        db_path, _version_stamp(store_module.SNAPSHOT_SCHEMA_VERSION + 7)
    )
    pool = _FakePool(db_path)

    with caplog.at_level(logging.ERROR, logger=_POOL_LOGGER), pytest.raises(
        SnapshotSchemaMismatch
    ):
        MysqlSnapshotStore(connection_pool=pool)

    assert pool.errors == []
    assert _pool_errors(caplog) == []


def test_the_version_probe_asks_information_schema_for_the_table_comment() -> None:
    """The stamp is read from the server's dictionary, not from the DDL text."""
    probe = mysql_store_module._SELECT_SCHEMA_COMMENT
    assert "information_schema.TABLES" in probe
    assert "TABLE_COMMENT" in probe
    assert "ENGINE" in probe
    assert "DATABASE()" in probe
    assert (
        mysql_store_module._STAMP_SCHEMA_COMMENT.count("%s") == 1
    ), "the stamp must be a bound parameter, not interpolated text"


def test_both_backends_refuse_the_same_forward_schema_version(tmp_path: Path) -> None:
    """Parity: neither backend will read or write a newer build's table."""
    sqlite_path = tmp_path / "parity_sqlite.db"
    SqliteSnapshotStore(sqlite_path).close()
    bumped = sqlite3.connect(str(sqlite_path))
    bumped.execute(f"PRAGMA user_version = {store_module.SNAPSHOT_SCHEMA_VERSION + 7}")
    bumped.close()

    mysql_path = tmp_path / "parity_mysql.db"
    MysqlSnapshotStore(connection_pool=_FakePool(mysql_path))
    _set_table_comment(
        mysql_path, _version_stamp(store_module.SNAPSHOT_SCHEMA_VERSION + 7)
    )

    with pytest.raises(SnapshotSchemaMismatch, match="sqlite"):
        SqliteSnapshotStore(sqlite_path)
    with pytest.raises(SnapshotSchemaMismatch, match="mysql"):
        MysqlSnapshotStore(connection_pool=_FakePool(mysql_path))


# --- guards on the double itself -------------------------------------------
#
# The two tests below assert nothing about the production code. They assert
# that the double models MySQL faithfully enough for the tests above to
# mean what they claim: a comment that lived on the pool object, or a
# `CREATE TABLE IF NOT EXISTS` that quietly re-stamped an existing table,
# would make every version test pass for the wrong reason.


def test_the_double_keeps_table_comments_in_the_database_not_the_pool(
    tmp_path: Path,
) -> None:
    """MySQL's comment is server-side state: a new pool must still see it."""
    db_path = tmp_path / "dictionary.db"
    MysqlSnapshotStore(connection_pool=_FakePool(db_path))

    other_pool = _FakePool(db_path)
    with other_pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(mysql_store_module._SELECT_SCHEMA_COMMENT, ("pi_eod_snapshot",))
        record = cur.fetchone()

    assert record is not None, "a second pool could not see the stamp"
    assert (
        store_module._parse_schema_version_comment(record["TABLE_COMMENT"])
        == store_module.SNAPSHOT_SCHEMA_VERSION
    )


def test_the_double_leaves_an_existing_comment_alone_on_create_if_not_exists(
    tmp_path: Path,
) -> None:
    """`CREATE TABLE IF NOT EXISTS` is a no-op — comment included.

    If the double reset the comment here, the forward-version test would
    be testing the double's amnesia rather than the store's check.
    """
    db_path = tmp_path / "no_restamp.db"
    MysqlSnapshotStore(connection_pool=_FakePool(db_path))
    foreign = _version_stamp(store_module.SNAPSHOT_SCHEMA_VERSION + 7)
    _set_table_comment(db_path, foreign)

    pool = _FakePool(db_path)
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(_PI_EOD_SNAPSHOT_DDL)

    assert _table_comment(db_path) == foreign


def test_information_schema_returns_no_comment_row_for_a_missing_table(
    tmp_path: Path,
) -> None:
    """No row (table absent) and `''` (no comment) are different answers.

    The store distinguishes them only in that both read as version 0, but
    a double that returned a row for a non-existent table would hide a
    `TypeError` in the production `record is not None` branch.
    """
    pool = _FakePool(tmp_path / "absent.db")
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(mysql_store_module._SELECT_SCHEMA_COMMENT, ("pi_eod_snapshot",))
        assert cur.fetchone() is None
        cur.execute(_PI_EOD_SNAPSHOT_DDL)
        cur.execute(mysql_store_module._SELECT_SCHEMA_COMMENT, ("pi_eod_snapshot",))
        assert cur.fetchone() == {"TABLE_COMMENT": "", "ENGINE": "InnoDB"}


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
# `utf8mb4_bin` to SQLite's BINARY and an *unpinned* column to
# `MYSQL_AI_CI`, so these assertions fail if the DDL ever loses its
# COLLATE.
#
# The DDL assertions below pin what *this build* would create. They say
# nothing about a table that already exists, because `CREATE TABLE IF NOT
# EXISTS` no-ops against one -- which is why construction also re-reads
# `information_schema.COLUMNS.COLLATION_NAME` and refuses anything that
# is not `utf8mb4_bin` (PR #2062 review). Those tests are in the section
# below this one.

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
    """
    unpinned = _PI_EOD_SNAPSHOT_DDL.replace(" COLLATE utf8mb4_bin", "").replace(
        " COLLATE=utf8mb4_bin", ""
    )
    assert "COLLATE" not in unpinned
    table_sql, _ = _ddl_to_sqlite(unpinned)
    conn = _connect(str(tmp_path / "unpinned.db"), isolation_level=None)
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


def test_the_double_folds_accents_when_a_column_is_unpinned(tmp_path: Path) -> None:
    """Guards the guard, accent half: `sector=cafe` vs `sector=café`.

    `canonical_key` casefolds but does *not* Unicode-normalize, so those
    two entity keys survive canonicalization as distinct strings and the
    only thing keeping them apart in the database is the collation. Under
    `_ci` they fold together on `ux_pi_eod_snapshot_live`, so promoting
    the second one would collide with -- or, on a server that resolved
    the tie the other way, silently overwrite -- the LIVE row of the
    first. That is a *different* failure from the `job_run_id` case
    collision above: it lands on the single-LIVE guard rather than the
    primary key.

    Reverse-verified: with `MYSQL_AI_CI` reduced to SQLite's `NOCASE`
    (which folds ASCII case only), the second insert succeeds and this
    test fails -- which is exactly why the double registers a real
    accent-folding collation instead (PR #2062 review).
    """
    unpinned = _PI_EOD_SNAPSHOT_DDL.replace(" COLLATE utf8mb4_bin", "").replace(
        " COLLATE=utf8mb4_bin", ""
    )
    table_sql, index_sql = _ddl_to_sqlite(unpinned)
    conn = _connect(str(tmp_path / "accents.db"), isolation_level=None)
    conn.execute(table_sql)
    for statement in index_sql:
        conn.execute(statement)

    # Two keys that `canonical_key` keeps distinct...
    assert canonical_key("sector=cafe") != canonical_key("sector=café")

    live = (
        "INSERT INTO pi_eod_snapshot (dataset, entity_key, as_of_session, "
        "created_at, job_run_id, status, state, validated, validation_reason, "
        "payload_json) VALUES (?, ?, '2026-09-04', '2026-09-04 00:00:00', ?, "
        "'ok', 'live', 1, '', '{}')"
    )
    conn.execute(live, ("techtrade.movers", "sector=cafe", "run-1"))
    # ... and that an `_ci` collation folds together on the LIVE guard.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(live, ("techtrade.movers", "sector=café", "run-2"))
    conn.close()


def test_the_pinned_ddl_keeps_accented_entity_keys_apart(tmp_path: Path) -> None:
    """The mirror image: under the *real* DDL both keys go LIVE.

    Same two entity keys, same single-LIVE guard, but with the DDL's
    `COLLATE utf8mb4_bin` left in place. Without this the test above
    could be passing for an unrelated reason (a broken index, a bad
    insert) rather than because of collation.
    """
    store = MysqlSnapshotStore(connection_pool=_FakePool(tmp_path / "pinned.db"))
    for entity_key in ("sector=cafe", "sector=café"):
        staged = _stage(
            store, payload={"rows": [{"symbol": "AAPL"}]}, entity_key=entity_key
        )
        assert store.validate(*staged).ok
        assert store.promote(*staged)

    for entity_key in ("sector=cafe", "sector=café"):
        live = store.get_live("techtrade.movers", entity_key)
        assert live is not None
        assert live.entity_key == canonical_key(entity_key)


# ---------------------------------------------------------------------------
# Collation is *verified*, not just declared (PR #2062 review)
# ---------------------------------------------------------------------------
#
# The DDL assertions above pin what this build would create. They cannot
# see the table that is actually there: `CREATE TABLE IF NOT EXISTS`
# no-ops against a pre-existing one, so a table created by an older
# build, by a migration tool, or by hand can carry the charset default
# collation and still satisfy every shape / guard / index check. Its
# `live_key` would then fold `sector=cafe` onto `sector=café` and its
# primary key would fold `Run-1` onto `run-1` -- the two divergences the
# section above proves are real -- and construction would stamp the table
# READY on the way past.
#
# So `_verify_schema` re-reads `information_schema.COLUMNS.COLLATION_NAME`
# and refuses anything that is not `utf8mb4_bin`, *before* the version
# stamp. The tests below mutate one column at a time and assert the
# refusal, and assert the refused table is left unstamped.


def _collation_refusal(tmp_path: Path, name: str, **seed: Any) -> str:
    """Seed a table with a bad collation, construct, return the message.

    Deliberately separate from `_refusal`: that helper asserts the
    message mentions the single-LIVE guard, and a collation refusal is a
    *different* failure with a different message. Sharing one helper
    would let a collation bug pass as a guard bug.
    """
    db_path = tmp_path / f"{name}.db"
    _seed_table(db_path, **seed)
    pool = _FakePool(db_path)
    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        MysqlSnapshotStore(connection_pool=pool)
    message = str(excinfo.value)
    assert "collation" in message
    assert "pi_eod_snapshot" in message
    # The refusal has to be actionable, not just loud.
    assert "ALTER TABLE" in message
    # ... and it must not be stamped READY on the way out.
    assert _table_comment(db_path) is None
    return message


def test_mysql_reports_the_collation_of_every_column_it_created(
    tmp_path: Path,
) -> None:
    """Control: the positive path is not vacuous.

    Every column the check requires is reported as `utf8mb4_bin` by the
    double against the table the production DDL built, and the probe the
    production code runs is the one that carries `COLLATION_NAME`.
    """
    assert "COLLATION_NAME" in mysql_store_module._SELECT_SCHEMA_COLUMNS

    pool = _FakePool(tmp_path / "good.db")
    MysqlSnapshotStore(connection_pool=pool)

    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            mysql_store_module._SELECT_SCHEMA_COLUMNS, (store_module._SNAPSHOT_TABLE,)
        )
        collations = {
            record["COLUMN_NAME"]: record["COLLATION_NAME"] for record in cur.fetchall()
        }

    for column in store_module._MYSQL_BINARY_COLLATED_COLUMNS:
        assert collations.get(column) == "utf8mb4_bin", column
    # Non-character columns report NULL, as they do on a real server --
    # which is what makes the "redeclared as a BLOB" refusal below a
    # genuine mutation rather than a missing key.
    assert collations["row_count"] is None
    assert collations["as_of_session"] is None


@pytest.mark.parametrize(
    "column",
    ["dataset", "entity_key", "job_run_id", "status", "state", "input_hash"],
)
def test_mysql_refuses_a_case_insensitive_key_column(
    tmp_path: Path, column: str
) -> None:
    """Mutation: one shared key column carries the charset default.

    Reverse-verified: with `_check_mysql_collations` neutered every one
    of these tables constructs cleanly -- shape, guard and index are all
    correct -- and gets stamped with this build's schema version.
    """
    seeded = _redeclare(column, f"TEXT COLLATE {_MYSQL_AI_CI}")

    db_path = tmp_path / f"ci_{column}.db"
    _seed_table_with_columns(db_path, seeded)
    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        MysqlSnapshotStore(connection_pool=_FakePool(db_path))

    message = str(excinfo.value)
    assert f"{column} -> '{_MYSQL_DEFAULT_COLLATION}'" in message
    assert _table_comment(db_path) is None


def test_mysql_refuses_a_case_insensitive_live_key(tmp_path: Path) -> None:
    """Mutation: the *generated* column is the one that is unpinned.

    `live_key` is the column the accent collision actually lands on, and
    it is generated -- so it is the one a migration is most likely to
    recreate without thinking about collation.
    """
    message = _collation_refusal(
        tmp_path,
        "ci_live_key",
        live_key_sql=(
            f"live_key TEXT COLLATE {_MYSQL_AI_CI} GENERATED ALWAYS AS "
            "(IIF(state = 'live', concat(dataset, char(31), entity_key), NULL)) STORED"  # codespell:ignore
        ),
    )
    assert f"live_key -> '{_MYSQL_DEFAULT_COLLATION}'" in message


@pytest.mark.parametrize("column", ["engine_version", "payload_schema_version"])
def test_mysql_refuses_a_case_insensitive_version_column(
    tmp_path: Path, column: str
) -> None:
    """Parity: the version columns are held to the same standard.

    They are not part of any key, but they are compared as strings by
    every caller that asks "was this produced by the build I expect?".
    An `_ci` collation there makes `v1.2.0-RC1` equal `v1.2.0-rc1`, and
    the whole point of the schema check is that comparison semantics are
    verified rather than assumed.
    """
    seeded = _redeclare(column, f"TEXT COLLATE {_MYSQL_AI_CI}")

    db_path = tmp_path / f"ci_{column}.db"
    _seed_table_with_columns(db_path, seeded)
    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        MysqlSnapshotStore(connection_pool=_FakePool(db_path))
    assert f"{column} -> '{_MYSQL_DEFAULT_COLLATION}'" in str(excinfo.value)


def test_mysql_refuses_a_key_column_that_is_no_longer_text(tmp_path: Path) -> None:
    """Mutation: `job_run_id` redeclared as a BLOB reports NULL collation.

    A NULL `COLLATION_NAME` is not "unset" -- it means the column is not
    character data at all, so its comparison semantics are whatever the
    binary type says. The check has to refuse that rather than treat
    NULL as "nothing to verify", which is the reading that would let a
    schema drift through unnoticed.
    """
    seeded = _redeclare("job_run_id", "BLOB")

    db_path = tmp_path / "blob_job_run_id.db"
    _seed_table_with_columns(db_path, seeded)
    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        MysqlSnapshotStore(connection_pool=_FakePool(db_path))
    assert "job_run_id -> NULL" in str(excinfo.value)


def test_mysql_refuses_a_stamped_table_with_the_wrong_collation(
    tmp_path: Path,
) -> None:
    """The version stamp buys no pass.

    A table stamped by *this* build still has to prove its collation.
    Otherwise the first build to stamp a mis-collated table would make
    every later build accept it -- the stamp would launder the defect.

    Reverse-verified: gate `_check_mysql_collations` behind the
    adopt-and-stamp branch (`if stamped == 0:`) -- the shape the check
    would have if it were treated as a one-time adoption cost rather
    than an invariant -- and this table constructs cleanly.
    """
    seeded = _redeclare("entity_key", f"TEXT COLLATE {_MYSQL_AI_CI}")
    db_path = tmp_path / "stamped_ci.db"
    stamp = _version_stamp(store_module.SNAPSHOT_SCHEMA_VERSION)
    _seed_table_with_columns(db_path, seeded, comment=stamp)
    assert _table_comment(db_path) == stamp

    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        MysqlSnapshotStore(connection_pool=_FakePool(db_path))
    assert "entity_key" in str(excinfo.value)


def test_mysql_collation_refusal_is_not_a_connection_fault(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A rejected schema is a caller error, not a broken connection.

    Same contract the guard refusals hold to: the pool must not record
    the borrow as faulted, or a refusal would poison the pool for every
    later caller and mask itself as an infrastructure problem.
    """
    seeded = _redeclare("dataset", f"TEXT COLLATE {_MYSQL_AI_CI}")
    db_path = tmp_path / "ci_not_a_fault.db"
    _seed_table_with_columns(db_path, seeded)
    pool = _FakePool(db_path)

    with caplog.at_level(logging.WARNING), pytest.raises(SnapshotSchemaMismatch):
        MysqlSnapshotStore(connection_pool=pool)

    assert pool.errors == []
    assert _pool_errors(caplog) == []


def test_mysql_collation_refusal_names_every_offender_at_once(
    tmp_path: Path,
) -> None:
    """One trip: a repair that fixes one column must not reveal the next.

    Three unpinned columns, one refusal, all three named. Fixing them
    one refusal at a time is three deploys instead of one.
    """
    seeded = _BASE_COLUMNS_SQL
    for column in ("dataset", "entity_key", "job_run_id"):
        seeded = re.sub(
            rf"^(\s*{column}\s+)TEXT\b",
            rf"\g<1>TEXT COLLATE {_MYSQL_AI_CI}",
            seeded,
            count=1,
            flags=re.M,
        )
    db_path = tmp_path / "ci_many.db"
    _seed_table_with_columns(db_path, seeded)

    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        MysqlSnapshotStore(connection_pool=_FakePool(db_path))
    message = str(excinfo.value)
    for column in ("dataset", "entity_key", "job_run_id"):
        assert f"{column} -> '{_MYSQL_DEFAULT_COLLATION}'" in message
    assert message.count("ALTER TABLE") == 3


def test_collation_check_accepts_a_clean_map() -> None:
    """Unit: the required columns, all binary, in any letter case.

    MySQL reports collation names lower-cased, but `SHOW`-derived tooling
    and hand-written migrations both produce upper-case spellings, and
    the *name* is not the thing being verified -- the semantics are.
    """
    clean = {
        column: "utf8mb4_bin" for column in store_module._MYSQL_BINARY_COLLATED_COLUMNS
    }
    store_module._check_mysql_collations(clean)
    store_module._check_mysql_collations({key: "UTF8MB4_BIN" for key in clean})
    # Columns outside the required set are not the check's business.
    store_module._check_mysql_collations(
        {**clean, "payload_json": _MYSQL_DEFAULT_COLLATION, "row_count": None}
    )


@pytest.mark.parametrize(
    "reported",
    [
        "utf8mb4_0900_ai_ci",
        "utf8mb4_general_ci",
        "utf8mb4_unicode_ci",
        "latin1_swedish_ci",
        None,
        "",
    ],
)
def test_collation_check_rejects_anything_but_binary(reported: str | None) -> None:
    """Unit: every non-binary spelling, including NULL and empty."""
    collations: dict[str, str | None] = {
        column: "utf8mb4_bin" for column in store_module._MYSQL_BINARY_COLLATED_COLUMNS
    }
    collations["entity_key"] = reported
    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        store_module._check_mysql_collations(collations)
    assert "entity_key" in str(excinfo.value)


def test_collation_check_rejects_a_different_binary_collation() -> None:
    """Fail closed on `utf8mb4_0900_bin`, same as the live-guard check.

    `utf8mb4_0900_bin` compares byte-for-byte too, so accepting it would
    arguably be correct -- but it also NO PADs differently, and the
    module's whole approach to schema drift is to refuse anything it did
    not write rather than to reason about equivalence at read time. An
    operator who genuinely wants it changes the pin in one place, in a
    reviewed diff.
    """
    collations: dict[str, str | None] = {
        column: "utf8mb4_bin" for column in store_module._MYSQL_BINARY_COLLATED_COLUMNS
    }
    collations["dataset"] = "utf8mb4_0900_bin"
    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        store_module._check_mysql_collations(collations)
    assert "utf8mb4_0900_bin" in str(excinfo.value)


def test_collation_check_rejects_a_missing_column() -> None:
    """A column the probe never reported is not silently exempt."""
    collations: dict[str, str | None] = {
        column: "utf8mb4_bin" for column in store_module._MYSQL_BINARY_COLLATED_COLUMNS
    }
    del collations["live_key"]
    with pytest.raises(SnapshotSchemaMismatch) as excinfo:
        store_module._check_mysql_collations(collations)
    assert "live_key" in str(excinfo.value)


def test_required_collated_columns_are_exactly_what_the_ddl_pins() -> None:
    """The required list and the DDL must not drift apart.

    If the DDL grows a `COLLATE utf8mb4_bin` column that the check does
    not require, the pin is unverified on adopted tables. If the check
    requires one the DDL does not pin, this build's own table is refused
    on the next construction. Either way it is caught here rather than in
    production.

    `validation_reason` and `payload_json` are deliberately *not* pinned
    and therefore deliberately not required: they are free text and JSON
    that nothing compares, keying or otherwise, and requiring a collation
    the DDL does not pin would make the store refuse the table it just
    created.
    """
    pinned = {
        column
        for column, collation in _column_collations(_PI_EOD_SNAPSHOT_DDL).items()
        if collation is not None
    }
    assert pinned == set(store_module._MYSQL_BINARY_COLLATED_COLUMNS)
    assert not pinned & {"validation_reason", "payload_json"}


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
    """The real server allows STAGING, rejects duplicate LIVE, and rolls back."""
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

        pool = get_connection_pool()
        with pool.get_connection() as conn:
            mysql_store_module._probe_mysql_live_guard(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM pi_eod_snapshot WHERE dataset LIKE %s",
                    (f"{store_module._LIVE_GUARD_PROBE_PREFIX}%",),
                )
                assert cur.fetchone()["n"] == 0

        with pool.get_connection() as conn, conn.cursor() as cur:
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
def test_live_mysql_pins_innodb_and_binary_collation_on_the_key_columns() -> None:
    """The server reports InnoDB and the collations the DDL asked for.

    Runs the *production* check over the *production* probe's answer, so
    it proves they agree on a real server: that the table engine and column
    names the check requires are values `information_schema` actually
    reports, and that `utf8mb4_bin` is the spelling this MySQL version
    returns for a column the DDL pinned. The double cannot answer those
    questions -- it renders both sides itself.
    """
    with _live_mysql_store() as store:
        del store
        from openbb_fmp_cached.utils.database import (  # noqa: PLC0415
            get_connection_pool,
        )

        with get_connection_pool().get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                mysql_store_module._SELECT_SCHEMA_COLUMNS,
                ("pi_eod_snapshot",),
            )
            collations = {
                record["COLUMN_NAME"]: record["COLLATION_NAME"]
                for record in cur.fetchall()
            }
            cur.execute(
                mysql_store_module._SELECT_SCHEMA_COMMENT,
                ("pi_eod_snapshot",),
            )
            table_metadata = cur.fetchone()

    assert table_metadata is not None
    assert table_metadata["ENGINE"].casefold() == "innodb"
    for column in store_module._MYSQL_BINARY_COLLATED_COLUMNS:
        assert (
            collations[column] == "utf8mb4_bin"
        ), f"{column} resolved to {collations[column]!r} on the live server"
    # Non-character columns really do report NULL, which is the reading
    # `_check_mysql_collations` refuses rather than skips.
    assert collations["row_count"] is None
    store_module._check_mysql_collations(collations)


@pytest.mark.integration
@pytest.mark.requires_mysql
@_requires_live_mysql
def test_live_mysql_has_exact_full_live_key_index_and_no_triggers() -> None:
    """The deployed table is safe for the constructor's synthetic probe."""
    with _live_mysql_store() as store:
        del store
        from openbb_fmp_cached.utils.database import (  # noqa: PLC0415
            get_connection_pool,
        )

        with get_connection_pool().get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                mysql_store_module._SELECT_SCHEMA_INDEXES,
                ("pi_eod_snapshot",),
            )
            indexes = mysql_store_module._index_shapes(cur.fetchall())
            cur.execute(
                mysql_store_module._SELECT_SCHEMA_TRIGGERS,
                ("pi_eod_snapshot",),
            )
            triggers = cur.fetchall()

    exact_guards = [
        index
        for index in indexes
        if index.unique
        and index.columns == ("live_key",)
        and index.expressions == (None,)
        and index.sub_parts == (None,)
    ]
    assert exact_guards == [
        store_module._IndexShape(
            name="ux_pi_eod_snapshot_live",
            unique=True,
            columns=("live_key",),
            expressions=(None,),
            sub_parts=(None,),
        )
    ]
    assert not triggers
