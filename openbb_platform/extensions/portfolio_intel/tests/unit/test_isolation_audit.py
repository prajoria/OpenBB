"""Cross-account isolation audit (#546) — SEV-1 gate.

PRD §10.3 + §16.2 privacy boundary. This test file is the LOAD-BEARING
proof that the paper-trading subsystem enforces user_id ↔ account_id
isolation at every store surface. A regression here is a SEV-1 gate
failure (a foreign user gaining read or write access to another
user's paper account) and MUST block a release.

## Scope

Every store that persists paper-trading state exposes a public read/
write surface keyed on ``(user_id, account_id, ...)``. This file
exercises each surface:

1. **AccountStore** (#562) — create/get/list/reset/delete
2. **PositionStore** (#563) — get/put on lots
3. **LedgerStore** (#545) — append/list_for_account

For each surface, we assert:

- **Read isolation**: foreign user querying account X returns
  ``None`` / empty / a flat Lot — never sees the owner's state.
- **Write isolation**: foreign user writing to account X does not
  clobber the owner's state; owner reads back their original data
  unchanged.
- **Mutation raises**: mutating operations (reset, delete) on a
  foreign-owned account raise ``AccountNotFoundError``.

## SQL-grep smoke test (PRD §16.2 requirement)

An additional test greps for any SQL fragment in the paper-trading
modules that references portfolio_basket / Portfolio_Positions /
Account_Owner / ESPP_Plan — these are the "real" portfolio tables
and MUST NEVER be referenced from paper_*. A single cross-namespace
JOIN would collapse the privacy boundary.

## What this does NOT cover

- **Router-level authentication** — the router that wires stores
  into ``obb.paper.*`` commands is not yet shipped; its job will be
  to bind the caller's authenticated user_id at the boundary.
  When the router lands, its own tests will re-run this suite as
  end-to-end integration coverage.
- **MySQL binding** — once follow-ups swap in-memory stores for
  MySQL-backed ones, re-run this suite against those implementations.
  The Protocol contract is shared; the suite runs unmodified.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from openbb_portfolio_intel.paper import (
    AccountConfig,
    AccountNotFoundError,
    InMemoryAccountStore,
    InMemoryLedgerStore,
    InMemoryPositionStore,
    Lot,
    deposit_entry,
    trade_entry,
)

D = Decimal
NOW = datetime(2026, 7, 20, 9, 30, 0)
LATER = NOW + timedelta(hours=1)

OWNER = "daisy"
ATTACKER = "mallory"


# ---------------------------------------------------------------------------
# AccountStore
# ---------------------------------------------------------------------------


@pytest.fixture
def account_store_with_owner():
    """AccountStore with one account owned by OWNER."""
    store = InMemoryAccountStore()
    acc = store.create(
        user_id=OWNER,
        config=AccountConfig(starting_cash=D("100000")),
        now=NOW,
    )
    return store, acc


def test_account_get_returns_none_for_attacker(account_store_with_owner):
    store, acc = account_store_with_owner
    assert store.get(acc.account_id, user_id=ATTACKER) is None


def test_account_list_excludes_owner_accounts_from_attacker(account_store_with_owner):
    store, acc = account_store_with_owner
    assert store.list(user_id=ATTACKER) == []
    assert acc in store.list(user_id=OWNER)


def test_account_reset_by_attacker_raises_not_found(account_store_with_owner):
    store, acc = account_store_with_owner
    with pytest.raises(AccountNotFoundError):
        store.reset(acc.account_id, user_id=ATTACKER, now=LATER)
    # Owner's cash unchanged
    still_owner = store.get(acc.account_id, user_id=OWNER)
    assert still_owner.cash_balance == acc.cash_balance


def test_account_delete_by_attacker_raises_not_found(account_store_with_owner):
    store, acc = account_store_with_owner
    with pytest.raises(AccountNotFoundError):
        store.delete(acc.account_id, user_id=ATTACKER, now=LATER)
    still_owner = store.get(acc.account_id, user_id=OWNER)
    assert still_owner.is_active is True


def test_account_attacker_can_create_own_account_with_same_id_scope():
    """OWNER + ATTACKER get their own listing — but account_ids are globally
    unique in InMemoryAccountStore (first-write-wins). Verifies scope."""
    store = InMemoryAccountStore()
    a1 = store.create(user_id=OWNER, config=AccountConfig(starting_cash=D("1000")), now=NOW)
    a2 = store.create(
        user_id=ATTACKER, config=AccountConfig(starting_cash=D("1000")), now=NOW
    )
    # Each user only sees their own account
    assert store.list(user_id=OWNER) == [a1]
    assert store.list(user_id=ATTACKER) == [a2]


# ---------------------------------------------------------------------------
# PositionStore
# ---------------------------------------------------------------------------


def _owner_lot() -> Lot:
    return Lot(symbol="AAPL", qty=D("10"), avg_cost=D("100"), realized_pnl=D("0"))


def test_position_get_returns_flat_for_attacker():
    """Attacker reading owner's (account_id, symbol) gets a fresh flat Lot."""
    pstore = InMemoryPositionStore()
    pstore.put("acc-1", _owner_lot(), user_id=OWNER)
    view = pstore.get("acc-1", "AAPL", user_id=ATTACKER)
    assert view.qty == D("0")
    assert view.avg_cost == D("0")


def test_position_write_by_attacker_does_not_clobber_owner():
    pstore = InMemoryPositionStore()
    pstore.put("acc-1", _owner_lot(), user_id=OWNER)
    # Attacker attempts a large short under same account_id
    attacker_lot = Lot(
        symbol="AAPL", qty=D("-9999"), avg_cost=D("1"), realized_pnl=D("0")
    )
    pstore.put("acc-1", attacker_lot, user_id=ATTACKER)
    # Owner's lot is unchanged
    assert pstore.get("acc-1", "AAPL", user_id=OWNER) == _owner_lot()
    # Attacker sees only their own view
    assert pstore.get("acc-1", "AAPL", user_id=ATTACKER) == attacker_lot


# ---------------------------------------------------------------------------
# LedgerStore
# ---------------------------------------------------------------------------


def test_ledger_list_for_attacker_returns_empty():
    lstore = InMemoryLedgerStore()
    e = deposit_entry(
        account_id="acc-1",
        user_id=OWNER,
        sequence=1,
        occurred_at=NOW,
        amount=D("1000"),
    )
    lstore.append(e)
    assert lstore.list_for_account("acc-1", user_id=ATTACKER) == []


def test_ledger_dedup_is_per_tenant():
    """Same entry_id from different tenants both land — no cross-tenant collision."""
    lstore = InMemoryLedgerStore()
    e_owner = deposit_entry(
        account_id="acc-1",
        user_id=OWNER,
        sequence=1,
        occurred_at=NOW,
        amount=D("1000"),
        entry_id="collision-id",
    )
    e_attacker = deposit_entry(
        account_id="acc-1",
        user_id=ATTACKER,
        sequence=1,
        occurred_at=NOW,
        amount=D("999"),
        entry_id="collision-id",
    )
    lstore.append(e_owner)
    lstore.append(e_attacker)
    assert lstore.list_for_account("acc-1", user_id=OWNER) == [e_owner]
    assert lstore.list_for_account("acc-1", user_id=ATTACKER) == [e_attacker]


def test_ledger_trade_entries_isolated():
    """Trade entries in owner's account are invisible to attacker."""
    lstore = InMemoryLedgerStore()
    lstore.append(
        trade_entry(
            account_id="acc-1",
            user_id=OWNER,
            sequence=1,
            occurred_at=NOW,
            symbol="AAPL",
            quantity=D("10"),
            price=D("100"),
        )
    )
    assert lstore.list_for_account("acc-1", user_id=ATTACKER) == []
    assert len(lstore.list_for_account("acc-1", user_id=OWNER)) == 1


# ---------------------------------------------------------------------------
# SQL-grep smoke — PRD §16.2 no-cross-namespace-JOIN rule
# ---------------------------------------------------------------------------


# Namespace tables that MUST NEVER be referenced from paper_* modules.
REAL_PORTFOLIO_TABLES: tuple[str, ...] = (
    "portfolio_basket",
    "Portfolio_Positions",
    "Account_Owner",
    "ESPP_Plan",
)

PAPER_MODULE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "openbb_portfolio_intel"
    / "paper"
)


def test_no_cross_namespace_sql_references() -> None:
    """SEV-1 gate: paper_* modules must not reference real-portfolio tables.

    Every file under ``openbb_portfolio_intel/paper/`` is grepped for
    the real-portfolio table names. Any hit is a privacy-boundary
    violation (PRD §10.3 + §16.2) and blocks the release.
    """
    assert PAPER_MODULE_ROOT.is_dir(), f"paper module root missing: {PAPER_MODULE_ROOT}"
    violations: list[tuple[str, str, int, str]] = []
    for py in PAPER_MODULE_ROOT.rglob("*.py"):
        try:
            for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                for name in REAL_PORTFOLIO_TABLES:
                    if name in line:
                        violations.append((str(py), name, i, line.strip()))
        except UnicodeDecodeError:
            continue
    assert not violations, (
        "PRD §10.3 / §16.2 violation — paper_* modules must not reference "
        "real-portfolio tables. Hits:\n"
        + "\n".join(f"  {p}:{ln}  [{name}]  {line}" for (p, name, ln, line) in violations)
    )


# ---------------------------------------------------------------------------
# Fuzz-style probe — combinatorial user × account matrix
# ---------------------------------------------------------------------------


def test_two_users_two_accounts_full_matrix_isolated():
    """Full 2x2 matrix — every foreign combination isolated across all 3 stores."""
    astore = InMemoryAccountStore()
    pstore = InMemoryPositionStore()
    lstore = InMemoryLedgerStore()

    accounts: dict[tuple[str, str], str] = {}
    for user in (OWNER, ATTACKER):
        for i in range(2):
            acc = astore.create(
                user_id=user,
                config=AccountConfig(starting_cash=D("1000")),
                now=NOW,
                account_id=f"{user}-acc-{i}",
            )
            accounts[(user, f"acc-{i}")] = acc.account_id
            pstore.put(
                acc.account_id,
                Lot(
                    symbol="AAPL",
                    qty=D(str(10 * (i + 1))),
                    avg_cost=D("100"),
                    realized_pnl=D("0"),
                ),
                user_id=user,
            )
            lstore.append(
                deposit_entry(
                    account_id=acc.account_id,
                    user_id=user,
                    sequence=1,
                    occurred_at=NOW,
                    amount=D(str(500 * (i + 1))),
                )
            )

    # Every user sees ONLY their own 2 accounts
    assert len(astore.list(user_id=OWNER)) == 2
    assert len(astore.list(user_id=ATTACKER)) == 2
    # Attacker cannot see any owner-account content in any store
    for i in range(2):
        owner_aid = accounts[(OWNER, f"acc-{i}")]
        assert astore.get(owner_aid, user_id=ATTACKER) is None
        assert pstore.get(owner_aid, "AAPL", user_id=ATTACKER).qty == D("0")
        assert lstore.list_for_account(owner_aid, user_id=ATTACKER) == []
