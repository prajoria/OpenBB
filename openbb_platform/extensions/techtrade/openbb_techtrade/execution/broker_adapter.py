"""Safe paper/live broker execution contract with durable audit (#1719)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from openbb_techtrade.execution import paper_engine as paper_engine_module
from openbb_techtrade.execution.broker_backends import (
    LiveBrokerAdapter,
    PaperBrokerAdapter,
)
from openbb_techtrade.execution.broker_contract import (
    AuditEvent,
    BrokerAdapter,
    BrokerBatchError,
    BrokerOrderAck,
    CancellationError,
    CancellationReceipt,
    ExecutionConfigurationError,
    ExecutionConfirmationError,
    ExecutionError,
    ExecutionGateError,
    ExecutionMode,
    ExecutionScope,
    ExecutionSubmissionError,
    LiveBrokerClient,
    OrderReceipt,
    SubmissionReceipt,
    SubmissionStatus,
    UnknownSubmissionStateError,
    reconciliation_receipt,
)
from openbb_techtrade.execution.execution_audit_schema import (
    deserialize_approved_batch,
    ensure_schema,
    order_receipt_from_row,
    serialize_approved_batch,
)
from openbb_techtrade.execution.order_sink import OrderBatch
from openbb_techtrade.execution.paper_engine import PaperEngine
from openbb_techtrade.execution.secure_file import (
    prepare_private_audit_directory,
    secure_owner_only,
)

_ORDER_NAMESPACE = uuid.UUID("f55055b1-f9c6-4e9c-8f77-3cf6704f26e6")


class SqliteExecutionAuditStore:
    """Durable idempotency and append-only audit journal."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        prepare_private_audit_directory(self.path.parent, self.path.name)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        secure_owner_only(self.path, directory=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock:
            ensure_schema(self._conn)

    def close(self) -> None:
        """Close this store's owned SQLite connection."""
        self._conn.close()

    def register_approved_batch(
        self,
        batch: OrderBatch,
        *,
        mode: ExecutionMode = ExecutionMode.PAPER,
        principal_id: str = "paper",
        broker_id: str = "paper-engine",
        account_id: str = "paper",
        request_sha256: str = "",
    ) -> None:
        """Persist a server-validated immutable batch for cross-worker use."""
        if not batch.plan_id or not batch.verdict_gate_pass:
            raise ExecutionGateError(
                "approved batch requires plan_id and verdict_gate_pass=True"
            )
        expected_sha = batch.sha256()
        expected_json = serialize_approved_batch(batch)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO pi_execution_approval "
                "(plan_id, mode, principal_id, broker_id, account_id, "
                "request_sha256, batch_sha256, batch_json, approved_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch.plan_id,
                    mode.value,
                    principal_id,
                    broker_id,
                    account_id,
                    request_sha256,
                    expected_sha,
                    expected_json,
                    _to_iso(_now()),
                ),
            )
            stored = self._conn.execute(
                "SELECT mode, principal_id, broker_id, account_id, request_sha256, "
                "batch_sha256, batch_json "
                "FROM pi_execution_approval WHERE plan_id = ?",
                (batch.plan_id,),
            ).fetchone()
            actual_binding = tuple(stored)[:-1]
            expected_binding = (
                mode.value,
                principal_id,
                broker_id,
                account_id,
                request_sha256,
                expected_sha,
            )
            if actual_binding != expected_binding:
                raise ExecutionGateError(
                    "approval UUID is already bound to different content or owner"
                )
            stored_context = json.loads(stored["batch_json"])
            expected_context = json.loads(expected_json)
            stored_context.pop("generated_at", None)
            expected_context.pop("generated_at", None)
            if stored_context != expected_context:
                raise ExecutionGateError(
                    "approval UUID is already bound to different content or owner"
                )

    def get_approved_batch(
        self,
        plan_id: str,
        *,
        mode: ExecutionMode = ExecutionMode.PAPER,
        principal_id: str = "paper",
        broker_id: str = "paper-engine",
        account_id: str = "paper",
        request_sha256: str | None = None,
    ) -> OrderBatch | None:
        """Restore a server-approved batch and verify its stored content hash."""
        with self._lock:
            row = self._conn.execute(
                "SELECT mode, principal_id, broker_id, account_id, request_sha256, "
                "batch_sha256, batch_json "
                "FROM pi_execution_approval WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
        if row is None:
            return None
        if row["mode"] != mode.value:
            raise ExecutionGateError("approval belongs to a different execution mode")
        if row["principal_id"] != principal_id:
            raise ExecutionGateError("approval belongs to a different principal")
        if row["broker_id"] != broker_id or row["account_id"] != account_id:
            raise ExecutionGateError("approval belongs to a different broker account")
        if request_sha256 is not None and row["request_sha256"] != request_sha256:
            raise ExecutionGateError(
                "approval UUID is bound to a different approval request"
            )
        batch = deserialize_approved_batch(row["batch_json"])
        if batch.sha256() != row["batch_sha256"]:
            raise ExecutionGateError(
                "stored T4 approval content does not match its audit hash"
            )
        if batch.plan_id != plan_id:
            raise ExecutionGateError(
                "stored T4 approval plan identity does not match its lookup key"
            )
        return batch

    def reserve(
        self,
        *,
        mode: ExecutionMode,
        broker_id: str,
        account_id: str,
        principal_id: str,
        plan_id: str,
        batch_sha256: str,
        order_count: int,
    ) -> tuple[SubmissionReceipt, bool]:
        """Reserve the idempotency key before any broker side effect."""
        with self._lock, self._conn:
            if mode in {ExecutionMode.PAPER, ExecutionMode.LIVE}:
                legacy = self._conn.execute(
                    "SELECT submission_id FROM pi_execution_submission "
                    "WHERE mode = ? AND account_id = ? "
                    "AND principal_id = 'legacy-unassigned' LIMIT 1",
                    (
                        mode.value,
                        account_id,
                    ),
                ).fetchone()
                if legacy is not None:
                    raise UnknownSubmissionStateError(
                        "legacy submission ownership is unknown; reconcile "
                        "before submitting this approval"
                    )
            submission_id = uuid.uuid4()
            now = _now()
            inserted = self._conn.execute(
                "INSERT OR IGNORE INTO pi_execution_submission "
                "(submission_id, mode, broker_id, account_id, principal_id, "
                "plan_id, batch_sha256, status, error, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(submission_id),
                    mode.value,
                    broker_id,
                    account_id,
                    principal_id,
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
                    "AND principal_id = ? AND plan_id = ? AND batch_sha256 = ?",
                    (
                        mode.value,
                        broker_id,
                        account_id,
                        principal_id,
                        plan_id,
                        batch_sha256,
                    ),
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
                    "principal_id": principal_id,
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
        self._reserve_live_broker_ids(submission_id, acknowledgements)
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
        try:
            self._reserve_live_broker_ids(submission_id, completed)
        except BrokerBatchError as exc:
            error = str(exc)
            completed = ()
            failed_order_uuid = None
            outcome_unknown = True
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
            if outcome_unknown:
                unknown_rows = self._conn.execute(
                    "SELECT order_uuid FROM pi_execution_order "
                    "WHERE submission_id = ? AND status = 'PLANNED'",
                    (str(submission_id),),
                ).fetchall()
                for row in unknown_rows:
                    order_uuid = uuid.UUID(row["order_uuid"])
                    self._conn.execute(
                        "UPDATE pi_execution_order SET status = 'UNKNOWN', "
                        "error = ? WHERE order_uuid = ?",
                        (error, str(order_uuid)),
                    )
                    self._append_event(
                        submission_id,
                        "ORDER_UNKNOWN",
                        {"error": error},
                        order_uuid,
                    )
            self._update_submission(submission_id, status, error=error)
            self._append_event(
                submission_id,
                "SUBMISSION_FAILED",
                {"error": error, "completed": len(completed)},
                failed_order_uuid,
            )
            return self._read_submission(submission_id)

    def _reserve_live_broker_ids(
        self,
        submission_id: uuid.UUID,
        acknowledgements: Sequence[BrokerOrderAck],
    ) -> None:
        """Atomically prevent broker IDs from aliasing within a live scope."""
        if not acknowledgements:
            return
        with self._lock, self._conn:
            scope = self._conn.execute(
                "SELECT mode, broker_id, account_id FROM pi_execution_submission "
                "WHERE submission_id = ?",
                (str(submission_id),),
            ).fetchone()
            if scope is None or scope["mode"] != ExecutionMode.LIVE.value:
                return
            for ack in acknowledgements:
                legacy = self._conn.execute(
                    "SELECT 1 FROM pi_execution_order o "
                    "JOIN pi_execution_submission s "
                    "ON o.submission_id = s.submission_id "
                    "WHERE s.mode = 'live' "
                    "AND s.principal_id = 'legacy-unassigned' "
                    "AND s.account_id = ? AND o.broker_order_id = ? LIMIT 1",
                    (scope["account_id"], ack.broker_order_id),
                ).fetchone()
                if legacy is not None:
                    raise BrokerBatchError(
                        "legacy broker order ownership requires reconciliation",
                        outcome_unknown=True,
                    )
                self._conn.execute(
                    "INSERT OR IGNORE INTO pi_execution_broker_order "
                    "(mode, broker_id, account_id, broker_order_id, order_uuid, "
                    "submission_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        scope["mode"],
                        scope["broker_id"],
                        scope["account_id"],
                        ack.broker_order_id,
                        str(ack.order_uuid),
                        str(submission_id),
                    ),
                )
                owner = self._conn.execute(
                    "SELECT order_uuid FROM pi_execution_broker_order "
                    "WHERE mode = ? AND broker_id = ? AND account_id = ? "
                    "AND broker_order_id = ?",
                    (
                        scope["mode"],
                        scope["broker_id"],
                        scope["account_id"],
                        ack.broker_order_id,
                    ),
                ).fetchone()
                if owner["order_uuid"] != str(ack.order_uuid):
                    raise BrokerBatchError(
                        "broker order identifier already belongs to another order",
                        outcome_unknown=True,
                    )

    def reserve_cancel(self, order_uuid: uuid.UUID) -> tuple[OrderReceipt, bool]:
        """Atomically reserve one cancellation before calling the broker."""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM pi_execution_order WHERE order_uuid = ?",
                (str(order_uuid),),
            ).fetchone()
            if row is None:
                raise ExecutionError(f"unknown audited order UUID {order_uuid}")
            order = order_receipt_from_row(row)
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
        return order_receipt_from_row(row)

    def get_order_context(
        self, order_uuid: uuid.UUID
    ) -> tuple[OrderReceipt, ExecutionMode, str, str, str]:
        """Return order plus its submission mode/account scope."""
        with self._lock:
            row = self._conn.execute(
                "SELECT o.*, s.mode, s.broker_id, s.account_id, s.principal_id "
                "FROM pi_execution_order o JOIN pi_execution_submission s "
                "ON o.submission_id = s.submission_id WHERE o.order_uuid = ?",
                (str(order_uuid),),
            ).fetchone()
        if row is None:
            raise ExecutionError(f"unknown audited order UUID {order_uuid}")
        return (
            order_receipt_from_row(row),
            ExecutionMode(row["mode"]),
            row["broker_id"],
            row["account_id"],
            row["principal_id"],
        )

    def record_cancel(
        self,
        order_uuid: uuid.UUID,
        *,
        status: str,
        error: str | None = None,
    ) -> CancellationReceipt:
        """Record cancellation success/failure and append an event."""
        order, _mode, _broker, _account, _principal = self.get_order_context(order_uuid)
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
        if row is None:
            raise UnknownSubmissionStateError(
                f"cancelled order {order_uuid} has no cancellation audit event; "
                "reconcile before relying on its timestamp"
            )
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
            scope=ExecutionScope(
                mode=ExecutionMode(submission["mode"]),
                broker_id=submission["broker_id"],
                account_id=submission["account_id"],
                principal_id=submission["principal_id"],
            ),
            plan_id=submission["plan_id"],
            batch_sha256=submission["batch_sha256"],
            status=SubmissionStatus(submission["status"]),
            orders=tuple(order_receipt_from_row(row) for row in rows),
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
        principal_id: str = "paper",
    ) -> None:
        self.adapter = adapter
        self.audit_store = audit_store
        self.configured_mode = configured_mode
        self.execute_enabled = execute_enabled
        self.live_enabled = live_enabled
        if principal_id == "legacy-unassigned":
            raise ExecutionConfigurationError(
                "legacy-unassigned is a reserved principal identity"
            )
        self.principal_id = principal_id

    def expected_confirmation(self, batch: OrderBatch) -> str:
        """Return the exact batch/account/mode-bound submission phrase."""
        return (
            f"SUBMIT {self.adapter.mode.value.upper()} "
            f"{self.adapter.broker_id} {self.adapter.account_id} "
            f"{self.principal_id} {batch.plan_id} {batch.sha256()}"
        )

    def expected_cancel_confirmation(self, order_uuid: uuid.UUID) -> str:
        """Return the exact order/account/mode-bound cancellation phrase."""
        return (
            f"CANCEL {self.adapter.mode.value.upper()} "
            f"{self.adapter.broker_id} {self.adapter.account_id} "
            f"{self.principal_id} {order_uuid}"
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
            principal_id=self.principal_id,
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
            ack_uuids = {ack.order_uuid for ack in acknowledgements}
            duplicate_broker_ids = len(
                {ack.broker_order_id for ack in acknowledgements}
            ) != len(acknowledgements)
            invalid_broker_ids = any(
                not isinstance(ack.broker_order_id, str)
                or not ack.broker_order_id.strip()
                for ack in acknowledgements
            )
            if (
                len(acknowledgements) != len(order_uuids)
                or ack_uuids != set(order_uuids)
                or duplicate_broker_ids
                or invalid_broker_ids
            ):
                reserved = set(order_uuids)
                validated: list[BrokerOrderAck] = []
                if not duplicate_broker_ids and not invalid_broker_ids:
                    seen: set[uuid.UUID] = set()
                    for ack in acknowledgements:
                        if ack.order_uuid in reserved and ack.order_uuid not in seen:
                            validated.append(ack)
                            seen.add(ack.order_uuid)
                raise BrokerBatchError(
                    "adapter acknowledgements do not match reserved order UUIDs",
                    completed=validated,
                    outcome_unknown=True,
                )
        except BrokerBatchError as exc:
            completed_uuids = {ack.order_uuid for ack in exc.completed}
            completed_broker_ids = {ack.broker_order_id for ack in exc.completed}
            invalid_completed_ids = any(
                not isinstance(ack.broker_order_id, str)
                or not ack.broker_order_id.strip()
                for ack in exc.completed
            )
            malformed_completed = (
                len(completed_uuids) != len(exc.completed)
                or not completed_uuids.issubset(order_uuids)
                or len(completed_broker_ids) != len(exc.completed)
                or invalid_completed_ids
            )
            malformed_failed = exc.failed_order_uuid is not None and (
                exc.failed_order_uuid not in order_uuids
                or exc.failed_order_uuid in completed_uuids
            )
            malformed = malformed_completed or malformed_failed
            trusted_completed = () if malformed else exc.completed
            try:
                failed = self.audit_store.record_failure(
                    receipt.submission_id,
                    error=str(exc),
                    completed=trusted_completed,
                    failed_order_uuid=(None if malformed else exc.failed_order_uuid),
                    outcome_unknown=exc.outcome_unknown or malformed,
                )
            except Exception:
                failed = reconciliation_receipt(
                    receipt,
                    trusted_completed,
                    str(exc),
                )
            raise ExecutionSubmissionError(str(exc), failed) from exc
        except Exception as exc:
            safe_error = f"broker operation failed ({type(exc).__name__})"
            try:
                failed = self.audit_store.record_failure(
                    receipt.submission_id,
                    error=safe_error,
                    completed=(),
                    failed_order_uuid=None,
                    outcome_unknown=True,
                )
            except Exception:
                failed = reconciliation_receipt(receipt, (), safe_error)
            raise ExecutionSubmissionError(safe_error, failed) from exc
        try:
            return self.audit_store.record_success(
                receipt.submission_id,
                acknowledgements,
            )
        except BrokerBatchError as exc:
            failed = self.audit_store.record_failure(
                receipt.submission_id,
                error=str(exc),
                completed=(),
                failed_order_uuid=None,
                outcome_unknown=True,
            )
            raise ExecutionSubmissionError(str(exc), failed) from exc
        except Exception as exc:
            safe_error = (
                "broker submission succeeded but audit persistence failed "
                f"({type(exc).__name__})"
            )
            try:
                failed = self.audit_store.record_failure(
                    receipt.submission_id,
                    error=safe_error,
                    completed=acknowledgements,
                    failed_order_uuid=None,
                    outcome_unknown=True,
                )
            except Exception:
                failed = reconciliation_receipt(
                    receipt,
                    acknowledgements,
                    safe_error,
                )
            raise ExecutionSubmissionError(safe_error, failed) from exc

    def cancel(
        self,
        order_uuid: uuid.UUID,
        *,
        confirmation: str,
    ) -> CancellationReceipt:
        """Cancel an acknowledged order with a separate explicit confirmation."""
        self._validate_adapter_mode()
        expected = self.expected_cancel_confirmation(order_uuid)
        if confirmation != expected:
            raise ExecutionConfirmationError(
                "explicit confirmation did not match the configured mode, "
                "account, and order"
            )
        order, mode, broker_id, account_id, principal_id = (
            self.audit_store.get_order_context(order_uuid)
        )
        if (
            mode is not self.adapter.mode
            or broker_id != self.adapter.broker_id
            or account_id != self.adapter.account_id
            or principal_id != self.principal_id
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
            try:
                self.audit_store.record_cancel(
                    order_uuid,
                    status="CANCEL_RECONCILIATION_REQUIRED",
                    error=safe_error,
                )
            except Exception:
                safe_error += "; audit persistence failed, reconciliation required"
            raise CancellationError(safe_error) from exc
        try:
            return self.audit_store.record_cancel(order_uuid, status="CANCELLED")
        except Exception as exc:
            raise CancellationError(
                "broker cancellation succeeded but audit persistence failed; "
                "reconciliation required"
            ) from exc

    def _validate_common_gates(self) -> None:
        if not self.execute_enabled:
            raise ExecutionGateError(
                "PI_ALLOW_T5_EXECUTE=true is required before execution"
            )
        self._validate_adapter_mode()
        if self.adapter.mode is ExecutionMode.LIVE and not self.live_enabled:
            raise ExecutionGateError(
                "PI_ALLOW_T5_LIVE=true is required for live execution"
            )

    def _validate_adapter_mode(self) -> None:
        if self.adapter.mode is not self.configured_mode:
            raise ExecutionGateError(
                f"adapter mode {self.adapter.mode.value!r} does not match "
                f"configured mode {self.configured_mode.value!r}"
            )


def get_default_broker_adapter(
    *,
    mode: ExecutionMode | str | None = None,
    account_id: str | None = None,
    paper_engine: PaperEngine | None = None,
    live_client: LiveBrokerClient | None = None,
    initialize: bool = True,
) -> BrokerAdapter:
    """Build the explicitly selected adapter; paper is the safe default."""
    resolved_mode = ExecutionMode(
        mode or os.environ.get("PI_T5_BROKER_MODE", ExecutionMode.PAPER.value)
    )
    if resolved_mode is ExecutionMode.PAPER:
        resolved_account = account_id or "paper"
        if paper_engine is None:
            paper_engine = paper_engine_module.get_default_engine(
                account_id=resolved_account,
                allow_fallback=False,
                initialize=initialize,
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


def get_default_paper_broker_id() -> str:
    """Return the configured paper broker/ledger identity without writes."""
    return f"paper-engine-{paper_engine_module.get_default_execution_scope_id()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)
