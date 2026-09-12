"""T5 P3.c — MySQL-backed paper trading engine (#1790).

Mirrors :class:`SqlitePaperEngine` byte-for-byte on FIFO realized-P&L
math, loud-rejection matrix, weighted-average cost basis, and cash
bookkeeping — but persists to the same MySQL instance as the corporate
FMP cache / positions history, backed by
:class:`openbb_fmp_cached.utils.database.DatabaseConfig`'s shared
connection pool.

Design deltas vs. SqlitePaperEngine
-----------------------------------
1. **Scope columns from day one.** Every ``pi_paper_*`` row carries a
   ``(run_id, strategy_id, account_id)`` triple. ``run_id='live'``
   isolates real paper trading from backtest replays; ``strategy_id``
   groups accounts by strategy; ``account_id`` is the multi-account key
   (no longer a P3.a singleton). Every query is scoped via
   :meth:`_scope_where`.
2. **fill_mode on pi_paper_fill.** Enum column tags the fill provenance:
   ``OPERATOR_RECORDED`` (P3.a default), ``BAR_SIMULATED`` (backtest
   replay, T5 P4), ``ACTIVITY_CSV_IMPORTED`` (P5 Fidelity reconcile).
3. **PyMySQL pool contract + storage types.** ``%s`` placeholders instead
   of ``?``; Decimals persist as ``VARCHAR(64)`` to preserve precision
   (matches the ``mysql_store.py`` convention for money fields — see
   #1744). Connections are borrowed through the shared pool's context
   manager, which owns cleanup. Because pooled sessions use autocommit,
   every write scope starts an explicit transaction with ``begin()``.
4. **Composite PKs.** ``pi_paper_account`` PK is
   ``(run_id, strategy_id, account_id)``; ``pi_paper_position`` PK adds
   ``symbol``. Order/fill/lot rows use surrogate string PKs but every
   read is scoped, so a scan across scopes is impossible by construction.
5. **Public Protocol API unchanged.** ``get_positions``,
   ``submit_batch``, ``record_fill``, etc., all match
   :class:`PaperEngine` — callers don't see the scope columns.

Non-goals
---------
- SQLite backend behavior is preserved verbatim in
  :mod:`openbb_techtrade.execution.paper_engine`; this file does not
  replace it. The factory in ``paper_engine.get_default_engine`` selects
  between backends via ``PI_PAPER_ENGINE``.
- Cross-scope reads are intentionally impossible — a "compare live vs.
  backtest" widget must instantiate two engines and diff at the
  application layer.
"""

# pylint: disable=too-many-lines,duplicate-code
# ruff: noqa: S608, D105
# S608 (hardcoded SQL): every f-string interpolates ONLY the _scope_where()
# fragment which is a static, module-owned constant plus placeholder tokens;
# all user data flows through parameterized %s bindings. Ruff can't prove
# that so we suppress at file scope.

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

# Reuse the dataclasses / enums / Protocol / errors from the sqlite module
# so callers see one set of types regardless of backend.
from openbb_techtrade.execution.paper_engine import (
    _ACTION_TO_SIDE,
    _BUY_SIDES,
    _SYMBOL_RE,
    OrderStatus,
    PaperAccount,
    PaperEngineError,
    PaperEquity,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperPositionMarked,
    Side,
    _new_order_id,
)

logger = logging.getLogger(__name__)

FillMode = Literal["OPERATOR_RECORDED", "BAR_SIMULATED", "ACTIVITY_CSV_IMPORTED"]

_VALID_FILL_MODES: frozenset[str] = frozenset(
    {"OPERATOR_RECORDED", "BAR_SIMULATED", "ACTIVITY_CSV_IMPORTED"}
)
_EXECUTION_SCOPE_NAMESPACE = uuid.UUID("cd6ea134-5078-4f4b-9794-a2b36017f60f")


# ---------------------------------------------------------------------------
# DDL — additive; never touches corporate Portfolio_Positions.
# ---------------------------------------------------------------------------

_PI_PAPER_ACCOUNT_DDL = """
CREATE TABLE IF NOT EXISTS pi_paper_account (
    run_id          VARCHAR(64) NOT NULL DEFAULT 'live',
    strategy_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    account_id      VARCHAR(64) NOT NULL DEFAULT 'paper',
    starting_cash   VARCHAR(64) NOT NULL,
    cash            VARCHAR(64) NOT NULL,
    realized_pl     VARCHAR(64) NOT NULL,
    created_at      DATETIME NOT NULL,
    PRIMARY KEY (run_id, strategy_id, account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_PI_PAPER_ORDER_DDL = """
CREATE TABLE IF NOT EXISTS pi_paper_order (
    order_id        VARCHAR(64) NOT NULL,
    run_id          VARCHAR(64) NOT NULL DEFAULT 'live',
    strategy_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    account_id      VARCHAR(64) NOT NULL DEFAULT 'paper',
    symbol          VARCHAR(16) NOT NULL,
    side            VARCHAR(16) NOT NULL,
    quantity        VARCHAR(64) NOT NULL,
    order_type      VARCHAR(16) NOT NULL,
    limit_price     VARCHAR(64),
    status          VARCHAR(16) NOT NULL,
    submitted_at    DATETIME NOT NULL,
    plan_id         VARCHAR(128) NOT NULL DEFAULT '',
    batch_sha256    VARCHAR(64) NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, strategy_id, account_id, order_id),
    INDEX ix_pi_paper_order_status (run_id, strategy_id, account_id, status),
    INDEX ix_pi_paper_order_batch (run_id, strategy_id, batch_sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_PI_PAPER_FILL_DDL = """
CREATE TABLE IF NOT EXISTS pi_paper_fill (
    fill_id         VARCHAR(64) NOT NULL,
    run_id          VARCHAR(64) NOT NULL DEFAULT 'live',
    strategy_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    account_id      VARCHAR(64) NOT NULL DEFAULT 'paper',
    order_id        VARCHAR(64) NOT NULL,
    symbol          VARCHAR(16) NOT NULL,
    side            VARCHAR(16) NOT NULL,
    filled_qty      VARCHAR(64) NOT NULL,
    price           VARCHAR(64) NOT NULL,
    commission      VARCHAR(64) NOT NULL,
    filled_at       DATETIME NOT NULL,
    fill_mode       ENUM('OPERATOR_RECORDED','BAR_SIMULATED','ACTIVITY_CSV_IMPORTED')
                    NOT NULL DEFAULT 'OPERATOR_RECORDED',
    PRIMARY KEY (run_id, strategy_id, account_id, fill_id),
    INDEX ix_pi_paper_fill_order (run_id, strategy_id, account_id, order_id),
    INDEX ix_pi_paper_fill_symbol (run_id, strategy_id, account_id, symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_PI_PAPER_POSITION_DDL = """
CREATE TABLE IF NOT EXISTS pi_paper_position (
    run_id          VARCHAR(64) NOT NULL DEFAULT 'live',
    strategy_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    account_id      VARCHAR(64) NOT NULL DEFAULT 'paper',
    symbol          VARCHAR(16) NOT NULL,
    quantity        VARCHAR(64) NOT NULL,
    avg_cost        VARCHAR(64) NOT NULL,
    realized_pl     VARCHAR(64) NOT NULL,
    last_updated    DATETIME NOT NULL,
    PRIMARY KEY (run_id, strategy_id, account_id, symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_PI_PAPER_LOT_DDL = """
CREATE TABLE IF NOT EXISTS _pi_paper_lot (
    lot_id          VARCHAR(64) NOT NULL,
    run_id          VARCHAR(64) NOT NULL DEFAULT 'live',
    strategy_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    account_id      VARCHAR(64) NOT NULL DEFAULT 'paper',
    symbol          VARCHAR(16) NOT NULL,
    qty             VARCHAR(64) NOT NULL,
    cost_per_unit   VARCHAR(64) NOT NULL,
    opened_at       DATETIME NOT NULL,
    opening_fill_id VARCHAR(64) NOT NULL,
    closed_at       DATETIME,
    closing_fill_id VARCHAR(64),
    PRIMARY KEY (run_id, strategy_id, account_id, lot_id),
    INDEX ix_pi_paper_lot_open
        (run_id, strategy_id, account_id, symbol, closed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_ALL_DDLS = (
    _PI_PAPER_ACCOUNT_DDL,
    _PI_PAPER_ORDER_DDL,
    _PI_PAPER_FILL_DDL,
    _PI_PAPER_POSITION_DDL,
    _PI_PAPER_LOT_DDL,
)


# ---------------------------------------------------------------------------
# MysqlPaperEngine
# ---------------------------------------------------------------------------


class MysqlPaperEngine:
    """MySQL-backed :class:`PaperEngine`.

    Every read/write is scoped to ``(run_id, strategy_id, account_id)``.
    Two engines with different scope tuples over the same pool observe
    fully-isolated ledgers — no accidental cross-scope contamination.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        connection_pool: Any = None,
        run_id: str = "live",
        strategy_id: str = "default",
        account_id: str = "paper",
        starting_cash: Decimal = Decimal("100000"),
        *,
        initialize: bool = True,
    ) -> None:
        if connection_pool is None:
            # pylint: disable=import-outside-toplevel
            from openbb_fmp_cached.utils.database import (  # noqa: PLC0415
                get_connection_pool,
            )

            connection_pool = get_connection_pool()
        self._pool = connection_pool
        self._run_id = run_id
        self._strategy_id = strategy_id
        self._account_id = account_id
        if initialize:
            self._ensure_schema()
            self._ensure_account(starting_cash)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Shared pool — nothing to close per-engine."""

    def __enter__(self) -> MysqlPaperEngine:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _acquire(self) -> Iterator[Any]:
        with self._pool.get_connection() as conn:
            yield conn

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """Explicit BEGIN/COMMIT (rollback on any exception)."""
        held: PaperEngineError | None = None
        with self._acquire() as conn:
            conn.begin()
            committed = False
            try:
                yield conn
                conn.commit()
                committed = True
            except PaperEngineError as exc:
                held = exc
            finally:
                if not committed:
                    self._restore(conn)
        if held is not None:
            raise held

    @staticmethod
    def _restore(conn: Any) -> None:
        try:
            conn.rollback()
        except Exception:  # pylint: disable=broad-except
            logger.warning("MysqlPaperEngine rollback failed", exc_info=True)

    # ------------------------------------------------------------------
    # schema + account bootstrap
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        with self.transaction() as conn:
            cur = conn.cursor()
            for ddl in _ALL_DDLS:
                cur.execute(ddl)
            cur.close()

    def _ensure_account(self, starting_cash: Decimal) -> None:
        """Idempotent: second call with a different starting_cash is a no-op."""
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO pi_paper_account "
                "(run_id, strategy_id, account_id, starting_cash, "
                "cash, realized_pl, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE account_id = account_id",
                (
                    self._run_id,
                    self._strategy_id,
                    self._account_id,
                    str(starting_cash),
                    str(starting_cash),
                    "0",
                    _now_utc(),
                ),
            )
            cur.close()

    # ------------------------------------------------------------------
    # scope helper
    # ------------------------------------------------------------------

    def _scope_where(self, extra_where: str = "") -> tuple[str, tuple]:
        """Return SQL WHERE fragment + params bound to this engine's scope.

        ``extra_where`` is appended with ``AND`` prefix (if provided).
        """
        clause = "run_id = %s AND strategy_id = %s AND account_id = %s"
        params: tuple = (self._run_id, self._strategy_id, self._account_id)
        if extra_where:
            clause = f"{clause} AND {extra_where}"
        return clause, params

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    @property
    def account_id(self) -> str:
        """Return this engine's scoped ledger account identity."""
        return self._account_id

    @property
    def execution_scope_id(self) -> str:
        """Return the MySQL run/strategy ledger identity."""
        try:
            params = self._pool.connection_params
        except (AttributeError, TypeError):
            params = {}
        database_scope = (
            str(params.get("host", "")),
            str(params.get("port", "")),
            str(
                params.get(
                    "database",
                    getattr(
                        self._pool,
                        "database",
                        getattr(self._pool, "path", ""),
                    ),
                )
            ),
        )
        identity = (
            f"{database_scope!r}:{len(self._run_id)}:{self._run_id}"
            f"{len(self._strategy_id)}:{self._strategy_id}"
        )
        return f"mysql-{uuid.uuid5(_EXECUTION_SCOPE_NAMESPACE, identity)}"

    def is_initialized(self) -> bool:
        """Check table and scoped-account presence without creating either."""
        with self._acquire() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) AS table_count FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = %s",
                ("pi_paper_account",),
            )
            (table_count,) = _row_values(cur.fetchone(), ("table_count",))
            if not table_count:
                cur.close()
                return False
            where, params = self._scope_where()
            cur.execute(
                f"SELECT 1 AS account_exists FROM pi_paper_account "
                f"WHERE {where} LIMIT 1",
                params,
            )
            exists = cur.fetchone() is not None
            cur.close()
            return exists

    def submit_batch(self, batch, plan_id: str = "") -> list[str]:  # noqa: ANN001
        """Insert every ticket as a PENDING order; returns order_ids."""
        tickets = getattr(batch, "tickets", None)
        if tickets is None:
            raise PaperEngineError(
                "submit_batch: `batch` must expose a .tickets sequence "
                "(got a bare list? wrap with order_sink.OrderBatch)"
            )
        batch_sha = getattr(batch, "sha256", lambda: "")()
        submitted_at = _now_utc()
        order_ids = (
            [
                _new_order_id(
                    f"{self._run_id}:{self._strategy_id}:{self._account_id}:"
                    f"{plan_id}:{batch_sha}:{ordinal}"
                )
                for ordinal, _ticket in enumerate(tickets)
            ]
            if plan_id
            else [_new_id("ord") for _ticket in tickets]
        )
        with self.transaction() as conn:
            cur = conn.cursor()
            for order_id, t in zip(order_ids, tickets, strict=True):
                _validate_symbol(t.symbol)
                side = _action_to_side(t.action)
                duplicate_clause = (
                    " ON DUPLICATE KEY UPDATE order_id = order_id" if plan_id else ""
                )
                cur.execute(
                    "INSERT INTO pi_paper_order "
                    "(order_id, run_id, strategy_id, account_id, symbol, "
                    "side, quantity, order_type, limit_price, status, "
                    "submitted_at, plan_id, batch_sha256) VALUES "
                    "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    + duplicate_clause,
                    (
                        order_id,
                        self._run_id,
                        self._strategy_id,
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
            if plan_id:
                where, scope_params = self._scope_where(
                    "plan_id = %s AND batch_sha256 = %s"
                )
                cur.execute(
                    f"SELECT order_id FROM pi_paper_order WHERE {where}",
                    (*scope_params, plan_id, batch_sha),
                )
                existing_ids = {
                    _row_values(row, ("order_id",))[0] for row in cur.fetchall()
                }
                if existing_ids != set(order_ids):
                    cur.close()
                    raise PaperEngineError(
                        "submit_batch: plan/batch idempotency key exists with "
                        "a different order identity set; reconcile the audit rows"
                    )
            cur.close()
        logger.info(
            "MysqlPaperEngine.submit_batch: %d orders PENDING (batch %s...)",
            len(order_ids),
            batch_sha[:8],
        )
        return order_ids

    def record_fill(  # pylint: disable=too-many-positional-arguments,too-many-arguments,too-many-locals
        self,
        order_id: str,
        price: Decimal,
        filled_qty: Decimal,
        at: datetime,
        commission: Decimal = Decimal("0"),
        fill_mode: FillMode = "OPERATOR_RECORDED",
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
        if fill_mode not in _VALID_FILL_MODES:
            raise PaperEngineError(
                f"record_fill: invalid fill_mode {fill_mode!r}; expected "
                f"one of {sorted(_VALID_FILL_MODES)}"
            )

        with self.transaction() as conn:
            cur = conn.cursor()
            where, params = self._scope_where("order_id = %s")
            cur.execute(
                f"SELECT order_id, symbol, side, quantity, status "
                f"FROM pi_paper_order WHERE {where} FOR UPDATE",
                params + (order_id,),
            )
            order_row = cur.fetchone()
            if order_row is None:
                raise PaperEngineError(f"record_fill: unknown order_id {order_id!r}")
            _oid, symbol, side_str, ordered_qty_str, status_str = _row_values(
                order_row, ("order_id", "symbol", "side", "quantity", "status")
            )
            status = OrderStatus(status_str)
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

            ordered_qty = Decimal(ordered_qty_str)
            side = Side(side_str)

            prior_filled = self._sum_prior_fills(cur, order_id)
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
            cur.execute(
                "INSERT INTO pi_paper_fill "
                "(fill_id, run_id, strategy_id, account_id, order_id, "
                "symbol, side, filled_qty, price, commission, filled_at, "
                "fill_mode) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    fill.fill_id,
                    self._run_id,
                    self._strategy_id,
                    self._account_id,
                    fill.order_id,
                    fill.symbol,
                    fill.side.value,
                    str(fill.filled_qty),
                    str(fill.price),
                    str(fill.commission),
                    _to_dt(fill.filled_at),
                    fill_mode,
                ),
            )

            new_status = (
                OrderStatus.FILLED if new_total == ordered_qty else OrderStatus.PARTIAL
            )
            where2, params2 = self._scope_where("order_id = %s")
            cur.execute(
                f"UPDATE pi_paper_order SET status = %s WHERE {where2}",
                (new_status.value,) + params2 + (order_id,),
            )

            self._apply_fill_side_effects(cur, fill)
            cur.close()

        logger.info(
            "MysqlPaperEngine.record_fill: order %s filled_qty=%s @ %s",
            order_id,
            filled_qty,
            price,
        )
        return fill

    def cancel_order(self, order_id: str, reason: str = "") -> None:
        """Cancel a PENDING/PARTIAL order. Idempotent (logs on repeat)."""
        with self.transaction() as conn:
            cur = conn.cursor()
            where, params = self._scope_where("order_id = %s")
            cur.execute(
                f"SELECT status FROM pi_paper_order WHERE {where} FOR UPDATE",
                params + (order_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise PaperEngineError(f"cancel_order: unknown order_id {order_id!r}")
            (status_str,) = _row_values(row, ("status",))
            status = OrderStatus(status_str)
            if status == OrderStatus.CANCELLED:
                logger.info(
                    "cancel_order: %r already CANCELLED (reason=%r)",
                    order_id,
                    reason,
                )
                cur.close()
                return
            if status in (OrderStatus.FILLED, OrderStatus.REJECTED):
                raise PaperEngineError(
                    f"cancel_order: order {order_id!r} is {status.value}; "
                    "cannot cancel a terminated order"
                )
            cur.execute(
                f"UPDATE pi_paper_order SET status = %s WHERE {where}",
                (OrderStatus.CANCELLED.value,) + params + (order_id,),
            )
            cur.close()
        logger.info("cancel_order: order %r CANCELLED (reason=%r)", order_id, reason)

    def get_account(self) -> PaperAccount:
        """Return the current scoped account snapshot."""
        where, params = self._scope_where()
        with self._acquire() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT account_id, starting_cash, cash, realized_pl, "
                f"created_at FROM pi_paper_account WHERE {where}",
                params,
            )
            row = cur.fetchone()
            cur.close()
        if row is None:  # pragma: no cover — _ensure_account guarantees this
            raise PaperEngineError(
                f"get_account: account {self._account_id!r} in scope "
                f"({self._run_id}/{self._strategy_id}) vanished"
            )
        (
            account_id,
            starting_cash,
            cash,
            realized_pl,
            created_at,
        ) = _row_values(
            row, ("account_id", "starting_cash", "cash", "realized_pl", "created_at")
        )
        return PaperAccount(
            account_id=account_id,
            starting_cash=Decimal(starting_cash),
            cash=Decimal(cash),
            realized_pl=Decimal(realized_pl),
            created_at=_as_utc(created_at),
        )

    def get_positions(self) -> list[PaperPosition]:
        """Return every non-zero materialized position in this scope."""
        where, params = self._scope_where()
        with self._acquire() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT account_id, symbol, quantity, avg_cost, realized_pl, "
                f"last_updated FROM pi_paper_position WHERE {where}",
                params,
            )
            rows = cur.fetchall()
            cur.close()
        result: list[PaperPosition] = []
        for r in rows:
            aid, symbol, qty, avg_cost, realized_pl, last_updated = _row_values(
                r,
                (
                    "account_id",
                    "symbol",
                    "quantity",
                    "avg_cost",
                    "realized_pl",
                    "last_updated",
                ),
            )
            if Decimal(qty) == 0:
                continue
            result.append(
                PaperPosition(
                    account_id=aid,
                    symbol=symbol,
                    quantity=Decimal(qty),
                    avg_cost=Decimal(avg_cost),
                    realized_pl=Decimal(realized_pl),
                    last_updated=_as_utc(last_updated),
                )
            )
        return result

    def get_orders(self, status: OrderStatus | None = None) -> list[PaperOrder]:
        """Return this scope's orders, optionally filtered by status."""
        with self._acquire() as conn:
            cur = conn.cursor()
            if status is None:
                where, params = self._scope_where()
                cur.execute(
                    f"SELECT * FROM pi_paper_order WHERE {where} "
                    f"ORDER BY submitted_at",
                    params,
                )
            else:
                where, params = self._scope_where("status = %s")
                cur.execute(
                    f"SELECT * FROM pi_paper_order WHERE {where} "
                    f"ORDER BY submitted_at",
                    params + (status.value,),
                )
            rows = cur.fetchall()
            cur.close()
        return [_row_to_order(r) for r in rows]

    def get_fills(self, since: datetime | None = None) -> list[PaperFill]:
        """Return recorded fills, optionally filtered by ``filled_at >= since``."""
        with self._acquire() as conn:
            cur = conn.cursor()
            if since is None:
                where, params = self._scope_where()
                cur.execute(
                    f"SELECT * FROM pi_paper_fill WHERE {where} " f"ORDER BY filled_at",
                    params,
                )
            else:
                where, params = self._scope_where("filled_at >= %s")
                cur.execute(
                    f"SELECT * FROM pi_paper_fill WHERE {where} " f"ORDER BY filled_at",
                    params + (_to_dt(since),),
                )
            rows = cur.fetchall()
            cur.close()
        return [_row_to_fill(r) for r in rows]

    # ------------------------------------------------------------------
    # P3.b unrealized P&L (same math as sqlite backend)
    # ------------------------------------------------------------------

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
                    f"negative marks indicate a misconfigured price feed."
                )
            if mark is None:
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
            mark_value = pos.quantity * mark
            unrealized_pl = pos.quantity * (mark - pos.avg_cost)
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

    # ------------------------------------------------------------------
    # internal — fill side effects (same math as sqlite backend)
    # ------------------------------------------------------------------

    def _sum_prior_fills(self, cur: Any, order_id: str) -> Decimal:
        where, params = self._scope_where("order_id = %s")
        cur.execute(
            f"SELECT filled_qty FROM pi_paper_fill WHERE {where}",
            params + (order_id,),
        )
        rows = cur.fetchall()
        total = Decimal("0")
        for r in rows:
            (q,) = _row_values(r, ("filled_qty",))
            total += Decimal(q)
        return total

    def _apply_fill_side_effects(self, cur: Any, fill: PaperFill) -> None:
        gross = fill.filled_qty * fill.price
        is_buy = fill.side in _BUY_SIDES
        cash_delta = -(gross + fill.commission) if is_buy else (gross - fill.commission)
        self._adjust_cash(cur, cash_delta)
        realized = self._apply_fifo(cur, fill, is_buy)
        self._update_position(cur, fill, is_buy, realized)

    def _adjust_cash(self, cur: Any, delta: Decimal) -> None:
        where, params = self._scope_where()
        cur.execute(
            f"SELECT cash FROM pi_paper_account WHERE {where} FOR UPDATE",
            params,
        )
        row = cur.fetchone()
        (cash_str,) = _row_values(row, ("cash",))
        new_cash = Decimal(cash_str) + delta
        if new_cash < 0:
            raise PaperEngineError(
                f"cash side effect: would drive cash negative "
                f"({cash_str} + {delta} = {new_cash}). "
                "Buy exceeds available cash — check the batch's "
                "gross notional against get_account().cash before submitting."
            )
        cur.execute(
            f"UPDATE pi_paper_account SET cash = %s WHERE {where}",
            (str(new_cash),) + params,
        )

    def _apply_fifo(  # pylint: disable=too-many-locals
        self, cur: Any, fill: PaperFill, is_buy: bool
    ) -> Decimal:
        if is_buy:
            cur.execute(
                "INSERT INTO _pi_paper_lot "
                "(lot_id, run_id, strategy_id, account_id, symbol, qty, "
                "cost_per_unit, opened_at, opening_fill_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    _new_id("lot"),
                    self._run_id,
                    self._strategy_id,
                    self._account_id,
                    fill.symbol,
                    str(fill.filled_qty),
                    str(fill.price),
                    _to_dt(fill.filled_at),
                    fill.fill_id,
                ),
            )
            return Decimal("0")

        # Sell: FIFO walk of open lots for this symbol in this scope.
        remaining = fill.filled_qty
        realized = Decimal("0")
        where, params = self._scope_where("symbol = %s AND closed_at IS NULL")
        cur.execute(
            f"SELECT lot_id, qty, cost_per_unit FROM _pi_paper_lot "
            f"WHERE {where} ORDER BY opened_at FOR UPDATE",
            params + (fill.symbol,),
        )
        open_lots = cur.fetchall()

        for lot in open_lots:
            if remaining <= 0:
                break
            lot_id, lot_qty_s, cost_s = _row_values(
                lot, ("lot_id", "qty", "cost_per_unit")
            )
            lot_qty = Decimal(lot_qty_s)
            cost = Decimal(cost_s)
            take = min(remaining, lot_qty)
            realized += take * (fill.price - cost)
            leftover = lot_qty - take
            if leftover == 0:
                where2, params2 = self._scope_where("lot_id = %s")
                cur.execute(
                    f"UPDATE _pi_paper_lot SET closed_at = %s, "
                    f"closing_fill_id = %s WHERE {where2}",
                    (_to_dt(fill.filled_at), fill.fill_id) + params2 + (lot_id,),
                )
            else:
                where2, params2 = self._scope_where("lot_id = %s")
                cur.execute(
                    f"UPDATE _pi_paper_lot SET qty = %s WHERE {where2}",
                    (str(leftover),) + params2 + (lot_id,),
                )
            remaining -= take

        if remaining > 0:
            raise PaperEngineError(
                f"_apply_fifo: sell of {fill.filled_qty} {fill.symbol} "
                f"exceeds long position by {remaining}. Short-sell? "
                "Open a SELL_SHORT order first."
            )

        # Roll realized P&L into scoped account row.
        where3, params3 = self._scope_where()
        cur.execute(
            f"SELECT realized_pl FROM pi_paper_account WHERE {where3} FOR UPDATE",
            params3,
        )
        row = cur.fetchone()
        (rpl_s,) = _row_values(row, ("realized_pl",))
        new_realized = Decimal(rpl_s) + realized
        cur.execute(
            f"UPDATE pi_paper_account SET realized_pl = %s WHERE {where3}",
            (str(new_realized),) + params3,
        )
        return realized

    def _update_position(  # pylint: disable=too-many-locals
        self, cur: Any, fill: PaperFill, is_buy: bool, realized: Decimal
    ) -> None:
        where, params = self._scope_where("symbol = %s")
        cur.execute(
            f"SELECT quantity, avg_cost, realized_pl FROM pi_paper_position "
            f"WHERE {where} FOR UPDATE",
            params + (fill.symbol,),
        )
        row = cur.fetchone()

        if row is None:
            qty = fill.filled_qty if is_buy else -fill.filled_qty
            avg_cost = fill.price if is_buy else Decimal("0")
            cur.execute(
                "INSERT INTO pi_paper_position "
                "(run_id, strategy_id, account_id, symbol, quantity, "
                "avg_cost, realized_pl, last_updated) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    self._run_id,
                    self._strategy_id,
                    self._account_id,
                    fill.symbol,
                    str(qty),
                    str(avg_cost),
                    str(realized),
                    _to_dt(fill.filled_at),
                ),
            )
            return

        old_qty_s, old_avg_s, rpl_s = _row_values(
            row, ("quantity", "avg_cost", "realized_pl")
        )
        old_qty = Decimal(old_qty_s)
        old_avg = Decimal(old_avg_s)
        cumulative_realized = Decimal(rpl_s) + realized

        if is_buy:
            new_qty = old_qty + fill.filled_qty
            new_avg = (
                (old_qty * old_avg + fill.filled_qty * fill.price) / new_qty
                if old_qty > 0
                else fill.price
            )
        else:
            new_qty = old_qty - fill.filled_qty
            new_avg = old_avg if new_qty != 0 else Decimal("0")

        cur.execute(
            f"UPDATE pi_paper_position SET quantity = %s, avg_cost = %s, "
            f"realized_pl = %s, last_updated = %s WHERE {where}",
            (
                str(new_qty),
                str(new_avg),
                str(cumulative_realized),
                _to_dt(fill.filled_at),
            )
            + params
            + (fill.symbol,),
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4()}"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _to_dt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def _as_utc(value: Any) -> datetime:
    """Coerce a DB DATETIME (mysql-connector returns naive) into UTC aware."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    # Some shims (sqlite test fake) return ISO strings.
    if isinstance(value, str):
        # Accept both "YYYY-MM-DD HH:MM:SS" and ISO "T" forms.
        raw = value.replace("T", " ")
        if "+" not in raw and "Z" not in raw:
            raw = raw + " +00:00"
            # Python fromisoformat wants T; normalize back:
            raw = raw.replace(" +00:00", "+00:00")
            raw = raw.replace(" ", "T", 1) if "T" not in raw else raw
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise PaperEngineError(f"cannot coerce {value!r} to a datetime")


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


_ORDER_COLUMNS = (
    "order_id",
    "run_id",
    "strategy_id",
    "account_id",
    "symbol",
    "side",
    "quantity",
    "order_type",
    "limit_price",
    "status",
    "submitted_at",
    "plan_id",
    "batch_sha256",
)


_FILL_COLUMNS = (
    "fill_id",
    "run_id",
    "strategy_id",
    "account_id",
    "order_id",
    "symbol",
    "side",
    "filled_qty",
    "price",
    "commission",
    "filled_at",
    "fill_mode",
)


def _row_values(row: Any, keys: Iterable[str]) -> tuple:
    """Fetch values from a row that may be tuple/list, sqlite3.Row, or dict.

    The MySQL cursor returns positional tuples by default; the SQLite
    test shim returns ``sqlite3.Row`` which supports both indexing modes.
    dict-cursor rows are also handled.
    """
    keys = tuple(keys)
    # dict-like access?
    try:
        return tuple(row[k] for k in keys)
    except (TypeError, KeyError, IndexError):
        pass
    # positional access based on the standard SELECT * ordering we use.
    # Callers must pass keys matching the SELECT column order.
    return tuple(row)


def _row_to_order(row: Any) -> PaperOrder:
    vals = _row_values(row, _ORDER_COLUMNS)
    (
        order_id,
        _run,
        _strat,
        account_id,
        symbol,
        side,
        quantity,
        order_type,
        limit_price,
        status,
        submitted_at,
        plan_id,
        batch_sha256,
    ) = vals
    return PaperOrder(
        order_id=order_id,
        account_id=account_id,
        symbol=symbol,
        side=Side(side),
        quantity=Decimal(quantity),
        order_type=order_type,  # type: ignore[arg-type]
        limit_price=Decimal(limit_price) if limit_price is not None else None,
        status=OrderStatus(status),
        submitted_at=_as_utc(submitted_at),
        plan_id=plan_id or "",
        batch_sha256=batch_sha256 or "",
    )


def _row_to_fill(row: Any) -> PaperFill:
    vals = _row_values(row, _FILL_COLUMNS)
    (
        fill_id,
        _run,
        _strat,
        _acct,
        order_id,
        symbol,
        side,
        filled_qty,
        price,
        commission,
        filled_at,
        _fill_mode,
    ) = vals
    return PaperFill(
        fill_id=fill_id,
        order_id=order_id,
        symbol=symbol,
        side=Side(side),
        filled_qty=Decimal(filled_qty),
        price=Decimal(price),
        commission=Decimal(commission),
        filled_at=_as_utc(filled_at),
    )


# Re-exported for ergonomics / test import parity.
__all__ = [
    "MysqlPaperEngine",
    "FillMode",
    "_PI_PAPER_ACCOUNT_DDL",
    "_PI_PAPER_ORDER_DDL",
    "_PI_PAPER_FILL_DDL",
    "_PI_PAPER_POSITION_DDL",
    "_PI_PAPER_LOT_DDL",
]


# Ensure `os` re-export lint is quiet if unused in future refactors.
_ = os
