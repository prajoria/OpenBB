"""Append-only positions history store — Protocol + backends.

The **Protocol** :class:`PortfolioStore` defines the 8-method surface every
backend must implement. Consumers (``ingest.py``, ``basket_bridge.py``,
CLI) depend on the Protocol only; the concrete backend is chosen at
runtime via :func:`get_default_store`.

Two backends ship today:

- :class:`SqlitePortfolioStore` — user-local, zero-dep. Default DB path
  ``~/.portfolio_importer/positions.db``. Kept as an OFFLINE FALLBACK
  only (see :func:`get_default_store` for the decision matrix).
- :class:`MySqlPortfolioStore` — canonical positions store (#1744).
  Backed by ``openbb_fmp_cache_test`` via
  :class:`openbb_fmp_cached.utils.database.DatabaseConfig`. New tables
  ``pi_snapshot`` / ``pi_position`` added additively — the corporate
  ``Portfolio_Positions`` / ``portfolio_basket`` pipeline is untouched.

Write path is idempotent by ``(source_sha256, user_id)``: re-importing
the same file is a no-op.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ContextManager, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SQLITE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS snapshot (
    snapshot_id       TEXT PRIMARY KEY,
    snapshot_date     TEXT NOT NULL,
    user_id           TEXT NOT NULL,
    source_filename   TEXT NOT NULL,
    source_sha256     TEXT NOT NULL,
    imported_at       TEXT NOT NULL DEFAULT (datetime('now')),
    row_count_raw     INTEGER NOT NULL,
    row_count_kept    INTEGER NOT NULL,
    row_count_skipped INTEGER NOT NULL,
    schema_version    INTEGER NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_snapshot_content ON snapshot(source_sha256, user_id);
CREATE INDEX IF NOT EXISTS ix_snapshot_date_user ON snapshot(snapshot_date, user_id);

CREATE TABLE IF NOT EXISTS position (
    position_id                 INTEGER PRIMARY KEY,
    snapshot_id                 TEXT NOT NULL,
    snapshot_date               TEXT NOT NULL,
    user_id                     TEXT NOT NULL,
    account_number              TEXT NOT NULL,
    account_name                TEXT,
    basket_name                 TEXT,
    symbol                      TEXT NOT NULL,
    description                 TEXT,
    type                        TEXT,
    quantity                    REAL,
    last_price                  REAL,
    last_price_change           REAL,
    current_value               REAL,
    today_gain_loss_dollar      REAL,
    today_gain_loss_percent     REAL,
    total_gain_loss_dollar      REAL,
    total_gain_loss_percent     REAL,
    percent_of_account          REAL,
    cost_basis_total            REAL,
    average_cost_basis          REAL,
    raw_row_number              INTEGER NOT NULL,
    FOREIGN KEY (snapshot_id) REFERENCES snapshot(snapshot_id)
);

CREATE INDEX IF NOT EXISTS ix_position_snapshot ON position(snapshot_id);
CREATE INDEX IF NOT EXISTS ix_position_date_user_symbol ON position(snapshot_date, user_id, symbol);
CREATE INDEX IF NOT EXISTS ix_position_date_user_account ON position(snapshot_date, user_id, account_number);
"""


# Column order shared by every backend's INSERT INTO position(...).
_POSITION_COLS: tuple[str, ...] = (
    "snapshot_id",
    "snapshot_date",
    "user_id",
    "account_number",
    "account_name",
    "basket_name",
    "symbol",
    "description",
    "type",
    "quantity",
    "last_price",
    "last_price_change",
    "current_value",
    "today_gain_loss_dollar",
    "today_gain_loss_percent",
    "total_gain_loss_dollar",
    "total_gain_loss_percent",
    "percent_of_account",
    "cost_basis_total",
    "average_cost_basis",
    "raw_row_number",
)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class PortfolioStore(Protocol):
    """The 8-method contract every positions-store backend must satisfy.

    Both :class:`SqlitePortfolioStore` and :class:`MySqlPortfolioStore`
    implement this. ``ingest.py`` and ``basket_bridge.py`` accept the
    Protocol as their type annotation — zero coupling to the concrete
    backend.
    """

    def snapshot_exists(self, source_sha256: str, user_id: str) -> str | None:
        """Return snapshot_id if ``(source_sha256, user_id)`` already imported."""
        ...

    def insert_snapshot(self, meta: dict) -> None:
        """Insert one snapshot row. Idempotent under repeated calls."""
        ...

    def insert_positions(self, rows: Iterable[dict]) -> int:
        """Bulk-insert position rows. Returns count written."""
        ...

    def list_snapshots(self, user_id: str | None = None) -> list:
        """Return snapshot rows, newest first."""
        ...

    def positions_for(self, snapshot_id: str) -> list:
        """Return position rows for one snapshot."""
        ...

    def latest_snapshot(self, user_id: str) -> Any:
        """Return the newest snapshot row for a user, or ``None``."""
        ...

    def transaction(self) -> ContextManager:
        """Explicit BEGIN/COMMIT scope (rollback on exception)."""
        ...

    def close(self) -> None:
        """Release any underlying connection."""
        ...


# ---------------------------------------------------------------------------
# SQLite backend (offline-fallback, was the original PortfolioStore)
# ---------------------------------------------------------------------------


class SqlitePortfolioStore:
    """Thin façade over a SQLite connection with the positions-history schema.

    Use as a context manager or call ``close()`` explicitly. Enables
    foreign keys and ``journal_mode=WAL`` by default (safe for
    concurrent readers).

    This is the original ``PortfolioStore`` class — renamed as part of
    #1744 to make the two-backend design explicit. Behavior unchanged.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._ensure_schema()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SqlitePortfolioStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Explicit BEGIN/COMMIT scope (rollback on exception)."""
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------
    def _ensure_schema(self) -> None:
        with self.transaction() as c:
            c.executescript(_SQLITE_SCHEMA_SQL)

    # ------------------------------------------------------------------
    # writes (append-only)
    # ------------------------------------------------------------------
    def snapshot_exists(self, source_sha256: str, user_id: str) -> str | None:
        """Return the existing snapshot_id if this (hash, user) is already imported."""
        row = self._conn.execute(
            "SELECT snapshot_id FROM snapshot WHERE source_sha256 = ? AND user_id = ?",
            (source_sha256, user_id),
        ).fetchone()
        return row["snapshot_id"] if row else None

    def insert_snapshot(self, meta: dict) -> None:
        """Insert one snapshot row. Caller must supply every field in the schema."""
        with self.transaction() as c:
            c.execute(
                """
                INSERT INTO snapshot(
                    snapshot_id, snapshot_date, user_id, source_filename,
                    source_sha256, row_count_raw, row_count_kept,
                    row_count_skipped, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def insert_positions(self, rows: Iterable[dict]) -> int:
        """Bulk-insert position rows. Returns the count actually written."""
        payload = list(rows)
        if not payload:
            return 0
        placeholders = ", ".join(["?"] * len(_POSITION_COLS))
        sql = (
            f"INSERT INTO position({', '.join(_POSITION_COLS)}) "
            f"VALUES ({placeholders})"
        )
        with self.transaction() as c:
            c.executemany(
                sql, [tuple(r.get(k) for k in _POSITION_COLS) for r in payload]
            )
        return len(payload)

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def list_snapshots(self, user_id: str | None = None) -> list[sqlite3.Row]:
        if user_id:
            return list(
                self._conn.execute(
                    "SELECT * FROM snapshot WHERE user_id = ? "
                    "ORDER BY snapshot_date DESC",
                    (user_id,),
                )
            )
        return list(
            self._conn.execute(
                "SELECT * FROM snapshot ORDER BY snapshot_date DESC, user_id"
            )
        )

    def positions_for(self, snapshot_id: str) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM position WHERE snapshot_id = ? "
                "ORDER BY account_number, symbol",
                (snapshot_id,),
            )
        )

    def latest_snapshot(self, user_id: str) -> sqlite3.Row | None:
        row = self._conn.execute(
            "SELECT * FROM snapshot WHERE user_id = ? "
            "ORDER BY snapshot_date DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return row


# ---------------------------------------------------------------------------
# Factory (`get_default_store`)
# ---------------------------------------------------------------------------


# Default SQLite location — user-local, never in the repo.
DEFAULT_SQLITE_PATH = Path.home() / ".portfolio_importer" / "positions.db"


def get_default_store(
    prefer: str | None = None,
    sqlite_path: Path | None = None,
) -> PortfolioStore:
    """Return the configured backend.

    Backend resolution order:

    1. Explicit ``prefer`` argument (``"mysql"`` or ``"sqlite"``).
    2. Environment override ``PI_PORTFOLIO_STORE`` (same values).
    3. Default: ``"mysql"`` (canonical per #1744).

    On MySQL selection, if the connection fails or credentials are
    missing, we log a WARNING and fall back to SQLite. On explicit
    ``prefer="mysql"`` failure the exception propagates (caller opted in
    explicitly).

    Args:
        prefer: Explicit backend selection. Overrides env var.
        sqlite_path: Path used when the SQLite backend is selected;
            defaults to :data:`DEFAULT_SQLITE_PATH`.
    """
    chosen = (
        prefer or os.environ.get("PI_PORTFOLIO_STORE", "").strip().lower() or "mysql"
    )
    if chosen not in {"mysql", "sqlite"}:
        raise ValueError(
            f"PI_PORTFOLIO_STORE must be 'mysql' or 'sqlite', got {chosen!r}"
        )

    if chosen == "sqlite":
        return SqlitePortfolioStore(sqlite_path or DEFAULT_SQLITE_PATH)

    # MySQL — import lazily so a machine without the fmp_cached provider
    # can still use SQLite via `prefer='sqlite'`.
    try:
        from portfolio_snapshot_importer.mysql_store import (  # noqa: PLC0415
            MySqlPortfolioStore,
        )

        return MySqlPortfolioStore()
    except Exception as exc:  # noqa: BLE001
        if prefer == "mysql":
            # Explicit opt-in — do not silently fall back.
            raise
        logger.warning(
            "MySqlPortfolioStore unavailable (%s); falling back to SQLite at %s",
            exc,
            sqlite_path or DEFAULT_SQLITE_PATH,
        )
        return SqlitePortfolioStore(sqlite_path or DEFAULT_SQLITE_PATH)
