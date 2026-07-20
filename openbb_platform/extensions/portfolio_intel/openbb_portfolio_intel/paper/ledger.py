"""Paper ledger — append-only journal + replay (#545).

PRD §16.3 + §16.7. The ledger is the **source of truth** for a paper
account's history: every state change is materialized as one immutable
row. State (cash balance, positions) is DERIVED from the ledger via
:func:`replay` — this satisfies PRD §16.7's replay contract:

    live_state == replay(ledger_entries_in_order)

So auditing / debugging / regulatory review only needs the ledger.

## Entry types (PRD §16.3)

- ``trade``      — a buy/sell fill (from #563 / #544). Modifies cash + position.
- ``dividend``   — cash dividend credit. Increases cash.
- ``split``      — stock split. Ratio-adjusts quantity + avg_cost.
- ``fee``        — miscellaneous fee. Decreases cash.
- ``deposit``    — external cash added to the account. Increases cash.
- ``withdraw``   — external cash removed. Decreases cash.

## Public API (openbb_portfolio_intel.paper)

- ``LedgerEntry``       — one row, frozen
- ``LedgerEntryType``   — enum of the six types above
- ``LedgerStore``       — Protocol (append / list_for_account)
- ``InMemoryLedgerStore`` — concrete implementation
- ``AccountState``      — replay result: (cash, positions[dict[str, Lot]])
- ``replay(entries)``   — deterministic reconstruction from ordered entries

## Ordering

Entries carry ``occurred_at`` (real time) and ``sequence`` (monotonic
int per account). ``replay`` processes in ``(occurred_at, sequence)``
order; ``sequence`` is the tiebreak for same-timestamp entries (a market
buy and its dividend record on the same instant).

## Isolation

Every entry carries ``account_id`` + ``user_id``. ``list_for_account``
takes user_id and returns only that user's entries — mirror of the
#562 / #563 isolation posture (#546 seed).

## Deferred

- **MySQL binding** — paper_ledger table already drafted in
  ``portfolio_app/migrations/001_paper_trading.sql``. A follow-up
  swaps ``InMemoryLedgerStore`` → MySQL-backed impl.
- **Corporate-action complexity** — this cut handles simple ratio
  splits and cash dividends. Spin-offs, mergers, and rights offerings
  land in a follow-up along with symbol renaming rules.
"""

from __future__ import annotations

# pylint: disable=too-many-arguments,too-many-positional-arguments  # entry constructors need every field

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from threading import Lock
from typing import Protocol
from uuid import uuid4

from openbb_portfolio_intel.paper.cost_basis import (
    FillEvent,
    Lot,
    apply_fill,
)


class LedgerEntryType(str, Enum):
    """PRD §16.3 six entry types."""

    TRADE = "trade"
    DIVIDEND = "dividend"
    SPLIT = "split"
    FEE = "fee"
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"


@dataclass(frozen=True)
class LedgerEntry:
    """One immutable journal row.

    Every state change is materialized as a LedgerEntry. Never mutate,
    never delete — the invariant that ``replay(entries) == live_state``
    depends on the ledger being append-only.

    Fields have entry-type-specific meanings:

    - ``TRADE``: ``symbol`` = ticker, ``quantity`` = signed fill qty
      (positive=buy, negative=sell), ``price`` = fill price,
      ``amount`` = cash delta (negative on buy, positive on sell),
      ``commission`` = commission paid.
    - ``DIVIDEND``: ``symbol`` = ticker paying the dividend,
      ``amount`` = cash credit (positive), ``quantity`` unused.
    - ``SPLIT``: ``symbol`` = ticker, ``quantity`` = ratio (e.g. 2 for
      a 2:1 forward split — held qty MULTIPLIED by this), ``amount`` = 0
      (splits are cashless).
    - ``FEE``: ``amount`` = negative cash delta (fee is a debit),
      ``symbol`` optional.
    - ``DEPOSIT`` / ``WITHDRAW``: ``amount`` = signed cash delta
      (positive for deposit, negative for withdraw), ``symbol`` unused.
    """

    entry_id: str
    account_id: str
    user_id: str
    entry_type: LedgerEntryType
    sequence: int
    occurred_at: datetime
    amount: Decimal  # signed cash delta (0 for splits)
    symbol: str = ""
    quantity: Decimal = Decimal("0")  # signed for trades, ratio for splits
    price: Decimal = Decimal("0")  # for trades only
    commission: Decimal = Decimal("0")  # for trades only
    notes: str = ""


class LedgerError(ValueError):
    """Raised on malformed ledger entries or replay conflicts."""


# ---------------------------------------------------------------------------
# Store protocol
# ---------------------------------------------------------------------------


class LedgerStore(Protocol):
    """Storage-agnostic ledger interface.

    ``user_id`` required on every read — matches #562 / #563 isolation
    posture. ``append`` is idempotent on ``entry_id`` (retry-safe).
    """

    def append(self, entry: LedgerEntry) -> None:
        """Add one entry to the journal. Duplicate entry_id is a no-op."""

    def list_for_account(self, account_id: str, *, user_id: str) -> list[LedgerEntry]:
        """Return all entries for (user_id, account_id), sorted by (occurred_at, sequence)."""


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------


@dataclass
class InMemoryLedgerStore:
    """Non-persistent LedgerStore. Fine for unit tests + demo.

    Cross-account isolation: keyed on (user_id, account_id). Foreign
    users querying an account they don't own get an empty list (never
    see another user's entries).
    """

    _entries: dict[tuple[str, str], list[LedgerEntry]] = field(default_factory=dict)
    # Per-tenant idempotency: (user_id, account_id) → set of seen entry_ids.
    # Scoping the dedup by tenant prevents cross-tenant collision, matches
    # the isolation posture of _entries, and preserves retry-safety within
    # a single account.
    _seen_ids: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def append(self, entry: LedgerEntry) -> None:
        """Idempotent append. Duplicate entry_id (per tenant) is silently ignored."""
        if not entry.entry_id:
            raise LedgerError("entry_id must be non-empty")
        with self._lock:
            key = (entry.user_id, entry.account_id)
            seen = self._seen_ids.setdefault(key, set())
            if entry.entry_id in seen:
                return
            seen.add(entry.entry_id)
            bucket = self._entries.setdefault(key, [])
            bucket.append(entry)

    def list_for_account(self, account_id: str, *, user_id: str) -> list[LedgerEntry]:
        """Return sorted entries for (user_id, account_id) or empty list."""
        with self._lock:
            bucket = self._entries.get((user_id, account_id), [])
            return sorted(bucket, key=lambda e: (e.occurred_at, e.sequence))


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccountState:
    """Reconstructed state after replaying a ledger.

    - ``cash`` — final cash balance
    - ``positions`` — final ``{symbol: Lot}`` map, EXCLUDING flat lots
    - ``entries_replayed`` — count of ledger rows consumed

    Immutable snapshot; a fresh replay creates a new AccountState.
    """

    cash: Decimal
    positions: dict[str, Lot]
    entries_replayed: int


def replay(
    entries: list[LedgerEntry], *, starting_cash: Decimal = Decimal("0")
) -> AccountState:
    """Reconstruct AccountState from a chronologically-ordered ledger.

    Deterministic — same entries + same starting_cash → identical
    AccountState. This is the load-bearing PRD §16.7 replay contract:
    ``replay(ledger_for_account) == live_state`` at all times.

    Parameters
    ----------
    entries
        Entries in canonical order. Callers usually pass
        ``store.list_for_account(...)`` which already sorts by
        ``(occurred_at, sequence)``.
    starting_cash
        The account's ``config.starting_cash`` from #562. Ledger
        deposits/withdrawals fold on top of this.

    Returns
    -------
    AccountState
        Snapshot with final cash + non-flat positions.

    Raises
    ------
    LedgerError
        If any entry is malformed (unknown type, negative price on a
        trade, ratio == 0 on a split, etc.).
    """
    cash = starting_cash
    lots: dict[str, Lot] = {}

    for entry in entries:
        if entry.entry_type is LedgerEntryType.TRADE:
            cash, lots = _apply_trade(entry, cash, lots)
        elif entry.entry_type is LedgerEntryType.DIVIDEND:
            _validate_positive(entry, "dividend amount")
            cash += entry.amount
        elif entry.entry_type is LedgerEntryType.SPLIT:
            lots = _apply_split(entry, lots)
        elif entry.entry_type is LedgerEntryType.FEE:
            _validate_negative(entry, "fee amount")
            cash += entry.amount
        elif entry.entry_type is LedgerEntryType.DEPOSIT:
            _validate_positive(entry, "deposit amount")
            cash += entry.amount
        elif entry.entry_type is LedgerEntryType.WITHDRAW:
            _validate_negative(entry, "withdraw amount")
            cash += entry.amount
        else:
            raise LedgerError(
                f"unknown entry_type {entry.entry_type} on {entry.entry_id}"
            )

    # Drop flat lots for a compact snapshot
    positions = {sym: lot for sym, lot in lots.items() if lot.qty != 0}
    return AccountState(cash=cash, positions=positions, entries_replayed=len(entries))


# ---------------------------------------------------------------------------
# Internal replay helpers
# ---------------------------------------------------------------------------


def _apply_trade(
    entry: LedgerEntry, cash: Decimal, lots: dict[str, Lot]
) -> tuple[Decimal, dict[str, Lot]]:
    """Apply one TRADE entry via #548 apply_fill. Returns new (cash, lots)."""
    if not entry.symbol:
        raise LedgerError(f"trade entry {entry.entry_id} missing symbol")
    if entry.quantity == 0:
        raise LedgerError(f"trade entry {entry.entry_id} has zero quantity")
    if not entry.price.is_finite() or entry.price < 0:
        raise LedgerError(
            f"trade entry {entry.entry_id} has invalid price {entry.price}"
        )
    lot = lots.get(
        entry.symbol,
        Lot(
            symbol=entry.symbol,
            qty=Decimal("0"),
            avg_cost=Decimal("0"),
            realized_pnl=Decimal("0"),
        ),
    )
    fill = FillEvent(
        symbol=entry.symbol,
        qty=entry.quantity,
        price=entry.price,
        commission=entry.commission,
    )
    new_lot, _ = apply_fill(lot, fill)
    # Cash delta stored on the entry — replay trusts the ledger; the
    # fill engine (#563) is responsible for writing consistent
    # (amount, quantity*price + commission) rows.
    new_lots = {**lots, entry.symbol: new_lot}
    return cash + entry.amount, new_lots


def _apply_split(entry: LedgerEntry, lots: dict[str, Lot]) -> dict[str, Lot]:
    """Ratio-adjust a lot on a split.

    For a 2:1 forward split, ``entry.quantity = 2`` — held qty doubles,
    avg_cost halves.  For a 1:2 reverse split, ``entry.quantity = 0.5``.
    """
    if not entry.symbol:
        raise LedgerError(f"split entry {entry.entry_id} missing symbol")
    if entry.quantity <= 0:
        raise LedgerError(
            f"split entry {entry.entry_id} has non-positive ratio {entry.quantity}"
        )
    lot = lots.get(entry.symbol)
    if lot is None or lot.qty == 0:
        # Split on a position we don't hold — no-op (paper trade may have
        # closed the position before the corporate action landed)
        return lots
    ratio = entry.quantity
    new_lot = Lot(
        symbol=lot.symbol,
        qty=lot.qty * ratio,
        avg_cost=lot.avg_cost / ratio,
        realized_pnl=lot.realized_pnl,
    )
    return {**lots, entry.symbol: new_lot}


def _validate_positive(entry: LedgerEntry, label: str) -> None:
    if not entry.amount.is_finite():
        raise LedgerError(f"{label} {entry.amount} on {entry.entry_id} not finite")
    if entry.amount <= 0:
        raise LedgerError(
            f"{label} {entry.amount} on {entry.entry_id} must be positive"
        )


def _validate_negative(entry: LedgerEntry, label: str) -> None:
    if not entry.amount.is_finite():
        raise LedgerError(f"{label} {entry.amount} on {entry.entry_id} not finite")
    if entry.amount >= 0:
        raise LedgerError(
            f"{label} {entry.amount} on {entry.entry_id} must be negative"
        )


# ---------------------------------------------------------------------------
# Convenience constructors — matches the shape router / fill-engine writes
# ---------------------------------------------------------------------------


def trade_entry(
    *,
    account_id: str,
    user_id: str,
    sequence: int,
    occurred_at: datetime,
    symbol: str,
    quantity: Decimal,  # signed
    price: Decimal,
    commission: Decimal = Decimal("0"),
    entry_id: str | None = None,
    notes: str = "",
) -> LedgerEntry:
    """Build a TRADE entry with correct amount = -(quantity * price + commission)."""
    amount = -(quantity * price + commission)
    return LedgerEntry(
        entry_id=entry_id or f"ent_{uuid4().hex[:16]}",
        account_id=account_id,
        user_id=user_id,
        entry_type=LedgerEntryType.TRADE,
        sequence=sequence,
        occurred_at=occurred_at,
        amount=amount,
        symbol=symbol,
        quantity=quantity,
        price=price,
        commission=commission,
        notes=notes,
    )


def deposit_entry(
    *,
    account_id: str,
    user_id: str,
    sequence: int,
    occurred_at: datetime,
    amount: Decimal,
    entry_id: str | None = None,
    notes: str = "",
) -> LedgerEntry:
    """Build a DEPOSIT entry."""
    return LedgerEntry(
        entry_id=entry_id or f"ent_{uuid4().hex[:16]}",
        account_id=account_id,
        user_id=user_id,
        entry_type=LedgerEntryType.DEPOSIT,
        sequence=sequence,
        occurred_at=occurred_at,
        amount=amount,
        notes=notes,
    )


def withdraw_entry(
    *,
    account_id: str,
    user_id: str,
    sequence: int,
    occurred_at: datetime,
    amount: Decimal,  # positive input; stored as negative
    entry_id: str | None = None,
    notes: str = "",
) -> LedgerEntry:
    """Build a WITHDRAW entry (caller passes positive; stored as negative amount)."""
    if amount <= 0:
        raise LedgerError(
            f"withdraw amount must be positive at construction; got {amount}"
        )
    return LedgerEntry(
        entry_id=entry_id or f"ent_{uuid4().hex[:16]}",
        account_id=account_id,
        user_id=user_id,
        entry_type=LedgerEntryType.WITHDRAW,
        sequence=sequence,
        occurred_at=occurred_at,
        amount=-amount,
        notes=notes,
    )


def dividend_entry(
    *,
    account_id: str,
    user_id: str,
    sequence: int,
    occurred_at: datetime,
    symbol: str,
    amount: Decimal,  # positive cash credit
    entry_id: str | None = None,
    notes: str = "",
) -> LedgerEntry:
    """Build a DIVIDEND entry."""
    return LedgerEntry(
        entry_id=entry_id or f"ent_{uuid4().hex[:16]}",
        account_id=account_id,
        user_id=user_id,
        entry_type=LedgerEntryType.DIVIDEND,
        sequence=sequence,
        occurred_at=occurred_at,
        amount=amount,
        symbol=symbol,
        notes=notes,
    )


def split_entry(
    *,
    account_id: str,
    user_id: str,
    sequence: int,
    occurred_at: datetime,
    symbol: str,
    ratio: Decimal,  # e.g. 2 for 2:1 forward, 0.5 for 1:2 reverse
    entry_id: str | None = None,
    notes: str = "",
) -> LedgerEntry:
    """Build a SPLIT entry (ratio stored in `quantity`; amount=0)."""
    return LedgerEntry(
        entry_id=entry_id or f"ent_{uuid4().hex[:16]}",
        account_id=account_id,
        user_id=user_id,
        entry_type=LedgerEntryType.SPLIT,
        sequence=sequence,
        occurred_at=occurred_at,
        amount=Decimal("0"),
        symbol=symbol,
        quantity=ratio,
        notes=notes,
    )


def fee_entry(
    *,
    account_id: str,
    user_id: str,
    sequence: int,
    occurred_at: datetime,
    amount: Decimal,  # positive input; stored as negative
    symbol: str = "",
    entry_id: str | None = None,
    notes: str = "",
) -> LedgerEntry:
    """Build a FEE entry (caller passes positive; stored as negative amount)."""
    if amount <= 0:
        raise LedgerError(f"fee amount must be positive at construction; got {amount}")
    return LedgerEntry(
        entry_id=entry_id or f"ent_{uuid4().hex[:16]}",
        account_id=account_id,
        user_id=user_id,
        entry_type=LedgerEntryType.FEE,
        sequence=sequence,
        occurred_at=occurred_at,
        amount=-amount,
        symbol=symbol,
        notes=notes,
    )
