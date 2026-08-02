"""One-shot SQLite -> MySQL positions backfill (#1744).

Reads every snapshot + positions row from a source SQLite DB and
INSERTs into the MySQL ``pi_snapshot`` / ``pi_position`` tables via
:class:`MySqlPortfolioStore`. Idempotent:

- ``pi_snapshot`` uses ``INSERT IGNORE`` on ``(source_sha256, user_id)``
  so re-running skips already-migrated snapshots.
- ``pi_position`` rows for a snapshot that's already been migrated are
  detected by the ``snapshot_exists`` probe and skipped as a group
  (positions inherit the snapshot's identity — no per-row hash).

Not designed for continuous dual-write. Run once after the operator
switches their default backend to MySQL; future imports go straight to
MySQL via the factory.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from portfolio_snapshot_importer.store import _POSITION_COLS, SqlitePortfolioStore

logger = logging.getLogger(__name__)


def backfill_sqlite_to_mysql(
    source_sqlite: Path,
    dry_run: bool = False,
    user_id: str | None = None,
    mysql_store: Any | None = None,
) -> dict[str, int]:
    """Copy every snapshot + positions from ``source_sqlite`` into MySQL.

    Args:
        source_sqlite: Path to the source SQLite ``positions.db``.
        dry_run: When ``True``, only counts rows without writing.
        user_id: When set, only backfill snapshots owned by this user.
        mysql_store: Optional injected store (for tests). Defaults to a
            fresh :class:`MySqlPortfolioStore` from the shared pool.

    Returns:
        Dict with ``snapshots``, ``positions``, ``skipped_existing``.

    Raises:
        FileNotFoundError: source SQLite doesn't exist.
    """
    if not source_sqlite.is_file():
        raise FileNotFoundError(f"source SQLite not found: {source_sqlite}")

    if mysql_store is None and not dry_run:
        from portfolio_snapshot_importer.mysql_store import (  # noqa: PLC0415
            MySqlPortfolioStore,
        )

        mysql_store = MySqlPortfolioStore()

    counts = {"snapshots": 0, "positions": 0, "skipped_existing": 0}

    src = SqlitePortfolioStore(source_sqlite)
    try:
        snapshots = src.list_snapshots(user_id=user_id)
        logger.info(
            "backfill: scanning %d snapshot(s) from %s%s",
            len(snapshots),
            source_sqlite,
            f" for user={user_id}" if user_id else "",
        )

        for snap in snapshots:
            meta = _row_to_dict(snap)
            source_sha = meta.get("source_sha256")
            uid = meta.get("user_id")
            if not source_sha or not uid:
                logger.warning(
                    "backfill: skipping snapshot %s (missing sha or user_id)",
                    meta.get("snapshot_id"),
                )
                continue

            if not dry_run:
                if mysql_store.snapshot_exists(source_sha, uid) is not None:
                    counts["skipped_existing"] += 1
                    continue

            # Read positions FIRST so we know how many rows we'd write.
            positions = [
                _row_to_position_dict(p) for p in src.positions_for(meta["snapshot_id"])
            ]

            if dry_run:
                counts["snapshots"] += 1
                counts["positions"] += len(positions)
                logger.info(
                    "backfill(dry-run): would import snapshot %s " "(%d positions)",
                    meta["snapshot_id"],
                    len(positions),
                )
                continue

            # Insert snapshot first (FK dependency), then positions.
            mysql_store.insert_snapshot(meta)
            n_written = mysql_store.insert_positions(positions)
            counts["snapshots"] += 1
            counts["positions"] += n_written
            logger.info(
                "backfill: imported snapshot %s (%d positions)",
                meta["snapshot_id"],
                n_written,
            )
    finally:
        src.close()

    return counts


def _row_to_dict(row: Any) -> dict:
    """Convert a sqlite3.Row (or dict) to a plain dict."""
    if isinstance(row, dict):
        return dict(row)
    return {k: row[k] for k in row.keys()}


def _row_to_position_dict(row: Any) -> dict:
    """Convert a SQLite position row into the shape MySqlPortfolioStore expects."""
    if isinstance(row, dict):
        base = dict(row)
    else:
        base = {k: row[k] for k in row.keys()}
    # Keep only the columns the target INSERT expects.
    return {k: base.get(k) for k in _POSITION_COLS}
