"""Simple synchronous MySQL database utilities for FMP cached provider."""

# pylint: disable=logging-fstring-interpolation,wrong-import-position,wrong-import-order,import-outside-toplevel

import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import pymysql.cursors

logger = logging.getLogger(__name__)
_database_override: ContextVar[str | None] = ContextVar(
    "fmp_cached_database_override", default=None
)
_connection_config_override: ContextVar[Any] = ContextVar(
    "fmp_cached_connection_config_override", default=None
)


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

    def _load_config(self) -> dict[str, Any]:
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
                with open(settings_path) as f:
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
    def connection_params(self) -> dict[str, Any]:
        """Get connection parameters for pymysql."""
        params = self.config.copy()
        # Remove non-pymysql parameters
        params.pop("test_mode", None)
        return params


class ConnectionPool:
    """Simple synchronous MySQL connection manager."""

    def __init__(self, config: DatabaseConfig, database: str | None = None):
        """Initialize MySQL connection manager."""
        self.config = config
        self.database = database

    @property
    def connection_params(self) -> dict[str, Any]:
        """Return connection parameters with any request-scoped database."""
        params = self.config.connection_params
        if self.database is not None:
            params["database"] = self.database
        return params

    @contextmanager
    def get_connection(self):
        """Get MySQL database connection (context manager)."""
        connection = pymysql.connect(
            **self.connection_params,
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
_connection_pool: ConnectionPool | None = None


def get_connection_pool() -> ConnectionPool:
    """Get global connection pool instance."""
    global _connection_pool  # noqa: PLW0603  # pylint: disable=global-statement
    scoped_config = _connection_config_override.get()
    if scoped_config is not None:
        return ConnectionPool(scoped_config, database=_database_override.get())
    if _connection_pool is None:
        config = DatabaseConfig()
        _connection_pool = ConnectionPool(config)
    override = _database_override.get()
    if override is not None:
        return ConnectionPool(_connection_pool.config, database=override)
    return _connection_pool


def execute_query(query: str, params: tuple = ()) -> Any:
    """Execute a MySQL query and return results."""
    pool = get_connection_pool()
    with pool.get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(query, params)
        if query.strip().upper().startswith("SELECT"):
            return cursor.fetchall()
        return cursor.rowcount


def execute_many(query: str, params_list: list) -> int:
    """Execute a MySQL query with multiple parameter sets."""
    pool = get_connection_pool()
    with pool.get_connection() as conn, conn.cursor() as cursor:
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


@contextmanager
def database_override(database: str | None):
    """Select a database for this execution context without global mutation."""
    if database is None:
        yield
        return

    validated = safe_identifier(database)
    token = _database_override.set(validated)
    try:
        yield
    finally:
        _database_override.reset(token)


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
    #
    # PR #414 code-reviewer P2: track whether columns came from the
    # caller (explicit) or from inference. When explicit, a missing row
    # key is a caller-contract violation and MUST raise loudly (matches
    # safe_identifier's loud-rejection philosophy). When inferred, the
    # union-of-keys means some rows genuinely have fewer keys — None-
    # fill is the correct default there.
    columns_were_explicit = columns is not None
    if columns is None:
        keys: set[str] = set()
        for row in rows:
            keys.update(row.keys())
        columns = sorted(keys)

    # PR #414 silent-failure-hunter P1: reject non-empty rows with an
    # empty columns list. Pre-fix ``if rows and columns:`` guarded the
    # INSERT on both being truthy — a caller passing rows + explicit
    # ``columns=[]`` would DELETE then silently skip the INSERT and
    # commit, producing the exact "cache empty after replace_rows"
    # failure this helper exists to prevent. If columns is inferred
    # from empty rows (all rows are empty dicts), also reject: nothing
    # to insert AND a non-empty rows list is a caller-contract error.
    if rows and not columns:
        raise ValueError(
            f"replace_rows called with {len(rows)} non-empty rows but no "
            f"columns to insert (columns_were_explicit={columns_were_explicit}). "
            f"Empty columns + non-empty rows would DELETE then silently skip "
            f"the INSERT — the exact silent-cache-empty failure this helper "
            f"exists to prevent (bd-kh08 PR #414 hunter P1). Pass an explicit "
            f"columns list or ensure rows contain non-empty dicts."
        )

    # Validate every column name too — same DDL-injection defense.
    for col in columns:
        safe_identifier(col)

    delete_sql = f"DELETE FROM {safe_table} WHERE {safe_where} = %s"  # noqa: S608
    inserted = 0

    # PR #414 code-reviewer P1: reuse the pool's config singleton
    # instead of instantiating DatabaseConfig() here. Pre-fix, every
    # call re-read ~/.openbb_platform/user_settings.json from disk +
    # re-parsed JSON. A batch caller hitting 100 symbols would do 100
    # disk reads on top of 100 fresh connections. Design D3 accepts
    # the connect cost — it doesn't need to accept the config cost.
    # The pool's config is a module-level singleton; connection_params
    # is already correct (strips test_mode etc.).
    connection_params = get_connection_pool().connection_params
    conn = pymysql.connect(
        **connection_params,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(delete_sql, (where_val,))
            if rows and columns:
                col_list = ", ".join(columns)
                placeholders = ", ".join(["%s"] * len(columns))
                insert_sql = f"INSERT INTO {safe_table} ({col_list}) VALUES ({placeholders})"  # noqa: S608
                # Build the parameter tuples in the same column order.
                # PR #414 code-reviewer P2: explicit columns mean the
                # caller declared a contract — a missing key is a bug,
                # raise loudly. Inferred columns come from the union of
                # keys across rows, so a missing key is expected and
                # gets None (SQL NULL).
                if columns_were_explicit:
                    params_list = []
                    for row_idx, row in enumerate(rows):
                        try:
                            params_list.append(tuple(row[col] for col in columns))
                        except KeyError as exc:
                            raise KeyError(
                                f"replace_rows row index {row_idx} is missing "
                                f"key {exc.args[0]!r} declared in the explicit "
                                f"columns list {columns!r}. Explicit columns are "
                                f"treated as a caller contract; use "
                                f"columns=None (inferred) if row shapes vary."
                            ) from exc
                else:
                    params_list = [
                        tuple(row.get(col) for col in columns) for row in rows
                    ]
                cursor.executemany(insert_sql, params_list)
                inserted = cursor.rowcount
        conn.commit()
    except Exception as orig_exc:
        # bd-kh08: rollback FIRST so the pre-existing rows survive,
        # then re-raise so the caller can decide what to do.
        try:
            conn.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            # PR #414 code-reviewer P2: include BOTH the original
            # exception (why rollback was needed) AND the rollback
            # failure (why cleanup broke) in the log so operators
            # debugging cache corruption see the full causal chain.
            # The traceback of orig_exc survives via the ``raise``
            # below for humans; the log is what monitoring systems
            # capture.
            logger.error(
                "replace_rows rollback failed for table %r: "
                "original exception was %r (rollback error: %r)",
                safe_table,
                orig_exc,
                rollback_exc,
            )
        raise
    finally:
        try:
            conn.close()
        except Exception as close_exc:  # noqa: BLE001
            # PR #414 hunter P2: log at DEBUG so operators tracing pool
            # exhaustion or MySQL configuration issues can see the
            # close-failure history. Not raised — best-effort close so
            # we don't mask user-visible errors from the try block.
            logger.debug(
                "replace_rows: connection close failed for table %r: %r",
                safe_table,
                close_exc,
            )

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

    # Initialization intentionally resolves fresh process configuration on
    # every call. Caching a failed configuration here would make later retries
    # ignore repaired settings. Apply only the context-local database choice.
    config = DatabaseConfig()
    temp_config = config.connection_params
    override = _database_override.get()
    if override is not None:
        temp_config["database"] = override
    database_name = temp_config.pop("database", "openbb_fmp_cache")

    # bd-9loj/o1oy: validate the database name BEFORE any DB work.
    # Rejection happens loudly (ValueError) before pymysql.connect fires,
    # so a malicious config value cannot reach the DDL string.
    safe_database_name = safe_identifier(database_name)

    # Connect to MySQL without specifying database to create it
    connection = pymysql.connect(**temp_config)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {safe_database_name}")
            logger.info(f"Database '{safe_database_name}' ready")
    finally:
        connection.close()

    # Now create tables in the target database
    from .cache_schema import create_all_tables

    token = _connection_config_override.set(config)
    try:
        result = create_all_tables()
    finally:
        _connection_config_override.reset(token)
    logger.info("Database initialization complete")
    return result


# ---------------------------------------------------------------------------
# Schema-version tracking (Wave 0 A4 / #1317)
# ---------------------------------------------------------------------------
#
# Motivation: `cache_schema.py` uses `CREATE TABLE IF NOT EXISTS` everywhere,
# so multiple downstream waves adding new tables are already idempotent at
# the DDL level. But some migrations are NOT idempotent (e.g. "add a column
# to an existing table" or "backfill a computed value"). For those we need
# a way to record whether a migration has run.
#
# Downstream contract:
#   if not migration_ran("W1-statements-add-ttm-tables"):
#       create_income_statement_ttm_table()
#       ...
#       record_migration("W1-statements-add-ttm-tables")
#
# The table itself is created lazily on first read/write so no init-order
# dance is needed. Failures degrade gracefully — if the DB is down or the
# schema_version table can't be created, the helper returns False (so the
# migration will re-run on next boot) rather than crashing the caller.


_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version VARCHAR(255) NOT NULL PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def _ensure_schema_version_table() -> bool:
    """Create the schema_version table if it doesn't exist.

    Returns True on success, False on any DB error (so callers can degrade
    gracefully without crashing on a missing DB).
    """
    try:
        execute_query(_SCHEMA_VERSION_DDL)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("schema_version table create failed: %s", exc)
        return False


def migration_ran(version: str) -> bool:
    """Return True if ``version`` has been recorded as applied.

    Downstream waves call this to gate non-idempotent DDL / backfills.
    If the schema_version table itself can't be created or queried,
    returns False (so the migration will attempt to run — which is the
    safe direction, since DDL is idempotent when it uses IF NOT EXISTS).
    """
    if not version or not isinstance(version, str):
        raise ValueError(
            f"migration_ran: version must be a non-empty str; got {version!r}"
        )
    if not _ensure_schema_version_table():
        return False
    try:
        rows = execute_query(
            "SELECT 1 FROM schema_version WHERE version = %s LIMIT 1",
            (version,),
        )
        return bool(rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("migration_ran query failed for %r: %s", version, exc)
        return False


def record_migration(version: str, notes: str | None = None) -> bool:
    """Record ``version`` as applied. Idempotent via INSERT IGNORE.

    Downstream waves call this AFTER the migration's DDL / backfill has
    succeeded. Returns True on success, False on DB error (with WARN log).
    Callers should treat False as a signal to re-run the migration on
    next boot rather than proceeding as if the recording succeeded.
    """
    if not version or not isinstance(version, str):
        raise ValueError(
            f"record_migration: version must be a non-empty str; got {version!r}"
        )
    if not _ensure_schema_version_table():
        return False
    try:
        # INSERT IGNORE so re-recording is a no-op (idempotent).
        execute_query(
            "INSERT IGNORE INTO schema_version (version, notes) VALUES (%s, %s)",
            (version, notes),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("record_migration failed for %r: %s", version, exc)
        return False


def list_migrations() -> list[dict]:
    """List all recorded migrations. Returns [] on DB error.

    Useful for ops-time debugging: which of the expected migrations
    have run in this deployment?
    """
    if not _ensure_schema_version_table():
        return []
    try:
        return (
            execute_query(
                "SELECT version, applied_at, notes FROM schema_version ORDER BY applied_at ASC"
            )
            or []
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("list_migrations failed: %s", exc)
        return []
