"""Simple synchronous MySQL database utilities for FMP cached provider."""

import os
from typing import Any, Dict, Optional
import json
import logging
from contextlib import contextmanager
import pymysql.cursors

logger = logging.getLogger(__name__)


class DatabaseConfig:
    """Database configuration manager."""

    def __init__(self):
        """Initialize database configuration from user settings."""
        self.config = self._load_config()
        self._require_credentials()

    def _require_credentials(self) -> None:
        """Fail fast when DB user/password are not configured.

        Credentials must be supplied via OpenBB ``user_settings.json`` or the
        ``DB_USER``/``DB_PASSWORD`` environment variables. We never ship a
        default credential pair in source.
        """
        missing = [
            field for field in ("user", "password") if not self.config.get(field)
        ]
        if missing:
            raise ValueError(
                "Missing MySQL credential(s): "
                f"{', '.join(missing)}. Configure them in "
                "~/.openbb_platform/user_settings.json (e.g. 'mysql_user', "
                "'mysql_password') or via the DB_USER/DB_PASSWORD environment "
                "variables. No default credentials are provided."
            )

    def _load_config(self) -> Dict[str, Any]:
        """Load database configuration from OpenBB user settings, with environment variable fallback."""

        # Check if we're in test mode
        is_test_mode = os.getenv("FMP_CACHE_TEST_MODE", "false").lower() == "true"
        test_database = "openbb_fmp_cache_test" if is_test_mode else "openbb_fmp_cache"

        # No hardcoded credential defaults: user/password must come from
        # OpenBB user_settings.json or environment variables. We fail fast
        # (see _require_credentials) if they are missing.
        default_config = {
            "host": "localhost",
            "port": 3306,
            "user": None,
            "password": None,
            "database": test_database,
            "charset": "utf8mb4",
            "test_mode": is_test_mode,
        }

        # First try OpenBB user settings (preferred)
        settings_path = os.path.expanduser("~/.openbb_platform/user_settings.json")

        try:
            if os.path.exists(settings_path):
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                    credentials = settings.get("credentials", {})

                    # Check if MySQL credentials are configured (try multiple naming patterns)
                    mysql_keys = [
                        "mysql_host",
                        "mysql_user",
                        "mysql_password",
                        "mysql_database",
                        "db_host",
                        "db_user",
                        "db_password",
                        "db_database",
                        "database_host",
                        "database_user",
                        "database_password",
                        "database_name",
                    ]

                    if any(key in credentials for key in mysql_keys):
                        # Try multiple naming patterns for each field
                        host = (
                            credentials.get("mysql_host")
                            or credentials.get("db_host")
                            or credentials.get("database_host")
                            or default_config["host"]
                        )

                        port = int(
                            credentials.get("mysql_port")
                            or credentials.get("db_port")
                            or credentials.get("database_port")
                            or default_config["port"]
                        )

                        user = (
                            credentials.get("mysql_user")
                            or credentials.get("db_user")
                            or credentials.get("database_user")
                            or default_config["user"]
                        )

                        password = (
                            credentials.get("mysql_password")
                            or credentials.get("db_password")
                            or credentials.get("database_password")
                            or default_config["password"]
                        )

                        database = (
                            credentials.get("mysql_database")
                            or credentials.get("db_database")
                            or credentials.get("database_name")
                            or default_config["database"]
                        )

                        # Override with test database if in test mode
                        if is_test_mode:
                            database = "openbb_fmp_cache_test"

                        config = {
                            "host": host,
                            "port": port,
                            "user": user,
                            "password": password,
                            "database": database,
                            "charset": default_config["charset"],
                            "test_mode": is_test_mode,
                        }

                        logger.info(
                            f"Using MySQL configuration from OpenBB user settings: {user}@{host}:{port}/{database}"
                        )
                        return config
        except Exception as e:
            logger.warning(f"Failed to load OpenBB user settings: {e}")

        # Fallback to environment variables
        env_database = os.getenv("DB_NAME", default_config["database"])
        if is_test_mode:
            env_database = "openbb_fmp_cache_test"

        env_config = {
            "host": os.getenv("DB_HOST", default_config["host"]),
            "port": int(os.getenv("DB_PORT", str(default_config["port"]))),
            "user": os.getenv("DB_USER", default_config["user"]),
            "password": os.getenv("DB_PASSWORD", default_config["password"]),
            "database": env_database,
            "charset": default_config["charset"],
            "test_mode": is_test_mode,
        }

        # If any environment variables are set, use them
        if any(
            os.getenv(var) for var in ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"]
        ):
            logger.info("Using MySQL configuration from environment variables")
            return env_config

        # Final fallback to defaults
        logger.info("Using default MySQL configuration")
        return default_config

    @property
    def connection_params(self) -> Dict[str, Any]:
        """Get connection parameters for pymysql."""
        params = self.config.copy()
        # Remove non-pymysql parameters
        params.pop("test_mode", None)
        return params


class ConnectionPool:
    """Simple synchronous MySQL connection manager."""

    def __init__(self, config: DatabaseConfig):
        """Initialize MySQL connection manager."""
        self.config = config

    @contextmanager
    def get_connection(self):
        """Get MySQL database connection (context manager)."""
        connection = pymysql.connect(
            **self.config.connection_params,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        try:
            yield connection
        except Exception as e:
            logger.error(f"MySQL connection error: {e}")
            raise
        finally:
            connection.close()


# Global connection pool instance
_connection_pool: Optional[ConnectionPool] = None


def get_connection_pool() -> ConnectionPool:
    """Get global connection pool instance."""
    global _connection_pool
    if _connection_pool is None:
        config = DatabaseConfig()
        _connection_pool = ConnectionPool(config)
    return _connection_pool


def execute_query(query: str, params: tuple = ()) -> Any:
    """Execute a MySQL query and return results."""
    pool = get_connection_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            if query.strip().upper().startswith("SELECT"):
                return cursor.fetchall()
            return cursor.rowcount


def execute_many(query: str, params_list: list) -> int:
    """Execute a MySQL query with multiple parameter sets."""
    pool = get_connection_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(query, params_list)
            return cursor.rowcount


# ---------------------------------------------------------------------------
# Tier-0 safety helpers (bd-kh08)
# ---------------------------------------------------------------------------
#
# Design spec:
#   docs/superpowers/specs/2026-07-08-bd-kh08-tier0-db-helpers-design.md
#
# safe_identifier — validates a caller-controlled string against a strict
#   regex allowlist BEFORE it can be interpolated into a DDL identifier
#   position. Fixes the CREATE-DATABASE SQL-injection cluster (bd-y5fn /
#   v9ri / 20zx / o1oy). Not a general SQL escape — use parameterized
#   queries for value positions.
#
# replace_rows — DELETE + INSERT wrapped in a single explicit transaction
#   on a fresh autocommit=False connection. Fixes the DELETE-then-INSERT
#   data-loss cluster where a mid-batch INSERT failure leaves the cache
#   empty (bd-ihdn / n3sf / 2650 / gykp / hyzu).


import re as _re  # local alias — module already imports os but not re

# MySQL 8.x unquoted identifier grammar (SQL-92 subset): 1-64 chars,
# leading letter/underscore, alphanumeric+underscore body. Rejects the
# entire universe of "identifiers-that-are-actually-SQL-fragments".
_IDENTIFIER_ALLOWLIST = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def safe_identifier(name: str) -> str:
    """Validate a SQL identifier against a strict regex allowlist (bd-kh08).

    MySQL's parameterized-query API does not accept identifier positions
    (database / table / column names) — only values. This helper is the
    ONLY approved way to interpolate a caller-controlled string into a
    DDL identifier position.

    Rules (matches MySQL 8.x unquoted identifier grammar, SQL-92 subset):
      * 1-64 characters
      * Must start with a letter (``A-Z``, ``a-z``) or underscore
      * Remaining chars: letters, digits, underscores

    Parameters
    ----------
    name : str
        The candidate identifier. Typically a database name from a CLI
        arg or config file that will be interpolated into a DDL statement
        (e.g. ``CREATE DATABASE IF NOT EXISTS {name}``).

    Returns
    -------
    str
        ``name`` unchanged if valid — so callers can write
        ``f"CREATE DATABASE IF NOT EXISTS {safe_identifier(db)}"``.

    Raises
    ------
    ValueError
        On any input that doesn't match the allowlist. The message
        includes ``repr(name)`` so operators can trace what was
        rejected.

    Notes
    -----
    NOT a general SQL escape — for value positions, use ``execute_query``
    with parameterized ``%s`` placeholders. This helper is *only* for
    DDL identifier positions that can't be parameterized.
    """
    if not isinstance(name, str) or not _IDENTIFIER_ALLOWLIST.match(name):
        raise ValueError(
            f"Invalid SQL identifier: {name!r}. Identifiers must match "
            f"the MySQL 8.x unquoted grammar (1-64 chars, leading "
            f"letter/underscore, alphanumeric+underscore body). Rejecting "
            f"loudly to prevent DDL injection (bd-kh08)."
        )
    return name


def replace_rows(
    table: str,
    where_col: str,
    where_val: Any,
    rows: list[dict[str, Any]],
    *,
    columns: list[str] | None = None,
) -> int:
    """Atomically DELETE + INSERT rows in a single transaction (bd-kh08).

    Wraps DELETE + INSERT in a single explicit transaction on a fresh
    ``autocommit=False`` connection. Fixes the autocommit + DELETE-then-
    INSERT data-loss class where a partial-write failure between the
    DELETE and the INSERT leaves the cache empty (bd-ihdn, bd-n3sf,
    bd-2650, bd-gykp, bd-hyzu).

    Parameters
    ----------
    table : str
        SQL table name. Passed through :func:`safe_identifier` (defense
        in depth — the ``INSERT INTO {table}`` position cannot be
        parameterized).
    where_col : str
        Column name for the ``DELETE ... WHERE {where_col} = %s`` clause.
        Passed through :func:`safe_identifier`.
    where_val : Any
        Value the WHERE clause matches. Parameterized — NOT interpolated.
    rows : list[dict[str, Any]]
        Row dicts to INSERT. An empty list is a valid degenerate case
        (just does the DELETE atomically) — the contract is "either
        everything happens or nothing happens", including the empty
        case.
    columns : list[str] | None, optional
        Explicit column list for the INSERT. If ``None`` (default), the
        columns are inferred from the SORTED union of keys across all
        ``rows`` (deterministic across Python versions, log-diff-stable).

    Returns
    -------
    int
        Number of rows inserted (from ``cursor.rowcount`` after the
        INSERT — 0 if ``rows`` was empty or the INSERT was skipped).

    Raises
    ------
    ValueError
        If ``table`` or ``where_col`` fails :func:`safe_identifier`.
    Exception
        Whatever the underlying DB raises. The transaction is rolled
        back FIRST, so the pre-existing rows survive.

    Notes
    -----
    Uses a fresh ``pymysql.connect(..., autocommit=False)`` connection,
    NOT the shared pool. The pool's connections have ``autocommit=True``
    baked in at get-time, and toggling autocommit mid-connection is a
    known pymysql footgun. Fresh connection + explicit
    commit/rollback/close is simpler and correct (design decision D3).
    """
    # Defense in depth: both identifiers land in un-parameterizable
    # positions in the SQL string below, so they MUST be allowlist-
    # validated first.
    safe_table = safe_identifier(table)
    safe_where = safe_identifier(where_col)

    # Column inference — sorted union of keys across all rows. Sorted
    # is deterministic (independent of Python's dict-hash-randomization)
    # and makes the resulting SQL diff-stable in logs (design D4).
    if columns is None:
        keys: set[str] = set()
        for row in rows:
            keys.update(row.keys())
        columns = sorted(keys)

    # Validate every column name too — same DDL-injection defense.
    for col in columns:
        safe_identifier(col)

    delete_sql = f"DELETE FROM {safe_table} WHERE {safe_where} = %s"
    inserted = 0

    conn = pymysql.connect(
        **DatabaseConfig().connection_params,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(delete_sql, (where_val,))
            if rows and columns:
                col_list = ", ".join(columns)
                placeholders = ", ".join(["%s"] * len(columns))
                insert_sql = (
                    f"INSERT INTO {safe_table} ({col_list}) " f"VALUES ({placeholders})"
                )
                # Build the parameter tuples in the same column order.
                # Missing keys default to None (represents SQL NULL) so
                # the caller doesn't have to pre-fill every dict.
                params_list = [tuple(row.get(col) for col in columns) for row in rows]
                cursor.executemany(insert_sql, params_list)
                inserted = cursor.rowcount
        conn.commit()
    except Exception:
        # bd-kh08: rollback FIRST so the pre-existing rows survive,
        # then re-raise so the caller can decide what to do.
        try:
            conn.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            # Rollback itself failed — log and swallow so we don't
            # mask the original exception the caller cares about.
            logger.error(
                "replace_rows rollback failed for table %r: %s",
                safe_table,
                rollback_exc,
            )
        raise
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass  # best-effort close; don't mask user-visible errors

    return inserted


def init_database(auto_create: bool = None):
    """Initialize MySQL database and create tables if they don't exist.

    Args:
        auto_create: If True, automatically create database and tables.
                    If False, skip creation and use existing database.
                    If None (default), use FMP_CACHE_AUTO_CREATE_DB environment variable.
                    Defaults to False if environment variable is not set.

    Returns:
        True if database/tables were created or already exist, False otherwise.
    """
    # Determine whether to auto-create based on explicit flag or environment variable
    if auto_create is None:
        auto_create = os.getenv("FMP_CACHE_AUTO_CREATE_DB", "false").lower() == "true"

    if not auto_create:
        logger.info("Skipping database/table creation (FMP_CACHE_AUTO_CREATE_DB=false)")
        return True

    config = DatabaseConfig()
    temp_config = config.connection_params.copy()
    database_name = temp_config.pop("database", "openbb_fmp_cache")

    # Connect to MySQL without specifying database to create it
    connection = pymysql.connect(**temp_config)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database_name}")
            logger.info(f"Database '{database_name}' ready")
    finally:
        connection.close()

    # Now create tables in the target database
    from .cache_schema import create_all_tables

    result = create_all_tables()
    logger.info("Database initialization complete")
    return result
