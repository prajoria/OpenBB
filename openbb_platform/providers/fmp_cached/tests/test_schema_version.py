"""Unit tests for schema-version tracking helpers (#1317).

Discriminators:

- **migration_ran** returns True only when the row exists; False on
  missing row + on DB error (never raises).
- **record_migration** uses INSERT IGNORE so re-recording is a
  no-op — critical for downstream waves that call it
  unconditionally.
- **DB-failure resilience** — if schema_version table can't be created
  (e.g. DB down), helpers log WARN and return False; they never
  propagate the exception. Downstream contract is "False means try
  again next boot".
- **Empty-string version** raises ValueError up-front rather than
  silently recording a placeholder.

Tests use monkeypatched execute_query so they don't hit a live MySQL.
Integration test that DOES hit MySQL lives in the record_http suite
(separate marker) so it's opt-in.
"""

from __future__ import annotations

import pytest


def test_migration_ran_returns_False_when_row_missing(monkeypatch):
    """No matching row -> False, no exception."""
    from openbb_fmp_cached.utils import database as db

    calls = []

    def fake_execute(sql, params=()):
        calls.append((sql, params))
        # DDL call returns None; SELECT returns []
        if "CREATE TABLE" in sql:
            return None
        return []

    monkeypatch.setattr(db, "execute_query", fake_execute)
    assert db.migration_ran("W1-nonexistent") is False
    # Verified: schema_version DDL runs (idempotent) + SELECT with the version
    assert any("CREATE TABLE" in c[0] for c in calls)
    assert any("SELECT 1 FROM schema_version" in c[0] for c in calls)


def test_migration_ran_returns_True_when_row_exists(monkeypatch):
    """SELECT returns a row -> True."""
    from openbb_fmp_cached.utils import database as db

    def fake_execute(sql, params=()):
        if "CREATE TABLE" in sql:
            return None
        return [{"1": 1}]

    monkeypatch.setattr(db, "execute_query", fake_execute)
    assert db.migration_ran("W1-statements-add-ttm-tables") is True


def test_migration_ran_returns_False_on_ddl_failure(monkeypatch):
    """DB down (DDL raises) -> False, no exception up."""
    from openbb_fmp_cached.utils import database as db

    def boom(sql, params=()):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "execute_query", boom)
    assert db.migration_ran("W1-anything") is False


def test_migration_ran_returns_False_on_select_failure(monkeypatch):
    """DDL succeeds but SELECT fails (weird schema state) -> False."""
    from openbb_fmp_cached.utils import database as db

    call_count = {"n": 0}

    def sometimes_boom(sql, params=()):
        call_count["n"] += 1
        if "CREATE TABLE" in sql:
            return None
        raise RuntimeError("select failed")

    monkeypatch.setattr(db, "execute_query", sometimes_boom)
    assert db.migration_ran("W1-x") is False


def test_migration_ran_rejects_empty_version(monkeypatch):
    """Empty string is a caller bug -> ValueError, not silent False."""
    from openbb_fmp_cached.utils import database as db

    for bad in ("", None):
        with pytest.raises(ValueError, match="non-empty"):
            db.migration_ran(bad)


def test_record_migration_uses_insert_ignore(monkeypatch):
    """Re-recording the same version must be idempotent via INSERT IGNORE."""
    from openbb_fmp_cached.utils import database as db

    sqls = []

    def fake_execute(sql, params=()):
        sqls.append(sql)

    monkeypatch.setattr(db, "execute_query", fake_execute)
    assert db.record_migration("W1-idem", notes="test") is True
    insert_sqls = [s for s in sqls if "INSERT" in s]
    assert insert_sqls, "no INSERT was emitted"
    assert (
        "INSERT IGNORE" in insert_sqls[0]
    ), "must use INSERT IGNORE so a second record_migration call is a no-op"


def test_record_migration_returns_False_on_db_failure(monkeypatch):
    """DDL failure -> False, no exception up."""
    from openbb_fmp_cached.utils import database as db

    def boom(sql, params=()):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "execute_query", boom)
    assert db.record_migration("W1-x") is False


def test_record_migration_rejects_empty_version(monkeypatch):
    """Empty version -> ValueError up-front."""
    from openbb_fmp_cached.utils import database as db

    with pytest.raises(ValueError, match="non-empty"):
        db.record_migration("")


def test_list_migrations_returns_empty_on_db_failure(monkeypatch):
    """DB down -> [], not exception."""
    from openbb_fmp_cached.utils import database as db

    def boom(sql, params=()):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "execute_query", boom)
    assert db.list_migrations() == []


def test_list_migrations_returns_recorded_rows(monkeypatch):
    """Happy path: returns whatever the SELECT gave back."""
    from datetime import datetime

    from openbb_fmp_cached.utils import database as db

    rows = [
        {"version": "W1-a", "applied_at": datetime(2026, 7, 22), "notes": "first"},
        {"version": "W1-b", "applied_at": datetime(2026, 7, 22), "notes": None},
    ]

    def fake_execute(sql, params=()):
        if "CREATE TABLE" in sql:
            return None
        return rows

    monkeypatch.setattr(db, "execute_query", fake_execute)
    result = db.list_migrations()
    assert result == rows


def test_downstream_usage_pattern(monkeypatch):
    """Documents the intended contract: guard DDL with migration_ran + record."""
    from openbb_fmp_cached.utils import database as db

    applied = set()

    def fake_execute(sql, params=()):
        if "CREATE TABLE" in sql:
            return None
        if "SELECT 1 FROM schema_version" in sql:
            return [{"1": 1}] if params[0] in applied else []
        if "INSERT IGNORE" in sql:
            applied.add(params[0])
            return None
        return []

    monkeypatch.setattr(db, "execute_query", fake_execute)

    # Simulate a downstream wave-task pattern:
    version = "W1-statements-add-ttm-tables"
    if not db.migration_ran(version):
        # ... run non-idempotent migration ...
        assert db.record_migration(version, notes="added ttm tables") is True

    # Next boot: already recorded, skip migration.
    assert db.migration_ran(version) is True
