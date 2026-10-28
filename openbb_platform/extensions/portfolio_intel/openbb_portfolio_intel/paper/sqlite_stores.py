"""Durable SQLite paper stores (#2333).

``SqliteAccountStore``, ``SqlitePositionStore`` and ``SqliteLedgerStore``
implement the same ``AccountStore``, ``PositionStore`` and ``LedgerStore``
protocols as the in-memory stores, with the same ownership rules: a foreign
``user_id`` reads ``None`` (or a flat lot, or no entries) and mutations on a
foreign account raise ``AccountNotFoundError``. Decimals
are stored as exact strings. ``apply_cash_delta`` checks the floor and writes
inside one ``BEGIN IMMEDIATE`` transaction, so concurrent fills cannot race
the balance below it, across threads or processes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from openbb_portfolio_intel.paper.accounts import (
    AccountConfig,
    AccountConfigError,
    AccountNotFoundError,
    PaperAccount,
    _validate_config,
)
from openbb_portfolio_intel.paper.cost_basis import Lot
from openbb_portfolio_intel.paper.ledger import (
    LedgerEntry,
    LedgerEntryType,
    LedgerError,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_accounts (
    account_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    config TEXT NOT NULL,
    cash_balance TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_active INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_positions (
    user_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    qty TEXT NOT NULL,
    avg_cost TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    PRIMARY KEY (user_id, account_id, symbol)
);
CREATE TABLE IF NOT EXISTS paper_ledger (
    user_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    occurred_at TEXT NOT NULL,
    amount TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quantity TEXT NOT NULL,
    price TEXT NOT NULL,
    commission TEXT NOT NULL,
    notes TEXT NOT NULL,
    PRIMARY KEY (user_id, account_id, entry_id)
);
"""


class _SqliteStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._ready = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if not self._ready:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, isolation_level=None, timeout=30)
        connection.row_factory = sqlite3.Row
        if not self._ready:
            connection.executescript(_SCHEMA)
            self._ready = True
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise


def _config_to_json(config: AccountConfig) -> str:
    data = asdict(config)
    data["starting_cash"] = str(config.starting_cash)
    return json.dumps(data, sort_keys=True)


def _config_from_json(text: str) -> AccountConfig:
    data = json.loads(text)
    data["starting_cash"] = Decimal(data["starting_cash"])
    return AccountConfig(**data)


def _account(row: sqlite3.Row) -> PaperAccount:
    return PaperAccount(
        account_id=row["account_id"],
        user_id=row["user_id"],
        config=_config_from_json(row["config"]),
        cash_balance=Decimal(row["cash_balance"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        is_active=bool(row["is_active"]),
    )


class SqliteAccountStore(_SqliteStore):
    """``AccountStore`` backed by one SQLite file."""

    def _write(self, connection: sqlite3.Connection, account: PaperAccount) -> None:
        connection.execute(
            "UPDATE paper_accounts SET cash_balance = ?, updated_at = ?,"
            " is_active = ? WHERE account_id = ?",
            (
                str(account.cash_balance),
                account.updated_at.isoformat(),
                int(account.is_active),
                account.account_id,
            ),
        )

    @staticmethod
    def _owned(
        connection: sqlite3.Connection, account_id: str, user_id: str
    ) -> PaperAccount | None:
        row = connection.execute(
            "SELECT * FROM paper_accounts WHERE account_id = ? AND user_id = ?",
            (account_id, user_id),
        ).fetchone()
        return _account(row) if row else None

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
        account = PaperAccount(
            account_id=aid,
            user_id=user_id,
            config=config,
            cash_balance=config.starting_cash,
            created_at=now,
            updated_at=now,
            is_active=True,
        )
        try:
            with self._transaction() as connection:
                connection.execute(
                    "INSERT INTO paper_accounts VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        aid,
                        user_id,
                        _config_to_json(config),
                        str(config.starting_cash),
                        now.isoformat(),
                        now.isoformat(),
                        1,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise AccountConfigError(
                f"account_id {aid!r} already exists; caller supplied a duplicate"
            ) from error
        return account

    def get(self, account_id: str, *, user_id: str) -> PaperAccount | None:
        """Return the account if it belongs to ``user_id``, else None (no info leak)."""
        with self._connect() as connection:
            return self._owned(connection, account_id, user_id)

    def list(self, *, user_id: str, active_only: bool = True) -> list[PaperAccount]:
        """Return all accounts owned by ``user_id``, sorted by created_at."""
        query = "SELECT * FROM paper_accounts WHERE user_id = ?"
        if active_only:
            query += " AND is_active = 1"
        with self._connect() as connection:
            rows = connection.execute(query + " ORDER BY created_at", (user_id,))
            return [_account(row) for row in rows.fetchall()]

    def _mutate(self, account_id: str, user_id: str, change) -> PaperAccount:
        with self._transaction() as connection:
            account = self._owned(connection, account_id, user_id)
            if account is None:
                raise AccountNotFoundError(
                    f"account {account_id!r} not found for user {user_id!r}"
                )
            updated = change(account)
            self._write(connection, updated)
            return updated

    def reset(self, account_id: str, *, user_id: str, now: datetime) -> PaperAccount:
        """Zero cash back to starting_cash + bump updated_at."""
        return self._mutate(
            account_id,
            user_id,
            lambda a: replace(a, cash_balance=a.config.starting_cash, updated_at=now),
        )

    def delete(self, account_id: str, *, user_id: str, now: datetime) -> PaperAccount:
        """Deactivate the account, keeping its row for audit."""
        return self._mutate(
            account_id,
            user_id,
            lambda a: replace(a, is_active=False, updated_at=now),
        )

    def update_cash(
        self,
        account_id: str,
        new_cash: Decimal,
        *,
        user_id: str,
        now: datetime,
    ) -> PaperAccount:
        """Set cash_balance under the store's lock + ownership check."""
        return self._mutate(
            account_id,
            user_id,
            lambda a: replace(a, cash_balance=new_cash, updated_at=now),
        )

    def apply_cash_delta(
        self,
        account_id: str,
        delta: Decimal,
        *,
        user_id: str,
        now: datetime,
        min_balance: Decimal | None = None,
    ) -> PaperAccount:
        """Atomic (load + check + write) cash-balance mutation."""

        def change(account: PaperAccount) -> PaperAccount:
            new_cash = account.cash_balance + delta
            if min_balance is not None and new_cash < min_balance:
                raise AccountConfigError(
                    f"cash delta {delta} would drive {account_id!r} balance "
                    f"to {new_cash}, below min_balance={min_balance}"
                )
            return replace(account, cash_balance=new_cash, updated_at=now)

        return self._mutate(account_id, user_id, change)


class SqlitePositionStore(_SqliteStore):
    """``PositionStore`` backed by one SQLite file."""

    def get(self, account_id: str, symbol: str, *, user_id: str) -> Lot:
        """Return the lot for (user_id, account_id, symbol) or a flat Lot."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM paper_positions WHERE user_id = ? AND account_id = ?"
                " AND symbol = ?",
                (user_id, account_id, symbol),
            ).fetchone()
        if row is None:
            return Lot(
                symbol=symbol,
                qty=Decimal("0"),
                avg_cost=Decimal("0"),
                realized_pnl=Decimal("0"),
            )
        return Lot(
            symbol=row["symbol"],
            qty=Decimal(row["qty"]),
            avg_cost=Decimal(row["avg_cost"]),
            realized_pnl=Decimal(row["realized_pnl"]),
        )

    def put(self, account_id: str, lot: Lot, *, user_id: str) -> None:
        """Write the lot back under (user_id, account_id, lot.symbol)."""
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO paper_positions VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (user_id, account_id, symbol) DO UPDATE SET"
                " qty = excluded.qty, avg_cost = excluded.avg_cost,"
                " realized_pnl = excluded.realized_pnl",
                (
                    user_id,
                    account_id,
                    lot.symbol,
                    str(lot.qty),
                    str(lot.avg_cost),
                    str(lot.realized_pnl),
                ),
            )

    def lots(self, account_id: str, *, user_id: str) -> list[Lot]:
        """Every non-flat lot of one account, by symbol."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT symbol FROM paper_positions WHERE user_id = ?"
                " AND account_id = ? ORDER BY symbol",
                (user_id, account_id),
            ).fetchall()
        lots = [self.get(account_id, row["symbol"], user_id=user_id) for row in rows]
        return [lot for lot in lots if lot.qty != 0 or lot.realized_pnl != 0]


def _entry(row: sqlite3.Row) -> LedgerEntry:
    return LedgerEntry(
        entry_id=row["entry_id"],
        account_id=row["account_id"],
        user_id=row["user_id"],
        entry_type=LedgerEntryType(row["entry_type"]),
        sequence=row["sequence"],
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        amount=Decimal(row["amount"]),
        symbol=row["symbol"],
        quantity=Decimal(row["quantity"]),
        price=Decimal(row["price"]),
        commission=Decimal(row["commission"]),
        notes=row["notes"],
    )


class SqliteLedgerStore(_SqliteStore):
    """``LedgerStore`` backed by one SQLite file; append-only."""

    def append(self, entry: LedgerEntry) -> None:
        """Idempotent append. Duplicate entry_id (per tenant) is silently ignored."""
        if not entry.entry_id:
            raise LedgerError("entry_id must be non-empty")
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO paper_ledger VALUES"
                " (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.user_id,
                    entry.account_id,
                    entry.entry_id,
                    entry.entry_type.value,
                    entry.sequence,
                    entry.occurred_at.isoformat(),
                    str(entry.amount),
                    entry.symbol,
                    str(entry.quantity),
                    str(entry.price),
                    str(entry.commission),
                    entry.notes,
                ),
            )

    def list_for_account(self, account_id: str, *, user_id: str) -> list[LedgerEntry]:
        """Return sorted entries for (user_id, account_id) or empty list."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM paper_ledger WHERE user_id = ? AND account_id = ?",
                (user_id, account_id),
            ).fetchall()
        # Sorted on parsed datetimes: ISO text does not order across offsets.
        return sorted(
            (_entry(row) for row in rows), key=lambda e: (e.occurred_at, e.sequence)
        )
