"""SQLite schema and migrations for the T5 execution audit store."""

from __future__ import annotations

import sqlite3

_SUBMISSION_DDL = """
CREATE TABLE IF NOT EXISTS pi_execution_submission (
    submission_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    broker_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    batch_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(
        mode, broker_id, account_id, principal_id, plan_id, batch_sha256
    )
)
"""

_ORDER_DDL = """
CREATE TABLE IF NOT EXISTS pi_execution_order (
    order_uuid TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    broker_order_id TEXT,
    status TEXT NOT NULL,
    error TEXT,
    FOREIGN KEY(submission_id) REFERENCES pi_execution_submission(submission_id),
    UNIQUE(submission_id, ordinal)
)
"""

_EVENT_DDL = """
CREATE TABLE IF NOT EXISTS pi_execution_audit_event (
    event_id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    order_uuid TEXT,
    event_type TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_APPROVAL_DDL = """
CREATE TABLE IF NOT EXISTS pi_execution_approval (
    plan_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    broker_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    batch_sha256 TEXT NOT NULL,
    batch_json TEXT NOT NULL,
    approved_at TEXT NOT NULL
)
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the current schema and safely migrate pre-principal databases."""
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN IMMEDIATE")
    try:
        submission_columns = _columns(conn, "pi_execution_submission")
        approval_columns = _columns(conn, "pi_execution_approval")
        if submission_columns and "principal_id" not in submission_columns:
            _migrate_submission(conn)
        if approval_columns and not {
            "principal_id",
            "broker_id",
            "account_id",
        }.issubset(approval_columns):
            _migrate_approval(conn, approval_columns)
        for ddl in (_SUBMISSION_DDL, _ORDER_DDL, _EVENT_DDL, _APPROVAL_DDL):
            conn.execute(ddl)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_submission(conn: sqlite3.Connection) -> None:
    has_order_table = bool(_columns(conn, "pi_execution_order"))
    if has_order_table:
        conn.execute("ALTER TABLE pi_execution_order RENAME TO _pi_execution_order_v1")
    conn.execute(
        "ALTER TABLE pi_execution_submission RENAME TO _pi_execution_submission_v1"
    )
    conn.execute(_SUBMISSION_DDL)
    conn.execute(
        "INSERT INTO pi_execution_submission "
        "(submission_id, mode, broker_id, account_id, principal_id, plan_id, "
        "batch_sha256, status, error, created_at, updated_at) "
        "SELECT submission_id, mode, broker_id, account_id, "
        "CASE WHEN mode = 'paper' THEN 'paper' ELSE 'legacy-unassigned' END, "
        "plan_id, batch_sha256, status, error, created_at, updated_at "
        "FROM _pi_execution_submission_v1"
    )
    if has_order_table:
        conn.execute(_ORDER_DDL)
        conn.execute(
            "INSERT INTO pi_execution_order "
            "(order_uuid, submission_id, ordinal, broker_order_id, status, error) "
            "SELECT order_uuid, submission_id, ordinal, broker_order_id, status, error "
            "FROM _pi_execution_order_v1"
        )
        conn.execute("DROP TABLE _pi_execution_order_v1")
    conn.execute("DROP TABLE _pi_execution_submission_v1")


def _migrate_approval(
    conn: sqlite3.Connection,
    columns: set[str],
) -> None:
    conn.execute(
        "ALTER TABLE pi_execution_approval RENAME TO _pi_execution_approval_v1"
    )
    conn.execute(_APPROVAL_DDL)
    if "request_sha256" in columns:
        conn.execute(
            "INSERT INTO pi_execution_approval "
            "(plan_id, principal_id, broker_id, account_id, request_sha256, "
            "batch_sha256, batch_json, approved_at) "
            "SELECT plan_id, 'legacy-unassigned', 'legacy-unassigned', "
            "'legacy-unassigned', request_sha256, "
            "batch_sha256, batch_json, approved_at "
            "FROM _pi_execution_approval_v1"
        )
    else:
        conn.execute(
            "INSERT INTO pi_execution_approval "
            "(plan_id, principal_id, broker_id, account_id, request_sha256, "
            "batch_sha256, batch_json, approved_at) "
            "SELECT plan_id, 'legacy-unassigned', 'legacy-unassigned', "
            "'legacy-unassigned', '', batch_sha256, "
            "batch_json, approved_at FROM _pi_execution_approval_v1"
        )
    conn.execute("DROP TABLE _pi_execution_approval_v1")
