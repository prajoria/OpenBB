"""Paper and live implementations of the T5 broker adapter contract."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence

from openbb_techtrade.execution.broker_contract import (
    BrokerBatchError,
    BrokerOrderAck,
    ExecutionConfigurationError,
    ExecutionMode,
    LiveBrokerClient,
)
from openbb_techtrade.execution.order_sink import OrderBatch
from openbb_techtrade.execution.paper_engine import PaperEngine

_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PaperBrokerAdapter:
    """Adapt the existing transactional paper engine to the broker contract."""

    mode = ExecutionMode.PAPER

    def __init__(self, engine: PaperEngine, account_id: str = "paper") -> None:
        if engine.account_id != account_id:
            raise ExecutionConfigurationError(
                "paper engine account does not match configured account_id"
            )
        self.engine = engine
        self._account_id = account_id
        self._broker_id = f"paper-engine-{engine.execution_scope_id}"

    @property
    def broker_id(self) -> str:
        """Return the concrete paper ledger identity."""
        return self._broker_id

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
                "match the submitted batch",
                outcome_unknown=True,
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
            except ExecutionConfigurationError as exc:
                if completed:
                    raise BrokerBatchError(
                        "live broker identity changed between order submissions",
                        completed=completed,
                        outcome_unknown=True,
                    ) from exc
                raise
            try:
                broker_order_id = self._client.submit_order(
                    ticket,
                    client_order_id=str(order_uuid),
                )
                self._verify_identity()
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
            acknowledgement = BrokerOrderAck(order_uuid, str(broker_order_id))
            try:
                self._verify_identity()
            except ExecutionConfigurationError as exc:
                raise BrokerBatchError(
                    "live broker identity changed after accepting an order",
                    completed=(*completed, acknowledgement),
                    outcome_unknown=True,
                ) from exc
            completed.append(acknowledgement)
        return tuple(completed)

    def cancel_order(self, broker_order_id: str) -> None:
        """Cancel through the injected live client."""
        self._verify_identity()
        self._client.cancel_order(broker_order_id)
        self._verify_identity()

    def _verify_identity(self) -> None:
        if (
            str(self._client.account_id) != self._account_id
            or str(self._client.broker_id) != self._broker_id
        ):
            raise ExecutionConfigurationError(
                "live broker client identity changed after adapter construction"
            )
