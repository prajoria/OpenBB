"""Tests for T5 P4 widget frontend rewrite (#1777)."""

# ruff: noqa: D101, D102, D103, D105

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient  # noqa: E402
from openbb_portfolio_intel.widget_backend.main import app  # noqa: E402
from openbb_portfolio_intel.widget_backend.widgets_endpoints import (  # noqa: E402
    _build_server_approved_t5_batch,
    _build_t5_demo_batch,
    register_t5_approved_batch,
)

_client = TestClient(app)

_MANIFEST_DIR = (
    Path(__file__).resolve().parents[2] / "openbb_portfolio_intel" / "widget_backend"
)


def _widgets() -> dict:
    return json.loads((_MANIFEST_DIR / "widgets.json").read_text(encoding="utf-8"))


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PI_PAPER_DB", str(tmp_path / "paper.db"))
    monkeypatch.setenv("PI_T5_EXECUTE_OUTPUT_DIR", str(tmp_path / "t5_out"))
    monkeypatch.setenv("PI_T5_EXECUTION_AUDIT_DB", str(tmp_path / "execution-audit.db"))
    monkeypatch.setenv("PI_T5_BROKER_MODE", "paper")
    monkeypatch.setenv("PI_PAPER_ENGINE", "sqlite")
    monkeypatch.delenv("PI_ALLOW_T5_EXECUTE", raising=False)
    monkeypatch.delenv("PI_ALLOW_T5_LIVE", raising=False)
    monkeypatch.delenv("PI_T5_LIVE_ACCOUNT_ID", raising=False)
    if hasattr(app.state, "t5_live_broker_client"):
        del app.state.t5_live_broker_client
    if hasattr(app.state, "t5_plan_approval_builder"):
        del app.state.t5_plan_approval_builder
    if hasattr(app.state, "t5_execution_principal_resolver"):
        del app.state.t5_execution_principal_resolver


def _authorize_live(monkeypatch: pytest.MonkeyPatch) -> None:
    app.state.t5_execution_principal_resolver = lambda _request: {
        "principal_id": "alice",
        "roles": {"live-trader"},
        "account_ids": {"fake-live"},
    }


# ---------------------------------------------------------------------------
# tt_execute_bridge — updated markdown output
# ---------------------------------------------------------------------------


class TestExecuteBridgeMarkdown:
    def test_pass_verdict_shows_write_batch_next_step(self, clean_env) -> None:
        """R7.11 twin: without the "write-batch" next-step link, the widget
        would still say READY but give the operator no path forward.
        """
        r = _client.get("/tt/execute/bridge?verdict=PASS")
        assert r.status_code == 200
        body = r.json()  # markdown endpoint returns json-string
        assert "write-batch" in body
        assert "approve-plan" in body
        assert "confirm=yes" in body
        assert "PI_ALLOW_T5_EXECUTE" in body
        assert "PI_T5_BROKER_MODE" in body
        assert "PI_ALLOW_T5_LIVE" in body

    def test_pass_verdict_shows_env_var_status(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        """Env var status must appear so the operator knows whether writes
        are enabled.
        """
        r = _client.get("/tt/execute/bridge?verdict=PASS")
        body = r.json()
        assert "DISABLED" in body or "🟡" in body

        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        r = _client.get("/tt/execute/bridge?verdict=PASS")
        body = r.json()
        assert "ENABLED" in body or "🟢" in body

    def test_fail_verdict_still_blocks(self, clean_env) -> None:
        """R7.11 twin: FAIL verdict must still show BLOCKED — the semantic
        gate can't regress.
        """
        r = _client.get("/tt/execute/bridge?verdict=FAIL")
        assert r.status_code == 200
        body = r.json()
        assert "BLOCKED" in body

    def test_invalid_verdict_still_400s(self, clean_env) -> None:
        r = _client.get("/tt/execute/bridge?verdict=MAYBE")
        assert r.status_code == 400


class TestBrokerExecutionGateway:
    def test_paper_retry_returns_same_submission(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")

        first = _client.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")
        second = _client.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["submission_id"] == first.json()["submission_id"]
        assert second.json()["order_uuids"] == first.json()["order_uuids"]

    def test_live_mode_requires_separate_kill_switch(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        monkeypatch.setenv("PI_T5_BROKER_MODE", "live")
        monkeypatch.setenv("PI_T5_LIVE_ACCOUNT_ID", "fake-live")
        _authorize_live(monkeypatch)
        app.state.t5_live_broker_client = _WidgetFakeLiveClient()
        batch = _build_t5_demo_batch("")
        confirm = (
            f"SUBMIT LIVE fake-broker fake-live alice "
            f"{batch.plan_id} {batch.sha256()}"
        )
        register_t5_approved_batch(
            batch,
            principal_id="alice",
            broker_id="fake-broker",
            account_id="fake-live",
        )

        response = _client.post(
            "/tt/execute/write-batch",
            params={
                "verdict": "PASS",
                "plan_id": batch.plan_id,
                "confirm": confirm,
            },
        )

        assert response.status_code == 403
        assert "PI_ALLOW_T5_LIVE" in response.json()["detail"]

    def test_live_mode_uses_only_injected_fake_client(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        monkeypatch.setenv("PI_ALLOW_T5_LIVE", "true")
        monkeypatch.setenv("PI_T5_BROKER_MODE", "live")
        monkeypatch.setenv("PI_T5_LIVE_ACCOUNT_ID", "fake-live")
        _authorize_live(monkeypatch)
        fake = _WidgetFakeLiveClient()
        app.state.t5_live_broker_client = fake
        batch = _build_t5_demo_batch("")
        register_t5_approved_batch(
            batch,
            principal_id="alice",
            broker_id="fake-broker",
            account_id="fake-live",
        )
        confirm = (
            f"SUBMIT LIVE fake-broker fake-live alice "
            f"{batch.plan_id} {batch.sha256()}"
        )

        response = _client.post(
            "/tt/execute/write-batch",
            params={
                "verdict": "PASS",
                "plan_id": batch.plan_id,
                "confirm": confirm,
            },
        )

        assert response.status_code == 200
        assert response.json()["mode"] == "live"
        assert len(fake.calls) == 3

    def test_live_mode_requires_server_side_approved_batch(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        monkeypatch.setenv("PI_ALLOW_T5_LIVE", "true")
        monkeypatch.setenv("PI_T5_BROKER_MODE", "live")
        monkeypatch.setenv("PI_T5_LIVE_ACCOUNT_ID", "fake-live")
        _authorize_live(monkeypatch)
        fake = _WidgetFakeLiveClient()
        app.state.t5_live_broker_client = fake
        batch = _build_t5_demo_batch("")

        response = _client.post(
            "/tt/execute/write-batch",
            params={
                "verdict": "PASS",
                "plan_id": batch.plan_id,
                "confirm": (
                    f"SUBMIT LIVE fake-broker fake-live "
                    f"alice {batch.plan_id} {batch.sha256()}"
                ),
            },
        )

        assert response.status_code == 403
        assert "server-side T4 approval" in response.json()["detail"]
        assert fake.calls == []

    def test_live_mode_requires_authorized_principal(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        monkeypatch.setenv("PI_ALLOW_T5_LIVE", "true")
        monkeypatch.setenv("PI_T5_BROKER_MODE", "live")
        monkeypatch.setenv("PI_T5_LIVE_ACCOUNT_ID", "fake-live")
        fake = _WidgetFakeLiveClient()
        app.state.t5_live_broker_client = fake
        batch = _build_t5_demo_batch("")
        register_t5_approved_batch(
            batch,
            principal_id="alice",
            broker_id="fake-broker",
            account_id="fake-live",
        )

        response = _client.post(
            "/tt/execute/write-batch",
            params={
                "verdict": "PASS",
                "plan_id": batch.plan_id,
                "confirm": "irrelevant",
            },
        )

        assert response.status_code == 403
        assert "principal" in response.json()["detail"]
        assert fake.calls == []

    @pytest.mark.parametrize(
        ("roles", "accounts", "expected"),
        [
            ("viewer", "fake-live", "live-trader role"),
            ("live-trader", "other-account", "account authorization"),
        ],
    )
    def test_live_mode_enforces_role_and_account_scope(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env,
        roles: str,
        accounts: str,
        expected: str,
    ) -> None:
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        monkeypatch.setenv("PI_ALLOW_T5_LIVE", "true")
        monkeypatch.setenv("PI_T5_BROKER_MODE", "live")
        monkeypatch.setenv("PI_T5_LIVE_ACCOUNT_ID", "fake-live")
        app.state.t5_execution_principal_resolver = lambda _request: {
            "principal_id": "alice",
            "roles": set(roles.split(",")),
            "account_ids": set(accounts.split(",")),
        }
        fake = _WidgetFakeLiveClient()
        app.state.t5_live_broker_client = fake
        batch = _build_t5_demo_batch("")
        register_t5_approved_batch(
            batch,
            principal_id="alice",
            broker_id="fake-broker",
            account_id="fake-live",
        )

        response = _client.post(
            "/tt/execute/write-batch",
            params={
                "verdict": "PASS",
                "plan_id": batch.plan_id,
                "confirm": "irrelevant",
            },
        )

        assert response.status_code == 403
        assert expected in response.json()["detail"]
        assert fake.calls == []

    def test_unknown_submission_returns_reconciliation_conflict(
        self, monkeypatch: pytest.MonkeyPatch, clean_env, tmp_path: Path
    ) -> None:
        from openbb_techtrade.execution.broker_adapter import (
            ExecutionMode,
            SqliteExecutionAuditStore,
        )
        from openbb_techtrade.execution.paper_engine import SqlitePaperEngine

        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        batch = _build_t5_demo_batch("")
        engine = SqlitePaperEngine(tmp_path / "paper.db")
        broker_id = f"paper-engine-{engine.execution_scope_id}"
        engine.close()
        store = SqliteExecutionAuditStore(tmp_path / "execution-audit.db")
        store.reserve(
            mode=ExecutionMode.PAPER,
            broker_id=broker_id,
            account_id="paper",
            principal_id="paper",
            plan_id=batch.plan_id,
            batch_sha256=batch.sha256(),
            order_count=len(batch.tickets),
        )
        store.close()

        response = _client.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")

        assert response.status_code == 409
        assert "reconcile" in response.json()["detail"]

    def test_unknown_cancellation_returns_reconciliation_conflict(
        self, monkeypatch: pytest.MonkeyPatch, clean_env, tmp_path: Path
    ) -> None:
        from uuid import UUID

        from openbb_techtrade.execution.broker_adapter import (
            SqliteExecutionAuditStore,
        )

        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        submitted = _client.post(
            "/tt/execute/write-batch?verdict=PASS&confirm=yes"
        ).json()
        order_uuid = UUID(submitted["order_uuids"][0])
        store = SqliteExecutionAuditStore(tmp_path / "execution-audit.db")
        store.reserve_cancel(order_uuid)
        store.close()

        response = _client.post(
            "/tt/execute/cancel",
            params={
                "order_uuid": str(order_uuid),
                "confirm": (
                    f"CANCEL PAPER {submitted['broker_id']} "
                    f"{submitted['account_id']} {submitted['principal_id']} "
                    f"{order_uuid}"
                ),
            },
        )

        assert response.status_code == 409
        assert "reconcile" in response.json()["detail"]

    def test_paper_order_cancel_requires_order_bound_confirmation(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        submitted = _client.post(
            "/tt/execute/write-batch?verdict=PASS&confirm=yes"
        ).json()
        order_uuid = submitted["order_uuids"][0]
        confirmation = (
            f"CANCEL PAPER {submitted['broker_id']} "
            f"{submitted['account_id']} {submitted['principal_id']} {order_uuid}"
        )

        rejected = _client.post(
            "/tt/execute/cancel",
            params={"order_uuid": order_uuid, "confirm": "yes"},
        )
        confirmed = _client.post(
            "/tt/execute/cancel",
            params={
                "order_uuid": order_uuid,
                "confirm": confirmation,
            },
        )
        replay = _client.post(
            "/tt/execute/cancel",
            params={
                "order_uuid": order_uuid,
                "confirm": confirmation,
            },
        )

        assert rejected.status_code == 403
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "CANCELLED"
        assert replay.json() == confirmed.json()


class _WidgetFakeLiveClient:
    account_id = "fake-live"
    broker_id = "fake-broker"

    def __init__(self) -> None:
        self.calls: list[tuple[object, str]] = []

    def submit_order(self, ticket, *, client_order_id: str) -> str:
        self.calls.append((ticket, client_order_id))
        return f"fake-{len(self.calls)}"

    def cancel_order(self, broker_order_id: str) -> None:
        return None


def test_approve_plan_registers_server_validated_batch(
    monkeypatch: pytest.MonkeyPatch, clean_env
) -> None:
    from decimal import Decimal

    from openbb_techtrade.execution.order_sink import OrderBatch, OrderTicket

    batch = OrderBatch(
        tickets=(OrderTicket("TSLA", "Buy", Decimal("2")),),
        plan_id="validated-plan",
        verdict_gate_pass=True,
    )
    request_id = "00000000-0000-4000-8000-000000000171"

    async def approved_builder(_plan, approval_id):
        return batch

    app.state.t5_plan_approval_builder = approved_builder
    response = _client.post(
        "/tt/execute/approve-plan",
        params={"approval_request_id": request_id},
        json={"symbol": "MSFT"},
    )

    assert response.status_code == 200
    assert response.json()["plan_id"] == f"t4-{request_id}"
    assert response.json()["batch_sha"] == batch.sha256()
    from openbb_techtrade.execution.broker_adapter import SqliteExecutionAuditStore

    store = SqliteExecutionAuditStore(os.environ["PI_T5_EXECUTION_AUDIT_DB"])
    restored = store.get_approved_batch(f"t4-{request_id}")
    assert restored is not None
    assert restored.sha256() == batch.sha256()
    store.close()

    monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
    execution = _client.post(
        "/tt/execute/write-batch",
        params={
            "verdict": "PASS",
            "confirm": "yes",
            "plan_id": f"t4-{request_id}",
        },
    )
    assert execution.status_code == 200
    assert execution.json()["batch_sha"] == batch.sha_short()

    second_request_id = "00000000-0000-4000-8000-000000000174"
    second_approval = _client.post(
        "/tt/execute/approve-plan",
        params={"approval_request_id": second_request_id},
        json={"symbol": "MSFT"},
    )
    second_execution = _client.post(
        "/tt/execute/write-batch",
        params={
            "verdict": "PASS",
            "confirm": "yes",
            "plan_id": second_approval.json()["plan_id"],
        },
    )
    assert second_execution.status_code == 200
    assert second_execution.json()["xlsx_path"] != execution.json()["xlsx_path"]

    mismatched_retry = _client.post(
        "/tt/execute/approve-plan",
        params={"approval_request_id": request_id},
        json={"symbol": "AAPL"},
    )
    assert mismatched_retry.status_code == 409
    assert "different approval request" in mismatched_retry.json()["detail"]


def test_approve_plan_rejects_unvalidated_injected_batch(
    monkeypatch: pytest.MonkeyPatch, clean_env
) -> None:
    from decimal import Decimal

    from openbb_techtrade.execution.order_sink import OrderBatch, OrderTicket

    async def unapproved_builder(_plan, _approval_id):
        return OrderBatch(
            tickets=(OrderTicket("MSFT", "Buy", Decimal("1")),),
            plan_id="untrusted",
            verdict_gate_pass=False,
        )

    app.state.t5_plan_approval_builder = unapproved_builder
    response = _client.post(
        "/tt/execute/approve-plan",
        params={"approval_request_id": "00000000-0000-4000-8000-000000000172"},
        json={"symbol": "MSFT"},
    )

    assert response.status_code == 403
    assert "verdict" in response.json()["detail"]


def test_approve_plan_rejects_invalid_broker_mode(
    monkeypatch: pytest.MonkeyPatch, clean_env
) -> None:
    monkeypatch.setenv("PI_T5_BROKER_MODE", "oracle")

    async def must_not_build(_plan, _approval_id):
        pytest.fail("invalid mode must be rejected before planning")

    app.state.t5_plan_approval_builder = must_not_build
    response = _client.post(
        "/tt/execute/approve-plan",
        params={"approval_request_id": "00000000-0000-4000-8000-000000000173"},
        json={"symbol": "MSFT"},
    )

    assert response.status_code == 503
    assert "PI_T5_BROKER_MODE" in response.json()["detail"]


def test_default_approval_builder_uses_server_generated_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from openbb_techtrade.engine import plan as plan_module
    from openbb_techtrade.models import Order
    from openbb_techtrade.validation import backtest_bridge

    server_plan = SimpleNamespace(
        orders=[
            Order(
                symbol="MSFT",
                side="buy",
                quantity=Decimal("3"),
                order_type="market",
                intent="entry",
            )
        ]
    )
    captured: dict = {}
    caller_thread = threading.current_thread()

    def build_plans(**kwargs):
        captured.update(kwargs)
        captured["thread"] = threading.current_thread()
        return [server_plan]

    async def validate_plan(plan, **kwargs):
        return plan, SimpleNamespace(verdict="robust")

    monkeypatch.setattr(plan_module, "build_plans", build_plans)
    monkeypatch.setattr(backtest_bridge, "validate_plan", validate_plan)

    batch = asyncio.run(
        _build_server_approved_t5_batch(
            {"symbol": "MSFT"},
            "t4-server-generated",
        )
    )

    assert captured["symbols"] == ["MSFT"]
    assert captured["risk"] == 0.01
    assert captured["thread"] is not caller_thread
    assert batch.tickets[0].symbol == "MSFT"
    assert batch.tickets[0].quantity == Decimal("3")
    assert batch.plan_id == "t4-server-generated"


def test_default_approval_builder_rejects_validation_policy_overrides() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException, match="unsupported approval fields"):
        asyncio.run(
            _build_server_approved_t5_batch(
                {
                    "symbol": "MSFT",
                    "thresholds": {
                        "pbo_robust": 2,
                        "dsr_robust": -1,
                    },
                },
                "t4-policy-bypass",
            )
        )


def test_cancel_reports_missing_techtrade_dependency(
    monkeypatch: pytest.MonkeyPatch, clean_env
) -> None:
    import builtins

    real_import = builtins.__import__

    def fail_broker_adapter(name, *args, **kwargs):
        if name == "openbb_techtrade.execution.broker_adapter":
            raise ImportError("simulated missing techtrade")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_broker_adapter)
    response = _client.post(
        "/tt/execute/cancel",
        params={
            "order_uuid": "00000000-0000-4000-8000-000000000001",
            "confirm": "anything",
        },
    )

    assert response.status_code == 500
    assert "t5_dependencies_missing" in response.json()["detail"]


# ---------------------------------------------------------------------------
# tt_execute_paper_status_markdown
# ---------------------------------------------------------------------------


class TestPaperStatusMarkdown:
    def test_no_db_shows_friendly_empty_state(self, clean_env) -> None:
        """R7.11 twin: raising on missing DB would make the widget crash
        every fresh install.
        """
        r = _client.get("/tt/execute/paper-status/markdown")
        assert r.status_code == 200
        body = r.json()
        assert "Paper Trading Engine" in body
        assert "No batches submitted yet" in body

    def test_after_batch_shows_state(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        """After a batch, the markdown includes the cash + positions header."""
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        _client.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")
        r = _client.get("/tt/execute/paper-status/markdown")
        assert r.status_code == 200
        body = r.json()
        assert "Cash" in body
        # After a submit_batch (no fills yet), positions is empty
        # so the "No open positions." fallback text appears.
        assert "PENDING" in body

    def test_status_uses_configured_paper_engine(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        from openbb_techtrade.execution import paper_engine

        class FakeEngine:
            def get_account(self):
                return SimpleNamespace(
                    account_id="mysql-paper",
                    cash=Decimal("100"),
                    realized_pl=Decimal("0"),
                    starting_cash=Decimal("100"),
                )

            def get_positions(self):
                return []

            def get_orders(self, status=None):
                return []

            def close(self):
                return None

        from decimal import Decimal

        monkeypatch.setenv("PI_PAPER_ENGINE", "mysql")

        def strict_engine(**kwargs):
            assert kwargs["allow_fallback"] is False
            return FakeEngine()

        monkeypatch.setattr(paper_engine, "get_default_engine", strict_engine)

        response = _client.get("/tt/execute/paper-status")

        assert response.status_code == 200
        assert response.json()["account"]["account_id"] == "mysql-paper"


# ---------------------------------------------------------------------------
# widgets.json manifest updates
# ---------------------------------------------------------------------------


class TestWidgetsJson:
    def test_bridge_description_updated(self) -> None:
        """R7.11 twin: reverting the description string here would surface
        the old '#1700 scaffold' text in the widget catalog.
        """
        w = _widgets().get("tt_execute_bridge")
        assert w is not None
        assert "#1719 P4" in w["description"]

    def test_new_paper_status_widget_declared(self) -> None:
        w = _widgets().get("tt_execute_paper_status")
        assert w is not None
        assert w["type"] == "markdown"
        assert w["endpoint"] == "tt/execute/paper-status/markdown"

    def test_new_route_registered(self) -> None:
        routes = {r.path for r in app.routes}
        assert "/tt/execute/paper-status/markdown" in routes
