"""Durability and cross-connection tests for the SQLite paper stores (#2333).

The shared store contract runs against these stores through the
``paper_store_backend`` fixture. These tests cover what only a durable store
promises: state survives a new store object on the same file, Decimals round
trip exactly, and the cash floor holds when separate connections race.
"""

# ruff: noqa: D101, D102, D103

import dataclasses
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from openbb_portfolio_intel.paper.accounts import AccountConfig, AccountConfigError
from openbb_portfolio_intel.paper.cost_basis import Lot
from openbb_portfolio_intel.paper.ledger import (
    LedgerError,
    deposit_entry,
    replay,
    trade_entry,
)
from openbb_portfolio_intel.paper.sqlite_stores import (
    SqliteAccountStore,
    SqliteLedgerStore,
    SqlitePositionStore,
)

NOW = datetime(2026, 10, 28, 14, 30, tzinfo=timezone.utc)


def test_account_state_survives_a_new_store_on_the_same_file(tmp_path) -> None:
    path = tmp_path / "paper.sqlite"
    first = SqliteAccountStore(path)
    account = first.create(
        user_id="daisy",
        config=AccountConfig(starting_cash=Decimal("1000.10")),
        now=NOW,
        account_id="paper",
    )
    first.apply_cash_delta("paper", Decimal("-0.03"), user_id="daisy", now=NOW)

    reopened = SqliteAccountStore(path).get("paper", user_id="daisy")

    assert reopened is not None
    assert reopened.cash_balance == Decimal("1000.07")
    assert str(reopened.cash_balance) == "1000.07"
    assert reopened.config == account.config
    assert reopened.created_at == NOW


def test_lots_survive_a_new_store_and_list_by_symbol(tmp_path) -> None:
    path = tmp_path / "paper.sqlite"
    first = SqlitePositionStore(path)
    first.put(
        "paper",
        Lot(symbol="MSFT", qty=Decimal("3"), avg_cost=Decimal("410.125")),
        user_id="daisy",
    )
    first.put(
        "paper",
        Lot(symbol="AAPL", qty=Decimal("2"), avg_cost=Decimal("201.5")),
        user_id="daisy",
    )
    first.put(
        "paper",
        Lot(symbol="FLAT", qty=Decimal("0"), avg_cost=Decimal("0")),
        user_id="daisy",
    )

    lots = SqlitePositionStore(path).lots("paper", user_id="daisy")

    assert [lot.symbol for lot in lots] == ["AAPL", "MSFT"]
    assert lots[1].avg_cost == Decimal("410.125")
    assert SqlitePositionStore(path).lots("paper", user_id="mallory") == []


def test_cash_floor_holds_across_racing_connections(tmp_path) -> None:
    """Separate store objects on one file must still serialize the floor check.

    Each worker owns its own store, so the per-object thread lock gives no
    protection; only the ``BEGIN IMMEDIATE`` write lock does. Exactly five
    $10 debits fit a $50 balance with a $0 floor, and none may hit a lock error.
    """
    path = tmp_path / "paper.sqlite"
    SqliteAccountStore(path).create(
        user_id="daisy",
        config=AccountConfig(starting_cash=Decimal("50")),
        now=NOW,
        account_id="paper",
    )
    workers = 12
    barrier = threading.Barrier(workers)
    outcomes: list[str] = []
    guard = threading.Lock()

    def debit() -> None:
        store = SqliteAccountStore(path)
        barrier.wait()
        try:
            store.apply_cash_delta(
                "paper",
                Decimal("-10"),
                user_id="daisy",
                now=NOW,
                min_balance=Decimal("0"),
            )
            outcome = "ok"
        except AccountConfigError:
            outcome = "floor"
        except Exception as error:  # pylint: disable=broad-exception-caught
            outcome = f"error: {error}"
        with guard:
            outcomes.append(outcome)

    threads = [threading.Thread(target=debit) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["floor"] * 7 + ["ok"] * 5, outcomes
    final = SqliteAccountStore(path).get("paper", user_id="daisy")
    assert final is not None
    assert final.cash_balance == Decimal("0")


def test_failed_floor_check_leaves_no_partial_write(tmp_path) -> None:
    store = SqliteAccountStore(tmp_path / "paper.sqlite")
    store.create(
        user_id="daisy",
        config=AccountConfig(starting_cash=Decimal("5")),
        now=NOW,
        account_id="paper",
    )
    with pytest.raises(AccountConfigError):
        store.apply_cash_delta(
            "paper",
            Decimal("-6"),
            user_id="daisy",
            now=NOW,
            min_balance=Decimal("0"),
        )
    account = store.get("paper", user_id="daisy")
    assert account is not None
    assert account.cash_balance == Decimal("5")


def test_ledger_survives_a_new_store_with_exact_values(tmp_path) -> None:
    path = tmp_path / "paper.sqlite"
    plus_two = timezone(timedelta(hours=2))
    entries = [
        trade_entry(
            account_id="paper",
            user_id="daisy",
            sequence=2,
            occurred_at=NOW,
            symbol="MSFT",
            quantity=Decimal("-1.5"),
            price=Decimal("410.0005"),
            commission=Decimal("0.35"),
        ),
        deposit_entry(
            account_id="paper",
            user_id="daisy",
            sequence=1,
            # 13:00 UTC: an earlier instant than NOW whose ISO text sorts later.
            occurred_at=datetime(2026, 10, 28, 15, 0, tzinfo=plus_two),
            amount=Decimal("1000.01"),
        ),
    ]
    first = SqliteLedgerStore(path)
    for entry in entries:
        first.append(entry)

    listed = SqliteLedgerStore(path).list_for_account("paper", user_id="daisy")

    assert [e.sequence for e in listed] == [1, 2]
    assert listed[1] == entries[0]
    assert listed[0].occurred_at.utcoffset() == timedelta(hours=2)
    assert replay(listed).cash == Decimal("1000.01") + Decimal("614.65075")


def test_ledger_rejects_an_empty_entry_id(tmp_path) -> None:
    store = SqliteLedgerStore(tmp_path / "paper.sqlite")
    entry = dataclasses.replace(
        deposit_entry(
            account_id="paper",
            user_id="daisy",
            sequence=1,
            occurred_at=NOW,
            amount=Decimal("1"),
        ),
        entry_id="",
    )
    with pytest.raises(LedgerError):
        store.append(entry)
    assert store.list_for_account("paper", user_id="daisy") == []
