"""T5 P3.a — paper trading engine (event-sourced, operator-recorded fills).

Fidelity has no API, so the operator files every order manually at
Fidelity's regular order-entry UI. This module is the **shadow book**:

1. The widget calls :meth:`PaperEngine.submit_batch` with an
   :class:`OrderBatch` (from P1); the engine writes PENDING orders.
2. The operator files each order at Fidelity manually.
3. The operator (or a paste-from-Activity-CSV step, in P5) calls
   :meth:`PaperEngine.record_fill(order_id, price, filled_qty, at)`.
4. The engine debits/credits cash, updates the materialized position,
   and computes realized P&L on any closing lots via FIFO.

Nothing here auto-fills. Nothing here talks to a broker. The paper
engine is a discipline-enforced ledger — you can't record a fill for
an order that was never submitted; you can't credit cash you don't
have on a buy; a sell that exceeds position raises loudly.

Storage: SQLite at ``~/.portfolio_intel/paper.db``. Same pattern as
:class:`SqlitePortfolioStore` from #1744 — the store is user-local,
never checked in, and the schema is documented in-file (see
``_SCHEMA``).

Interface: :class:`PaperEngine` Protocol + :class:`SqlitePaperEngine`
concrete impl. Mirrors the OrderSink Protocol shape from #1719 P1.

Tax lots: FIFO for realized P&L (matches Fidelity's default). Wash-sale
tracking is out of scope for P3.a — it's a rules-engine layer that
belongs above the ledger, not inside it.

Non-goals for P3.a
------------------
- Auto-fill: no bar-by-bar broker simulator. Every fill is
  operator-recorded (or, in P5, parsed from a Fidelity Activity CSV).
- Unrealized P&L: needs a live price feed (ChainedFetcher, #1715).
  Lands in P3.b.
- Wash-sale + tax lots beyond FIFO: LIFO/HIFO/SpecificID are user-
  configurable in tax software; the paper engine's job is to expose
  the fill sequence, not to compute the operator's tax return.
- Reconciliation vs. Fidelity's real positions snapshot: lands in P3.c
  once P3.a + P3.b are exercised.
"""

# pylint: disable=too-many-lines
# P3.b added unrealized-P&L methods + dataclasses (~120 lines). Splitting
# out feels premature — the new code closely couples to PaperPosition
# and the SqlitePaperEngine internals. Reconsider if P3.c grows the file
# past ~1500 lines.

from __future__ import annotations

import logging
import os
import re
import sqlite3
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums + data types
# ---------------------------------------------------------------------------


class OrderStatus(str, Enum):
    """Order lifecycle: pending until the operator records the outcome."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class Side(str, Enum):
    """Buy / Sell / short semantics — matches OrderTicket.action.

    Kept as a lowercase-ish enum here (not "Buy"/"Sell") so DB rows are
    stable across UI-label refactors. The mapping to Fidelity labels
    lives at the OrderTicket adapter boundary.
    """

    BUY = "BUY"
    SELL = "SELL"
    BUY_TO_COVER = "BUY_TO_COVER"
    SELL_SHORT = "SELL_SHORT"


_BUY_SIDES = frozenset({Side.BUY, Side.BUY_TO_COVER})

_ACTION_TO_SIDE: dict[str, Side] = {
    "Buy": Side.BUY,
    "Sell": Side.SELL,
    "BuyToCover": Side.BUY_TO_COVER,
    "SellShort": Side.SELL_SHORT,
}

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9./\-]{0,15}$")


class PaperEngineError(RuntimeError):
    """Loud rejection: insufficient cash, sell-more-than-position, etc.

    Never silently coerced — a paper engine that swallows a bad state
    hides the real-world bad state it's shadowing.
    """


@dataclass(frozen=True)
class PaperAccount:
    """The operator's simulated brokerage account snapshot.

    ``cash`` = free cash after all committed fills (not buying power).
    ``equity`` = cash + sum(position market value) — computed by the
    caller if they have a price feed; the ledger only tracks realized
    numbers (unrealized needs live prices, P3.b).
    """

    account_id: str
    starting_cash: Decimal
    cash: Decimal
    realized_pl: Decimal
    created_at: datetime


@dataclass(frozen=True)
class PaperOrder:
    """One PENDING/FILLED/etc. row in ``pi_paper_order``.

    Persisted immediately on ``submit_batch``. Fill events on this order
    write ``pi_paper_fill`` rows and update ``status`` (PENDING →
    PARTIAL → FILLED, or PENDING → CANCELLED / REJECTED).
    """

    order_id: str
    account_id: str
    symbol: str
    side: Side
    quantity: Decimal
    order_type: Literal["Market", "Limit", "StopLoss", "StopLimit"]
    limit_price: Decimal | None
    status: OrderStatus
    submitted_at: datetime
    plan_id: str = ""
    batch_sha256: str = ""


@dataclass(frozen=True)
class PaperFill:
    """A recorded fill against a :class:`PaperOrder`.

    Filled quantity may be less than the parent order's quantity (partial
    fills). The engine keeps summing fills until they equal the order's
    quantity, at which point status flips FILLED.
    """

    fill_id: str
    order_id: str
    symbol: str
    side: Side
    filled_qty: Decimal
    price: Decimal
    commission: Decimal
    filled_at: datetime


@dataclass(frozen=True)
class PaperPosition:
    """Materialized current position (cost basis + qty).

    Updated on every fill so widget reads don't have to replay the
    fill log. Short positions carry negative ``quantity``.
    """

    account_id: str
    symbol: str
    quantity: Decimal
    avg_cost: (
        Decimal  # positive for longs, positive for shorts (short-sale credit basis)
    )
    realized_pl: Decimal
    last_updated: datetime


@dataclass(frozen=True)
class PaperPositionMarked:
    """Position augmented with a mark price + unrealized P&L (P3.b).

    ``mark_price`` is None when the caller's pricing dict didn't cover
    this symbol; ``unrealized_pl`` and ``unrealized_pl_pct`` are also
    None in that case (loud-empty — silent zero would hide a broken
    price feed).

    Unrealized P&L formula:

    - **Long** (``quantity > 0``):
      ``unrealized_pl = quantity * (mark_price - avg_cost)``
    - **Short** (``quantity < 0``):
      ``unrealized_pl = quantity * (mark_price - avg_cost)``
      (same formula — negative quantity flips the sign automatically,
      since a short profits when mark drops below basis)
    """

    account_id: str
    symbol: str
    quantity: Decimal
    avg_cost: Decimal
    realized_pl: Decimal
    last_updated: datetime
    mark_price: Decimal | None
    mark_value: Decimal | None  # quantity * mark_price
    unrealized_pl: Decimal | None
    unrealized_pl_pct: Decimal | None


@dataclass(frozen=True)
class PaperEquity:
    """Snapshot of total account equity given a pricing dict (P3.b).

    ``equity`` = ``cash`` + ``sum(mark_value for known-marked positions)``.
    Positions with missing marks are excluded from the sum AND surfaced
    in ``symbols_missing_marks`` so the caller can't ignore them.
    """

    account_id: str
    cash: Decimal
    realized_pl: Decimal
    marked_value: Decimal
    equity: Decimal
    unrealized_pl: Decimal
    symbols_missing_marks: tuple[str, ...]


# Tax lot for FIFO realized-P&L computation — kept private, exposed to
# tests via a debug hook.
@dataclass
class _Lot:
    """One open lot: qty acquired at cost, opened at ``opened_at``."""

    qty: Decimal
    cost_basis_per_unit: Decimal
    opened_at: datetime


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class PaperEngine(Protocol):
    """Structural contract for any paper-trading backend.

    Mirrors :class:`OrderSink` from P1 — the widget code depends on
    this Protocol, not on the concrete SQLite class.
    """

    def submit_batch(self, batch, plan_id: str = "") -> list[str]:  # noqa: ANN001
        """Persist every ticket in ``batch`` as a PENDING order.

        Returns the list of assigned ``order_id`` values in submission
        order. ``batch`` is an :class:`OrderBatch` from
        :mod:`.order_sink`; the accepted-type dep is on the runtime
        duck shape (``batch.tickets``, ``batch.sha256()``, etc.) to
        keep this Protocol independent of that module.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def record_fill(  # pylint: disable=too-many-positional-arguments
        self,
        order_id: str,
        price: Decimal,
        filled_qty: Decimal,
        at: datetime,
        commission: Decimal = Decimal("0"),
    ) -> PaperFill:
        """Record a real-world fill against a PENDING/PARTIAL order.

        Raises on unknown order_id, overfill, non-positive price/qty,
        or a fill on a CANCELLED/REJECTED order.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def cancel_order(self, order_id: str, reason: str = "") -> None:
        """Cancel a PENDING order. Idempotent — a second cancel logs."""
        ...  # pylint: disable=unnecessary-ellipsis

    def get_account(self) -> PaperAccount:
        """Return the current account state (single-account for P3.a)."""
        ...  # pylint: disable=unnecessary-ellipsis

    def get_positions(self) -> list[PaperPosition]:
        """Return all non-zero materialized positions."""
        ...  # pylint: disable=unnecessary-ellipsis

    def get_orders(self, status: OrderStatus | None = None) -> list[PaperOrder]:
        """Return orders, optionally filtered by lifecycle status."""
        ...  # pylint: disable=unnecessary-ellipsis

    def get_fills(self, since: datetime | None = None) -> list[PaperFill]:
        """Return every recorded fill after ``since`` (or all if None)."""
        ...  # pylint: disable=unnecessary-ellipsis

    # -- P3.b unrealized P&L ---------------------------------------------

    def get_positions_with_unrealized(
        self, pricing: Mapping[str, Decimal]
    ) -> list[PaperPositionMarked]:
        """Return current positions augmented with mark + unrealized P&L.

        ``pricing`` maps symbol → last-close (or bid/ask midpoint, or
        whatever mark source the caller chose). Symbols we hold that are
        missing from ``pricing`` render with ``mark_price=None`` and
        ``unrealized_pl=None`` — loud-empty, never silent zero.

        Raises :class:`PaperEngineError` when a supplied mark_price is
        non-positive (misconfigured feed). A None mark price is a
        genuine "no data" state and is preserved; a zero mark is a bug.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def get_account_equity(self, pricing: Mapping[str, Decimal]) -> PaperEquity:
        """Return equity = cash + sum(mark_value for known-marked positions).

        Positions with missing marks are excluded from ``marked_value``
        but SURFACED in ``symbols_missing_marks`` — caller decides
        whether that's tolerable. Returns a :class:`PaperEquity`
        snapshot.
        """
        ...  # pylint: disable=unnecessary-ellipsis


# ---------------------------------------------------------------------------
# SqlitePaperEngine — the concrete backend.
# ---------------------------------------------------------------------------


_SCHEMA = """
CREATE TABLE IF NOT EXISTS pi_paper_account (
    account_id      TEXT PRIMARY KEY,
    starting_cash   TEXT NOT NULL,
    cash            TEXT NOT NULL,
    realized_pl     TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pi_paper_order (
    order_id        TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES pi_paper_account(account_id),
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    quantity        TEXT NOT NULL,
    order_type      TEXT NOT NULL,
    limit_price     TEXT,
    status          TEXT NOT NULL,
    submitted_at    TEXT NOT NULL,
    plan_id         TEXT NOT NULL DEFAULT '',
    batch_sha256    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_pi_paper_order_status ON pi_paper_order(status);
CREATE INDEX IF NOT EXISTS ix_pi_paper_order_batch ON pi_paper_order(batch_sha256);

CREATE TABLE IF NOT EXISTS pi_paper_fill (
    fill_id         TEXT PRIMARY KEY,
    order_id        TEXT NOT NULL REFERENCES pi_paper_order(order_id),
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    filled_qty      TEXT NOT NULL,
    price           TEXT NOT NULL,
    commission      TEXT NOT NULL,
    filled_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pi_paper_fill_order ON pi_paper_fill(order_id);
CREATE INDEX IF NOT EXISTS ix_pi_paper_fill_symbol ON pi_paper_fill(symbol);

CREATE TABLE IF NOT EXISTS pi_paper_position (
    account_id      TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    quantity        TEXT NOT NULL,
    avg_cost        TEXT NOT NULL,
    realized_pl     TEXT NOT NULL,
    last_updated    TEXT NOT NULL,
    PRIMARY KEY (account_id, symbol)
);

-- FIFO tax-lot ledger: one row per opened lot, closed lots archived
-- with closed_at + closing_fill_id. Kept private (leading underscore
-- convention) — used only by the engine's internal FIFO walker.
CREATE TABLE IF NOT EXISTS _pi_paper_lot (
    lot_id          TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    qty             TEXT NOT NULL,
    cost_per_unit   TEXT NOT NULL,
    opened_at       TEXT NOT NULL,
    opening_fill_id TEXT NOT NULL,
    closed_at       TEXT,
    closing_fill_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_pi_paper_lot_open
    ON _pi_paper_lot(account_id, symbol, closed_at);
"""


class SqlitePaperEngine:
    """SQLite-backed paper trading engine.

    Threading: sqlite3 is used with ``check_same_thread=False`` and a
    module-level RLock so a widget-backend uvicorn worker can call from
    multiple threads. All writes happen inside ``self._tx()``.
    """

    def __init__(
        self,
        db_path: Path | str,
        account_id: str = "paper",
        starting_cash: Decimal = Decimal("100000"),
    ) -> None:
        self._db_path = Path(db_path).resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._account_id = account_id
        self._conn = sqlite3.connect(
            str(self._db_path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.executescript(_SCHEMA)
        self._ensure_account(starting_cash)

    # --- lifecycle helpers ------------------------------------------------

    def _ensure_account(self, starting_cash: Decimal) -> None:
        row = self._conn.execute(
            "SELECT account_id FROM pi_paper_account WHERE account_id = ?",
            (self._account_id,),
        ).fetchone()
        if row is None:
            now = _now_iso()
            self._conn.execute(
                "INSERT INTO pi_paper_account "
                "(account_id, starting_cash, cash, realized_pl, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    self._account_id,
                    str(starting_cash),
                    str(starting_cash),
                    "0",
                    now,
                ),
            )
            logger.info(
                "SqlitePaperEngine: created account %r with starting cash %s",
                self._account_id,
                starting_cash,
            )

    @contextmanager
    def _tx(self) -> Iterator[None]:
        """Transaction scope — all-or-nothing for multi-row updates."""
        try:
            self._conn.execute("BEGIN")
            yield
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        """Release the SQLite connection."""
        self._conn.close()

    # --- Protocol methods -------------------------------------------------

    def submit_batch(self, batch, plan_id: str = "") -> list[str]:  # noqa: ANN001
        """Insert every ticket as a PENDING order. Returns order_ids."""
        # Duck-typed on the OrderBatch shape to keep this module free of
        # a hard import cycle with order_sink.
        tickets = getattr(batch, "tickets", None)
        if tickets is None:
            raise PaperEngineError(
                "submit_batch: `batch` must expose a .tickets sequence "
                "(got a bare list? wrap with order_sink.OrderBatch)"
            )
        batch_sha = getattr(batch, "sha256", lambda: "")()
        submitted_at = _now_iso()
        order_ids: list[str] = []
        with self._tx():
            for t in tickets:
                _validate_symbol(t.symbol)
                side = _action_to_side(t.action)
                order_id = _new_id("ord")
                self._conn.execute(
                    "INSERT INTO pi_paper_order "
                    "(order_id, account_id, symbol, side, quantity, "
                    "order_type, limit_price, status, submitted_at, "
                    "plan_id, batch_sha256) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        order_id,
                        self._account_id,
                        t.symbol,
                        side.value,
                        str(t.quantity),
                        t.order_type,
                        str(t.limit_price) if t.limit_price is not None else None,
                        OrderStatus.PENDING.value,
                        submitted_at,
                        plan_id,
                        batch_sha,
                    ),
                )
                order_ids.append(order_id)
        logger.info(
            "SqlitePaperEngine.submit_batch: %d orders PENDING (batch %s...)",
            len(order_ids),
            batch_sha[:8],
        )
        return order_ids

    def record_fill(  # pylint: disable=too-many-positional-arguments
        self,
        order_id: str,
        price: Decimal,
        filled_qty: Decimal,
        at: datetime,
        commission: Decimal = Decimal("0"),
    ) -> PaperFill:
        """Record a fill; loud on unknown order / overfill / bad state."""
        if price <= 0:
            raise PaperEngineError(f"record_fill: price must be positive; got {price}")
        if filled_qty <= 0:
            raise PaperEngineError(
                f"record_fill: filled_qty must be positive; got {filled_qty}"
            )
        if commission < 0:
            raise PaperEngineError(
                f"record_fill: commission must be non-negative; got {commission}"
            )

        with self._tx():
            order_row = self._conn.execute(
                "SELECT * FROM pi_paper_order WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if order_row is None:
                raise PaperEngineError(f"record_fill: unknown order_id {order_id!r}")
            status = OrderStatus(order_row["status"])
            if status in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
                raise PaperEngineError(
                    f"record_fill: order {order_id!r} is {status.value}; "
                    "cannot record fill on a terminated order"
                )
            if status == OrderStatus.FILLED:
                raise PaperEngineError(
                    f"record_fill: order {order_id!r} is already FILLED; "
                    "check for a duplicate fill event before retrying"
                )

            ordered_qty = Decimal(order_row["quantity"])
            side = Side(order_row["side"])
            symbol = order_row["symbol"]

            # Sum prior fills to compute remaining capacity.
            prior_filled = self._sum_prior_fills(order_id)
            new_total = prior_filled + filled_qty
            if new_total > ordered_qty:
                raise PaperEngineError(
                    f"record_fill: overfill on {order_id!r} — "
                    f"ordered={ordered_qty}, prior={prior_filled}, "
                    f"this={filled_qty} → would total {new_total}"
                )

            fill_id = _new_id("fil")
            fill = PaperFill(
                fill_id=fill_id,
                order_id=order_id,
                symbol=symbol,
                side=side,
                filled_qty=filled_qty,
                price=price,
                commission=commission,
                filled_at=at,
            )
            self._conn.execute(
                "INSERT INTO pi_paper_fill "
                "(fill_id, order_id, symbol, side, filled_qty, price, "
                "commission, filled_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fill.fill_id,
                    fill.order_id,
                    fill.symbol,
                    fill.side.value,
                    str(fill.filled_qty),
                    str(fill.price),
                    str(fill.commission),
                    _to_iso(fill.filled_at),
                ),
            )

            # Update order status.
            new_status = (
                OrderStatus.FILLED if new_total == ordered_qty else OrderStatus.PARTIAL
            )
            self._conn.execute(
                "UPDATE pi_paper_order SET status = ? WHERE order_id = ?",
                (new_status.value, order_id),
            )

            # Apply cash + FIFO lot bookkeeping + position roll-up.
            self._apply_fill_side_effects(fill)

        logger.info(
            "SqlitePaperEngine.record_fill: order %s filled_qty=%s @ %s",
            order_id,
            filled_qty,
            price,
        )
        return fill

    def cancel_order(self, order_id: str, reason: str = "") -> None:
        """Cancel a PENDING/PARTIAL order. Idempotent (logs on repeat)."""
        with self._tx():
            row = self._conn.execute(
                "SELECT status FROM pi_paper_order WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is None:
                raise PaperEngineError(f"cancel_order: unknown order_id {order_id!r}")
            status = OrderStatus(row["status"])
            if status == OrderStatus.CANCELLED:
                logger.info(
                    "cancel_order: %r already CANCELLED (reason=%r)",
                    order_id,
                    reason,
                )
                return
            if status in (OrderStatus.FILLED, OrderStatus.REJECTED):
                raise PaperEngineError(
                    f"cancel_order: order {order_id!r} is {status.value}; "
                    "cannot cancel a terminated order"
                )
            self._conn.execute(
                "UPDATE pi_paper_order SET status = ? WHERE order_id = ?",
                (OrderStatus.CANCELLED.value, order_id),
            )
        logger.info("cancel_order: order %r CANCELLED (reason=%r)", order_id, reason)

    def get_account(self) -> PaperAccount:
        """Return the current single-account snapshot (cash + realized_pl)."""
        row = self._conn.execute(
            "SELECT * FROM pi_paper_account WHERE account_id = ?",
            (self._account_id,),
        ).fetchone()
        if row is None:  # pragma: no cover — _ensure_account guarantees this
            raise PaperEngineError(
                f"get_account: account {self._account_id!r} vanished — "
                "did another process delete it?"
            )
        return PaperAccount(
            account_id=row["account_id"],
            starting_cash=Decimal(row["starting_cash"]),
            cash=Decimal(row["cash"]),
            realized_pl=Decimal(row["realized_pl"]),
            created_at=_from_iso(row["created_at"]),
        )

    def get_positions(self) -> list[PaperPosition]:
        """Return every non-zero materialized position for this account."""
        rows = self._conn.execute(
            "SELECT * FROM pi_paper_position WHERE account_id = ? "
            "AND CAST(quantity AS REAL) != 0",
            (self._account_id,),
        ).fetchall()
        return [
            PaperPosition(
                account_id=r["account_id"],
                symbol=r["symbol"],
                quantity=Decimal(r["quantity"]),
                avg_cost=Decimal(r["avg_cost"]),
                realized_pl=Decimal(r["realized_pl"]),
                last_updated=_from_iso(r["last_updated"]),
            )
            for r in rows
        ]

    def get_orders(self, status: OrderStatus | None = None) -> list[PaperOrder]:
        """Return this account's orders, optionally filtered by status."""
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM pi_paper_order WHERE account_id = ? "
                "ORDER BY submitted_at",
                (self._account_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM pi_paper_order WHERE account_id = ? "
                "AND status = ? ORDER BY submitted_at",
                (self._account_id, status.value),
            ).fetchall()
        return [_row_to_order(r) for r in rows]

    def get_fills(self, since: datetime | None = None) -> list[PaperFill]:
        """Return recorded fills, optionally filtered by ``filled_at >= since``."""
        if since is None:
            rows = self._conn.execute(
                "SELECT f.* FROM pi_paper_fill f "
                "JOIN pi_paper_order o ON f.order_id = o.order_id "
                "WHERE o.account_id = ? ORDER BY f.filled_at",
                (self._account_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT f.* FROM pi_paper_fill f "
                "JOIN pi_paper_order o ON f.order_id = o.order_id "
                "WHERE o.account_id = ? AND f.filled_at >= ? "
                "ORDER BY f.filled_at",
                (self._account_id, _to_iso(since)),
            ).fetchall()
        return [_row_to_fill(r) for r in rows]

    # -- P3.b unrealized P&L -------------------------------------------

    def get_positions_with_unrealized(
        self, pricing: Mapping[str, Decimal]
    ) -> list[PaperPositionMarked]:
        """See :class:`PaperEngine` for the contract."""
        results: list[PaperPositionMarked] = []
        for pos in self.get_positions():
            mark = pricing.get(pos.symbol)
            if mark is not None and mark <= 0:
                raise PaperEngineError(
                    f"get_positions_with_unrealized: mark_price for "
                    f"{pos.symbol!r} is non-positive ({mark}). Zero or "
                    f"negative marks indicate a misconfigured price feed; "
                    f"correct upstream before proceeding."
                )
            if mark is None:
                # Loud-empty: we HELD this symbol but the caller's
                # pricing dict didn't cover it. Preserve as None so the
                # caller cannot mistake it for zero.
                results.append(
                    PaperPositionMarked(
                        account_id=pos.account_id,
                        symbol=pos.symbol,
                        quantity=pos.quantity,
                        avg_cost=pos.avg_cost,
                        realized_pl=pos.realized_pl,
                        last_updated=pos.last_updated,
                        mark_price=None,
                        mark_value=None,
                        unrealized_pl=None,
                        unrealized_pl_pct=None,
                    )
                )
                continue

            # Same formula for longs and shorts: quantity carries the
            # sign, so negative-quantity shorts profit when mark drops.
            mark_value = pos.quantity * mark
            unrealized_pl = pos.quantity * (mark - pos.avg_cost)
            # Percent uses avg_cost as denominator; short position with
            # avg_cost basis works fine. Guard against zero-basis
            # (would be a bug in the ledger but let's not divide by 0).
            unrealized_pct: Decimal | None = (
                (mark - pos.avg_cost) / pos.avg_cost * Decimal("100")
                if pos.avg_cost != 0
                else None
            )
            results.append(
                PaperPositionMarked(
                    account_id=pos.account_id,
                    symbol=pos.symbol,
                    quantity=pos.quantity,
                    avg_cost=pos.avg_cost,
                    realized_pl=pos.realized_pl,
                    last_updated=pos.last_updated,
                    mark_price=mark,
                    mark_value=mark_value,
                    unrealized_pl=unrealized_pl,
                    unrealized_pl_pct=unrealized_pct,
                )
            )
        return results

    def get_account_equity(self, pricing: Mapping[str, Decimal]) -> PaperEquity:
        """See :class:`PaperEngine` for the contract."""
        acct = self.get_account()
        marked = self.get_positions_with_unrealized(pricing)
        marked_value = Decimal("0")
        unrealized_total = Decimal("0")
        missing: list[str] = []
        for m in marked:
            if m.mark_value is None:
                missing.append(m.symbol)
                continue
            marked_value += m.mark_value
            if m.unrealized_pl is not None:
                unrealized_total += m.unrealized_pl
        return PaperEquity(
            account_id=acct.account_id,
            cash=acct.cash,
            realized_pl=acct.realized_pl,
            marked_value=marked_value,
            equity=acct.cash + marked_value,
            unrealized_pl=unrealized_total,
            symbols_missing_marks=tuple(missing),
        )

    # --- internal: fill side effects --------------------------------------

    def _sum_prior_fills(self, order_id: str) -> Decimal:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(CAST(filled_qty AS REAL)), 0) AS s "
            "FROM pi_paper_fill WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        return Decimal(str(row["s"]))

    def _apply_fill_side_effects(self, fill: PaperFill) -> None:
        """Update cash, tax lots, materialized position for a fill."""
        gross = fill.filled_qty * fill.price
        is_buy = fill.side in _BUY_SIDES

        # Cash side effect: buy debits cash + commission; sell credits
        # cash minus commission.
        cash_delta = -(gross + fill.commission) if is_buy else (gross - fill.commission)
        self._adjust_cash(cash_delta)

        # Lot side effect + realized-P&L.
        realized = self._apply_fifo(fill, is_buy)

        # Materialized position update.
        self._update_position(fill, is_buy, realized)

    def _adjust_cash(self, delta: Decimal) -> None:
        row = self._conn.execute(
            "SELECT cash FROM pi_paper_account WHERE account_id = ?",
            (self._account_id,),
        ).fetchone()
        new_cash = Decimal(row["cash"]) + delta
        if new_cash < 0:
            raise PaperEngineError(
                f"cash side effect: would drive cash negative "
                f"({row['cash']} + {delta} = {new_cash}). "
                "Buy exceeds available cash — check the batch's "
                "gross notional against get_account().cash before submitting."
            )
        self._conn.execute(
            "UPDATE pi_paper_account SET cash = ? WHERE account_id = ?",
            (str(new_cash), self._account_id),
        )

    def _apply_fifo(self, fill: PaperFill, is_buy: bool) -> Decimal:
        """Return realized P&L for this fill (0 on opening lots)."""
        if is_buy:
            # Opening (or covering short) — new lot.
            self._conn.execute(
                "INSERT INTO _pi_paper_lot "
                "(lot_id, account_id, symbol, qty, cost_per_unit, "
                "opened_at, opening_fill_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _new_id("lot"),
                    self._account_id,
                    fill.symbol,
                    str(fill.filled_qty),
                    str(fill.price),
                    _to_iso(fill.filled_at),
                    fill.fill_id,
                ),
            )
            return Decimal("0")

        # Closing (sell) — walk open lots FIFO, compute realized P&L.
        remaining = fill.filled_qty
        realized = Decimal("0")
        open_lots = self._conn.execute(
            "SELECT lot_id, qty, cost_per_unit FROM _pi_paper_lot "
            "WHERE account_id = ? AND symbol = ? AND closed_at IS NULL "
            "ORDER BY opened_at",
            (self._account_id, fill.symbol),
        ).fetchall()

        for lot in open_lots:
            if remaining <= 0:
                break
            lot_qty = Decimal(lot["qty"])
            cost = Decimal(lot["cost_per_unit"])
            take = min(remaining, lot_qty)
            realized += take * (fill.price - cost)
            leftover = lot_qty - take
            if leftover == 0:
                self._conn.execute(
                    "UPDATE _pi_paper_lot SET closed_at = ?, "
                    "closing_fill_id = ? WHERE lot_id = ?",
                    (_to_iso(fill.filled_at), fill.fill_id, lot["lot_id"]),
                )
            else:
                self._conn.execute(
                    "UPDATE _pi_paper_lot SET qty = ? WHERE lot_id = ?",
                    (str(leftover), lot["lot_id"]),
                )
            remaining -= take

        if remaining > 0:
            raise PaperEngineError(
                f"_apply_fifo: sell of {fill.filled_qty} {fill.symbol} "
                f"exceeds long position by {remaining}. Short-sell? "
                "Open a SELL_SHORT order first."
            )

        # Roll realized P&L into account — Decimal arithmetic in
        # Python, then persist as TEXT so we never round-trip through
        # float and lose precision on cent-fractional realizeds.
        row = self._conn.execute(
            "SELECT realized_pl FROM pi_paper_account WHERE account_id = ?",
            (self._account_id,),
        ).fetchone()
        new_realized = Decimal(row["realized_pl"]) + realized
        self._conn.execute(
            "UPDATE pi_paper_account SET realized_pl = ? WHERE account_id = ?",
            (str(new_realized), self._account_id),
        )
        return realized

    def _update_position(
        self, fill: PaperFill, is_buy: bool, realized: Decimal
    ) -> None:
        row = self._conn.execute(
            "SELECT quantity, avg_cost, realized_pl FROM pi_paper_position "
            "WHERE account_id = ? AND symbol = ?",
            (self._account_id, fill.symbol),
        ).fetchone()

        if row is None:
            qty = fill.filled_qty if is_buy else -fill.filled_qty
            avg_cost = fill.price if is_buy else Decimal("0")
            self._conn.execute(
                "INSERT INTO pi_paper_position "
                "(account_id, symbol, quantity, avg_cost, realized_pl, "
                "last_updated) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self._account_id,
                    fill.symbol,
                    str(qty),
                    str(avg_cost),
                    str(realized),
                    _to_iso(fill.filled_at),
                ),
            )
            return

        old_qty = Decimal(row["quantity"])
        old_avg = Decimal(row["avg_cost"])
        cumulative_realized = Decimal(row["realized_pl"]) + realized

        if is_buy:
            # Weighted-average-cost update for adds to a long position.
            # Ternary reads: adds to an existing long → weighted; flat
            # or short → new cost basis is the fill price.
            new_qty = old_qty + fill.filled_qty
            new_avg = (
                (old_qty * old_avg + fill.filled_qty * fill.price) / new_qty
                if old_qty > 0
                else fill.price
            )
        else:
            new_qty = old_qty - fill.filled_qty
            # avg_cost stays the same on partial close (FIFO already booked
            # the realized P&L above); goes to 0 when position closes flat.
            new_avg = old_avg if new_qty != 0 else Decimal("0")

        self._conn.execute(
            "UPDATE pi_paper_position SET quantity = ?, avg_cost = ?, "
            "realized_pl = ?, last_updated = ? "
            "WHERE account_id = ? AND symbol = ?",
            (
                str(new_qty),
                str(new_avg),
                str(cumulative_realized),
                _to_iso(fill.filled_at),
                self._account_id,
                fill.symbol,
            ),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_default_engine(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    db_path: Path | str | None = None,
    account_id: str = "paper",
    starting_cash: Decimal = Decimal("100000"),
    run_id: str = "live",
    strategy_id: str = "default",
) -> PaperEngine:
    """Return the configured paper engine.

    Backend selection (P3.c, #1790):

    - ``PI_PAPER_ENGINE=mysql`` (default) — return
      :class:`~openbb_techtrade.execution.mysql_paper_engine.MysqlPaperEngine`
      against the shared FMP-cache MySQL pool. On MySQL-unreachable
      (import fails or pool raises), we emit a WARNING and fall back
      to SQLite — matches the ``MySqlPortfolioStore`` graceful-fallback
      pattern from #1744.
    - ``PI_PAPER_ENGINE=sqlite`` — force the file-backed
      :class:`SqlitePaperEngine` under ``~/.portfolio_intel/paper.db``
      (or ``PI_PAPER_DB``).

    Idempotent: re-invocation opens the same store and returns an
    engine against the same account. Starting cash is honored only on
    account creation.
    """
    backend = os.environ.get("PI_PAPER_ENGINE", "mysql").strip().lower()

    if backend == "mysql":
        try:
            # pylint: disable=import-outside-toplevel,cyclic-import
            from openbb_techtrade.execution.mysql_paper_engine import (  # noqa: PLC0415
                MysqlPaperEngine,
            )

            return MysqlPaperEngine(
                run_id=run_id,
                strategy_id=strategy_id,
                account_id=account_id,
                starting_cash=starting_cash,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "get_default_engine: MySQL backend unreachable (%s); "
                "falling back to SQLite at ~/.portfolio_intel/paper.db",
                exc,
            )
            # fall through to sqlite

    resolved = (
        Path(db_path)
        if db_path is not None
        else (
            Path(os.environ.get("PI_PAPER_DB", ""))
            if os.environ.get("PI_PAPER_DB")
            else Path.home() / ".portfolio_intel" / "paper.db"
        )
    )
    return SqlitePaperEngine(
        resolved, account_id=account_id, starting_cash=starting_cash
    )


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


def orders_from_batch_shape(tickets: Iterable) -> list[dict]:  # noqa: ANN001
    """Debug helper: normalize an :class:`OrderBatch`.tickets to dicts.

    Not used by the engine's happy path (submit_batch is duck-typed).
    Useful for the widget-side test fixtures.
    """
    out: list[dict] = []
    for t in tickets:
        out.append(
            {
                "symbol": t.symbol,
                "action": t.action,
                "quantity": t.quantity,
                "order_type": t.order_type,
                "limit_price": t.limit_price,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    """Short unique-per-row identifier — prefix + 12-char uuid tail."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _from_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _validate_symbol(symbol: str) -> None:
    if not _SYMBOL_RE.match(symbol):
        raise PaperEngineError(
            f"symbol must match {_SYMBOL_RE.pattern!r}; got {symbol!r}"
        )


def _action_to_side(action: str) -> Side:
    side = _ACTION_TO_SIDE.get(action)
    if side is None:
        raise PaperEngineError(
            f"unknown OrderTicket.action {action!r}; expected one of "
            f"{sorted(_ACTION_TO_SIDE)}"
        )
    return side


def _row_to_order(r: sqlite3.Row) -> PaperOrder:
    return PaperOrder(
        order_id=r["order_id"],
        account_id=r["account_id"],
        symbol=r["symbol"],
        side=Side(r["side"]),
        quantity=Decimal(r["quantity"]),
        order_type=r["order_type"],  # type: ignore[arg-type]
        limit_price=Decimal(r["limit_price"]) if r["limit_price"] is not None else None,
        status=OrderStatus(r["status"]),
        submitted_at=_from_iso(r["submitted_at"]),
        plan_id=r["plan_id"],
        batch_sha256=r["batch_sha256"],
    )


def _row_to_fill(r: sqlite3.Row) -> PaperFill:
    return PaperFill(
        fill_id=r["fill_id"],
        order_id=r["order_id"],
        symbol=r["symbol"],
        side=Side(r["side"]),
        filled_qty=Decimal(r["filled_qty"]),
        price=Decimal(r["price"]),
        commission=Decimal(r["commission"]),
        filled_at=_from_iso(r["filled_at"]),
    )
