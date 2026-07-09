"""Unit tests for the DDL-injection cluster fix — bd-9loj.

Four sibling sites in the codebase built ``CREATE DATABASE`` DDL via
f-string interpolation of caller-controlled input. Fixed in this PR by
routing each site through ``safe_identifier()`` from bd-kh08 (Tier-0
helpers, PR #414).

Sites:
1. ``Tools/parse_fidelity_positions.py`` — ``--database`` CLI arg
   (bd-v9ri, real injection surface).
2. ``Tools/load_espp_plan.py`` — ``--database`` CLI arg (bd-y5fn,
   real injection surface).
3. ``openbb_fmp_cached/utils/database.py::init_database`` — reads
   ``database`` from ``DatabaseConfig`` (bd-o1oy, injection if config
   is ever caller-influenced).
4. ``openbb_fmp_cached/utils/cache_schema.py::get_table_name`` —
   builds table names for ~60 ``CREATE TABLE`` sites (bd-20zx,
   allowlist-validate to shore up the entire surface).

Each test proves the malicious-input rejection AND the happy-path
regression lock on the exact site.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest


# Ensure the repo's Tools/ directory is importable for the Tools/*.py tests.
_REPO_ROOT = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..",
        "..",
        "..",
    )
)
_TOOLS_DIR = os.path.join(_REPO_ROOT, "Tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)


# ---------------------------------------------------------------------------
# Site 1: Tools/parse_fidelity_positions.py::get_connection
# ---------------------------------------------------------------------------


class TestParseFidelityGetConnection:
    """Tools/parse_fidelity_positions.py — --database CLI arg (bd-v9ri)."""

    def test_rejects_malicious_database_name(self):
        """A malicious --database value MUST raise ValueError before DDL fires."""
        with patch("pymysql.connect") as mock_connect:
            import parse_fidelity_positions as tool

            with pytest.raises(ValueError):
                tool.get_connection(database="my_db; DROP TABLE users; --")

        # pymysql.connect must NOT have been called — the rejection
        # happens BEFORE any DB work.
        assert mock_connect.call_count == 0, (
            f"pymysql.connect was called {mock_connect.call_count} times "
            f"despite malicious --database — the safe_identifier check "
            f"must run BEFORE the connection (bd-9loj/v9ri)."
        )

    def test_accepts_valid_database_name(self):
        """Regression lock: a valid database name still works end-to-end."""
        import parse_fidelity_positions as tool

        with patch("pymysql.connect", return_value=MagicMock()):
            # Should not raise.
            tool.get_connection(database="valid_db_name")


# ---------------------------------------------------------------------------
# Site 2: Tools/load_espp_plan.py::get_connection
# ---------------------------------------------------------------------------


class TestLoadEsppPlanGetConnection:
    """Tools/load_espp_plan.py — --database CLI arg (bd-y5fn)."""

    def test_rejects_malicious_database_name(self):
        """A malicious --database value MUST raise ValueError before DDL fires."""
        with patch("pymysql.connect") as mock_connect:
            import load_espp_plan as tool

            with pytest.raises(ValueError):
                tool.get_connection(database="'; DROP DATABASE openbb; --")

        assert mock_connect.call_count == 0, (
            f"pymysql.connect was called {mock_connect.call_count} times "
            f"despite malicious --database — safe_identifier must run first."
        )

    def test_accepts_valid_database_name(self):
        """Regression lock."""
        import load_espp_plan as tool

        with patch("pymysql.connect", return_value=MagicMock()):
            tool.get_connection(database="valid_db_name")


# ---------------------------------------------------------------------------
# Site 3: openbb_fmp_cached/utils/database.py::init_database
# ---------------------------------------------------------------------------


class TestInitDatabase:
    """utils/database.py::init_database — database name from DatabaseConfig (bd-o1oy)."""

    def test_rejects_malicious_database_name_from_config(self, monkeypatch):
        """Malicious database name in DatabaseConfig MUST raise (bd-o1oy)."""
        monkeypatch.setenv("FMP_CACHE_AUTO_CREATE_DB", "true")

        from openbb_fmp_cached.utils import database

        # Fake DatabaseConfig that returns a malicious database name.
        fake_config = MagicMock()
        fake_config.connection_params = {
            "host": "localhost",
            "user": "test",
            "password": "test",
            "database": "openbb; DROP DATABASE foo; --",
            "port": 3306,
        }

        with patch.object(database, "DatabaseConfig", return_value=fake_config), patch(
            "openbb_fmp_cached.utils.database.pymysql.connect"
        ) as mock_connect:
            with pytest.raises(ValueError):
                database.init_database(auto_create=True)

        # Connection MUST NOT have been opened — rejection happens
        # BEFORE any DB work.
        assert mock_connect.call_count == 0

    def test_accepts_valid_database_name(self, monkeypatch):
        """Regression lock: a valid database name completes init."""
        monkeypatch.setenv("FMP_CACHE_AUTO_CREATE_DB", "true")

        from openbb_fmp_cached.utils import database

        fake_config = MagicMock()
        fake_config.connection_params = {
            "host": "localhost",
            "user": "test",
            "password": "test",
            "database": "openbb_fmp_cache_valid",
            "port": 3306,
        }

        fake_conn = MagicMock()
        fake_cursor = MagicMock()
        fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
        fake_conn.cursor.return_value.__exit__.return_value = False

        with patch.object(database, "DatabaseConfig", return_value=fake_config), patch(
            "openbb_fmp_cached.utils.database.pymysql.connect", return_value=fake_conn
        ), patch(
            "openbb_fmp_cached.utils.cache_schema.create_all_tables"
        ) as mock_create:
            database.init_database(auto_create=True)

        # Cursor should have executed a CREATE DATABASE with the
        # sanitized (unchanged) name.
        executed_sql = fake_cursor.execute.call_args_list[0].args[0]
        assert "CREATE DATABASE" in executed_sql.upper()
        assert "openbb_fmp_cache_valid" in executed_sql
        # And create_all_tables must have been called (init flow completed).
        assert mock_create.call_count == 1


# ---------------------------------------------------------------------------
# Site 4: openbb_fmp_cached/utils/cache_schema.py::get_table_name
# ---------------------------------------------------------------------------


class TestGetTableName:
    """utils/cache_schema.py::get_table_name — allowlist-validate base (bd-20zx).

    ~60 create-table functions f-string-interpolate the return value of
    get_table_name() into CREATE TABLE DDL. If get_table_name ever
    accepts unsanitized input, every one of those 60 becomes an
    injection vector. The fix routes base_name through safe_identifier
    inside get_table_name so the invariant is structurally enforced.
    """

    def test_rejects_malicious_base_name(self, monkeypatch):
        """A malicious base_name MUST raise, not fall through to CREATE TABLE."""
        monkeypatch.delenv("FMP_CACHE_TEST_MODE", raising=False)

        from openbb_fmp_cached.utils.cache_schema import get_table_name

        with pytest.raises(ValueError):
            get_table_name("balance_sheet; DROP TABLE users; --")

    def test_rejects_malicious_base_name_in_test_mode(self, monkeypatch):
        """test-mode prefix must not save malicious base names.

        Pre-fix ``get_table_name`` would prepend ``test_`` and return
        the composed string — but the composed ``test_balance_sheet;
        DROP TABLE users; --`` is still an injection payload. Post-fix
        the base is validated BEFORE the prefix is applied.
        """
        monkeypatch.setenv("FMP_CACHE_TEST_MODE", "true")

        from openbb_fmp_cached.utils.cache_schema import get_table_name

        with pytest.raises(ValueError):
            get_table_name("balance_sheet; DROP TABLE users; --")

    def test_accepts_valid_base_name(self, monkeypatch):
        """Regression lock: standard snake_case table names still work."""
        monkeypatch.delenv("FMP_CACHE_TEST_MODE", raising=False)

        from openbb_fmp_cached.utils.cache_schema import get_table_name

        assert get_table_name("balance_sheet") == "balance_sheet"
        assert get_table_name("analyst_estimates") == "analyst_estimates"

    def test_accepts_valid_base_name_in_test_mode(self, monkeypatch):
        """Regression lock: test-mode prefixing preserved for valid names."""
        monkeypatch.setenv("FMP_CACHE_TEST_MODE", "true")

        from openbb_fmp_cached.utils.cache_schema import get_table_name

        # test_ prefix + valid base should compose into a valid
        # identifier (test_balance_sheet is still allowlist-compliant).
        result = get_table_name("balance_sheet")
        assert result == "test_balance_sheet"
