"""Human-approved, isolated story paper actions (#2331, N09a)."""

# pylint: disable=redefined-outer-name,protected-access

import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_mcp_server.story_adapters import paper, paper_approve
from openbb_mcp_server.story_adapters.paper import (
    ApprovalMismatch,
    compose_story_paper_app,
)
from openbb_mcp_server.story_adapters.registry import compose_story_registry_app

REPO_ROOT = Path(__file__).resolve().parents[5]
MANIFESTS = (
    REPO_ROOT
    / "openbb_platform"
    / "extensions"
    / "agents"
    / "openbb_agents"
    / "notebook_guide"
    / "stories"
)
KEY = "k" * 48
BATCH = {
    "plan_id": "plan-1",
    "tickets": [
        {"symbol": "MSFT", "action": "Buy", "quantity": "10"},
        {
            "symbol": "NVDA",
            "action": "Buy",
            "quantity": "5",
            "order_type": "Limit",
            "limit_price": "120.50",
        },
    ],
    "verdict_gate_pass": True,
    "verdict_gates": [
        {"name": "PBO", "threshold": "< 0.5", "actual": "0.21", "passed": True}
    ],
}


def _client(principal, store, root):
    app = compose_story_registry_app(
        FastAPI(), principal=principal, manifest_dir=MANIFESTS, store_path=store
    )
    app = compose_story_paper_app(
        app, principal=principal, store_path=store, paper_root=root
    )
    return TestClient(app)


@pytest.fixture
def paper_harness(tmp_path, monkeypatch):
    """Build a run, a TechTrade sandbox with one submitted batch, and an approver."""
    monkeypatch.setenv(paper.APPROVAL_KEY_ENV, KEY)
    store = tmp_path / "runs.sqlite"
    root = tmp_path / "paper"
    alice = _client("alice", store, root)
    bob = _client("bob", store, root)
    confirmations = []

    def human(summary):
        confirmations.append(summary)
        return True

    def new_run(client=alice, story_id="techtrade/08"):
        response = client.post("/api/v1/story/runs", json={"story_id": story_id})
        assert response.status_code == 200, response.text
        return response.json()["run_id"]

    def new_sandbox(run_id, client=alice, starting_cash="100000"):
        response = client.post(
            f"/api/v1/story/runs/{run_id}/paper/sandboxes",
            json={"engine": "techtrade", "starting_cash": starting_cash},
        )
        assert response.status_code == 200, response.text
        return response.json()["sandbox_id"]

    def prepare(sandbox_id, action, arguments, operation_id, client=alice):
        return client.post(
            f"/api/v1/story/paper/sandboxes/{sandbox_id}/prepare",
            json={
                "operation_id": operation_id,
                "action": action,
                "arguments": arguments,
            },
        )

    def sign(request_id, confirm=human):
        return paper_approve.approve_request(request_id, db_path=store, confirm=confirm)

    def apply_raw(request_id, approval, action, arguments, client=alice):
        return client.post(
            f"/api/v1/story/paper/requests/{request_id}/apply",
            json={"approval": approval, "action": action, "arguments": arguments},
        )

    def run_action(sandbox_id, action, arguments, operation_id, client=alice):
        prepared = prepare(sandbox_id, action, arguments, operation_id, client=client)
        assert prepared.status_code == 200, prepared.text
        request_id = prepared.json()["request_id"]
        applied = apply_raw(
            request_id, sign(request_id), action, arguments, client=client
        )
        assert applied.status_code == 200, applied.text
        return applied.json()

    def state(sandbox_id, client=alice):
        response = client.get(f"/api/v1/story/paper/sandboxes/{sandbox_id}")
        assert response.status_code == 200, response.text
        return response.json()

    run_id = new_run()
    sandbox_id = new_sandbox(run_id)
    submitted = run_action(sandbox_id, "submit_batch", BATCH, "submit-1")
    order_ids = submitted["result"]["order_ids"]

    def fill_args(quantity, order=0, price="100.00"):
        return {
            "order_id": order_ids[order],
            "price": price,
            "filled_qty": str(quantity),
            "at": "2024-01-16T14:30:00Z",
        }

    class Harness(SimpleNamespace):
        """Fixture namespace for the plan's ``paper_harness`` contract."""

        ApprovalMismatch = ApprovalMismatch

        def approve(self, quantity, operation_id="fill-1"):
            """Prepare a fill and have the human approve it."""
            prepared = prepare(
                sandbox_id, "record_fill", fill_args(quantity), operation_id
            )
            assert prepared.status_code == 200, prepared.text
            request_id = prepared.json()["request_id"]
            return SimpleNamespace(request_id=request_id, token=sign(request_id))

        def apply(self, approval, quantity):
            """Apply an approved fill; raise ApprovalMismatch on a 409 mismatch."""
            response = apply_raw(
                approval.request_id, approval.token, "record_fill", fill_args(quantity)
            )
            if response.status_code == 409 and "approval_mismatch" in response.text:
                raise ApprovalMismatch(response.json()["detail"])
            return response

        @property
        def fill_count(self):
            return len(state(sandbox_id)["fills"])

    return Harness(
        alice=alice,
        bob=bob,
        store=store,
        root=root,
        run_id=run_id,
        sandbox_id=sandbox_id,
        order_ids=order_ids,
        new_run=new_run,
        new_sandbox=new_sandbox,
        prepare=prepare,
        sign=sign,
        apply_raw=apply_raw,
        run_action=run_action,
        state=state,
        fill_args=fill_args,
        confirmations=confirmations,
    )


def test_changed_arguments_require_new_approval(paper_harness):
    """The plan's anchor case: a different quantity is a different approval."""
    approval = paper_harness.approve(quantity=1)
    with pytest.raises(paper_harness.ApprovalMismatch):
        paper_harness.apply(approval=approval, quantity=2)
    assert paper_harness.fill_count == 0


def test_an_approved_fill_is_recorded_with_exact_decimals(paper_harness):
    """The approved action runs once; cash moves by the exact Decimal amount."""
    approval = paper_harness.approve(quantity=4)
    response = paper_harness.apply(approval=approval, quantity=4)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "applied"
    assert body["result"]["fill"]["filled_qty"] == "4"
    snapshot = paper_harness.state(paper_harness.sandbox_id)
    assert snapshot["account"]["cash"] == "99600.00"
    assert [p["symbol"] for p in snapshot["positions"]] == ["MSFT"]
    assert snapshot["positions"][0]["quantity"] == "4"
    orders = {o["order_id"]: o["status"] for o in snapshot["orders"]}
    assert orders[paper_harness.order_ids[0]] == "PARTIAL"


def test_duplicate_delivery_never_creates_a_second_fill(paper_harness):
    """Re-applying the same approved request returns the first result."""
    approval = paper_harness.approve(quantity=2)
    first = paper_harness.apply(approval=approval, quantity=2).json()
    second = paper_harness.apply(approval=approval, quantity=2).json()
    assert second == first
    assert paper_harness.fill_count == 1


def test_an_interrupted_apply_is_not_retried_blindly(paper_harness):
    """After an apply that may have run, the caller must inspect state first."""
    approval = paper_harness.approve(quantity=2)
    with sqlite3.connect(paper_harness.store) as connection:
        connection.execute(
            "UPDATE story_paper_requests SET status = 'applying'"
            " WHERE request_id = ?",
            (approval.request_id,),
        )
    response = paper_harness.apply(approval=approval, quantity=2)
    assert response.status_code == 409
    assert "uncertain" in response.text
    assert paper_harness.fill_count == 0


def test_reusing_an_operation_for_different_arguments_conflicts(paper_harness):
    """An operation ID names one prepared action."""
    paper_harness.approve(quantity=1, operation_id="op-x")
    again = paper_harness.prepare(
        paper_harness.sandbox_id,
        "record_fill",
        paper_harness.fill_args(3),
        "op-x",
    )
    assert again.status_code == 409
    same = paper_harness.prepare(
        paper_harness.sandbox_id, "record_fill", paper_harness.fill_args(1), "op-x"
    )
    assert same.status_code == 200


def test_a_forged_approval_is_refused(paper_harness):
    """Only the operator key can approve; a guessed or foreign token fails."""
    approval = paper_harness.approve(quantity=1)
    approval.token = "0" * 64
    response = paper_harness.apply(approval=approval, quantity=1)
    assert response.status_code == 403
    assert paper_harness.fill_count == 0


def test_an_approval_signed_with_another_key_is_refused(paper_harness, monkeypatch):
    """Rotating the key invalidates outstanding approvals."""
    approval = paper_harness.approve(quantity=1)
    monkeypatch.setenv(paper.APPROVAL_KEY_ENV, "z" * 48)
    response = paper_harness.apply(approval=approval, quantity=1)
    assert response.status_code == 403
    assert paper_harness.fill_count == 0


def test_an_approval_cannot_be_moved_to_another_request(paper_harness):
    """The token binds one request; it does not approve a sibling."""
    first = paper_harness.approve(quantity=1, operation_id="a")
    second = paper_harness.approve(quantity=1, operation_id="b")
    response = paper_harness.apply_raw(
        second.request_id,
        first.token,
        "record_fill",
        paper_harness.fill_args(1),
    )
    assert response.status_code == 403
    assert paper_harness.fill_count == 0


def test_an_expired_approval_is_refused(paper_harness, monkeypatch):
    """Approvals expire; resume never renews them silently."""
    approval = paper_harness.approve(quantity=1)
    real_now = paper._now
    monkeypatch.setattr(
        paper, "_now", lambda: real_now() + paper.APPROVAL_TTL + timedelta(seconds=1)
    )
    response = paper_harness.apply(approval=approval, quantity=1)
    assert response.status_code == 410
    assert paper_harness.fill_count == 0


def test_a_tampered_request_fails_the_signature(paper_harness):
    """Moving a stored request to another sandbox breaks its signature."""
    other = paper_harness.new_sandbox(paper_harness.run_id)
    approval = paper_harness.approve(quantity=1)
    with sqlite3.connect(paper_harness.store) as connection:
        connection.execute(
            "UPDATE story_paper_requests SET sandbox_id = ? WHERE request_id = ?",
            (other, approval.request_id),
        )
    response = paper_harness.apply(approval=approval, quantity=1)
    assert response.status_code == 403
    assert paper_harness.fill_count == 0


def test_another_principal_cannot_apply_or_inspect(paper_harness):
    """Bob cannot use Alice's approved request or read her sandbox."""
    approval = paper_harness.approve(quantity=1)
    response = paper_harness.apply_raw(
        approval.request_id,
        approval.token,
        "record_fill",
        paper_harness.fill_args(1),
        client=paper_harness.bob,
    )
    assert response.status_code == 404
    sandbox = paper_harness.bob.get(
        f"/api/v1/story/paper/sandboxes/{paper_harness.sandbox_id}"
    )
    assert sandbox.status_code == 404
    prepared = paper_harness.prepare(
        paper_harness.sandbox_id,
        "record_fill",
        paper_harness.fill_args(1),
        "bob-op",
        client=paper_harness.bob,
    )
    assert prepared.status_code == 404
    assert paper_harness.fill_count == 0


def test_a_changed_manifest_invalidates_the_approval(paper_harness):
    """An approval names the manifest version it was granted under."""
    approval = paper_harness.approve(quantity=1)
    with sqlite3.connect(paper_harness.store) as connection:
        record = json.loads(
            connection.execute("SELECT record FROM story_runs").fetchone()[0]
        )
        record["manifest_version"] = "techtrade/08@000000000000"
        connection.execute("UPDATE story_runs SET record = ?", (json.dumps(record),))
    response = paper_harness.apply(approval=approval, quantity=1)
    assert response.status_code == 409
    assert "manifest" in response.text
    assert paper_harness.fill_count == 0


def test_a_human_can_decline(paper_harness):
    """Declining issues no token, and nothing is applied."""
    prepared = paper_harness.prepare(
        paper_harness.sandbox_id, "record_fill", paper_harness.fill_args(1), "op-d"
    )
    request_id = prepared.json()["request_id"]
    with pytest.raises(paper_approve.ApprovalDenied):
        paper_harness.sign(request_id, confirm=lambda summary: False)
    assert paper_harness.fill_count == 0


def test_the_human_sees_the_stored_arguments_not_the_callers_text(paper_harness):
    """The summary comes from what the server will apply."""
    paper_harness.approve(quantity=3)
    summary = paper_harness.confirmations[-1]
    assert "record_fill" in summary
    assert "filled_qty: 3" in summary
    assert paper_harness.order_ids[0] in summary
    assert paper_harness.sandbox_id in summary


def test_without_a_signing_key_paper_actions_are_disabled(paper_harness, monkeypatch):
    """No configured key means no approvals and no prepared actions."""
    monkeypatch.delenv(paper.APPROVAL_KEY_ENV)
    response = paper_harness.prepare(
        paper_harness.sandbox_id, "record_fill", paper_harness.fill_args(1), "op-n"
    )
    assert response.status_code == 503
    assert paper.APPROVAL_KEY_ENV in response.text


def test_a_short_signing_key_is_rejected(paper_harness, monkeypatch):
    """A guessable key is treated as no key."""
    monkeypatch.setenv(paper.APPROVAL_KEY_ENV, "short")
    response = paper_harness.prepare(
        paper_harness.sandbox_id, "record_fill", paper_harness.fill_args(1), "op-s"
    )
    assert response.status_code == 503


def test_a_failed_verdict_cannot_be_submitted(paper_harness):
    """A batch whose verdict gates failed is refused before approval."""
    failed_gate = {
        **BATCH,
        "verdict_gates": [
            {"name": "PBO", "threshold": "< 0.5", "actual": "0.81", "passed": False}
        ],
    }
    no_pass = {**BATCH, "verdict_gate_pass": False}
    for index, batch in enumerate((failed_gate, no_pass)):
        response = paper_harness.prepare(
            paper_harness.sandbox_id, "submit_batch", batch, f"bad-{index}"
        )
        assert response.status_code == 422, response.text
        assert "verdict" in response.text


def test_engine_rejections_consume_the_approval(paper_harness):
    """An overfill fails loudly; the same approval cannot be retried."""
    approval = paper_harness.approve(quantity=11)
    response = paper_harness.apply(approval=approval, quantity=11)
    assert response.status_code == 422
    assert "overfill" in response.text
    again = paper_harness.apply(approval=approval, quantity=11)
    assert again.status_code == 409
    assert "failed" in again.text
    assert paper_harness.fill_count == 0


def test_cash_and_positions_are_conserved_across_buy_and_sell(paper_harness):
    """Buy 10 at 100 with commission 1, then sell 4 at 110: FIFO arithmetic."""
    harness = paper_harness
    harness.run_action(
        harness.sandbox_id,
        "record_fill",
        {**harness.fill_args(10), "commission": "1"},
        "buy-10",
    )
    sell_batch = {
        **BATCH,
        "plan_id": "plan-2",
        "tickets": [{"symbol": "MSFT", "action": "Sell", "quantity": "4"}],
    }
    sold = harness.run_action(harness.sandbox_id, "submit_batch", sell_batch, "sell")
    sell_order = sold["result"]["order_ids"][0]
    harness.run_action(
        harness.sandbox_id,
        "record_fill",
        {
            "order_id": sell_order,
            "price": "110.00",
            "filled_qty": "4",
            "at": "2024-01-17T14:30:00Z",
        },
        "sell-4",
    )
    snapshot = harness.state(harness.sandbox_id)
    # 100000 - (10 * 100 + 1) + 4 * 110 = 99439
    assert snapshot["account"]["cash"] == "99439.00"
    assert snapshot["positions"][0]["quantity"] == "6"
    # FIFO against the 100 lot; commission is cash, not cost basis: 4 * 10.
    assert snapshot["account"]["realized_pl"] == "40.00"
    assert len(snapshot["fills"]) == 2


def test_cancel_is_an_approved_action_and_idempotent_in_the_engine(paper_harness):
    """Cancelling a pending order needs approval; repeating it changes nothing."""
    harness = paper_harness
    order = harness.order_ids[1]
    harness.run_action(
        harness.sandbox_id, "cancel_order", {"order_id": order, "reason": "x"}, "c1"
    )
    harness.run_action(
        harness.sandbox_id, "cancel_order", {"order_id": order, "reason": "x"}, "c2"
    )
    orders = {
        o["order_id"]: o["status"] for o in harness.state(harness.sandbox_id)["orders"]
    }
    assert orders[order] == "CANCELLED"


def test_sandboxes_are_isolated(paper_harness):
    """A second sandbox starts from its own cash and sees no orders."""
    other = paper_harness.new_sandbox(paper_harness.run_id, starting_cash="5000")
    snapshot = paper_harness.state(other)
    assert snapshot["account"]["cash"] == "5000"
    assert snapshot["orders"] == []
    assert len(paper_harness.state(paper_harness.sandbox_id)["orders"]) == 2


def test_an_approved_request_reads_back_its_status(paper_harness):
    """The request shows pending, then applied, without exposing the key."""
    approval = paper_harness.approve(quantity=1)
    path = f"/api/v1/story/paper/requests/{approval.request_id}"
    assert paper_harness.alice.get(path).json()["status"] == "pending"
    paper_harness.apply(approval=approval, quantity=1)
    shown = paper_harness.alice.get(path).json()
    assert shown["status"] == "applied"
    assert KEY not in json.dumps(shown)
    assert approval.token not in json.dumps(shown)


def test_responses_never_carry_a_filesystem_path(paper_harness):
    """No sandbox, request or state response names a local path."""
    approval = paper_harness.approve(quantity=1)
    applied = paper_harness.apply(approval=approval, quantity=1).json()
    blob = json.dumps([applied, paper_harness.state(paper_harness.sandbox_id)])
    for marker in (str(paper_harness.root), paper_harness.root.as_posix(), ".sqlite"):
        assert marker not in blob


def test_unknown_actions_and_engines_are_rejected(paper_harness):
    """Only the reviewed actions and engines exist."""
    response = paper_harness.prepare(
        paper_harness.sandbox_id, "wire_transfer", {"amount": "1"}, "op-w"
    )
    assert response.status_code == 422
    bad_engine = paper_harness.alice.post(
        f"/api/v1/story/runs/{paper_harness.run_id}/paper/sandboxes",
        json={"engine": "broker", "starting_cash": "1"},
    )
    assert bad_engine.status_code == 422


def test_the_paper_routes_are_the_six_mcp_tools(tmp_path):
    """No tool approves; apply is the only mutation and needs a token."""
    app = compose_story_paper_app(
        FastAPI(), principal="alice", store_path=tmp_path / "r.sqlite"
    )
    routes = [r for r in app.routes if getattr(r, "openapi_extra", None)]
    names = {r.openapi_extra["mcp_config"]["name"] for r in routes}
    assert names == {
        "story_paper_sandbox_create",
        "story_paper_state",
        "story_paper_prepare",
        "story_paper_request",
        "story_paper_apply",
        "story_paper_sandbox_list",
    }
    assert not any("approve" in name for name in names)
    assert all(r.dependencies for r in routes)
    assert not (tmp_path / "r.sqlite").exists()
    with pytest.raises(ValueError):
        compose_story_paper_app(FastAPI(), principal="")


def test_the_approver_command_asks_a_human(paper_harness, monkeypatch, capsys):
    """The console approver shows the summary and needs an explicit yes."""
    prepared = paper_harness.prepare(
        paper_harness.sandbox_id, "record_fill", paper_harness.fill_args(1), "op-cli"
    )
    request_id = prepared.json()["request_id"]
    monkeypatch.setattr(paper_approve, "_is_terminal", lambda: True)
    answers = iter(["y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    code = paper_approve.main([request_id, "--store", str(paper_harness.store)])
    assert code == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    response = paper_harness.apply_raw(
        request_id, token, "record_fill", paper_harness.fill_args(1)
    )
    assert response.status_code == 200, response.text
    answers = iter(["n"])
    other = paper_harness.prepare(
        paper_harness.sandbox_id, "record_fill", paper_harness.fill_args(1), "op-cli2"
    ).json()["request_id"]
    assert paper_approve.main([other, "--store", str(paper_harness.store)]) == 1


def test_the_approver_command_refuses_a_pipe(paper_harness, monkeypatch, capsys):
    """Approval needs a person at a terminal, not text piped in by a program."""
    request_id = paper_harness.prepare(
        paper_harness.sandbox_id, "record_fill", paper_harness.fill_args(1), "op-pipe"
    ).json()["request_id"]
    monkeypatch.setattr(paper_approve, "_is_terminal", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert paper_approve.main([request_id, "--store", str(paper_harness.store)]) == 2
    assert "terminal" in capsys.readouterr().err


def test_the_approver_refuses_an_expired_request(paper_harness, monkeypatch):
    """An expired request cannot be approved after the fact."""
    request_id = paper_harness.prepare(
        paper_harness.sandbox_id, "record_fill", paper_harness.fill_args(1), "op-old"
    ).json()["request_id"]
    real_now = paper._now
    monkeypatch.setattr(
        paper, "_now", lambda: real_now() + paper.APPROVAL_TTL + timedelta(seconds=1)
    )
    with pytest.raises(paper_approve.ApprovalDenied, match="expired"):
        paper_harness.sign(request_id)


def test_a_run_holds_a_bounded_number_of_sandboxes(paper_harness, monkeypatch):
    """Sandboxes per run are capped."""
    monkeypatch.setattr(paper, "MAX_SANDBOXES_PER_RUN", 2)
    paper_harness.new_sandbox(paper_harness.run_id)
    response = paper_harness.alice.post(
        f"/api/v1/story/runs/{paper_harness.run_id}/paper/sandboxes",
        json={"engine": "techtrade", "starting_cash": "1000"},
    )
    assert response.status_code == 429


@pytest.mark.parametrize(
    "ticket",
    [
        {"symbol": "MSFT", "action": "Buy", "quantity": "1", "notes": "=HYPERLINK(1)"},
        {"symbol": "MSFT", "action": "Buy", "quantity": "NaN"},
        {"symbol": "MSFT", "action": "Buy", "quantity": "-1"},
        {"symbol": "msft;", "action": "Buy", "quantity": "1"},
        {"symbol": "MSFT", "action": "Buy", "quantity": "1", "extra": True},
    ],
)
def test_ticket_fields_are_validated_before_approval(paper_harness, ticket):
    """Formula text, NaN, non-positive amounts and odd symbols never reach a human."""
    batch = {**BATCH, "tickets": [ticket]}
    response = paper_harness.prepare(
        paper_harness.sandbox_id, "submit_batch", batch, "op-bad-ticket"
    )
    assert response.status_code == 422, response.text


def _link_dir(link, target):
    import os  # pylint: disable=import-outside-toplevel
    import sys  # pylint: disable=import-outside-toplevel

    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32":
        import _winapi  # pylint: disable=import-outside-toplevel

        _winapi.CreateJunction(str(target), str(link))
        return
    pytest.skip("cannot create a directory link here")


def test_a_linked_sandbox_directory_is_refused(paper_harness, tmp_path):
    """A planted link for a sandbox's directory cannot redirect its book."""
    outside = tmp_path / "outside"
    outside.mkdir()
    response = paper_harness.alice.post(
        f"/api/v1/story/runs/{paper_harness.run_id}/paper/sandboxes",
        json={"engine": "techtrade", "starting_cash": "1000"},
    )
    sandbox_id = response.json()["sandbox_id"]
    directory = (
        paper_harness.root / paper.ArtifactStore.principal_key("alice") / sandbox_id
    )
    for item in directory.iterdir():
        item.unlink()
    directory.rmdir()
    _link_dir(directory, outside)
    state = paper_harness.alice.get(f"/api/v1/story/paper/sandboxes/{sandbox_id}")
    assert state.status_code == 409
    assert not list(outside.iterdir())


def test_another_principal_cannot_read_a_request(paper_harness):
    """A request's arguments and status are its principal's alone."""
    approval = paper_harness.approve(quantity=1)
    response = paper_harness.bob.get(
        f"/api/v1/story/paper/requests/{approval.request_id}"
    )
    assert response.status_code == 404


def test_a_stale_read_cannot_apply_twice(paper_harness, monkeypatch):
    """The claim is conditional: a request already applied is never re-run."""
    approval = paper_harness.approve(quantity=1)
    assert paper_harness.apply(approval=approval, quantity=1).status_code == 200
    real_request = paper.PaperStore.request

    def stale(self, request_id, principal=None):
        row = real_request(self, request_id, principal)
        if row is None:
            return None
        data = dict(row)
        data["status"] = "pending"
        return data

    monkeypatch.setattr(paper.PaperStore, "request", stale)
    response = paper_harness.apply(approval=approval, quantity=1)
    assert response.status_code == 409
    assert "concurrently" in response.text
    monkeypatch.setattr(paper.PaperStore, "request", real_request)
    assert paper_harness.fill_count == 1


@pytest.mark.asyncio
async def test_only_the_ops_profile_can_apply(tmp_path, monkeypatch):
    """Read profiles prepare and inspect; applying needs portfolio-ops."""
    # pylint: disable=import-outside-toplevel
    from openbb_mcp_server.app.app import create_mcp_server
    from openbb_mcp_server.models.settings import MCPSettings

    monkeypatch.setenv("OPENBB_STORY_RUN_STORE", str(tmp_path / "runs.sqlite"))
    monkeypatch.setenv(paper.PAPER_ROOT_ENV, str(tmp_path / "paper"))
    names = {}
    for profile in ("portfolio-read", "portfolio-ops"):
        mcp = create_mcp_server(
            MCPSettings(
                api_prefix="/api/v1",
                capability_profile=profile,
                default_tool_categories=["all"],
                default_skills_dir=None,
            ),
            FastAPI(),
            auth=("synthetic-user", "x" * 32),
        )
        names[profile] = {
            tool.name
            for tool in await mcp.list_tools()
            if tool.name.startswith("story_paper_")
        }
    assert "story_paper_prepare" in names["portfolio-read"]
    assert "story_paper_apply" not in names["portfolio-read"]
    assert "story_paper_apply" in names["portfolio-ops"]
    assert not any("approve" in name for name in names["portfolio-ops"])
