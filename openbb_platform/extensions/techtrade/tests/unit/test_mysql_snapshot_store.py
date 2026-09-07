"""Tests for the #1963 MySQL snapshot backend (Task 4).

Every behavioral scenario in ``test_snapshot_store.py`` (Task 2-3) is
mirrored here against :class:`MysqlSnapshotStore`, plus MySQL-specific
guards for the native ``DATE``/``DATETIME(6)`` columns, the generated
nullable ``live_key`` unique constraint, ``%s`` parameter binding, and
commit/rollback discipline.

The test double
---------------
``_FakePool`` speaks the ``mysql-connector`` pool API
(``pool.get_connection() -> conn``, ``conn.cursor(dictionary=...)``,
``cursor.execute(sql, params)``, ``conn.commit()/rollback()/close()``)
over an on-disk SQLite database, mirroring the pattern already used by
``test_mysql_paper_engine.py`` and
``portfolio_snapshot_importer/tests/test_mysql_store.py``. It is
deliberately *stricter* than the real driver in three places so that
dialect leakage cannot pass silently:

1. ``execute`` raises when ``sql.count("%s") != len(params)`` — the real
   driver raises ``ProgrammingError`` here too.
2. Binding a **tz-aware** ``datetime`` raises, mirroring MySQL strict
   mode rejecting an offset in a ``DATETIME`` literal. The backend must
   therefore bind naive UTC and re-attach ``timezone.utc`` on read.
3. Binding a **string** that looks like an ISO date/datetime raises.
   Real MySQL would accept it; the double refuses so that a copy-pasted
   SQLite-style ``.isoformat()`` workaround fails loudly instead of
   silently round-tripping through a ``DATE`` column.

Column types for the read-side conversion are parsed out of the module's
own ``_PI_SNAPSHOT_DDL``, so a ``DATE``/``DATETIME(6)`` column really is
handed back as ``datetime.date``/``datetime.datetime`` exactly like
``mysql-connector`` does.

R7 note: every load-bearing assertion below was reverse-verified by
mutating the production code it guards (see the task report).
"""

# ruff: noqa: D101, D102, D103, D105, SLF001, S608

from __future__ import annotations

import inspect
import itertools
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
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
# mysql-connector-shaped test double
# ---------------------------------------------------------------------------


class _FakeMysqlError(Exception):
    """Stand-in for ``mysql.connector.Error``."""


class _FakeProgrammingError(_FakeMysqlError):
    """Stand-in for ``mysql.connector.ProgrammingError``."""


class _FakeIntegrityError(_FakeMysqlError):
    """Stand-in for ``mysql.connector.IntegrityError``."""


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


class _FakeCursor:
    def __init__(self, conn: _FakeConnection, *, dictionary: bool) -> None:
        self._conn = conn
        self._dictionary = dictionary
        self._cursor = conn.raw.cursor()

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

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
        try:
            self._cursor.execute(
                sql.replace("%s", "?"), tuple(_adapt(value) for value in bound)
            )
        except sqlite3.IntegrityError as exc:
            raise _FakeIntegrityError(str(exc)) from exc

    def _shape(self, row: Any) -> Any:
        if row is None:
            return None
        names = [column[0] for column in self._cursor.description]
        values = [_convert(name, value) for name, value in zip(names, row)]
        if self._dictionary:
            return dict(zip(names, values))
        return tuple(values)

    def fetchone(self) -> Any:
        return self._shape(self._cursor.fetchone())

    def fetchall(self) -> list[Any]:
        return [self._shape(row) for row in self._cursor.fetchall()]

    def close(self) -> None:
        self._cursor.close()


class _FakeConnection:
    def __init__(self, pool: _FakePool) -> None:
        self._pool = pool
        self.raw = pool.raw

    def cursor(self, dictionary: bool = False, buffered: bool = False) -> _FakeCursor:
        del buffered
        return _FakeCursor(self, dictionary=dictionary)

    def record(self, sql: str, params: tuple) -> None:
        self._pool.statements.append((sql, params))

    def commit(self) -> None:
        self._pool.commits += 1
        self.raw.commit()

    def rollback(self) -> None:
        self._pool.rollbacks += 1
        self.raw.rollback()

    def close(self) -> None:
        # Pooled connections are returned, not torn down.
        self._pool.returned += 1


class _FakePool:
    def __init__(self, path: Path | str) -> None:
        self.raw = sqlite3.connect(str(path))
        self.commits = 0
        self.rollbacks = 0
        self.handed_out = 0
        self.returned = 0
        self.statements: list[tuple[str, tuple]] = []

    def get_connection(self) -> _FakeConnection:
        self.handed_out += 1
        return _FakeConnection(self)


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def pool(tmp_path: Path) -> _FakePool:
    return _FakePool(tmp_path / "snapshot_mysql_test.db")


@pytest.fixture
def store(pool: _FakePool) -> MysqlSnapshotStore:
    return MysqlSnapshotStore(connection_pool=pool)


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
    conn = pool.get_connection()
    cur = conn.cursor()
    try:
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
    finally:
        cur.close()
        conn.close()


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
    commits_before = pool.commits
    _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert pool.commits == commits_before + 1

    commits_after_write = pool.commits
    rollbacks_before_read = pool.rollbacks
    assert store.get_live("techtrade.movers", "sector=technology") is None
    store.list_history("techtrade.movers", "sector=technology")
    assert pool.commits == commits_after_write
    # Reads must close their InnoDB read transaction rather than leak it
    # back into the pool.
    assert pool.rollbacks > rollbacks_before_read


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
