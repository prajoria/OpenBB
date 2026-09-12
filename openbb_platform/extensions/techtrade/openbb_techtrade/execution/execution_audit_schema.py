"""SQLite schema and migrations for the T5 execution audit store."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from openbb_techtrade.execution.broker_contract import OrderReceipt
from openbb_techtrade.execution.order_sink import (
    OrderBatch,
    OrderTicket,
    PlanContext,
    VerdictGate,
)

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

_BROKER_ORDER_DDL = """
CREATE TABLE IF NOT EXISTS pi_execution_broker_order (
    mode TEXT NOT NULL,
    broker_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    broker_order_id TEXT NOT NULL,
    order_uuid TEXT NOT NULL UNIQUE,
    submission_id TEXT NOT NULL,
    PRIMARY KEY(mode, broker_id, account_id, broker_order_id)
)
"""

_BROKER_ORDER_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS ix_pi_execution_order_broker_id
ON pi_execution_order(broker_order_id)
"""

_META_DDL = """
CREATE TABLE IF NOT EXISTS pi_execution_schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_APPROVAL_DDL = """
CREATE TABLE IF NOT EXISTS pi_execution_approval (
    plan_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
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
            "mode",
        }.issubset(approval_columns):
            _migrate_approval(conn, approval_columns)
        for ddl in (
            _SUBMISSION_DDL,
            _ORDER_DDL,
            _EVENT_DDL,
            _BROKER_ORDER_DDL,
            _BROKER_ORDER_INDEX_DDL,
            _APPROVAL_DDL,
            _META_DDL,
        ):
            conn.execute(ddl)
        migrated = conn.execute(
            "SELECT 1 FROM pi_execution_schema_meta "
            "WHERE key = 'live_broker_backfill_v1'"
        ).fetchone()
        if migrated is None:
            _backfill_live_broker_orders(conn)
            conn.execute(
                "INSERT INTO pi_execution_schema_meta (key, value) VALUES (?, ?)",
                ("live_broker_backfill_v1", "complete"),
            )
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
    legacy_rows = conn.execute("SELECT * FROM _pi_execution_submission_v1").fetchall()
    migrated_rows = []
    for row in legacy_rows:
        columns = set(row.keys())
        migrated_rows.append(
            (
                row["submission_id"],
                row["mode"],
                row["broker_id"] if "broker_id" in columns else "legacy-unassigned",
                row["account_id"],
                "legacy-unassigned",
                row["plan_id"] if "plan_id" in columns else "legacy-unassigned",
                row["batch_sha256"],
                row["status"],
                row["error"],
                row["created_at"],
                row["updated_at"],
            )
        )
    conn.executemany(
        "INSERT INTO pi_execution_submission "
        "(submission_id, mode, broker_id, account_id, principal_id, plan_id, "
        "batch_sha256, status, error, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        migrated_rows,
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
            "(plan_id, mode, principal_id, broker_id, account_id, request_sha256, "
            "batch_sha256, batch_json, approved_at) "
            "SELECT plan_id, 'legacy-unassigned', 'legacy-unassigned', "
            "'legacy-unassigned', "
            "'legacy-unassigned', request_sha256, "
            "batch_sha256, batch_json, approved_at "
            "FROM _pi_execution_approval_v1"
        )
    else:
        conn.execute(
            "INSERT INTO pi_execution_approval "
            "(plan_id, mode, principal_id, broker_id, account_id, request_sha256, "
            "batch_sha256, batch_json, approved_at) "
            "SELECT plan_id, 'legacy-unassigned', 'legacy-unassigned', "
            "'legacy-unassigned', "
            "'legacy-unassigned', '', batch_sha256, "
            "batch_json, approved_at FROM _pi_execution_approval_v1"
        )
    conn.execute("DROP TABLE _pi_execution_approval_v1")


def _backfill_live_broker_orders(conn: sqlite3.Connection) -> None:
    """Reserve existing live broker IDs and reject historical collisions."""
    rows = conn.execute(
        "SELECT s.mode, s.broker_id, s.account_id, o.broker_order_id, "
        "o.order_uuid, o.submission_id "
        "FROM pi_execution_order o JOIN pi_execution_submission s "
        "ON o.submission_id = s.submission_id "
        "WHERE s.mode = 'live' AND o.broker_order_id IS NOT NULL"
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT OR IGNORE INTO pi_execution_broker_order "
            "(mode, broker_id, account_id, broker_order_id, order_uuid, "
            "submission_id) VALUES (?, ?, ?, ?, ?, ?)",
            tuple(row),
        )
        owner = conn.execute(
            "SELECT order_uuid FROM pi_execution_broker_order "
            "WHERE mode = ? AND broker_id = ? AND account_id = ? "
            "AND broker_order_id = ?",
            tuple(row)[:4],
        ).fetchone()
        if owner["order_uuid"] != row["order_uuid"]:
            raise RuntimeError(
                "historical live broker-order collision requires reconciliation"
            )


def serialize_approved_batch(batch: OrderBatch) -> str:
    """Serialize all execution and workbook context deterministically."""
    payload = {
        "plan_id": batch.plan_id,
        "generated_at": batch.generated_at.astimezone(timezone.utc).isoformat(),
        "pricing": (
            {key: str(value) for key, value in batch.pricing.items()}
            if batch.pricing is not None
            else None
        ),
        "pre_execution_positions": (
            {key: str(value) for key, value in batch.pre_execution_positions.items()}
            if batch.pre_execution_positions is not None
            else None
        ),
        "plan_context": (
            {
                "verdict_gates": [
                    {
                        "name": gate.name,
                        "threshold": gate.threshold,
                        "actual": gate.actual,
                        "passed": gate.passed,
                        "notes": gate.notes,
                    }
                    for gate in batch.plan_context.verdict_gates
                ],
                "generator_version": batch.plan_context.generator_version,
                "git_sha": batch.plan_context.git_sha,
            }
            if batch.plan_context is not None
            else None
        ),
        "tickets": [
            {
                "symbol": ticket.symbol,
                "action": ticket.action,
                "quantity": str(ticket.quantity),
                "order_type": ticket.order_type,
                "limit_price": (
                    str(ticket.limit_price) if ticket.limit_price is not None else None
                ),
                "tif": ticket.tif,
                "account_masked": ticket.account_masked,
                "notes": ticket.notes,
            }
            for ticket in batch.tickets
        ],
    }
    return json.dumps(payload, sort_keys=True)


def deserialize_approved_batch(payload_json: str) -> OrderBatch:
    """Restore an approved batch from its deterministic JSON representation."""
    payload = json.loads(payload_json)
    tickets = tuple(
        OrderTicket(
            symbol=item["symbol"],
            action=item["action"],
            quantity=Decimal(item["quantity"]),
            order_type=item["order_type"],
            limit_price=(
                Decimal(item["limit_price"])
                if item["limit_price"] is not None
                else None
            ),
            tif=item["tif"],
            account_masked=item["account_masked"],
            notes=item["notes"],
        )
        for item in payload["tickets"]
    )
    context = payload["plan_context"]
    return OrderBatch(
        tickets=tickets,
        plan_id=payload["plan_id"],
        verdict_gate_pass=True,
        generated_at=datetime.fromisoformat(payload["generated_at"]).astimezone(
            timezone.utc
        ),
        pricing=(
            {key: Decimal(value) for key, value in payload["pricing"].items()}
            if payload["pricing"] is not None
            else None
        ),
        pre_execution_positions=(
            {
                key: Decimal(value)
                for key, value in payload["pre_execution_positions"].items()
            }
            if payload["pre_execution_positions"] is not None
            else None
        ),
        plan_context=(
            PlanContext(
                verdict_gates=tuple(
                    VerdictGate(**gate) for gate in context["verdict_gates"]
                ),
                generator_version=context["generator_version"],
                git_sha=context["git_sha"],
            )
            if context is not None
            else None
        ),
    )


def order_receipt_from_row(row: sqlite3.Row) -> OrderReceipt:
    """Convert one SQLite audit-order row to its public receipt."""
    return OrderReceipt(
        order_uuid=UUID(row["order_uuid"]),
        broker_order_id=row["broker_order_id"],
        status=row["status"],
        error=row["error"],
    )
