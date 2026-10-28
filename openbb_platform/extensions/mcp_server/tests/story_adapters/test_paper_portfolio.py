"""Portfolio paper blotter and low-buying-power alert in a sandbox (#2333, N09c)."""

# pylint: disable=redefined-outer-name

import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_mcp_server.story_adapters import paper, paper_approve
from openbb_mcp_server.story_adapters.paper import compose_story_paper_app
from openbb_mcp_server.story_adapters.paper_portfolio import PortfolioBook
from openbb_mcp_server.story_adapters.registry import compose_story_registry_app
from openbb_portfolio_intel.paper.accounts import AccountConfig, InMemoryAccountStore
from openbb_portfolio_intel.paper.cost_basis import Lot
from openbb_portfolio_intel.paper.fills import (
    InMemoryPositionStore,
    OrderRequest,
    OrderType,
    Quote,
    submit_order,
)
from openbb_portfolio_intel.paper.sqlite_stores import (
    SqliteAccountStore,
    SqlitePositionStore,
)

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
OPENED = datetime(2026, 10, 28, 14, 30, tzinfo=timezone.utc)
SEEDS = [
    {"symbol": "VNQ", "quantity": "40", "avg_cost": "85"},
    {"symbol": "AMD", "quantity": "30", "avg_cost": "135"},
]


def _client(principal, store, root):
    app = compose_story_registry_app(
        FastAPI(), principal=principal, manifest_dir=MANIFESTS, store_path=store
    )
    app = compose_story_paper_app(
        app, principal=principal, store_path=store, paper_root=root
    )
    return TestClient(app)


def order(symbol, side, quantity, last, *, at=None, **extra):
    """Arguments of one ``submit_order`` with its approved quote."""
    quoted_at = at or OPENED + timedelta(minutes=1)
    return {
        "symbol": symbol,
        "side": side,
        "quantity": str(quantity),
        "quote": {"last": str(last), "quoted_at": quoted_at.isoformat()},
        **extra,
    }


@pytest.fixture
def book(tmp_path, monkeypatch):
    """Build a Portfolio chapter 5 run with a seeded sandbox and a movable clock."""
    monkeypatch.setenv(paper.APPROVAL_KEY_ENV, KEY)
    clock = SimpleNamespace(now=OPENED)
    monkeypatch.setattr(paper, "_now", lambda: clock.now)
    store = tmp_path / "runs.sqlite"
    root = tmp_path / "paper"
    alice = _client("alice", store, root)
    run = alice.post("/api/v1/story/runs", json={"story_id": "portfolio/05"})
    assert run.status_code == 200, run.text
    run_id = run.json()["run_id"]
    created = alice.post(
        f"/api/v1/story/runs/{run_id}/paper/sandboxes",
        json={
            "engine": "portfolio",
            "starting_cash": "100000",
            "initial_positions": SEEDS,
        },
    )
    assert created.status_code == 200, created.text
    sandbox_id = created.json()["sandbox_id"]
    clock.now = OPENED + timedelta(minutes=2)

    def prepare(arguments, operation_id, action="submit_order", sandbox=sandbox_id):
        return alice.post(
            f"/api/v1/story/paper/sandboxes/{sandbox}/prepare",
            json={
                "operation_id": operation_id,
                "action": action,
                "arguments": arguments,
            },
        )

    def sign(request_id):
        return paper_approve.approve_request(
            request_id, db_path=store, confirm=lambda summary: True
        )

    def apply(request_id, approval, arguments, action="submit_order"):
        return alice.post(
            f"/api/v1/story/paper/requests/{request_id}/apply",
            json={"approval": approval, "action": action, "arguments": arguments},
        )

    def submit(arguments, operation_id):
        prepared = prepare(arguments, operation_id)
        assert prepared.status_code == 200, prepared.text
        request_id = prepared.json()["request_id"]
        applied = apply(request_id, sign(request_id), arguments)
        assert applied.status_code == 200, applied.text
        assert applied.json()["status"] == "applied"
        return applied.json()["result"]

    def state():
        response = alice.get(f"/api/v1/story/paper/sandboxes/{sandbox_id}")
        assert response.status_code == 200, response.text
        return response.json()

    return SimpleNamespace(
        alice=alice,
        clock=clock,
        root=root,
        run_id=run_id,
        sandbox_id=sandbox_id,
        prepare=prepare,
        sign=sign,
        apply=apply,
        submit=submit,
        state=state,
    )


def test_a_seeded_book_opens_reconciled_with_its_starting_cash(book):
    """Seed lots enter the ledger as deposit plus trade; cash is untouched."""
    state = book.state()
    assert state["engine"] == "portfolio"
    assert state["account"] == {
        "starting_cash": "100000",
        "cash": "100000",
        "realized_pl": "0",
    }
    assert {
        p["symbol"]: (p["quantity"], p["avg_cost"]) for p in state["positions"]
    } == {
        "AMD": ("30", "135"),
        "VNQ": ("40", "85"),
    }
    assert state["ledger"] == {"entries": 4, "reconciled": True}
    assert state["blotter"] == []


def test_the_blotter_conserves_cash_and_positions_with_exact_decimals(book):
    """Chapter 5's three trades: add NVDA, trim VNQ, close AMD."""
    buy = book.submit(order("NVDA", "buy", 10, "120.10"), "nvda")
    trim = book.submit(order("VNQ", "sell", 40, "90"), "vnq")
    close = book.submit(order("AMD", "sell", 30, "140"), "amd")

    # Five basis points of slippage against the trader, zero commission; the
    # prices are the exact Decimal products, scale included.
    up, down = Decimal("1.0005"), Decimal("0.9995")
    assert buy["fill"]["price"] == str(Decimal("120.10") * up) == "120.160050"
    assert trim["fill"]["price"] == str(Decimal("90") * down) == "89.9550"
    assert close["fill"]["price"] == str(Decimal("140") * down) == "139.9300"
    cash = (
        Decimal("100000")
        - Decimal("10") * Decimal("120.16005")
        + Decimal("40") * Decimal("89.955")
        + Decimal("30") * Decimal("139.93")
    )
    assert Decimal(close["cash"]) == cash
    state = book.state()
    assert Decimal(state["account"]["cash"]) == cash
    assert Decimal(state["account"]["realized_pl"]) == (
        Decimal("40") * (Decimal("89.955") - Decimal("85"))
        + Decimal("30") * (Decimal("139.93") - Decimal("135"))
    )
    held = {p["symbol"]: p for p in state["positions"] if Decimal(p["quantity"])}
    assert list(held) == ["NVDA"]
    assert Decimal(held["NVDA"]["avg_cost"]) == Decimal("120.16005")
    assert state["ledger"] == {"entries": 7, "reconciled": True}
    assert [row["status"] for row in state["blotter"]] == ["filled"] * 3
    assert [row["order_id"] for row in state["blotter"]] == [
        buy["order_id"],
        trim["order_id"],
        close["order_id"],
    ]


def test_low_buying_power_is_an_explicit_rejection_with_an_alert(book):
    """A ~$3.8M order on a $100k book is refused, alerted and changes nothing."""
    before = book.state()
    result = book.submit(order("MSFT", "buy", 10000, "380"), "too-big")

    assert result["status"] == "rejected"
    assert result["reason"].startswith("insufficient cash")
    assert result["alert"]["kind"] == "low_buying_power"
    assert result["alert"]["severity"] == "warning"
    assert result["alert"]["trigger"] == "paper_trading_event"
    assert result["alert"]["message"].startswith("Order rejected for MSFT")
    after = book.state()
    assert after["account"] == before["account"]
    assert after["positions"] == before["positions"]
    assert after["ledger"] == {"entries": 4, "reconciled": True}
    assert [(r["symbol"], r["status"]) for r in after["blotter"]] == [
        ("MSFT", "rejected")
    ]
    assert after["blotter"][0]["reason"] == result["reason"]


def _engine_reason(arguments):
    """Return the reason the fill engine itself gives, on fresh in-memory stores."""
    accounts = InMemoryAccountStore()
    positions = InMemoryPositionStore()
    accounts.create(
        user_id="u",
        config=AccountConfig(starting_cash=Decimal("100000")),
        now=OPENED,
        account_id="a",
    )
    for seed in SEEDS:
        positions.put(
            "a",
            Lot(
                symbol=seed["symbol"],
                qty=Decimal(seed["quantity"]),
                avg_cost=Decimal(seed["avg_cost"]),
            ),
            user_id="u",
        )
    quantity = Decimal(arguments["quantity"])
    quoted_at = datetime.fromisoformat(arguments["quote"]["quoted_at"])

    class Fixed:
        """The approved quote."""

        def fetch(
            self, symbol, *, now
        ):  # noqa: ARG002  # pylint: disable=unused-argument
            """Return the quote."""
            return Quote(
                symbol=symbol,
                last=Decimal(arguments["quote"]["last"]),
                quoted_at=quoted_at,
            )

    limit = arguments.get("limit_price")
    result = submit_order(
        OrderRequest(
            symbol=arguments["symbol"],
            qty=quantity if arguments["side"] == "buy" else -quantity,
            order_type=OrderType(arguments.get("order_type", "market")),
            limit_price=None if limit is None else Decimal(limit),
        ),
        user_id="u",
        account_id="a",
        account_store=accounts,
        position_store=positions,
        quote_fetcher=Fixed(),
        now=quoted_at,
    )
    return result.reason.replace("'a'", "'<account>'")


@pytest.mark.parametrize(
    "arguments, expected",
    [
        (order("MSFT", "buy", 10000, "380"), "insufficient cash"),
        (
            order("NVDA", "buy", 5, "120", order_type="limit", limit_price="100"),
            "buy limit 100",
        ),
        (
            order("VNQ", "sell", 5, "80", order_type="limit", limit_price="85"),
            "sell limit 85",
        ),
        (order("VNQ", "sell", 41, "90"), "would drive VNQ qty from 40 to -1"),
        (order("TSLA", "sell", 1, "250"), "would drive TSLA qty from 0 to -1"),
    ],
)
def test_the_rejection_matrix_matches_the_fill_engine(book, arguments, expected):
    """The sandbox refuses exactly what ``submit_order`` refuses, with its reason."""
    result = book.submit(arguments, f"op-{expected[:10]}".replace(" ", "-"))
    assert result["status"] == "rejected"
    assert expected in result["reason"]
    engine = _engine_reason(arguments)
    sandbox_account = f"'{book.sandbox_id}'"
    assert result["reason"].replace(sandbox_account, "'<account>'") == engine
    assert book.state()["ledger"] == {"entries": 4, "reconciled": True}


@pytest.mark.parametrize(
    "shift, reason",
    [
        (timedelta(minutes=10), "stamped in the future"),
        (-timedelta(minutes=31), "older than 30 minutes"),
    ],
)
def test_a_quote_outside_the_window_is_rejected_at_apply(book, shift, reason):
    """The quote is checked against the clock when the order is applied."""
    arguments = order("NVDA", "buy", 1, "120", at=book.clock.now + shift)
    result = book.submit(arguments, "window")
    assert result["status"] == "rejected"
    assert reason in result["reason"]
    assert result["alert"]["kind"] == "order_rejected"
    assert book.state()["ledger"]["entries"] == 4


def test_an_approved_quote_that_ages_past_the_window_is_rejected(book):
    """Approval does not freeze time: a quote can age out before it is applied."""
    arguments = order("NVDA", "buy", 1, "120", at=book.clock.now)
    prepared = book.prepare(arguments, "aging")
    request_id = prepared.json()["request_id"]
    approval = book.sign(request_id)
    book.clock.now += timedelta(minutes=14)
    fresh = book.apply(request_id, approval, arguments)
    assert fresh.json()["result"]["status"] == "filled"

    late = order("NVDA", "buy", 1, "120", at=book.clock.now - timedelta(minutes=29))
    prepared = book.prepare(late, "late")
    request_id = prepared.json()["request_id"]
    approval = book.sign(request_id)
    book.clock.now += timedelta(minutes=2)
    response = book.apply(request_id, approval, late)
    result = response.json()["result"]
    assert result["status"] == "rejected"
    assert "older than 30 minutes" in result["reason"]


def test_a_quote_that_predates_the_last_entry_is_rejected(book):
    """Ledger order is application order: no fill may land before the last one."""
    book.submit(order("NVDA", "buy", 1, "120", at=book.clock.now), "first")
    earlier = order("NVDA", "buy", 1, "120", at=book.clock.now - timedelta(minutes=1))
    result = book.submit(earlier, "earlier")
    assert result["status"] == "rejected"
    assert "predates the book's last entry" in result["reason"]
    assert book.state()["ledger"] == {"entries": 5, "reconciled": True}


def test_the_approval_binds_the_quote(book):
    """Changing the price after approval needs a new approval."""
    arguments = order("NVDA", "buy", 10, "120.10")
    prepared = book.prepare(arguments, "bind")
    request_id = prepared.json()["request_id"]
    approval = book.sign(request_id)
    cheaper = {**arguments, "quote": {**arguments["quote"], "last": "1.00"}}

    response = book.apply(request_id, approval, cheaper)

    assert response.status_code == 409
    assert "approval_mismatch" in response.text
    assert book.state()["blotter"] == []


def test_a_redelivered_apply_fills_once(book):
    """The N09a once-only apply holds for Portfolio orders."""
    arguments = order("NVDA", "buy", 10, "120.10")
    prepared = book.prepare(arguments, "once")
    request_id = prepared.json()["request_id"]
    approval = book.sign(request_id)
    first = book.apply(request_id, approval, arguments)
    second = book.apply(request_id, approval, arguments)
    assert first.json() == second.json()
    state = book.state()
    assert len(state["blotter"]) == 1
    assert state["ledger"]["entries"] == 5


def test_actions_belong_to_their_engine(book):
    """A Portfolio book has no TechTrade actions, and the reverse."""
    batch = {
        "plan_id": "p",
        "tickets": [{"symbol": "MSFT", "action": "Buy", "quantity": "1"}],
        "verdict_gate_pass": True,
    }
    assert book.prepare(batch, "tt", action="submit_batch").status_code == 422
    techtrade = book.alice.post(
        f"/api/v1/story/runs/{book.run_id}/paper/sandboxes",
        json={"engine": "techtrade"},
    ).json()["sandbox_id"]
    response = book.prepare(order("MSFT", "buy", 1, "380"), "pi", sandbox=techtrade)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"engine": "techtrade", "initial_positions": SEEDS},
        {"engine": "portfolio", "initial_positions": [SEEDS[0], SEEDS[0]]},
        {
            "engine": "portfolio",
            "initial_positions": [{"symbol": "VNQ", "quantity": "-1", "avg_cost": "1"}],
        },
        {
            "engine": "portfolio",
            "initial_positions": [{"symbol": "=CMD", "quantity": "1", "avg_cost": "1"}],
        },
    ],
)
def test_seed_positions_are_validated(book, body):
    """Seeds exist only for Portfolio books, once per symbol, positive."""
    response = book.alice.post(
        f"/api/v1/story/runs/{book.run_id}/paper/sandboxes", json=body
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "arguments",
    [
        order("NVDA", "buy", 1, "120", order_type="limit"),
        order("NVDA", "buy", 1, "120", limit_price="121"),
        order("NVDA", "buy", -1, "120"),
        order("NVDA", "buy", 1, "120", order_type="stop"),
        {**order("NVDA", "buy", 1, "120"), "quote": {"last": "120"}},
        {
            **order("NVDA", "buy", 1, "120"),
            "quote": {"last": "120", "quoted_at": "2026-10-28T14:31:00"},
        },
    ],
)
def test_order_fields_are_validated_before_approval(book, arguments):
    """Malformed orders never reach a person or the engine."""
    assert book.prepare(arguments, "bad").status_code == 422


def test_separate_book_objects_serialize_on_the_book_lock(book):
    """Two server processes share a book file; the lock keeps every lot update."""
    directory = next(book.root.glob(f"*/{book.sandbox_id}"))
    workers = 8
    barrier = threading.Barrier(workers)
    errors = []

    def buy():
        shared = PortfolioBook(
            directory,
            user_id=directory.parent.name,
            account_id=book.sandbox_id,
            starting_cash=Decimal("100000"),
        )
        barrier.wait()
        try:
            result = shared.run("submit_order", order("NVDA", "buy", 1, "120"))
            if result["status"] != "filled":
                errors.append(result)
        except Exception as error:  # pylint: disable=broad-exception-caught
            errors.append(repr(error))

    threads = [threading.Thread(target=buy) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    state = book.state()
    nvda = next(p for p in state["positions"] if p["symbol"] == "NVDA")
    assert Decimal(nvda["quantity"]) == workers
    assert state["ledger"] == {"entries": 4 + workers, "reconciled": True}
    assert len(state["blotter"]) == workers


@pytest.mark.parametrize("drift", ["cash", "lot"])
def test_the_ledger_check_reports_a_book_that_drifted(book, drift):
    """A write outside the ledger, such as a crash between stores, is visible."""
    book.submit(order("NVDA", "buy", 10, "120.10"), "drift")
    directory = next(book.root.glob(f"*/{book.sandbox_id}"))
    owner, path = directory.parent.name, directory / "portfolio.sqlite"
    if drift == "cash":
        SqliteAccountStore(path).apply_cash_delta(
            book.sandbox_id, Decimal("-1"), user_id=owner, now=book.clock.now
        )
    else:
        SqlitePositionStore(path).put(
            book.sandbox_id,
            Lot(symbol="NVDA", qty=Decimal("11"), avg_cost=Decimal("120.16005")),
            user_id=owner,
        )
    assert book.state()["ledger"] == {"entries": 5, "reconciled": False}


def test_responses_never_carry_a_filesystem_path(book):
    """Neither the result nor the state names the sandbox directory."""
    result = book.submit(order("NVDA", "buy", 1, "120"), "path")
    text = repr(result) + repr(book.state())
    assert str(book.root) not in text
    assert "portfolio.sqlite" not in text
