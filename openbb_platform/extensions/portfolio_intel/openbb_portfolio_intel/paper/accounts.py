"""Paper trading account model + CRUD (#562).

PRD §16.5 — paper account management API. Ships the frozen data model +
an in-memory ``AccountStore`` implementing the five documented CRUD
operations (create, list, get, reset, delete). MySQL persistence layered
on later via a subclass of the same interface — this cut is store-agnostic
so the fill engine (#563) + ledger (#545) can build against the API from
day one.

## Design decisions

1. **Two data classes.** ``AccountConfig`` is the create-time input
   (immutable knobs: starting_cash, currency, margin, commission,
   slippage). ``PaperAccount`` is the persisted record (adds account_id,
   user_id, mutable cash_balance, timestamps, is_active).

2. **Store interface, not global singleton.** Callers pass an
   ``AccountStore`` instance so tests hit an isolated store per
   fixture. In-memory implementation is ``InMemoryAccountStore``;
   a MySQL implementation lives in a follow-up (backed by the schema
   at ``portfolio_app/migrations/001_paper_trading.sql``).

3. **user_id is load-bearing.** Every operation is scoped by user_id.
   ``get(account_id, *, user_id)`` returns None if the account belongs
   to a different user (never raise-on-access, that's an info leak).
   This is the seed of the cross-account isolation guarantee (#546).

4. **``reset`` zeroes cash + drops positions.** Preserves the account
   row (same account_id, same config); mimics broker "reset to starting
   cash" semantics. Downstream fill / ledger stores need matching reset
   hooks; this cut only handles the account row.

5. **All monetary quantities are ``Decimal``.** Matches the SQL schema
   (DECIMAL(18, 4)) and the cost-basis math in #548.

6. **``updated_at`` / ``created_at`` are passed in explicitly** (not
   ``datetime.now()``). Deterministic + testable, matches the pattern
   from #543's ``today`` parameter.

## Out of scope (documented, deferred)

- **MySQL binding** — a follow-up wires ``portfolio_app/db/paper_pool.py``
  to a MySQL implementation of ``AccountStore``.
- **Deposit / withdraw**  — real cash movements are ledger entries
  (#545 owns paper_ledger), not account-level operations. This cut
  only supports the reset-to-starting-cash operation.
- **Multi-currency accounts** — ``currency`` is stored per-account but
  no FX conversion happens here. A follow-up covers multi-currency
  book valuation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from threading import Lock
from typing import Protocol
from uuid import uuid4

# Commission models supported at account create. String-typed so a
# follow-up can add new models without touching the paper_accounts
# schema.
SUPPORTED_COMMISSION_MODELS: tuple[str, ...] = (
    "zero",
    "per_share",
    "per_trade",
    "tiered",
)


@dataclass(frozen=True)
class AccountConfig:
    """Immutable knobs set at account creation time.

    All monetary quantities are Decimal to match the SQL schema.
    """

    starting_cash: Decimal
    currency: str = "USD"
    margin_enabled: bool = False
    commission_model: str = "zero"
    slippage_bps: int = 5
    display_name: str | None = None


@dataclass(frozen=True)
class PaperAccount:
    """One paper account — persisted record.

    Frozen: mutations go through :meth:`AccountStore.reset` which
    returns a new PaperAccount, matching the immutability convention
    used throughout portfolio_intel.
    """

    account_id: str
    user_id: str
    config: AccountConfig
    cash_balance: Decimal
    created_at: datetime
    updated_at: datetime
    is_active: bool = True

    @property
    def display_name(self) -> str:
        """Return the human-readable name (falls back to a truncated account_id)."""
        return self.config.display_name or f"Paper Account {self.account_id[:8]}"


# ---------------------------------------------------------------------------
# Store protocol
# ---------------------------------------------------------------------------


class AccountStore(Protocol):
    """Storage-agnostic CRUD interface (PRD §16.5).

    ``user_id`` is REQUIRED on every operation — this is the seed of
    the cross-account isolation guarantee (#546). Operations that
    reference an account belonging to a different user return None
    or raise, never leak.
    """

    def create(
        self,
        *,
        user_id: str,
        config: AccountConfig,
        now: datetime,
        account_id: str | None = None,
    ) -> PaperAccount:
        """Create a new account. Returns the persisted record."""

    def get(self, account_id: str, *, user_id: str) -> PaperAccount | None:
        """Return the account IF it belongs to ``user_id``, else None."""

    def list(self, *, user_id: str, active_only: bool = True) -> list[PaperAccount]:
        """Return all accounts owned by ``user_id``."""

    def reset(self, account_id: str, *, user_id: str, now: datetime) -> PaperAccount:
        """Zero cash back to starting_cash + bump updated_at.

        Raises :class:`AccountNotFoundError` if not owned by ``user_id``.
        The fill engine (#563) + ledger (#545) subscribe to the store
        so they can drop positions / clear journal on reset — that
        wiring lives in the follow-up router.
        """

    def delete(self, account_id: str, *, user_id: str, now: datetime) -> PaperAccount:
        """Soft-delete (is_active=False). Preserves history for audit.

        Raises :class:`AccountNotFoundError` if not owned by ``user_id``.
        """

    def update_cash(
        self,
        account_id: str,
        new_cash: Decimal,
        *,
        user_id: str,
        now: datetime,
    ) -> PaperAccount:
        """Set cash_balance to ``new_cash`` under the store's own lock.

        DEPRECATED for external callers — kept for the transition. Prefer
        :meth:`apply_cash_delta` for atomic buy/sell posting; a lost
        update between an unlocked read and a locked write here would
        silently overwrite concurrent activity. Implementations MUST
        still enforce user_id ownership.
        """

    def apply_cash_delta(
        self,
        account_id: str,
        delta: Decimal,
        *,
        user_id: str,
        now: datetime,
        min_balance: Decimal | None = None,
    ) -> PaperAccount:
        """Atomically add ``delta`` (signed) to cash_balance under a per-store lock.

        This is the load-bearing primitive for the fill engine (#563 →
        #547 hardening). All of (load current, sufficiency check,
        arithmetic, write) happen in one critical section so concurrent
        submit_orders cannot race the cash balance below the floor.

        Parameters
        ----------
        account_id, user_id
            Ownership pair; foreign users raise ``AccountNotFoundError``.
        delta
            Signed cash delta. Negative on buys, positive on sells /
            dividends / deposits.
        min_balance
            Optional floor. If the post-delta balance would fall below
            ``min_balance``, raise ``AccountConfigError`` and DO NOT
            apply the delta. Fill engine passes ``Decimal(0)`` on
            non-margin accounts for the cash-check.
        """


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AccountNotFoundError(LookupError):
    """Raised by mutating ops when the account is missing or foreign-owned."""


class AccountConfigError(ValueError):
    """Raised when ``AccountConfig`` violates a validation rule."""


# ---------------------------------------------------------------------------
# Config validation (called by create)
# ---------------------------------------------------------------------------


def _validate_config(config: AccountConfig) -> None:
    if config.starting_cash < 0:
        raise AccountConfigError(f"starting_cash={config.starting_cash} must be >= 0")
    if not config.currency or len(config.currency) != 3:
        raise AccountConfigError(
            f"currency={config.currency!r} must be a 3-letter ISO code"
        )
    if config.commission_model not in SUPPORTED_COMMISSION_MODELS:
        raise AccountConfigError(
            f"commission_model={config.commission_model!r} not in "
            f"{SUPPORTED_COMMISSION_MODELS}"
        )
    if config.slippage_bps < 0:
        raise AccountConfigError(f"slippage_bps={config.slippage_bps} must be >= 0")


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------


@dataclass
class InMemoryAccountStore:
    """Non-persistent AccountStore. Fine for unit tests + demo scaffolds.

    A MySQL-backed implementation lives in a follow-up, wired to
    ``portfolio_app/migrations/001_paper_trading.sql``.

    Concurrency: all mutations happen under ``self._lock``. Callers
    can share one store instance across threads safely; the lock
    serializes create/reset/delete/update_cash/apply_cash_delta.
    """

    _accounts: dict[str, PaperAccount] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def create(
        self,
        *,
        user_id: str,
        config: AccountConfig,
        now: datetime,
        account_id: str | None = None,
    ) -> PaperAccount:
        """Create a new account (auto-generate account_id if not supplied)."""
        if not user_id:
            raise AccountConfigError("user_id is required")
        _validate_config(config)
        aid = account_id or f"acc_{uuid4().hex[:16]}"
        if aid in self._accounts:
            raise AccountConfigError(
                f"account_id {aid!r} already exists; caller supplied a duplicate"
            )
        account = PaperAccount(
            account_id=aid,
            user_id=user_id,
            config=config,
            cash_balance=config.starting_cash,
            created_at=now,
            updated_at=now,
            is_active=True,
        )
        self._accounts[aid] = account
        return account

    def get(self, account_id: str, *, user_id: str) -> PaperAccount | None:
        """Return the account if it belongs to ``user_id``, else None (no info leak)."""
        acc = self._accounts.get(account_id)
        if acc is None or acc.user_id != user_id:
            # Foreign-owned accounts return None — never raise (info leak).
            return None
        return acc

    def list(self, *, user_id: str, active_only: bool = True) -> list[PaperAccount]:
        """Return all accounts owned by ``user_id``, sorted by created_at."""
        return sorted(
            (
                acc
                for acc in self._accounts.values()
                if acc.user_id == user_id and (not active_only or acc.is_active)
            ),
            key=lambda a: a.created_at,
        )

    def reset(self, account_id: str, *, user_id: str, now: datetime) -> PaperAccount:
        """Zero cash back to starting_cash + bump updated_at."""
        acc = self.get(account_id, user_id=user_id)
        if acc is None:
            raise AccountNotFoundError(
                f"account {account_id!r} not found for user {user_id!r}"
            )
        reset_acc = replace(
            acc,
            cash_balance=acc.config.starting_cash,
            updated_at=now,
        )
        self._accounts[account_id] = reset_acc
        return reset_acc

    def delete(self, account_id: str, *, user_id: str, now: datetime) -> PaperAccount:
        """Soft-delete (is_active=False); preserves history for audit."""
        acc = self.get(account_id, user_id=user_id)
        if acc is None:
            raise AccountNotFoundError(
                f"account {account_id!r} not found for user {user_id!r}"
            )
        deleted_acc = replace(acc, is_active=False, updated_at=now)
        self._accounts[account_id] = deleted_acc
        return deleted_acc

    def update_cash(
        self,
        account_id: str,
        new_cash: Decimal,
        *,
        user_id: str,
        now: datetime,
    ) -> PaperAccount:
        """Set cash_balance under the store's lock + ownership check.

        Kept for the transition; prefer apply_cash_delta for atomic
        buy/sell posting (which combines the check + arithmetic under
        one lock so concurrent submit_orders cannot race the balance).
        """
        with self._lock:
            acc = self._accounts.get(account_id)
            if acc is None or acc.user_id != user_id:
                raise AccountNotFoundError(
                    f"account {account_id!r} not found for user {user_id!r}"
                )
            updated = replace(acc, cash_balance=new_cash, updated_at=now)
            self._accounts[account_id] = updated
            return updated

    def apply_cash_delta(
        self,
        account_id: str,
        delta: Decimal,
        *,
        user_id: str,
        now: datetime,
        min_balance: Decimal | None = None,
    ) -> PaperAccount:
        """Atomic (load + check + write) cash-balance mutation.

        Load → optional floor check → apply delta → write, all under
        ``self._lock`` so concurrent submit_orders cannot race the
        cash balance below the floor.
        """
        with self._lock:
            acc = self._accounts.get(account_id)
            if acc is None or acc.user_id != user_id:
                raise AccountNotFoundError(
                    f"account {account_id!r} not found for user {user_id!r}"
                )
            new_cash = acc.cash_balance + delta
            if min_balance is not None and new_cash < min_balance:
                raise AccountConfigError(
                    f"cash delta {delta} would drive {account_id!r} balance "
                    f"to {new_cash}, below min_balance={min_balance}"
                )
            updated = replace(acc, cash_balance=new_cash, updated_at=now)
            self._accounts[account_id] = updated
            return updated
