"""T5 paper/live broker adapter contract tests (#1719)."""

# ruff: noqa: D101, D102, D103

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import json
import sqlite3
from threading import Event, Thread
from uuid import UUID

import pytest
from openbb_techtrade.execution.broker_adapter import (
    BrokerAdapter,
    BrokerBatchError,
    BrokerOrderAck,
    CancellationError,
    ExecutionConfigurationError,
    ExecutionConfirmationError,
    ExecutionGateError,
    ExecutionGateway,
    ExecutionMode,
    ExecutionSubmissionError,
    LiveBrokerAdapter,
    PaperBrokerAdapter,
    SqliteExecutionAuditStore,
    SubmissionStatus,
    UnknownSubmissionStateError,
    get_default_broker_adapter,
)
from openbb_techtrade.execution.order_sink import OrderBatch, OrderTicket
from openbb_techtrade.execution.order_sink import PlanContext, VerdictGate


def _batch(*symbols: str) -> OrderBatch:
    return OrderBatch(
        tickets=tuple(
            OrderTicket(symbol=symbol, action="Buy", quantity=Decimal("1"))
            for symbol in symbols
        ),
        plan_id="plan-1719",
        verdict_gate_pass=True,
    )


class _FakePaperEngine:
    execution_scope_id = "fake-ledger"

    def __init__(self) -> None:
        self.submissions = 0
        self.cancelled: list[str] = []
        self.account_id = "paper"

    def submit_batch(self, batch: OrderBatch, plan_id: str = "") -> list[str]:
        self.submissions += 1
        return [f"paper-{index}" for index, _ in enumerate(batch.tickets)]

    def cancel_order(self, order_id: str, reason: str = "") -> None:
        self.cancelled.append(order_id)


@dataclass
class _FakeLiveClient:
    fail_at: int | None = None
    account_id: str = "fake-live"
    broker_id: str = "fake-broker"

    def __post_init__(self) -> None:
        self.calls: list[tuple[OrderTicket, str]] = []
        self.cancelled: list[str] = []

    def submit_order(self, ticket: OrderTicket, *, client_order_id: str) -> str:
        if self.fail_at == len(self.calls):
            raise RuntimeError("fake broker rejected order")
        UUID(client_order_id)
        self.calls.append((ticket, client_order_id))
        return f"live-{len(self.calls)}"

    def cancel_order(self, broker_order_id: str) -> None:
        self.cancelled.append(broker_order_id)


@pytest.fixture
def audit(tmp_path: Path) -> SqliteExecutionAuditStore:
    store = SqliteExecutionAuditStore(tmp_path / "execution-audit.db")
    yield store
    store.close()


def _gateway(
    adapter: BrokerAdapter,
    audit: SqliteExecutionAuditStore,
    *,
    mode: ExecutionMode,
    live_enabled: bool = False,
) -> ExecutionGateway:
    return ExecutionGateway(
        adapter=adapter,
        audit_store=audit,
        configured_mode=mode,
        execute_enabled=True,
        live_enabled=live_enabled,
        principal_id=("paper" if mode is ExecutionMode.PAPER else "alice"),
    )


class TestAdapterContract:
    def test_paper_adapter_satisfies_protocol(self) -> None:
        assert isinstance(PaperBrokerAdapter(_FakePaperEngine()), BrokerAdapter)

    def test_paper_adapter_rejects_engine_account_mismatch(self) -> None:
        with pytest.raises(ExecutionConfigurationError, match="account"):
            PaperBrokerAdapter(_FakePaperEngine(), account_id="different")

    def test_live_adapter_satisfies_protocol(self) -> None:
        assert isinstance(
            LiveBrokerAdapter(_FakeLiveClient(), account_id="fake-live"),
            BrokerAdapter,
        )

    def test_live_adapter_rejects_client_account_mismatch(self) -> None:
        with pytest.raises(ExecutionConfigurationError, match="account"):
            LiveBrokerAdapter(
                _FakeLiveClient(account_id="actual-account"),
                account_id="confirmed-account",
            )

    def test_live_adapter_rechecks_client_identity_before_submit(self) -> None:
        client = _FakeLiveClient()
        adapter = LiveBrokerAdapter(client, account_id="fake-live")
        client.account_id = "different-account"

        with pytest.raises(BrokerBatchError) as raised:
            adapter.submit_batch(
                _batch("MSFT"),
                (UUID("00000000-0000-4000-8000-000000000001"),),
            )

        assert raised.value.completed == ()
        assert raised.value.outcome_unknown is True
        assert client.calls == []

    def test_live_adapter_rechecks_identity_before_each_order(self) -> None:
        class SwitchingClient(_FakeLiveClient):
            def submit_order(self, ticket: OrderTicket, *, client_order_id: str) -> str:
                result = super().submit_order(
                    ticket,
                    client_order_id=client_order_id,
                )
                self.account_id = "switched-account"
                return result

        client = SwitchingClient()
        adapter = LiveBrokerAdapter(client, account_id="fake-live")

        with pytest.raises(BrokerBatchError) as raised:
            adapter.submit_batch(
                _batch("MSFT", "AAPL"),
                (
                    UUID("00000000-0000-4000-8000-000000000001"),
                    UUID("00000000-0000-4000-8000-000000000002"),
                ),
            )

        assert raised.value.completed == ()
        assert raised.value.outcome_unknown is True
        assert len(client.calls) == 1

    @pytest.mark.parametrize("account_id", ["", " ", "live account", "../live"])
    def test_live_adapter_rejects_unsafe_account_scope(self, account_id: str) -> None:
        with pytest.raises(ExecutionConfigurationError, match="account_id"):
            LiveBrokerAdapter(_FakeLiveClient(), account_id=account_id)

    def test_live_adapter_propagates_order_uuids(self) -> None:
        client = _FakeLiveClient()
        adapter = LiveBrokerAdapter(client, account_id="fake-live")
        batch = _batch("MSFT", "AAPL")
        order_uuids = (
            UUID("00000000-0000-4000-8000-000000000001"),
            UUID("00000000-0000-4000-8000-000000000002"),
        )

        acks = adapter.submit_batch(batch, order_uuids)

        assert [call[1] for call in client.calls] == [
            str(value) for value in order_uuids
        ]
        assert [ack.broker_order_id for ack in acks] == ["live-1", "live-2"]

    def test_live_adapter_preserves_partial_acknowledgements(self) -> None:
        client = _FakeLiveClient(fail_at=1)
        adapter = LiveBrokerAdapter(client, account_id="fake-live")
        order_uuids = (
            UUID("00000000-0000-4000-8000-000000000001"),
            UUID("00000000-0000-4000-8000-000000000002"),
        )

        with pytest.raises(BrokerBatchError) as raised:
            adapter.submit_batch(_batch("MSFT", "AAPL"), order_uuids)

        assert len(raised.value.completed) == 1
        assert raised.value.failed_order_uuid == order_uuids[1]

    def test_live_adapter_does_not_expose_client_exception_text(self) -> None:
        client = _FakeLiveClient(fail_at=0)
        adapter = LiveBrokerAdapter(client, account_id="fake-live")

        with pytest.raises(BrokerBatchError) as raised:
            adapter.submit_batch(
                _batch("MSFT"),
                (UUID("00000000-0000-4000-8000-000000000001"),),
            )

        assert "fake broker rejected order" not in str(raised.value)
        assert "RuntimeError" in str(raised.value)

    def test_empty_live_acknowledgement_requires_reconciliation(self) -> None:
        class EmptyAckClient(_FakeLiveClient):
            def submit_order(self, ticket: OrderTicket, *, client_order_id: str) -> str:
                return ""

        adapter = LiveBrokerAdapter(EmptyAckClient(), account_id="fake-live")

        with pytest.raises(BrokerBatchError) as raised:
            adapter.submit_batch(
                _batch("MSFT"),
                (UUID("00000000-0000-4000-8000-000000000001"),),
            )

        assert raised.value.outcome_unknown is True


class TestExecutionGateway:
    def test_reserved_legacy_principal_is_rejected(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        with pytest.raises(ExecutionConfigurationError, match="reserved principal"):
            ExecutionGateway(
                adapter=LiveBrokerAdapter(
                    _FakeLiveClient(),
                    account_id="fake-live",
                ),
                audit_store=audit,
                configured_mode=ExecutionMode.LIVE,
                execute_enabled=True,
                live_enabled=True,
                principal_id="legacy-unassigned",
            )

    def test_legacy_audit_schema_migrates_with_fail_closed_principal(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "legacy-audit.db"
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE pi_execution_submission (
                submission_id TEXT PRIMARY KEY, mode TEXT NOT NULL,
                account_id TEXT NOT NULL, batch_sha256 TEXT NOT NULL,
                status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(mode, account_id, batch_sha256)
            );
            CREATE TABLE pi_execution_approval (
                plan_id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL,
                batch_sha256 TEXT NOT NULL, batch_json TEXT NOT NULL,
                approved_at TEXT NOT NULL
            );
            CREATE TABLE pi_execution_order (
                order_uuid TEXT PRIMARY KEY, submission_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL, broker_order_id TEXT,
                status TEXT NOT NULL, error TEXT,
                FOREIGN KEY(submission_id)
                    REFERENCES pi_execution_submission(submission_id),
                UNIQUE(submission_id, ordinal)
            );
            """)
        conn.execute(
            "INSERT INTO pi_execution_submission VALUES " "(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "00000000-0000-4000-8000-000000000001",
                "live",
                "fake-live",
                "a" * 64,
                "FAILED",
                None,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO pi_execution_order VALUES (?, ?, ?, ?, ?, ?)",
            (
                "00000000-0000-4000-8000-000000000002",
                "00000000-0000-4000-8000-000000000001",
                0,
                "legacy-broker-order",
                "SUBMITTED",
                None,
            ),
        )
        conn.commit()
        conn.close()

        store = SqliteExecutionAuditStore(path)
        row = store._conn.execute(  # noqa: SLF001
            "SELECT principal_id FROM pi_execution_submission"
        ).fetchone()
        columns = {
            item[1]
            for item in store._conn.execute(  # noqa: SLF001
                "PRAGMA table_info(pi_execution_approval)"
            ).fetchall()
        }
        foreign_parent = store._conn.execute(  # noqa: SLF001
            "PRAGMA foreign_key_list(pi_execution_order)"
        ).fetchone()[2]
        broker_owner = store._conn.execute(  # noqa: SLF001
            "SELECT order_uuid FROM pi_execution_broker_order "
            "WHERE broker_order_id = 'legacy-broker-order'"
        ).fetchone()
        migration_marker = store._conn.execute(  # noqa: SLF001
            "SELECT value FROM pi_execution_schema_meta "
            "WHERE key = 'live_broker_backfill_v1'"
        ).fetchone()
        store.close()

        assert row["principal_id"] == "legacy-unassigned"
        assert {"principal_id", "broker_id", "account_id"} <= columns
        assert foreign_parent == "pi_execution_submission"
        assert broker_owner["order_uuid"] == "00000000-0000-4000-8000-000000000002"
        assert migration_marker["value"] == "complete"

        reopened = SqliteExecutionAuditStore(path)
        with pytest.raises(UnknownSubmissionStateError, match="legacy live"):
            reopened.reserve(
                mode=ExecutionMode.LIVE,
                broker_id="fake-broker",
                account_id="fake-live",
                principal_id="alice",
                plan_id="different-plan",
                batch_sha256="b" * 64,
                order_count=1,
            )
        reopened.close()

    def test_approved_batch_replays_across_store_instances(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "execution-audit.db"
        batch = OrderBatch(
            tickets=_batch("MSFT", "AAPL").tickets,
            plan_id="plan-1719",
            verdict_gate_pass=True,
            pricing={"MSFT": Decimal("400")},
            pre_execution_positions={"MSFT": Decimal("0.25")},
            plan_context=PlanContext(
                verdict_gates=(
                    VerdictGate(
                        name="robustness",
                        threshold="PASS",
                        actual="PASS",
                        passed=True,
                    ),
                ),
                generator_version="test",
                git_sha="abc123",
            ),
        )
        first = SqliteExecutionAuditStore(path)
        first.register_approved_batch(batch)
        first.close()

        second = SqliteExecutionAuditStore(path)
        restored = second.get_approved_batch(batch.plan_id)
        second.close()

        assert restored is not None
        assert restored.sha256() == batch.sha256()
        assert restored.tickets == batch.tickets
        assert restored.pricing == batch.pricing
        assert restored.pre_execution_positions == batch.pre_execution_positions
        assert restored.plan_context == batch.plan_context

    def test_approved_batch_rejects_tampered_plan_identity(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        batch = _batch("MSFT")
        audit.register_approved_batch(batch)
        row = audit._conn.execute(  # noqa: SLF001
            "SELECT batch_json FROM pi_execution_approval WHERE plan_id = ?",
            (batch.plan_id,),
        ).fetchone()
        payload = json.loads(row["batch_json"])
        payload["plan_id"] = "tampered-plan"
        audit._conn.execute(  # noqa: SLF001
            "UPDATE pi_execution_approval SET batch_json = ? WHERE plan_id = ?",
            (json.dumps(payload, sort_keys=True), batch.plan_id),
        )
        audit._conn.commit()  # noqa: SLF001

        with pytest.raises(ExecutionGateError, match="plan identity"):
            audit.get_approved_batch(batch.plan_id)

    def test_approval_is_bound_to_broker_account_and_principal(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        batch = _batch("MSFT")
        audit.register_approved_batch(
            batch,
            principal_id="alice",
            broker_id="fake-broker",
            account_id="account-a",
        )

        with pytest.raises(ExecutionGateError, match="broker account"):
            audit.get_approved_batch(
                batch.plan_id,
                principal_id="alice",
                broker_id="fake-broker",
                account_id="account-b",
            )
        with pytest.raises(ExecutionGateError, match="principal"):
            audit.get_approved_batch(
                batch.plan_id,
                principal_id="mallory",
                broker_id="fake-broker",
                account_id="account-a",
            )

    def test_concurrent_approval_uuid_cannot_bind_different_requests(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "execution-audit.db"
        stores = [SqliteExecutionAuditStore(path), SqliteExecutionAuditStore(path)]
        first = _batch("MSFT")
        second = OrderBatch(
            tickets=_batch("AAPL").tickets,
            plan_id=first.plan_id,
            verdict_gate_pass=True,
        )
        outcomes: list[str] = []

        def register(
            store: SqliteExecutionAuditStore,
            batch: OrderBatch,
            request_sha: str,
        ) -> None:
            try:
                store.register_approved_batch(
                    batch,
                    principal_id="alice",
                    request_sha256=request_sha,
                )
                outcomes.append("registered")
            except ExecutionGateError:
                outcomes.append("rejected")

        workers = [
            Thread(target=register, args=(stores[0], first, "a" * 64)),
            Thread(target=register, args=(stores[1], second, "b" * 64)),
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
        for store in stores:
            store.close()

        assert sorted(outcomes) == ["registered", "rejected"]

    def test_identical_approval_retry_ignores_generated_at(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        first = _batch("MSFT")
        second = OrderBatch(
            tickets=first.tickets,
            plan_id=first.plan_id,
            verdict_gate_pass=True,
            generated_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        )

        audit.register_approved_batch(
            first,
            principal_id="alice",
            broker_id="fake-broker",
            account_id="fake-live",
            request_sha256="a" * 64,
        )
        audit.register_approved_batch(
            second,
            principal_id="alice",
            broker_id="fake-broker",
            account_id="fake-live",
            request_sha256="a" * 64,
        )

        restored = audit.get_approved_batch(
            first.plan_id,
            principal_id="alice",
            broker_id="fake-broker",
            account_id="fake-live",
            request_sha256="a" * 64,
        )
        assert restored is not None
        assert restored.generated_at == first.generated_at

    def test_approval_retry_rejects_changed_audit_context(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        first = OrderBatch(
            tickets=_batch("MSFT").tickets,
            plan_id="same-approval",
            verdict_gate_pass=True,
            pricing={"MSFT": Decimal("100")},
        )
        changed = OrderBatch(
            tickets=first.tickets,
            plan_id=first.plan_id,
            verdict_gate_pass=True,
            pricing={"MSFT": Decimal("200")},
        )
        audit.register_approved_batch(first, request_sha256="a" * 64)

        with pytest.raises(ExecutionGateError, match="different content"):
            audit.register_approved_batch(changed, request_sha256="a" * 64)

    def test_submission_requires_all_gates(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        adapter = PaperBrokerAdapter(_FakePaperEngine())
        batch = _batch("MSFT")
        gateway = ExecutionGateway(
            adapter=adapter,
            audit_store=audit,
            configured_mode=ExecutionMode.PAPER,
            execute_enabled=False,
        )
        with pytest.raises(ExecutionGateError, match="PI_ALLOW_T5_EXECUTE"):
            gateway.submit(batch, verdict="PASS", confirmation="anything")

        gateway = _gateway(adapter, audit, mode=ExecutionMode.PAPER)
        with pytest.raises(ExecutionGateError, match="verdict"):
            gateway.submit(batch, verdict="FAIL", confirmation="anything")
        with pytest.raises(
            ExecutionConfirmationError, match="explicit confirmation did not match"
        ) as raised:
            gateway.submit(batch, verdict="PASS", confirmation="yes")
        assert batch.sha256() not in str(raised.value)

    def test_batch_verdict_must_be_persisted_pass(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        batch = OrderBatch(tickets=_batch("MSFT").tickets, verdict_gate_pass=False)
        gateway = _gateway(
            PaperBrokerAdapter(_FakePaperEngine()),
            audit,
            mode=ExecutionMode.PAPER,
        )
        with pytest.raises(ExecutionGateError, match="batch verdict"):
            gateway.submit(
                batch,
                verdict="PASS",
                confirmation=gateway.expected_confirmation(batch),
            )

    def test_submit_is_durable_and_idempotent(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        engine = _FakePaperEngine()
        gateway = _gateway(PaperBrokerAdapter(engine), audit, mode=ExecutionMode.PAPER)
        batch = _batch("MSFT", "AAPL")
        confirmation = gateway.expected_confirmation(batch)

        first = gateway.submit(batch, verdict="PASS", confirmation=confirmation)
        second = gateway.submit(batch, verdict="PASS", confirmation=confirmation)

        assert second == first
        assert engine.submissions == 1
        assert first.status is SubmissionStatus.SUBMITTED
        assert first.broker_id == "paper-engine-fake-ledger"
        assert first.principal_id == "paper"
        assert len(first.orders) == 2
        assert len({order.order_uuid for order in first.orders}) == 2
        assert all(order.order_uuid.version == 5 for order in first.orders)
        assert {
            event.event_type for event in audit.list_events(first.submission_id)
        } >= {
            "SUBMISSION_RESERVED",
            "SUBMISSION_SUCCEEDED",
        }

    def test_distinct_approvals_with_same_tickets_execute_independently(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        engine = _FakePaperEngine()
        gateway = _gateway(PaperBrokerAdapter(engine), audit, mode=ExecutionMode.PAPER)
        first_batch = _batch("MSFT")
        second_batch = OrderBatch(
            tickets=first_batch.tickets,
            plan_id="second-approval",
            verdict_gate_pass=True,
        )

        first = gateway.submit(
            first_batch,
            verdict="PASS",
            confirmation=gateway.expected_confirmation(first_batch),
        )
        second = gateway.submit(
            second_batch,
            verdict="PASS",
            confirmation=gateway.expected_confirmation(second_batch),
        )

        assert first.submission_id != second.submission_id
        assert engine.submissions == 2

    def test_principal_is_part_of_submission_and_cancel_scope(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        adapter = LiveBrokerAdapter(_FakeLiveClient(), account_id="fake-live")
        alice = _gateway(
            adapter,
            audit,
            mode=ExecutionMode.LIVE,
            live_enabled=True,
        )
        batch = _batch("MSFT")
        receipt = alice.submit(
            batch,
            verdict="PASS",
            confirmation=alice.expected_confirmation(batch),
        )
        mallory = ExecutionGateway(
            adapter=adapter,
            audit_store=audit,
            configured_mode=ExecutionMode.LIVE,
            execute_enabled=True,
            live_enabled=True,
            principal_id="mallory",
        )

        with pytest.raises(ExecutionGateError, match="scope"):
            mallory.cancel(
                receipt.orders[0].order_uuid,
                confirmation=mallory.expected_cancel_confirmation(
                    receipt.orders[0].order_uuid
                ),
            )

    def test_audit_replays_after_store_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-audit.db"
        engine = _FakePaperEngine()
        batch = _batch("MSFT")
        first_store = SqliteExecutionAuditStore(path)
        first_gateway = _gateway(
            PaperBrokerAdapter(engine), first_store, mode=ExecutionMode.PAPER
        )
        first = first_gateway.submit(
            batch,
            verdict="PASS",
            confirmation=first_gateway.expected_confirmation(batch),
        )
        first_store.close()

        second_store = SqliteExecutionAuditStore(path)
        second_gateway = _gateway(
            PaperBrokerAdapter(engine), second_store, mode=ExecutionMode.PAPER
        )
        second = second_gateway.submit(
            batch,
            verdict="PASS",
            confirmation=second_gateway.expected_confirmation(batch),
        )
        second_store.close()

        assert second == first
        assert engine.submissions == 1

    def test_concurrent_reservation_has_one_winner(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-audit.db"
        stores = [SqliteExecutionAuditStore(path), SqliteExecutionAuditStore(path)]
        outcomes: list[tuple[object, bool]] = []
        errors: list[Exception] = []

        def reserve(store: SqliteExecutionAuditStore) -> None:
            try:
                outcomes.append(
                    store.reserve(
                        mode=ExecutionMode.PAPER,
                        broker_id="paper-engine",
                        account_id="paper",
                        principal_id="paper",
                        plan_id="plan-concurrent",
                        batch_sha256="a" * 64,
                        order_count=1,
                    )
                )
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        workers = [Thread(target=reserve, args=(store,)) for store in stores]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
        for store in stores:
            store.close()

        assert errors == []
        assert sorted(is_new for _receipt, is_new in outcomes) == [False, True]
        assert len({receipt.submission_id for receipt, _is_new in outcomes}) == 1

    def test_live_mode_requires_mode_gate_and_kill_switch(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        adapter = LiveBrokerAdapter(_FakeLiveClient(), account_id="fake-live")
        batch = _batch("MSFT")
        wrong_mode = _gateway(adapter, audit, mode=ExecutionMode.PAPER)
        with pytest.raises(ExecutionGateError, match="configured mode"):
            wrong_mode.submit(
                batch,
                verdict="PASS",
                confirmation=wrong_mode.expected_confirmation(batch),
            )
        live_disabled = _gateway(adapter, audit, mode=ExecutionMode.LIVE)
        with pytest.raises(ExecutionGateError, match="PI_ALLOW_T5_LIVE"):
            live_disabled.submit(
                batch,
                verdict="PASS",
                confirmation=live_disabled.expected_confirmation(batch),
            )

    def test_live_mode_requires_exact_batch_bound_confirmation(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        client = _FakeLiveClient()
        gateway = _gateway(
            LiveBrokerAdapter(client, account_id="fake-live"),
            audit,
            mode=ExecutionMode.LIVE,
            live_enabled=True,
        )
        with pytest.raises(
            ExecutionConfirmationError, match="explicit confirmation did not match"
        ):
            gateway.submit(_batch("MSFT"), verdict="PASS", confirmation="yes")
        assert client.calls == []

    def test_live_partial_failure_is_audited_and_not_retried(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        client = _FakeLiveClient(fail_at=1)
        gateway = _gateway(
            LiveBrokerAdapter(client, account_id="fake-live"),
            audit,
            mode=ExecutionMode.LIVE,
            live_enabled=True,
        )
        batch = _batch("MSFT", "AAPL")
        confirmation = gateway.expected_confirmation(batch)

        with pytest.raises(ExecutionSubmissionError) as raised:
            gateway.submit(batch, verdict="PASS", confirmation=confirmation)
        assert raised.value.receipt.status is SubmissionStatus.RECONCILIATION_REQUIRED
        assert raised.value.receipt.orders[1].status == "UNKNOWN"
        assert {
            event.event_type
            for event in audit.list_events(raised.value.receipt.submission_id)
        } >= {"ORDER_SUBMITTED", "ORDER_UNKNOWN", "SUBMISSION_FAILED"}

        with pytest.raises(UnknownSubmissionStateError, match="reconcile"):
            gateway.submit(batch, verdict="PASS", confirmation=confirmation)
        assert len(client.calls) == 1

    def test_paper_transport_failure_requires_reconciliation(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        class AmbiguousPaperEngine(_FakePaperEngine):
            def submit_batch(self, batch: OrderBatch, plan_id: str = "") -> list[str]:
                raise ConnectionError("commit response lost")

        gateway = _gateway(
            PaperBrokerAdapter(AmbiguousPaperEngine()),
            audit,
            mode=ExecutionMode.PAPER,
        )
        batch = _batch("MSFT")

        with pytest.raises(ExecutionSubmissionError) as raised:
            gateway.submit(
                batch,
                verdict="PASS",
                confirmation=gateway.expected_confirmation(batch),
            )

        assert raised.value.receipt.status is SubmissionStatus.RECONCILIATION_REQUIRED

    def test_malformed_live_acknowledgements_require_reconciliation(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        class MalformedLiveAdapter:
            mode = ExecutionMode.LIVE
            broker_id = "fake-broker"
            account_id = "fake-live"

            def submit_batch(self, batch, order_uuids):
                return (BrokerOrderAck(UUID(int=1), "possibly-accepted"),)

            def cancel_order(self, broker_order_id):
                return None

        gateway = _gateway(
            MalformedLiveAdapter(),
            audit,
            mode=ExecutionMode.LIVE,
            live_enabled=True,
        )
        batch = _batch("MSFT")

        with pytest.raises(ExecutionSubmissionError) as raised:
            gateway.submit(
                batch,
                verdict="PASS",
                confirmation=gateway.expected_confirmation(batch),
            )

        assert raised.value.receipt.status is SubmissionStatus.RECONCILIATION_REQUIRED
        assert raised.value.receipt.orders[0].broker_order_id is None
        assert raised.value.receipt.orders[0].status == "UNKNOWN"

    def test_malformed_paper_acknowledgements_require_reconciliation(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        class MalformedPaperEngine(_FakePaperEngine):
            def submit_batch(self, batch: OrderBatch, plan_id: str = "") -> list[str]:
                return []

        gateway = _gateway(
            PaperBrokerAdapter(MalformedPaperEngine()),
            audit,
            mode=ExecutionMode.PAPER,
        )
        batch = _batch("MSFT")

        with pytest.raises(ExecutionSubmissionError) as raised:
            gateway.submit(
                batch,
                verdict="PASS",
                confirmation=gateway.expected_confirmation(batch),
            )

        assert raised.value.receipt.status is SubmissionStatus.RECONCILIATION_REQUIRED
        assert raised.value.receipt.orders[0].status == "UNKNOWN"

    def test_duplicate_broker_acknowledgements_require_reconciliation(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        class DuplicateAckAdapter:
            mode = ExecutionMode.LIVE
            broker_id = "fake-broker"
            account_id = "fake-live"

            def submit_batch(self, batch, order_uuids):
                return tuple(
                    BrokerOrderAck(order_uuid, "duplicate-broker-id")
                    for order_uuid in order_uuids
                )

            def cancel_order(self, broker_order_id):
                return None

        gateway = _gateway(
            DuplicateAckAdapter(),
            audit,
            mode=ExecutionMode.LIVE,
            live_enabled=True,
        )
        batch = _batch("MSFT", "AAPL")

        with pytest.raises(ExecutionSubmissionError) as raised:
            gateway.submit(
                batch,
                verdict="PASS",
                confirmation=gateway.expected_confirmation(batch),
            )

        assert raised.value.receipt.status is SubmissionStatus.RECONCILIATION_REQUIRED
        assert {order.status for order in raised.value.receipt.orders} == {"UNKNOWN"}

    def test_blank_broker_acknowledgement_requires_reconciliation(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        class BlankAckAdapter:
            mode = ExecutionMode.PAPER
            broker_id = "paper-engine-test"
            account_id = "paper"

            def submit_batch(self, batch, order_uuids):
                return (BrokerOrderAck(order_uuids[0], "  "),)

            def cancel_order(self, broker_order_id):
                return None

        gateway = _gateway(
            BlankAckAdapter(),
            audit,
            mode=ExecutionMode.PAPER,
        )
        batch = _batch("MSFT")

        with pytest.raises(ExecutionSubmissionError) as raised:
            gateway.submit(
                batch,
                verdict="PASS",
                confirmation=gateway.expected_confirmation(batch),
            )

        assert raised.value.receipt.status is SubmissionStatus.RECONCILIATION_REQUIRED
        assert raised.value.receipt.orders[0].status == "UNKNOWN"

    def test_overlapping_completed_and_failed_ack_is_all_unknown(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        class OverlappingAckAdapter:
            mode = ExecutionMode.LIVE
            broker_id = "fake-broker"
            account_id = "fake-live"

            def submit_batch(self, batch, order_uuids):
                ack = BrokerOrderAck(order_uuids[0], "broker-1")
                raise BrokerBatchError(
                    "contradictory response",
                    completed=(ack,),
                    failed_order_uuid=order_uuids[0],
                )

            def cancel_order(self, broker_order_id):
                return None

        gateway = _gateway(
            OverlappingAckAdapter(),
            audit,
            mode=ExecutionMode.LIVE,
            live_enabled=True,
        )
        batch = _batch("MSFT", "AAPL")

        with pytest.raises(ExecutionSubmissionError) as raised:
            gateway.submit(
                batch,
                verdict="PASS",
                confirmation=gateway.expected_confirmation(batch),
            )

        assert {order.status for order in raised.value.receipt.orders} == {"UNKNOWN"}
        assert all(
            order.broker_order_id is None for order in raised.value.receipt.orders
        )

    def test_reserved_unknown_outcome_fails_closed(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        engine = _FakePaperEngine()
        gateway = _gateway(PaperBrokerAdapter(engine), audit, mode=ExecutionMode.PAPER)
        batch = _batch("MSFT")
        audit.reserve(
            mode=ExecutionMode.PAPER,
            broker_id=gateway.adapter.broker_id,
            account_id="paper",
            principal_id="paper",
            plan_id=batch.plan_id,
            batch_sha256=batch.sha256(),
            order_count=1,
        )

        with pytest.raises(UnknownSubmissionStateError, match="reconcile"):
            gateway.submit(
                batch,
                verdict="PASS",
                confirmation=gateway.expected_confirmation(batch),
            )

        assert engine.submissions == 0

    def test_cancel_requires_confirmation_and_is_idempotent(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        engine = _FakePaperEngine()
        gateway = _gateway(PaperBrokerAdapter(engine), audit, mode=ExecutionMode.PAPER)
        batch = _batch("MSFT")
        receipt = gateway.submit(
            batch,
            verdict="PASS",
            confirmation=gateway.expected_confirmation(batch),
        )
        order_uuid = receipt.orders[0].order_uuid

        with pytest.raises(ExecutionConfirmationError):
            gateway.cancel(order_uuid, confirmation="yes")
        confirmation = gateway.expected_cancel_confirmation(order_uuid)
        first = gateway.cancel(order_uuid, confirmation=confirmation)
        second = gateway.cancel(order_uuid, confirmation=confirmation)

        assert second == first
        assert engine.cancelled == ["paper-0"]
        assert first.status == "CANCELLED"

    def test_live_kill_switch_does_not_block_cancellation(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        client = _FakeLiveClient()
        gateway = _gateway(
            LiveBrokerAdapter(client, account_id="fake-live"),
            audit,
            mode=ExecutionMode.LIVE,
            live_enabled=True,
        )
        batch = _batch("MSFT")
        receipt = gateway.submit(
            batch,
            verdict="PASS",
            confirmation=gateway.expected_confirmation(batch),
        )
        order_uuid = receipt.orders[0].order_uuid
        gateway.execute_enabled = False
        gateway.live_enabled = False

        cancelled = gateway.cancel(
            order_uuid,
            confirmation=gateway.expected_cancel_confirmation(order_uuid),
        )

        assert cancelled.status == "CANCELLED"
        assert client.cancelled == ["live-1"]

    def test_live_broker_id_cannot_alias_prior_submission(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        class ReusedIdClient(_FakeLiveClient):
            def submit_order(self, ticket: OrderTicket, *, client_order_id: str) -> str:
                self.calls.append((ticket, client_order_id))
                return "same-broker-id"

        client = ReusedIdClient()
        gateway = _gateway(
            LiveBrokerAdapter(client, account_id="fake-live"),
            audit,
            mode=ExecutionMode.LIVE,
            live_enabled=True,
        )
        first = _batch("MSFT")
        second = OrderBatch(
            tickets=_batch("AAPL").tickets,
            plan_id="second-plan",
            verdict_gate_pass=True,
        )
        gateway.submit(
            first,
            verdict="PASS",
            confirmation=gateway.expected_confirmation(first),
        )

        with pytest.raises(ExecutionSubmissionError) as raised:
            gateway.submit(
                second,
                verdict="PASS",
                confirmation=gateway.expected_confirmation(second),
            )

        assert raised.value.receipt.status is SubmissionStatus.RECONCILIATION_REQUIRED

    def test_cancel_replay_keeps_its_order_timestamp(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        engine = _FakePaperEngine()
        gateway = _gateway(PaperBrokerAdapter(engine), audit, mode=ExecutionMode.PAPER)
        batch = _batch("MSFT", "AAPL")
        receipt = gateway.submit(
            batch,
            verdict="PASS",
            confirmation=gateway.expected_confirmation(batch),
        )
        first_uuid, second_uuid = (order.order_uuid for order in receipt.orders)
        first = gateway.cancel(
            first_uuid,
            confirmation=gateway.expected_cancel_confirmation(first_uuid),
        )
        gateway.cancel(
            second_uuid,
            confirmation=gateway.expected_cancel_confirmation(second_uuid),
        )

        replay = gateway.cancel(
            first_uuid,
            confirmation=gateway.expected_cancel_confirmation(first_uuid),
        )

        assert replay == first

    def test_cancel_replay_without_audit_event_fails_closed(
        self, audit: SqliteExecutionAuditStore
    ) -> None:
        engine = _FakePaperEngine()
        gateway = _gateway(PaperBrokerAdapter(engine), audit, mode=ExecutionMode.PAPER)
        batch = _batch("MSFT")
        receipt = gateway.submit(
            batch,
            verdict="PASS",
            confirmation=gateway.expected_confirmation(batch),
        )
        order_uuid = receipt.orders[0].order_uuid
        confirmation = gateway.expected_cancel_confirmation(order_uuid)
        gateway.cancel(order_uuid, confirmation=confirmation)
        audit._conn.execute(  # noqa: SLF001
            "DELETE FROM pi_execution_audit_event WHERE order_uuid = ?",
            (str(order_uuid),),
        )
        audit._conn.commit()  # noqa: SLF001

        with pytest.raises(UnknownSubmissionStateError, match="audit event"):
            gateway.cancel(order_uuid, confirmation=confirmation)

    def test_cancel_failure_is_audited(self, audit: SqliteExecutionAuditStore) -> None:
        class FailingCancelEngine(_FakePaperEngine):
            def cancel_order(self, order_id: str, reason: str = "") -> None:
                raise RuntimeError("fake cancel failure")

        gateway = _gateway(
            PaperBrokerAdapter(FailingCancelEngine()),
            audit,
            mode=ExecutionMode.PAPER,
        )
        batch = _batch("MSFT")
        receipt = gateway.submit(
            batch,
            verdict="PASS",
            confirmation=gateway.expected_confirmation(batch),
        )
        order_uuid = receipt.orders[0].order_uuid

        with pytest.raises(CancellationError, match="RuntimeError"):
            gateway.cancel(
                order_uuid,
                confirmation=gateway.expected_cancel_confirmation(order_uuid),
            )
        assert "fake cancel failure" not in audit.get_order(order_uuid).error
        assert audit.get_order(order_uuid).status == "CANCEL_RECONCILIATION_REQUIRED"

    def test_concurrent_cancel_reserves_single_broker_call(
        self, tmp_path: Path
    ) -> None:
        class SlowCancelEngine(_FakePaperEngine):
            def __init__(self) -> None:
                super().__init__()
                self.entered = Event()
                self.release = Event()

            def cancel_order(self, order_id: str, reason: str = "") -> None:
                self.cancelled.append(order_id)
                self.entered.set()
                self.release.wait(timeout=5)

        engine = SlowCancelEngine()
        first_store = SqliteExecutionAuditStore(tmp_path / "audit.db")
        first = _gateway(
            PaperBrokerAdapter(engine), first_store, mode=ExecutionMode.PAPER
        )
        batch = _batch("MSFT")
        receipt = first.submit(
            batch,
            verdict="PASS",
            confirmation=first.expected_confirmation(batch),
        )
        order_uuid = receipt.orders[0].order_uuid
        confirmation = first.expected_cancel_confirmation(order_uuid)
        result: list[object] = []

        worker = Thread(
            target=lambda: result.append(
                first.cancel(order_uuid, confirmation=confirmation)
            )
        )
        worker.start()
        assert engine.entered.wait(timeout=5)

        second_store = SqliteExecutionAuditStore(tmp_path / "audit.db")
        second = _gateway(
            PaperBrokerAdapter(engine), second_store, mode=ExecutionMode.PAPER
        )
        with pytest.raises(UnknownSubmissionStateError, match="reconcile"):
            second.cancel(order_uuid, confirmation=confirmation)

        engine.release.set()
        worker.join(timeout=5)
        first_store.close()
        second_store.close()
        assert len(engine.cancelled) == 1
        assert len(result) == 1


class TestFactory:
    def test_paper_factory_uses_default_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _FakePaperEngine()
        monkeypatch.setattr(
            "openbb_techtrade.execution.paper_engine.get_default_engine",
            lambda **kwargs: (
                engine
                if kwargs["allow_fallback"] is False
                else pytest.fail("audited execution must disable backend fallback")
            ),
        )
        adapter = get_default_broker_adapter(
            mode=ExecutionMode.PAPER,
            account_id="paper",
        )
        assert isinstance(adapter, PaperBrokerAdapter)
        assert adapter.engine is engine

    def test_live_factory_requires_injected_client(self) -> None:
        with pytest.raises(ExecutionConfigurationError, match="injected"):
            get_default_broker_adapter(
                mode=ExecutionMode.LIVE,
                account_id="fake-live",
            )
