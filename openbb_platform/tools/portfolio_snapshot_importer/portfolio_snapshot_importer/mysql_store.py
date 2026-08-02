"""MySQL-backed positions history store (#1744).

Adds ``pi_snapshot`` / ``pi_position`` as **additive** tables in the
existing ``openbb_fmp_cache_test`` database. The corporate
``Portfolio_Positions`` / ``portfolio_basket`` pipeline is NOT touched.

Backed by :class:`openbb_fmp_cached.utils.database.DatabaseConfig` for
connection resolution and connection pooling. Idempotent on
``(source_sha256, user_id)`` via ``INSERT IGNORE`` (matches the
``parse_fidelity_positions.py`` style — no ``ON DUPLICATE KEY UPDATE``,
which would silently overwrite historical rows on hash collision).

Design contract: this class satisfies the
:class:`portfolio_snapshot_importer.store.PortfolioStore` Protocol.
Every method returns rows shaped identically to the SQLite backend so
``basket_bridge`` and the widget backend can consume either
interchangeably.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from portfolio_snapshot_importer.store import _POSITION_COLS, SCHEMA_VERSION

logger = logging.getLogger(__name__)


_PI_SNAPSHOT_DDL = """
CREATE TABLE IF NOT EXISTS pi_snapshot (
    snapshot_id       VARCHAR(64) PRIMARY KEY,
    snapshot_date     DATE NOT NULL,
    user_id           VARCHAR(64) NOT NULL,
    source_filename   TEXT NOT NULL,
    source_sha256     CHAR(64) NOT NULL,
    imported_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    row_count_raw     INT NOT NULL,
    row_count_kept    INT NOT NULL,
    row_count_skipped INT NOT NULL,
    schema_version    INT NOT NULL,
    UNIQUE KEY ux_pi_snapshot_content (source_sha256, user_id),
    INDEX ix_pi_snapshot_date_user (snapshot_date, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_PI_POSITION_DDL = """
CREATE TABLE IF NOT EXISTS pi_position (
    position_id                 INT AUTO_INCREMENT PRIMARY KEY,
    snapshot_id                 VARCHAR(64) NOT NULL,
    snapshot_date               DATE NOT NULL,
    user_id                     VARCHAR(64) NOT NULL,
    account_number              VARCHAR(32) NOT NULL,
    account_name                VARCHAR(128),
    basket_name                 VARCHAR(128),
    symbol                      VARCHAR(16) NOT NULL,
    description                 TEXT,
    type                        VARCHAR(32),
    quantity                    DECIMAL(20, 6),
    last_price                  DECIMAL(20, 6),
    last_price_change           DECIMAL(20, 6),
    current_value               DECIMAL(20, 4),
    today_gain_loss_dollar      DECIMAL(20, 4),
    today_gain_loss_percent     DECIMAL(10, 6),
    total_gain_loss_dollar      DECIMAL(20, 4),
    total_gain_loss_percent     DECIMAL(10, 6),
    percent_of_account          DECIMAL(10, 8),
    cost_basis_total            DECIMAL(20, 4),
    average_cost_basis          DECIMAL(20, 6),
    raw_row_number              INT NOT NULL,
    INDEX ix_pi_position_snapshot (snapshot_id),
    INDEX ix_pi_position_dus (snapshot_date, user_id, symbol),
    INDEX ix_pi_position_dua (snapshot_date, user_id, account_number),
    CONSTRAINT fk_pi_position_snapshot
        FOREIGN KEY (snapshot_id) REFERENCES pi_snapshot(snapshot_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


class MySqlPortfolioStore:
    """MySQL-backed PortfolioStore.

    Instantiation resolves connection params through
    :class:`DatabaseConfig` — the FMP-cache pool. Fails loudly if
    the DB isn't reachable (the factory in ``store.py`` catches this
    for the fallback path).
    """

    def __init__(self, connection_pool: Any = None) -> None:
        """Instantiate. ``connection_pool`` is injectable for tests.

        In production, we default to the shared pool from
        ``get_connection_pool()``. Tests inject a mock pool that
        speaks SQLite-with-a-thin-shim so the same test suite runs
        without a live MySQL.
        """
        if connection_pool is None:
            from openbb_fmp_cached.utils.database import (  # noqa: PLC0415
                get_connection_pool,
            )

            connection_pool = get_connection_pool()
        self._pool = connection_pool
        self._ensure_schema()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        # Connections come from a shared pool; don't close it here.
        pass

    def __enter__(self) -> MySqlPortfolioStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _acquire(self) -> Iterator[Any]:
        conn = self._pool.get_connection()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """Explicit BEGIN/COMMIT scope (rollback on exception)."""
        with self._acquire() as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------
    def _ensure_schema(self) -> None:
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute(_PI_SNAPSHOT_DDL)
            cur.execute(_PI_POSITION_DDL)
            cur.close()

    # ------------------------------------------------------------------
    # writes (append-only)
    # ------------------------------------------------------------------
    def snapshot_exists(self, source_sha256: str, user_id: str) -> str | None:
        with self._acquire() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT snapshot_id FROM pi_snapshot "
                "WHERE source_sha256 = %s AND user_id = %s",
                (source_sha256, user_id),
            )
            row = cur.fetchone()
            cur.close()
        if row is None:
            return None
        # Rows may come back as tuple/list, sqlite3.Row, or dict depending
        # on cursor config. Handle all three.
        if isinstance(row, (tuple, list)):
            return row[0]
        try:
            return row["snapshot_id"]
        except (KeyError, IndexError):
            return None

    def insert_snapshot(self, meta: dict) -> None:
        """INSERT IGNORE — duplicate (sha, user) is silently skipped."""
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT IGNORE INTO pi_snapshot(
                    snapshot_id, snapshot_date, user_id, source_filename,
                    source_sha256, row_count_raw, row_count_kept,
                    row_count_skipped, schema_version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    meta["snapshot_id"],
                    meta["snapshot_date"],
                    meta["user_id"],
                    meta["source_filename"],
                    meta["source_sha256"],
                    meta["row_count_raw"],
                    meta["row_count_kept"],
                    meta["row_count_skipped"],
                    meta.get("schema_version", SCHEMA_VERSION),
                ),
            )
            cur.close()

    def insert_positions(self, rows: Iterable[dict]) -> int:
        payload = list(rows)
        if not payload:
            return 0
        placeholders = ", ".join(["%s"] * len(_POSITION_COLS))
        sql = (
            f"INSERT INTO pi_position({', '.join(_POSITION_COLS)}) "
            f"VALUES ({placeholders})"
        )
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.executemany(
                sql, [tuple(r.get(k) for k in _POSITION_COLS) for r in payload]
            )
            cur.close()
        return len(payload)

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def list_snapshots(self, user_id: str | None = None) -> list:
        with self._acquire() as conn:
            cur = (
                conn.cursor(dictionary=True)
                if _supports_dict_cursor(conn)
                else conn.cursor()
            )
            if user_id:
                cur.execute(
                    "SELECT * FROM pi_snapshot WHERE user_id = %s "
                    "ORDER BY snapshot_date DESC",
                    (user_id,),
                )
            else:
                cur.execute(
                    "SELECT * FROM pi_snapshot " "ORDER BY snapshot_date DESC, user_id"
                )
            rows = cur.fetchall()
            cur.close()
        return list(rows)

    def positions_for(self, snapshot_id: str) -> list:
        with self._acquire() as conn:
            cur = (
                conn.cursor(dictionary=True)
                if _supports_dict_cursor(conn)
                else conn.cursor()
            )
            cur.execute(
                "SELECT * FROM pi_position WHERE snapshot_id = %s "
                "ORDER BY account_number, symbol",
                (snapshot_id,),
            )
            rows = cur.fetchall()
            cur.close()
        return list(rows)

    def latest_snapshot(self, user_id: str) -> Any:
        with self._acquire() as conn:
            cur = (
                conn.cursor(dictionary=True)
                if _supports_dict_cursor(conn)
                else conn.cursor()
            )
            cur.execute(
                "SELECT * FROM pi_snapshot WHERE user_id = %s "
                "ORDER BY snapshot_date DESC LIMIT 1",
                (user_id,),
            )
            row = cur.fetchone()
            cur.close()
        return row


def _supports_dict_cursor(conn: Any) -> bool:
    """Best-effort probe: MySQL Connector supports ``cursor(dictionary=True)``.

    Test doubles that use sqlite3 don't. This lets us keep one code
    path for both.
    """
    try:
        # cursor() with dictionary= exists on mysql.connector but not on
        # sqlite3. Try a very cheap call.
        return (
            "dictionary"
            in getattr(
                conn.cursor, "__code__", type("", (), {"co_varnames": ()})
            ).co_varnames
        )
    except Exception:  # noqa: BLE001
        return False
