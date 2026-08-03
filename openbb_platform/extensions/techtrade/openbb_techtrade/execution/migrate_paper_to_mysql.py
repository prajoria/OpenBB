r"""One-shot migration: SQLite paper.db -> MySQL pi_paper_* (#1790).

Usage::

    python -m openbb_techtrade.execution.migrate_paper_to_mysql \\
        --from ~/.portfolio_intel/paper.db [--dry-run] \\
        [--run-id live] [--strategy-id default]

Reads every ``pi_paper_*`` row from the source SQLite DB and inserts
into MySQL under ``(run_id, strategy_id, account_id=<source>)``.

Idempotent: uses ``INSERT IGNORE`` so re-running the migration on the
same source is safe.

Prints per-table row counts. ``--dry-run`` skips the writes but still
counts + validates connectivity.
"""

# ruff: noqa: S608, T201
# S608: only allow-listed table names are interpolated (see _TABLES).
# T201: this is a CLI script; print() is the expected output channel.

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbb_techtrade.execution.mysql_paper_engine import MysqlPaperEngine

logger = logging.getLogger(__name__)


_TABLES = (
    "pi_paper_account",
    "pi_paper_order",
    "pi_paper_fill",
    "pi_paper_position",
    "_pi_paper_lot",
)


def _read_all(src: Path, table: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(src))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM {table}")  # noqa: S608 — table name is allow-listed
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _iso(value: Any) -> Any:
    """SQLite stores TEXT ISO timestamps; MySQL wants DATETIME strings."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    if isinstance(value, str):
        # Round-trip parse for validation.
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def migrate(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    src: Path,
    run_id: str = "live",
    strategy_id: str = "default",
    dry_run: bool = False,
    connection_pool: Any = None,
) -> dict[str, int]:
    """Run the migration; return {table: rows_written}."""
    if not src.exists():
        raise FileNotFoundError(f"source SQLite DB not found: {src}")

    # Bootstrap the MySQL schema (uses the engine's DDL).
    if connection_pool is None:
        # pylint: disable=import-outside-toplevel
        from openbb_fmp_cached.utils.database import (  # noqa: PLC0415
            get_connection_pool,
        )

        connection_pool = get_connection_pool()

    # Instantiate an engine just to run _ensure_schema; the account row
    # this may seed is harmless (INSERT IGNORE below preserves the real
    # migrated rows).
    _ = MysqlPaperEngine(
        connection_pool=connection_pool,
        run_id=run_id,
        strategy_id=strategy_id,
        account_id="__migration_bootstrap__",
    )

    counts: dict[str, int] = {}
    for table in _TABLES:
        try:
            rows = _read_all(src, table)
        except sqlite3.OperationalError as exc:
            logger.warning("skip %s (not present in source): %s", table, exc)
            counts[table] = 0
            continue

        if dry_run:
            logger.info("[dry-run] %s: %d rows would be migrated", table, len(rows))
            counts[table] = len(rows)
            continue

        conn = connection_pool.get_connection()
        try:
            cur = conn.cursor()
            written = 0
            for row in rows:
                written += _insert_row(cur, table, row, run_id, strategy_id)
            conn.commit()
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        counts[table] = written
        logger.info("%s: %d rows migrated", table, written)

    return counts


def _insert_row(  # pylint: disable=too-many-return-statements,too-many-branches
    cur: Any, table: str, row: dict[str, Any], run_id: str, strategy_id: str
) -> int:
    """Insert one SQLite row into the MySQL table with scope columns added.

    Returns 1 if inserted, 0 if the row already existed (INSERT IGNORE).
    """
    if table == "pi_paper_account":
        cur.execute(
            "INSERT IGNORE INTO pi_paper_account "
            "(run_id, strategy_id, account_id, starting_cash, cash, "
            "realized_pl, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                run_id,
                strategy_id,
                row["account_id"],
                row["starting_cash"],
                row["cash"],
                row["realized_pl"],
                _iso(row["created_at"]),
            ),
        )
    elif table == "pi_paper_order":
        cur.execute(
            "INSERT IGNORE INTO pi_paper_order "
            "(order_id, run_id, strategy_id, account_id, symbol, side, "
            "quantity, order_type, limit_price, status, submitted_at, "
            "plan_id, batch_sha256) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                row["order_id"],
                run_id,
                strategy_id,
                row["account_id"],
                row["symbol"],
                row["side"],
                row["quantity"],
                row["order_type"],
                row["limit_price"],
                row["status"],
                _iso(row["submitted_at"]),
                row.get("plan_id") or "",
                row.get("batch_sha256") or "",
            ),
        )
    elif table == "pi_paper_fill":
        cur.execute(
            "INSERT IGNORE INTO pi_paper_fill "
            "(fill_id, run_id, strategy_id, account_id, order_id, symbol, "
            "side, filled_qty, price, commission, filled_at, fill_mode) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                row["fill_id"],
                run_id,
                strategy_id,
                # SQLite fills don't carry account_id — join via order_id
                # is idiomatic. For the migration we need it; look it up.
                _account_for_order(cur, row["order_id"], run_id, strategy_id)
                or "paper",
                row["order_id"],
                row["symbol"],
                row["side"],
                row["filled_qty"],
                row["price"],
                row["commission"],
                _iso(row["filled_at"]),
                "OPERATOR_RECORDED",
            ),
        )
    elif table == "pi_paper_position":
        cur.execute(
            "INSERT IGNORE INTO pi_paper_position "
            "(run_id, strategy_id, account_id, symbol, quantity, avg_cost, "
            "realized_pl, last_updated) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                run_id,
                strategy_id,
                row["account_id"],
                row["symbol"],
                row["quantity"],
                row["avg_cost"],
                row["realized_pl"],
                _iso(row["last_updated"]),
            ),
        )
    elif table == "_pi_paper_lot":
        cur.execute(
            "INSERT IGNORE INTO _pi_paper_lot "
            "(lot_id, run_id, strategy_id, account_id, symbol, qty, "
            "cost_per_unit, opened_at, opening_fill_id, closed_at, "
            "closing_fill_id) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                row["lot_id"],
                run_id,
                strategy_id,
                row["account_id"],
                row["symbol"],
                row["qty"],
                row["cost_per_unit"],
                _iso(row["opened_at"]),
                row["opening_fill_id"],
                _iso(row.get("closed_at")),
                row.get("closing_fill_id"),
            ),
        )
    else:
        return 0
    # Approximate row-changed count via cursor.rowcount when the driver
    # exposes it; treat unknown as 1.
    changed = getattr(cur, "rowcount", 1)
    return 1 if changed in (-1, None) else max(int(changed), 0)


def _account_for_order(
    cur: Any, order_id: str, run_id: str, strategy_id: str
) -> str | None:
    cur.execute(
        "SELECT account_id FROM pi_paper_order WHERE run_id=%s "
        "AND strategy_id=%s AND order_id=%s",
        (run_id, strategy_id, order_id),
    )
    row = cur.fetchone()
    if row is None:
        return None
    if isinstance(row, (tuple, list)):
        return row[0]
    return row.get("account_id") if hasattr(row, "get") else row[0]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="migrate_paper_to_mysql",
        description=(
            "Migrate a SQLite paper.db into the MySQL pi_paper_* tables "
            "under a chosen (run_id, strategy_id) scope."
        ),
    )
    parser.add_argument("--from", dest="src", required=True, type=Path)
    parser.add_argument("--run-id", default="live")
    parser.add_argument("--strategy-id", default="default")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    counts = migrate(
        src=args.src.expanduser(),
        run_id=args.run_id,
        strategy_id=args.strategy_id,
        dry_run=args.dry_run,
    )
    total = sum(counts.values())
    print(f"Migration {'(dry-run) ' if args.dry_run else ''}complete: {total} rows")
    for table, n in counts.items():
        print(f"  {table}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
