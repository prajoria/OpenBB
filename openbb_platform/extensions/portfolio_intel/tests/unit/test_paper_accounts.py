"""Unit tests for paper-trading account CRUD (#562)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from openbb_portfolio_intel.paper import (
    AccountConfig,
    AccountConfigError,
    AccountNotFoundError,
    InMemoryAccountStore,
    PaperAccount,
)

NOW = datetime(2026, 7, 20, 9, 30, 0)
LATER = datetime(2026, 7, 20, 10, 0, 0)


def _cfg(**overrides) -> AccountConfig:
    base = {
        "starting_cash": Decimal("100000"),
        "currency": "USD",
        "margin_enabled": False,
        "commission_model": "zero",
        "slippage_bps": 5,
    }
    base.update(overrides)
    return AccountConfig(**base)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_returns_persisted_account_with_starting_cash() -> None:
    store = InMemoryAccountStore()
    acc = store.create(user_id="daisy", config=_cfg(), now=NOW)
    assert isinstance(acc, PaperAccount)
    assert acc.user_id == "daisy"
    assert acc.cash_balance == Decimal("100000")
    assert acc.is_active is True
    assert acc.created_at == NOW
    assert acc.updated_at == NOW
    assert acc.account_id.startswith("acc_")


def test_create_with_explicit_account_id() -> None:
    store = InMemoryAccountStore()
    acc = store.create(user_id="daisy", config=_cfg(), now=NOW, account_id="MY_ID")
    assert acc.account_id == "MY_ID"


def test_create_rejects_duplicate_account_id() -> None:
    store = InMemoryAccountStore()
    store.create(user_id="daisy", config=_cfg(), now=NOW, account_id="X")
    with pytest.raises(AccountConfigError, match=r"already exists"):
        store.create(user_id="daisy", config=_cfg(), now=NOW, account_id="X")


def test_create_rejects_negative_starting_cash() -> None:
    with pytest.raises(AccountConfigError, match=r"starting_cash"):
        InMemoryAccountStore().create(
            user_id="daisy",
            config=_cfg(starting_cash=Decimal("-1")),
            now=NOW,
        )


def test_create_rejects_bad_currency_length() -> None:
    with pytest.raises(AccountConfigError, match=r"currency"):
        InMemoryAccountStore().create(
            user_id="daisy", config=_cfg(currency="US"), now=NOW
        )


def test_create_rejects_unknown_commission_model() -> None:
    with pytest.raises(AccountConfigError, match=r"commission_model"):
        InMemoryAccountStore().create(
            user_id="daisy", config=_cfg(commission_model="bogus"), now=NOW
        )


def test_create_rejects_negative_slippage_bps() -> None:
    with pytest.raises(AccountConfigError, match=r"slippage_bps"):
        InMemoryAccountStore().create(
            user_id="daisy", config=_cfg(slippage_bps=-1), now=NOW
        )


def test_create_rejects_empty_user_id() -> None:
    with pytest.raises(AccountConfigError, match=r"user_id"):
        InMemoryAccountStore().create(user_id="", config=_cfg(), now=NOW)


# ---------------------------------------------------------------------------
# get — cross-account isolation seed (#546)
# ---------------------------------------------------------------------------


def test_get_returns_account_for_owner() -> None:
    store = InMemoryAccountStore()
    acc = store.create(user_id="daisy", config=_cfg(), now=NOW)
    assert store.get(acc.account_id, user_id="daisy") == acc


def test_get_returns_none_for_foreign_user() -> None:
    """Cross-account isolation — foreign user gets None, not raise (no info leak)."""
    store = InMemoryAccountStore()
    acc = store.create(user_id="daisy", config=_cfg(), now=NOW)
    assert store.get(acc.account_id, user_id="mallory") is None


def test_get_returns_none_for_missing_account() -> None:
    assert InMemoryAccountStore().get("nonexistent", user_id="daisy") is None


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_returns_only_owner_accounts_sorted_by_created() -> None:
    store = InMemoryAccountStore()
    a1 = store.create(user_id="daisy", config=_cfg(), now=datetime(2026, 7, 20, 9))
    a2 = store.create(user_id="daisy", config=_cfg(), now=datetime(2026, 7, 20, 10))
    store.create(user_id="mallory", config=_cfg(), now=datetime(2026, 7, 20, 11))
    daisy_accounts = store.list(user_id="daisy")
    assert [a.account_id for a in daisy_accounts] == [a1.account_id, a2.account_id]


def test_list_excludes_inactive_by_default() -> None:
    store = InMemoryAccountStore()
    a1 = store.create(user_id="daisy", config=_cfg(), now=NOW)
    store.delete(a1.account_id, user_id="daisy", now=LATER)
    assert store.list(user_id="daisy") == []
    assert len(store.list(user_id="daisy", active_only=False)) == 1


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


def test_reset_zeros_cash_back_to_starting() -> None:
    store = InMemoryAccountStore()
    acc = store.create(
        user_id="daisy", config=_cfg(starting_cash=Decimal("50000")), now=NOW
    )
    # Simulate a drawn-down balance via internal mutation for the test
    store._accounts[acc.account_id] = _spend_cash(
        store._accounts[acc.account_id], Decimal("30000")
    )
    assert store._accounts[acc.account_id].cash_balance == Decimal("20000")
    reset = store.reset(acc.account_id, user_id="daisy", now=LATER)
    assert reset.cash_balance == Decimal("50000")
    assert reset.updated_at == LATER
    assert reset.created_at == NOW  # unchanged


def test_reset_foreign_user_raises_not_found() -> None:
    store = InMemoryAccountStore()
    acc = store.create(user_id="daisy", config=_cfg(), now=NOW)
    with pytest.raises(AccountNotFoundError):
        store.reset(acc.account_id, user_id="mallory", now=LATER)


def test_reset_missing_account_raises_not_found() -> None:
    with pytest.raises(AccountNotFoundError):
        InMemoryAccountStore().reset("nope", user_id="daisy", now=NOW)


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_soft_deletes_preserving_row() -> None:
    store = InMemoryAccountStore()
    acc = store.create(user_id="daisy", config=_cfg(), now=NOW)
    deleted = store.delete(acc.account_id, user_id="daisy", now=LATER)
    assert deleted.is_active is False
    # Row still accessible via active_only=False list
    assert len(store.list(user_id="daisy", active_only=False)) == 1


def test_delete_foreign_user_raises() -> None:
    store = InMemoryAccountStore()
    acc = store.create(user_id="daisy", config=_cfg(), now=NOW)
    with pytest.raises(AccountNotFoundError):
        store.delete(acc.account_id, user_id="mallory", now=LATER)


# ---------------------------------------------------------------------------
# display_name
# ---------------------------------------------------------------------------


def test_display_name_defaults_to_prefix() -> None:
    store = InMemoryAccountStore()
    acc = store.create(user_id="daisy", config=_cfg(), now=NOW)
    assert acc.display_name.startswith("Paper Account ")


def test_display_name_uses_config_override() -> None:
    store = InMemoryAccountStore()
    acc = store.create(
        user_id="daisy", config=_cfg(display_name="My Test Book"), now=NOW
    )
    assert acc.display_name == "My Test Book"


# ---------------------------------------------------------------------------
# Frozen dataclass identity
# ---------------------------------------------------------------------------


def test_paper_account_is_frozen() -> None:
    store = InMemoryAccountStore()
    acc = store.create(user_id="daisy", config=_cfg(), now=NOW)
    with pytest.raises(Exception):
        acc.cash_balance = Decimal("0")  # type: ignore[misc]


def test_account_config_is_frozen() -> None:
    cfg = _cfg()
    with pytest.raises(Exception):
        cfg.starting_cash = Decimal("0")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# R7.11 — cross-account isolation is load-bearing
# ---------------------------------------------------------------------------


def test_r711_user_scope_prevents_reset_hijack() -> None:
    """Prove the user_id check in reset is load-bearing.

    If reset ignored user_id, mallory could reset daisy's account.
    Verifies AccountNotFoundError raises AND daisy's cash is unchanged.
    """
    store = InMemoryAccountStore()
    acc = store.create(
        user_id="daisy", config=_cfg(starting_cash=Decimal("100")), now=NOW
    )
    store._accounts[acc.account_id] = _spend_cash(
        store._accounts[acc.account_id], Decimal("40")
    )
    balance_before = store.get(acc.account_id, user_id="daisy").cash_balance
    with pytest.raises(AccountNotFoundError):
        store.reset(acc.account_id, user_id="mallory", now=LATER)
    balance_after = store.get(acc.account_id, user_id="daisy").cash_balance
    assert balance_before == balance_after, "reset must have been a no-op"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _spend_cash(acc: PaperAccount, amount: Decimal) -> PaperAccount:
    """Test-only helper: build a new PaperAccount with reduced cash.

    Production code would do this via the fill engine (#563); the tests
    reach in via dataclasses.replace to simulate a drawn-down state.
    """
    from dataclasses import replace

    return replace(acc, cash_balance=acc.cash_balance - amount)
