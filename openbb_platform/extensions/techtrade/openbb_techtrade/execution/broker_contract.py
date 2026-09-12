"""Types and protocols for the T5 broker execution boundary."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, runtime_checkable

from openbb_techtrade.execution.order_sink import OrderBatch, OrderTicket


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


def validate_partial_acknowledgements(
    completed: Sequence[BrokerOrderAck],
    reserved_order_uuids: Sequence[uuid.UUID],
    failed_order_uuid: uuid.UUID | None,
) -> tuple[tuple[BrokerOrderAck, ...], bool]:
    """Return trustworthy partial acknowledgements and whether input was malformed."""
    completed = tuple(completed)
    if not all(
        isinstance(ack, BrokerOrderAck)
        and isinstance(ack.order_uuid, uuid.UUID)
        and isinstance(ack.broker_order_id, str)
        and bool(ack.broker_order_id.strip())
        for ack in completed
    ) or (
        failed_order_uuid is not None and not isinstance(failed_order_uuid, uuid.UUID)
    ):
        return (), True
    completed_uuids = {ack.order_uuid for ack in completed}
    completed_broker_ids = {ack.broker_order_id for ack in completed}
    malformed = (
        len(completed_uuids) != len(completed)
        or not completed_uuids.issubset(reserved_order_uuids)
        or len(completed_broker_ids) != len(completed)
        or (
            failed_order_uuid is not None
            and (
                failed_order_uuid not in reserved_order_uuids
                or failed_order_uuid in completed_uuids
            )
        )
    )
    return (() if malformed else completed), malformed


@dataclass(frozen=True)
class OrderReceipt:
    """Durable state for one submitted order."""

    order_uuid: uuid.UUID
    broker_order_id: str | None
    status: str
    error: str | None = None


@dataclass(frozen=True)
class ExecutionScope:
    """Broker, account, and principal bound to an execution."""

    mode: ExecutionMode
    broker_id: str
    account_id: str
    principal_id: str


@dataclass(frozen=True)
class SubmissionReceipt:
    """Durable result for an idempotent batch submission."""

    submission_id: uuid.UUID
    scope: ExecutionScope
    plan_id: str
    batch_sha256: str
    status: SubmissionStatus
    orders: tuple[OrderReceipt, ...]
    created_at: datetime
    updated_at: datetime
    error: str | None = None

    @property
    def mode(self) -> ExecutionMode:
        """Return the execution mode."""
        return self.scope.mode

    @property
    def broker_id(self) -> str:
        """Return the broker identity."""
        return self.scope.broker_id

    @property
    def account_id(self) -> str:
        """Return the broker account identity."""
        return self.scope.account_id

    @property
    def principal_id(self) -> str:
        """Return the authenticated principal identity."""
        return self.scope.principal_id


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


def reconciliation_receipt(
    receipt: SubmissionReceipt,
    acknowledgements: Sequence[BrokerOrderAck],
    error: str,
) -> SubmissionReceipt:
    """Build a fail-closed receipt when the durable audit itself is unavailable."""
    ack_by_uuid = {ack.order_uuid: ack.broker_order_id for ack in acknowledgements}
    return replace(
        receipt,
        status=SubmissionStatus.RECONCILIATION_REQUIRED,
        orders=tuple(
            replace(
                order,
                broker_order_id=ack_by_uuid.get(order.order_uuid),
                status="UNKNOWN",
                error=error,
            )
            for order in receipt.orders
        ),
        updated_at=datetime.now(timezone.utc),
        error=error,
    )


@runtime_checkable
class BrokerAdapter(Protocol):
    """Backend-neutral order submission and cancellation contract."""

    @property
    def mode(self) -> ExecutionMode:
        """Execution mode implemented by this adapter."""
        raise NotImplementedError

    @property
    def broker_id(self) -> str:
        """Stable broker/provider identity used by the audit scope."""
        raise NotImplementedError

    @property
    def account_id(self) -> str:
        """Backend account scope (never a credential)."""
        raise NotImplementedError

    def submit_batch(
        self,
        batch: OrderBatch,
        order_uuids: Sequence[uuid.UUID],
    ) -> tuple[BrokerOrderAck, ...]:
        """Submit the batch using UUIDs as client idempotency keys."""
        raise NotImplementedError

    def cancel_order(self, broker_order_id: str) -> None:
        """Cancel a backend order by its acknowledged identifier."""
        raise NotImplementedError


@runtime_checkable
class LiveBrokerClient(Protocol):
    """Injected vendor client boundary; implementations may perform I/O."""

    @property
    def broker_id(self) -> str:
        """Return the broker-verified provider identifier."""
        raise NotImplementedError

    @property
    def account_id(self) -> str:
        """Return the account identity verified by the broker session."""
        raise NotImplementedError

    def submit_order(self, ticket: OrderTicket, *, client_order_id: str) -> str:
        """Submit one ticket and return the vendor order identifier."""
        raise NotImplementedError

    def cancel_order(self, broker_order_id: str) -> None:
        """Cancel one vendor order."""
        raise NotImplementedError
