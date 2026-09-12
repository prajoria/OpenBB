"""Safe paper/live broker execution contract with durable audit (#1719)."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from openbb_techtrade.execution.order_sink import OrderBatch, OrderTicket
from openbb_techtrade.execution.paper_engine import PaperEngine

_ORDER_NAMESPACE = uuid.UUID("f55055b1-f9c6-4e9c-8f77-3cf6704f26e6")
_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ExecutionMode(str, Enum):
    """Supported execution modes."""

    PAPER = "paper"
    LIVE = "live"


class SubmissionStatus(str, Enum):
    """Durable submission lifecycle."""

    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class ExecutionError(RuntimeError):
    """Base error for the T5 execution gateway."""


class ExecutionGateError(ExecutionError):
    """A safety gate rejected the request before any broker call."""


class ExecutionConfirmationError(ExecutionGateError):
    """The explicit confirmation phrase did not match."""


class ExecutionConfigurationError(ExecutionError):
    """Execution mode or adapter configuration is unsafe/incomplete."""


class UnknownSubmissionStateError(ExecutionError):
    """A prior attempt may have made side effects and needs reconciliation."""


@dataclass(frozen=True)
class BrokerOrderAck:
    """One adapter acknowledgement."""

    order_uuid: uuid.UUID
    broker_order_id: str


class BrokerBatchError(ExecutionError):
    """Adapter failed after zero or more orders were acknowledged."""

    def __init__(
        self,
        message: str,
        *,
        completed: Sequence[BrokerOrderAck] = (),
        failed_order_uuid: uuid.UUID | None = None,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.completed = tuple(completed)
        self.failed_order_uuid = failed_order_uuid
        self.outcome_unknown = outcome_unknown


@dataclass(frozen=True)
class OrderReceipt:
    """Durable state for one submitted order."""

    order_uuid: uuid.UUID
    broker_order_id: str | None
    status: str
    error: str | None = None


@dataclass(frozen=True)
class SubmissionReceipt:
    """Durable result for an idempotent batch submission."""

    submission_id: uuid.UUID
    mode: ExecutionMode
    broker_id: str
    account_id: str
    plan_id: str
    batch_sha256: str
    status: SubmissionStatus
    orders: tuple[OrderReceipt, ...]
    created_at: datetime
    updated_at: datetime
    error: str | None = None


@dataclass(frozen=True)
class CancellationReceipt:
    """Durable result of cancelling one order."""

    order_uuid: uuid.UUID
    broker_order_id: str
    status: str
    updated_at: datetime


@dataclass(frozen=True)
class AuditEvent:
    """One append-only execution audit event."""

    event_id: uuid.UUID
    submission_id: uuid.UUID
    order_uuid: uuid.UUID | None
    event_type: str
    detail: dict[str, object]
    created_at: datetime


class ExecutionSubmissionError(ExecutionError):
    """Submission failed; ``receipt`` is the durable terminal state."""

    def __init__(self, message: str, receipt: SubmissionReceipt) -> None:
        super().__init__(message)
        self.receipt = receipt


class CancellationError(ExecutionError):
    """Cancellation failed and the failure was written to the audit."""


@runtime_checkable
class BrokerAdapter(Protocol):
    """Backend-neutral order submission and cancellation contract."""

    @property
    def mode(self) -> ExecutionMode:
        """Execution mode implemented by this adapter."""
        ...

    @property
    def broker_id(self) -> str:
        """Stable broker/provider identity used by the audit scope."""
        ...

    @property
    def account_id(self) -> str:
        """Backend account scope (never a credential)."""
        ...

    def submit_batch(
        self,
        batch: OrderBatch,
        order_uuids: Sequence[uuid.UUID],
    ) -> tuple[BrokerOrderAck, ...]:
        """Submit the batch using UUIDs as client idempotency keys."""
        ...

    def cancel_order(self, broker_order_id: str) -> None:
        """Cancel a backend order by its acknowledged identifier."""
        ...


@runtime_checkable
class LiveBrokerClient(Protocol):
    """Injected vendor client boundary; implementations may perform I/O."""

    @property
    def broker_id(self) -> str:
        """Return the broker-verified provider identifier."""
        ...

    @property
    def account_id(self) -> str:
        """Return the account identity verified by the broker session."""
        ...

    def submit_order(self, ticket: OrderTicket, *, client_order_id: str) -> str:
        """Submit one ticket and return the vendor order identifier."""
        ...

    def cancel_order(self, broker_order_id: str) -> None:
        """Cancel one vendor order."""
        ...


class PaperBrokerAdapter:
    """Adapt the existing transactional paper engine to ``BrokerAdapter``."""

    mode = ExecutionMode.PAPER
    broker_id = "paper-engine"

    def __init__(self, engine: PaperEngine, account_id: str = "paper") -> None:
        self.engine = engine
        self._account_id = account_id

    @property
    def account_id(self) -> str:
        """Return the paper account scope."""
        return self._account_id

    def submit_batch(
        self,
        batch: OrderBatch,
        order_uuids: Sequence[uuid.UUID],
    ) -> tuple[BrokerOrderAck, ...]:
        """Submit through the paper engine and map its acknowledgements."""
        broker_ids = self.engine.submit_batch(batch, plan_id=batch.plan_id)
        if len(broker_ids) != len(order_uuids):
            raise BrokerBatchError(
                "paper engine returned an acknowledgement count that does not "
                "match the submitted batch"
            )
        return tuple(
            BrokerOrderAck(order_uuid=order_uuid, broker_order_id=broker_id)
            for order_uuid, broker_id in zip(order_uuids, broker_ids, strict=True)
        )

    def cancel_order(self, broker_order_id: str) -> None:
        """Cancel through the paper engine."""
        self.engine.cancel_order(broker_order_id, reason="T5 execution gateway")


class LiveBrokerAdapter:
    """Adapt an explicitly injected live client without reading credentials."""

    mode = ExecutionMode.LIVE

    def __init__(self, client: LiveBrokerClient, *, account_id: str) -> None:
        if not _ACCOUNT_ID_RE.fullmatch(account_id):
            raise ExecutionConfigurationError(
                "live broker adapter account_id must match "
                f"{_ACCOUNT_ID_RE.pattern!r}"
            )
        client_account = str(client.account_id)
        if client_account != account_id:
            raise ExecutionConfigurationError(
                "live broker client account does not match configured account_id"
            )
        client_broker = str(client.broker_id)
        if not _ACCOUNT_ID_RE.fullmatch(client_broker):
            raise ExecutionConfigurationError(
                "live broker client broker_id must match " f"{_ACCOUNT_ID_RE.pattern!r}"
            )
        self._client = client
        self._account_id = account_id
        self._broker_id = client_broker

    @property
    def broker_id(self) -> str:
        """Return the broker-verified provider identity."""
        return self._broker_id

    @property
    def account_id(self) -> str:
        """Return the configured live account scope."""
        return self._account_id

    def submit_batch(
        self,
        batch: OrderBatch,
        order_uuids: Sequence[uuid.UUID],
    ) -> tuple[BrokerOrderAck, ...]:
        """Submit each ticket with its reserved client-order UUID."""
        if len(batch.tickets) != len(order_uuids):
            raise BrokerBatchError("order UUID count does not match the batch")
        completed: list[BrokerOrderAck] = []
        for ticket, order_uuid in zip(batch.tickets, order_uuids, strict=True):
            try:
                self._verify_identity()
                broker_order_id = self._client.submit_order(
                    ticket,
                    client_order_id=str(order_uuid),
                )
            except Exception as exc:
                raise BrokerBatchError(
                    f"live broker submission failed ({type(exc).__name__})",
                    completed=completed,
                    failed_order_uuid=order_uuid,
                    outcome_unknown=True,
                ) from exc
            if not broker_order_id:
                raise BrokerBatchError(
                    "live broker returned an empty order identifier",
                    completed=completed,
                    failed_order_uuid=order_uuid,
                    outcome_unknown=True,
                )
            completed.append(BrokerOrderAck(order_uuid, str(broker_order_id)))
        return tuple(completed)

    def cancel_order(self, broker_order_id: str) -> None:
        """Cancel through the injected live client."""
        self._verify_identity()
        self._client.cancel_order(broker_order_id)

    def _verify_identity(self) -> None:
        if (
            str(self._client.account_id) != self._account_id
            or str(self._client.broker_id) != self._broker_id
        ):
            raise ExecutionConfigurationError(
                "live broker client identity changed after adapter construction"
            )


class SqliteExecutionAuditStore:
    """Durable idempotency and append-only audit journal."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS pi_execution_submission (
                    submission_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    broker_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    batch_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(mode, broker_id, account_id, plan_id, batch_sha256)
                );
                CREATE TABLE IF NOT EXISTS pi_execution_order (
                    order_uuid TEXT PRIMARY KEY,
                    submission_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    broker_order_id TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    FOREIGN KEY(submission_id)
                        REFERENCES pi_execution_submission(submission_id),
                    UNIQUE(submission_id, ordinal)
                );
                CREATE TABLE IF NOT EXISTS pi_execution_audit_event (
                    event_id TEXT PRIMARY KEY,
                    submission_id TEXT NOT NULL,
                    order_uuid TEXT,
                    event_type TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pi_execution_approval (
                    plan_id TEXT PRIMARY KEY,
                    batch_sha256 TEXT NOT NULL,
                    batch_json TEXT NOT NULL,
                    approved_at TEXT NOT NULL
                );
                """)

    def close(self) -> None:
        """Close this store's owned SQLite connection."""
        self._conn.close()

    def register_approved_batch(self, batch: OrderBatch) -> None:
        """Persist a server-validated immutable batch for cross-worker use."""
        if not batch.plan_id or not batch.verdict_gate_pass:
            raise ExecutionGateError(
                "approved batch requires plan_id and verdict_gate_pass=True"
            )
        payload = {
            "plan_id": batch.plan_id,
            "generated_at": _to_iso(batch.generated_at),
            "tickets": [
                {
                    "symbol": ticket.symbol,
                    "action": ticket.action,
                    "quantity": str(ticket.quantity),
                    "order_type": ticket.order_type,
                    "limit_price": (
                        str(ticket.limit_price)
                        if ticket.limit_price is not None
                        else None
                    ),
                    "tif": ticket.tif,
                    "account_masked": ticket.account_masked,
                    "notes": ticket.notes,
                }
                for ticket in batch.tickets
            ],
        }
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT batch_sha256 FROM pi_execution_approval WHERE plan_id = ?",
                (batch.plan_id,),
            ).fetchone()
            if existing is not None and existing["batch_sha256"] != batch.sha256():
                raise ExecutionGateError(
                    "approval plan_id is already bound to different batch content"
                )
            self._conn.execute(
                "INSERT OR IGNORE INTO pi_execution_approval "
                "(plan_id, batch_sha256, batch_json, approved_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    batch.plan_id,
                    batch.sha256(),
                    json.dumps(payload, sort_keys=True),
                    _to_iso(_now()),
                ),
            )

    def get_approved_batch(self, plan_id: str) -> OrderBatch | None:
        """Restore a server-approved batch and verify its stored content hash."""
        with self._lock:
            row = self._conn.execute(
                "SELECT batch_sha256, batch_json FROM pi_execution_approval "
                "WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["batch_json"])
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
        batch = OrderBatch(
            tickets=tickets,
            plan_id=payload["plan_id"],
            verdict_gate_pass=True,
            generated_at=_from_iso(payload["generated_at"]),
        )
        if batch.sha256() != row["batch_sha256"]:
            raise ExecutionGateError(
                "stored T4 approval content does not match its audit hash"
            )
        return batch

    def reserve(
        self,
        *,
        mode: ExecutionMode,
        broker_id: str,
        account_id: str,
        plan_id: str,
        batch_sha256: str,
        order_count: int,
    ) -> tuple[SubmissionReceipt, bool]:
        """Reserve the idempotency key before any broker side effect."""
        with self._lock, self._conn:
            submission_id = uuid.uuid4()
            now = _now()
            inserted = self._conn.execute(
                "INSERT OR IGNORE INTO pi_execution_submission "
                "(submission_id, mode, broker_id, account_id, plan_id, "
                "batch_sha256, status, error, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(submission_id),
                    mode.value,
                    broker_id,
                    account_id,
                    plan_id,
                    batch_sha256,
                    SubmissionStatus.SUBMITTING.value,
                    None,
                    _to_iso(now),
                    _to_iso(now),
                ),
            ).rowcount
            if inserted == 0:
                row = self._conn.execute(
                    "SELECT submission_id FROM pi_execution_submission "
                    "WHERE mode = ? AND broker_id = ? AND account_id = ? "
                    "AND plan_id = ? AND batch_sha256 = ?",
                    (mode.value, broker_id, account_id, plan_id, batch_sha256),
                ).fetchone()
                return self._read_submission(uuid.UUID(row["submission_id"])), False
            for ordinal in range(order_count):
                order_uuid = uuid.uuid5(
                    _ORDER_NAMESPACE,
                    f"{submission_id}:{ordinal}",
                )
                self._conn.execute(
                    "INSERT INTO pi_execution_order "
                    "(order_uuid, submission_id, ordinal, broker_order_id, "
                    "status, error) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        str(order_uuid),
                        str(submission_id),
                        ordinal,
                        None,
                        "PLANNED",
                        None,
                    ),
                )
            self._append_event(
                submission_id,
                "SUBMISSION_RESERVED",
                {
                    "mode": mode.value,
                    "broker_id": broker_id,
                    "plan_id": plan_id,
                    "batch_sha256": batch_sha256,
                },
            )
            return self._read_submission(submission_id), True

    def record_success(
        self,
        submission_id: uuid.UUID,
        acknowledgements: Sequence[BrokerOrderAck],
    ) -> SubmissionReceipt:
        """Record all broker acknowledgements and terminal success."""
        with self._lock, self._conn:
            for ack in acknowledgements:
                self._conn.execute(
                    "UPDATE pi_execution_order SET broker_order_id = ?, "
                    "status = 'SUBMITTED', error = NULL "
                    "WHERE submission_id = ? AND order_uuid = ?",
                    (ack.broker_order_id, str(submission_id), str(ack.order_uuid)),
                )
                self._append_event(
                    submission_id,
                    "ORDER_SUBMITTED",
                    {"broker_order_id": ack.broker_order_id},
                    ack.order_uuid,
                )
            self._update_submission(
                submission_id,
                SubmissionStatus.SUBMITTED,
                error=None,
            )
            self._append_event(submission_id, "SUBMISSION_SUCCEEDED", {})
            return self._read_submission(submission_id)

    def record_failure(
        self,
        submission_id: uuid.UUID,
        *,
        error: str,
        completed: Sequence[BrokerOrderAck],
        failed_order_uuid: uuid.UUID | None,
        outcome_unknown: bool = False,
    ) -> SubmissionReceipt:
        """Persist terminal failure while retaining partial acknowledgements."""
        status = (
            SubmissionStatus.RECONCILIATION_REQUIRED
            if outcome_unknown
            else SubmissionStatus.PARTIAL if completed else SubmissionStatus.FAILED
        )
        with self._lock, self._conn:
            for ack in completed:
                self._conn.execute(
                    "UPDATE pi_execution_order SET broker_order_id = ?, "
                    "status = 'SUBMITTED', error = NULL "
                    "WHERE submission_id = ? AND order_uuid = ?",
                    (ack.broker_order_id, str(submission_id), str(ack.order_uuid)),
                )
                self._append_event(
                    submission_id,
                    "ORDER_SUBMITTED",
                    {"broker_order_id": ack.broker_order_id},
                    ack.order_uuid,
                )
            if failed_order_uuid is not None:
                self._conn.execute(
                    "UPDATE pi_execution_order SET status = ?, error = ? "
                    "WHERE submission_id = ? AND order_uuid = ?",
                    (
                        "UNKNOWN" if outcome_unknown else "FAILED",
                        error,
                        str(submission_id),
                        str(failed_order_uuid),
                    ),
                )
                self._append_event(
                    submission_id,
                    "ORDER_UNKNOWN" if outcome_unknown else "ORDER_FAILED",
                    {"error": error},
                    failed_order_uuid,
                )
            self._update_submission(submission_id, status, error=error)
            self._append_event(
                submission_id,
                "SUBMISSION_FAILED",
                {"error": error, "completed": len(completed)},
                failed_order_uuid,
            )
            return self._read_submission(submission_id)

    def reserve_cancel(self, order_uuid: uuid.UUID) -> tuple[OrderReceipt, bool]:
        """Atomically reserve one cancellation before calling the broker."""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM pi_execution_order WHERE order_uuid = ?",
                (str(order_uuid),),
            ).fetchone()
            if row is None:
                raise ExecutionError(f"unknown audited order UUID {order_uuid}")
            order = _order_from_row(row)
            if order.status == "CANCELLED":
                return order, False
            if order.status in {"CANCELLING", "CANCEL_RECONCILIATION_REQUIRED"}:
                raise UnknownSubmissionStateError(
                    f"cancellation for order {order_uuid} has an unknown outcome; "
                    "reconcile before retrying"
                )
            if order.status != "SUBMITTED":
                raise ExecutionGateError(
                    f"order {order_uuid} is {order.status}; cancellation requires "
                    "a broker-acknowledged order"
                )
            changed = self._conn.execute(
                "UPDATE pi_execution_order SET status = 'CANCELLING', error = NULL "
                "WHERE order_uuid = ? AND status = 'SUBMITTED'",
                (str(order_uuid),),
            ).rowcount
            if changed != 1:
                raise UnknownSubmissionStateError(
                    f"cancellation for order {order_uuid} was concurrently reserved; "
                    "reconcile before retrying"
                )
            submission = self._conn.execute(
                "SELECT submission_id FROM pi_execution_order WHERE order_uuid = ?",
                (str(order_uuid),),
            ).fetchone()
            self._append_event(
                uuid.UUID(submission["submission_id"]),
                "CANCELLATION_RESERVED",
                {},
                order_uuid,
            )
            return self.get_order(order_uuid), True

    def get_order(self, order_uuid: uuid.UUID) -> OrderReceipt:
        """Return an audited order or raise for an unknown UUID."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM pi_execution_order WHERE order_uuid = ?",
                (str(order_uuid),),
            ).fetchone()
        if row is None:
            raise ExecutionError(f"unknown audited order UUID {order_uuid}")
        return _order_from_row(row)

    def get_order_context(
        self, order_uuid: uuid.UUID
    ) -> tuple[OrderReceipt, ExecutionMode, str, str]:
        """Return order plus its submission mode/account scope."""
        with self._lock:
            row = self._conn.execute(
                "SELECT o.*, s.mode, s.broker_id, s.account_id "
                "FROM pi_execution_order o JOIN pi_execution_submission s "
                "ON o.submission_id = s.submission_id WHERE o.order_uuid = ?",
                (str(order_uuid),),
            ).fetchone()
        if row is None:
            raise ExecutionError(f"unknown audited order UUID {order_uuid}")
        return (
            _order_from_row(row),
            ExecutionMode(row["mode"]),
            row["broker_id"],
            row["account_id"],
        )

    def record_cancel(
        self,
        order_uuid: uuid.UUID,
        *,
        status: str,
        error: str | None = None,
    ) -> CancellationReceipt:
        """Record cancellation success/failure and append an event."""
        order, _mode, _broker, _account = self.get_order_context(order_uuid)
        if order.broker_order_id is None:
            raise ExecutionError(f"order {order_uuid} has no broker acknowledgement")
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE pi_execution_order SET status = ?, error = ? "
                "WHERE order_uuid = ?",
                (status, error, str(order_uuid)),
            )
            row = self._conn.execute(
                "SELECT submission_id FROM pi_execution_order WHERE order_uuid = ?",
                (str(order_uuid),),
            ).fetchone()
            now = _now()
            self._conn.execute(
                "UPDATE pi_execution_submission SET updated_at = ? "
                "WHERE submission_id = ?",
                (_to_iso(now), row["submission_id"]),
            )
            self._append_event(
                uuid.UUID(row["submission_id"]),
                (
                    "ORDER_CANCELLED"
                    if status == "CANCELLED"
                    else "ORDER_CANCEL_OUTCOME_UNKNOWN"
                ),
                {"error": error} if error else {},
                order_uuid,
                at=now,
            )
        return CancellationReceipt(
            order_uuid=order_uuid,
            broker_order_id=order.broker_order_id,
            status=status,
            updated_at=now,
        )

    def cancellation_receipt(self, order_uuid: uuid.UUID) -> CancellationReceipt:
        """Reconstruct a previously completed cancellation."""
        order = self.get_order(order_uuid)
        with self._lock:
            row = self._conn.execute(
                "SELECT created_at FROM pi_execution_audit_event "
                "WHERE order_uuid = ? AND event_type = 'ORDER_CANCELLED' "
                "ORDER BY rowid DESC LIMIT 1",
                (str(order_uuid),),
            ).fetchone()
        if order.broker_order_id is None:
            raise ExecutionError(f"order {order_uuid} has no broker acknowledgement")
        return CancellationReceipt(
            order_uuid=order_uuid,
            broker_order_id=order.broker_order_id,
            status=order.status,
            updated_at=_from_iso(row["created_at"]),
        )

    def list_events(self, submission_id: uuid.UUID) -> tuple[AuditEvent, ...]:
        """Return append-only events in creation order."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM pi_execution_audit_event "
                "WHERE submission_id = ? ORDER BY rowid",
                (str(submission_id),),
            ).fetchall()
        return tuple(
            AuditEvent(
                event_id=uuid.UUID(row["event_id"]),
                submission_id=uuid.UUID(row["submission_id"]),
                order_uuid=(
                    uuid.UUID(row["order_uuid"]) if row["order_uuid"] else None
                ),
                event_type=row["event_type"],
                detail=json.loads(row["detail_json"]),
                created_at=_from_iso(row["created_at"]),
            )
            for row in rows
        )

    def _update_submission(
        self,
        submission_id: uuid.UUID,
        status: SubmissionStatus,
        *,
        error: str | None,
    ) -> None:
        self._conn.execute(
            "UPDATE pi_execution_submission SET status = ?, error = ?, "
            "updated_at = ? WHERE submission_id = ?",
            (status.value, error, _to_iso(_now()), str(submission_id)),
        )

    def _append_event(
        self,
        submission_id: uuid.UUID,
        event_type: str,
        detail: dict[str, object],
        order_uuid: uuid.UUID | None = None,
        *,
        at: datetime | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO pi_execution_audit_event "
            "(event_id, submission_id, order_uuid, event_type, detail_json, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                str(submission_id),
                str(order_uuid) if order_uuid else None,
                event_type,
                json.dumps(detail, sort_keys=True),
                _to_iso(at or _now()),
            ),
        )

    def _read_submission(self, submission_id: uuid.UUID) -> SubmissionReceipt:
        submission = self._conn.execute(
            "SELECT * FROM pi_execution_submission WHERE submission_id = ?",
            (str(submission_id),),
        ).fetchone()
        if submission is None:
            raise ExecutionError(f"unknown submission UUID {submission_id}")
        rows = self._conn.execute(
            "SELECT * FROM pi_execution_order WHERE submission_id = ? "
            "ORDER BY ordinal",
            (str(submission_id),),
        ).fetchall()
        return SubmissionReceipt(
            submission_id=submission_id,
            mode=ExecutionMode(submission["mode"]),
            broker_id=submission["broker_id"],
            account_id=submission["account_id"],
            plan_id=submission["plan_id"],
            batch_sha256=submission["batch_sha256"],
            status=SubmissionStatus(submission["status"]),
            orders=tuple(_order_from_row(row) for row in rows),
            created_at=_from_iso(submission["created_at"]),
            updated_at=_from_iso(submission["updated_at"]),
            error=submission["error"],
        )


class ExecutionGateway:
    """Own all gates, confirmation, idempotency, audit, and error semantics."""

    def __init__(
        self,
        *,
        adapter: BrokerAdapter,
        audit_store: SqliteExecutionAuditStore,
        configured_mode: ExecutionMode,
        execute_enabled: bool,
        live_enabled: bool = False,
    ) -> None:
        self.adapter = adapter
        self.audit_store = audit_store
        self.configured_mode = configured_mode
        self.execute_enabled = execute_enabled
        self.live_enabled = live_enabled

    def expected_confirmation(self, batch: OrderBatch) -> str:
        """Return the exact batch/account/mode-bound submission phrase."""
        return (
            f"SUBMIT {self.adapter.mode.value.upper()} "
            f"{self.adapter.broker_id} {self.adapter.account_id} "
            f"{batch.plan_id} {batch.sha256()}"
        )

    def expected_cancel_confirmation(self, order_uuid: uuid.UUID) -> str:
        """Return the exact order/account/mode-bound cancellation phrase."""
        return (
            f"CANCEL {self.adapter.mode.value.upper()} "
            f"{self.adapter.broker_id} {self.adapter.account_id} {order_uuid}"
        )

    def submit(
        self,
        batch: OrderBatch,
        *,
        verdict: str,
        confirmation: str,
    ) -> SubmissionReceipt:
        """Validate gates, reserve audit identity, and submit exactly once."""
        self._validate_common_gates()
        if verdict != "PASS":
            raise ExecutionGateError("verdict gate requires exact PASS")
        if not batch.verdict_gate_pass:
            raise ExecutionGateError("batch verdict was not persisted as passed")
        expected = self.expected_confirmation(batch)
        if confirmation != expected:
            raise ExecutionConfirmationError(
                "explicit confirmation did not match the configured mode, "
                "account, and batch"
            )

        receipt, is_new = self.audit_store.reserve(
            mode=self.adapter.mode,
            broker_id=self.adapter.broker_id,
            account_id=self.adapter.account_id,
            plan_id=batch.plan_id,
            batch_sha256=batch.sha256(),
            order_count=len(batch.tickets),
        )
        if not is_new:
            if receipt.status in {
                SubmissionStatus.SUBMITTING,
                SubmissionStatus.RECONCILIATION_REQUIRED,
            }:
                raise UnknownSubmissionStateError(
                    "submission has an unknown broker outcome; "
                    "reconcile before retrying"
                )
            return receipt

        order_uuids = tuple(order.order_uuid for order in receipt.orders)
        try:
            acknowledgements = self.adapter.submit_batch(batch, order_uuids)
            if len(acknowledgements) != len(order_uuids) or {
                ack.order_uuid for ack in acknowledgements
            } != set(order_uuids):
                reserved = set(order_uuids)
                validated: list[BrokerOrderAck] = []
                seen: set[uuid.UUID] = set()
                for ack in acknowledgements:
                    if ack.order_uuid in reserved and ack.order_uuid not in seen:
                        validated.append(ack)
                        seen.add(ack.order_uuid)
                raise BrokerBatchError(
                    "adapter acknowledgements do not match reserved order UUIDs",
                    completed=validated,
                    outcome_unknown=self.adapter.mode is ExecutionMode.LIVE,
                )
        except BrokerBatchError as exc:
            failed = self.audit_store.record_failure(
                receipt.submission_id,
                error=str(exc),
                completed=exc.completed,
                failed_order_uuid=exc.failed_order_uuid,
                outcome_unknown=exc.outcome_unknown,
            )
            raise ExecutionSubmissionError(str(exc), failed) from exc
        except Exception as exc:
            safe_error = f"broker operation failed ({type(exc).__name__})"
            failed = self.audit_store.record_failure(
                receipt.submission_id,
                error=safe_error,
                completed=(),
                failed_order_uuid=None,
                outcome_unknown=self.adapter.mode is ExecutionMode.LIVE,
            )
            raise ExecutionSubmissionError(safe_error, failed) from exc
        return self.audit_store.record_success(
            receipt.submission_id,
            acknowledgements,
        )

    def cancel(
        self,
        order_uuid: uuid.UUID,
        *,
        confirmation: str,
    ) -> CancellationReceipt:
        """Cancel an acknowledged order with a separate explicit confirmation."""
        self._validate_common_gates()
        expected = self.expected_cancel_confirmation(order_uuid)
        if confirmation != expected:
            raise ExecutionConfirmationError(
                "explicit confirmation did not match the configured mode, "
                "account, and order"
            )
        order, mode, broker_id, account_id = self.audit_store.get_order_context(
            order_uuid
        )
        if (
            mode is not self.adapter.mode
            or broker_id != self.adapter.broker_id
            or account_id != self.adapter.account_id
        ):
            raise ExecutionGateError(
                "audited order does not belong to the configured adapter scope"
            )
        order, is_new = self.audit_store.reserve_cancel(order_uuid)
        if not is_new:
            return self.audit_store.cancellation_receipt(order_uuid)
        if order.broker_order_id is None:
            raise ExecutionError(f"order {order_uuid} has no broker acknowledgement")
        try:
            self.adapter.cancel_order(order.broker_order_id)
        except Exception as exc:
            safe_error = f"broker cancellation failed ({type(exc).__name__})"
            self.audit_store.record_cancel(
                order_uuid,
                status="CANCEL_RECONCILIATION_REQUIRED",
                error=safe_error,
            )
            raise CancellationError(safe_error) from exc
        return self.audit_store.record_cancel(order_uuid, status="CANCELLED")

    def _validate_common_gates(self) -> None:
        if not self.execute_enabled:
            raise ExecutionGateError(
                "PI_ALLOW_T5_EXECUTE=true is required before execution"
            )
        if self.adapter.mode is not self.configured_mode:
            raise ExecutionGateError(
                f"adapter mode {self.adapter.mode.value!r} does not match "
                f"configured mode {self.configured_mode.value!r}"
            )
        if self.adapter.mode is ExecutionMode.LIVE and not self.live_enabled:
            raise ExecutionGateError(
                "PI_ALLOW_T5_LIVE=true is required for live execution"
            )


def get_default_broker_adapter(
    *,
    mode: ExecutionMode | str | None = None,
    account_id: str | None = None,
    paper_engine: PaperEngine | None = None,
    live_client: LiveBrokerClient | None = None,
) -> BrokerAdapter:
    """Build the explicitly selected adapter; paper is the safe default."""
    resolved_mode = ExecutionMode(
        mode or os.environ.get("PI_T5_BROKER_MODE", ExecutionMode.PAPER.value)
    )
    if resolved_mode is ExecutionMode.PAPER:
        resolved_account = account_id or "paper"
        if paper_engine is None:
            from openbb_techtrade.execution.paper_engine import (  # noqa: PLC0415
                get_default_engine,
            )

            paper_engine = get_default_engine(
                account_id=resolved_account,
                allow_fallback=False,
            )
        return PaperBrokerAdapter(paper_engine, account_id=resolved_account)

    resolved_account = account_id or os.environ.get("PI_T5_LIVE_ACCOUNT_ID", "")
    if not resolved_account.strip():
        raise ExecutionConfigurationError(
            "live mode requires PI_T5_LIVE_ACCOUNT_ID or an explicit account_id"
        )
    if live_client is None:
        raise ExecutionConfigurationError(
            "live mode requires an explicitly injected LiveBrokerClient; "
            "no SDK or credential fallback is permitted"
        )
    return LiveBrokerAdapter(live_client, account_id=resolved_account)


def _order_from_row(row: sqlite3.Row) -> OrderReceipt:
    return OrderReceipt(
        order_uuid=uuid.UUID(row["order_uuid"]),
        broker_order_id=row["broker_order_id"],
        status=row["status"],
        error=row["error"],
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)
