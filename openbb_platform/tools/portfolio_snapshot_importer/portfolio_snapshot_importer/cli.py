"""CLI for the portfolio snapshot importer.

Usage:

    portfolio-snapshot-import <path> [<path> ...] [--db PATH] [--user-id NAME]
    portfolio-snapshot-import --folder DIR [--db PATH] [--user-id NAME]
    portfolio-snapshot-import list [--db PATH] [--user-id NAME]
    portfolio-snapshot-import show SNAPSHOT_ID [--db PATH]
    portfolio-snapshot-import basket ... (see subcommand help)
    portfolio-snapshot-import backfill-to-mysql --from PATH [--dry-run]

Default DB: ``~/.portfolio_importer/positions.db``. The DB path MUST NOT sit
inside the repo checkout (defense-in-depth against committing brokerage
data; see CLAUDE.md).

Backend selection (#1744):

- ``--store mysql`` (or env ``PI_PORTFOLIO_STORE=mysql``) — canonical.
- ``--store sqlite`` — offline fallback; uses ``--db`` path.
- Omitted: default is MySQL if available, else SQLite with WARNING.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from portfolio_snapshot_importer.basket_bridge import write_basket_json
from portfolio_snapshot_importer.ingest import (
    IngestReport,
    import_files,
    import_folder,
)
from portfolio_snapshot_importer.store import (
    DEFAULT_SQLITE_PATH,
    PortfolioStore,
    SqlitePortfolioStore,
    get_default_store,
)

DEFAULT_DB = DEFAULT_SQLITE_PATH  # kept for backwards compat


class ConfigError(RuntimeError):
    pass


def _validate_db_outside_repo(db_path: Path) -> None:
    """Refuse a DB path that sits under the git repo root."""
    resolved = db_path.resolve()
    # Walk up from here looking for the git root; if the DB is under it, bail.
    cur = Path(__file__).resolve()
    for parent in (cur, *cur.parents):
        if (parent / ".git").is_dir():
            repo_root = parent
            break
    else:
        return  # not in a git checkout, no rule to enforce
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        return  # outside repo — OK
    raise ConfigError(
        f"DB path {resolved} is inside the git repo at {repo_root}. "
        "Brokerage data must live outside the repo (see CLAUDE.md). "
        "Use --db ~/.portfolio_importer/positions.db or a path under H:\\masterswork\\ etc."
    )


def _print_report(report: IngestReport, verbose: bool) -> None:
    for r in report.results:
        tag = {
            "imported": "IMPORTED",
            "duplicate": "DUP",
            "skipped_unrecognized": "SKIP",
            "skipped_no_positions": "SKIP",
            "error": "ERR",
        }.get(r.status, r.status.upper())
        line = f"  [{tag:<9}] {r.path.name}"
        if r.snapshot_date:
            line += f"  date={r.snapshot_date}"
        if r.user_id:
            line += f"  user={r.user_id}"
        if r.status == "imported":
            line += f"  kept={r.row_count_kept}/{r.row_count_raw}"
            if r.row_count_skipped:
                line += f"  bad_rows={r.row_count_skipped}"
        if verbose and r.message:
            line += f"  — {r.message}"
        print(line)

    print(
        f"\nSummary: imported={report.imported}  "
        f"duplicates={report.duplicates}  "
        f"skipped={report.skipped}  "
        f"errors={report.errors}"
    )


def _resolve_store(args: argparse.Namespace) -> PortfolioStore:
    """Instantiate the requested backend (per #1744).

    Precedence: ``--store`` flag → ``PI_PORTFOLIO_STORE`` env → default.
    SQLite path is validated to sit outside the repo.
    """
    prefer = getattr(args, "store", None) or None
    if prefer == "sqlite" or (prefer is None and _sqlite_forced_by_env()):
        db = Path(args.db)
        _validate_db_outside_repo(db)
        return SqlitePortfolioStore(db)
    return get_default_store(prefer=prefer, sqlite_path=Path(args.db))


def _sqlite_forced_by_env() -> bool:
    return os.environ.get("PI_PORTFOLIO_STORE", "").strip().lower() == "sqlite"


def _cmd_import(args: argparse.Namespace) -> int:
    with _resolve_store(args) as store:
        if args.folder:
            report = import_folder(
                args.folder, store=store, user_id_fallback=args.user_id
            )
        else:
            report = import_files(
                args.paths, store=store, user_id_fallback=args.user_id
            )
    _print_report(report, verbose=args.verbose)
    return 0 if report.errors == 0 else 1


def _cmd_list(args: argparse.Namespace) -> int:
    with _resolve_store(args) as store:
        rows = store.list_snapshots(user_id=args.user_id)
        if not rows:
            print("(no snapshots)")
            return 0
        print(f"{'snapshot_id':<34} {'date':<12} {'user':<20} {'kept':>6} {'file'}")
        print("-" * 100)
        for r in rows:
            print(
                f"{r['snapshot_id']:<34} {r['snapshot_date']:<12} "
                f"{r['user_id']:<20} {r['row_count_kept']:>6}  {r['source_filename']}"
            )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    with _resolve_store(args) as store:
        rows = store.positions_for(args.snapshot_id)
        if not rows:
            print(f"(no positions for snapshot {args.snapshot_id})")
            return 0
        print(
            f"{'account_number':<14} {'symbol':<8} {'type':<10} "
            f"{'qty':>10} {'value':>12} {'pct':>6}"
        )
        print("-" * 70)
        for r in rows:
            pct = f"{(r['percent_of_account'] or 0) * 100:>5.2f}%"
            print(
                f"{(r['account_number'] or '')[:14]:<14} "
                f"{(r['symbol'] or '')[:8]:<8} "
                f"{(r['type'] or '')[:10]:<10} "
                f"{(r['quantity'] or 0):>10.3f} "
                f"{(r['current_value'] or 0):>12,.2f} "
                f"{pct:>6}"
            )
    return 0


def _cmd_basket(args: argparse.Namespace) -> int:
    with _resolve_store(args) as store:
        try:
            basket = write_basket_json(
                store,
                out_path=args.out,
                user_id=args.user_id,
                snapshot_date=args.snapshot_date,
                include_cash=args.include_cash,
                account_number=args.account_number,
                top_n=args.top_n,
            )
        except LookupError as exc:
            print(f"lookup error: {exc}", file=sys.stderr)
            return 4
    meta = basket["metadata"]
    print(
        f"Wrote basket to {args.out}\n"
        f"  user_id     : {meta['user_id']}\n"
        f"  snapshot    : {meta['snapshot_date']} (id {meta['snapshot_id'][:12]}…)\n"
        f"  positions   : {meta['n_positions_in_basket']} of {meta['n_positions_in_snapshot']} in snapshot"
    )
    return 0


def _cmd_backfill_to_mysql(args: argparse.Namespace) -> int:
    """One-shot SQLite → MySQL migration (#1744).

    Reads every snapshot from the source SQLite DB, INSERT IGNOREs into
    ``pi_snapshot``, then INSERTs each snapshot's positions into
    ``pi_position``. Idempotent — re-running is safe. On any error the
    exit code is non-zero and the exception is printed.
    """
    from portfolio_snapshot_importer.backfill import (  # noqa: PLC0415
        backfill_sqlite_to_mysql,
    )

    src = Path(args.source).expanduser()
    if not src.is_file():
        print(f"source SQLite DB not found: {src}", file=sys.stderr)
        return 5

    try:
        result = backfill_sqlite_to_mysql(
            source_sqlite=src,
            dry_run=args.dry_run,
            user_id=args.user_id,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"backfill failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        f"backfill{' (dry-run)' if args.dry_run else ''}: "
        f"snapshots={result['snapshots']} positions={result['positions']} "
        f"skipped={result['skipped_existing']}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="portfolio-snapshot-import")
    p.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"SQLite DB path (default: {DEFAULT_DB})",
    )
    p.add_argument(
        "--store",
        choices=["mysql", "sqlite"],
        default=None,
        help=(
            "Backend selection (#1744). Default: MySQL if reachable, else "
            "SQLite fallback. Env var: PI_PORTFOLIO_STORE."
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=False)

    imp = sub.add_parser("import", help="Import one or more CSV files")
    imp.add_argument("paths", nargs="*", type=Path)
    imp.add_argument("--folder", type=Path, help="Recursively import from folder")
    imp.add_argument(
        "--user-id",
        dest="user_id",
        default=None,
        help="Fallback user_id if filename lacks the suffix",
    )
    imp.set_defaults(func=_cmd_import)

    ls = sub.add_parser("list", help="List snapshots in the store")
    ls.add_argument("--user-id", dest="user_id", default=None)
    ls.set_defaults(func=_cmd_list)

    sh = sub.add_parser("show", help="Print positions for a snapshot_id")
    sh.add_argument("snapshot_id")
    sh.set_defaults(func=_cmd_show)

    bk = sub.add_parser("basket", help="Emit a basket.json for notebook consumers")
    bk.add_argument("--user-id", dest="user_id", required=True)
    bk.add_argument(
        "--snapshot-date",
        dest="snapshot_date",
        default=None,
        help="YYYY-MM-DD; defaults to latest snapshot for the user",
    )
    bk.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output basket.json path (typically .notebook_state/basket.json)",
    )
    bk.add_argument("--account-number", dest="account_number", default=None)
    bk.add_argument(
        "--include-cash",
        action="store_true",
        help="Keep SPAXX/FCASH-style money-market rows in the basket",
    )
    bk.add_argument("--top-n", dest="top_n", type=int, default=None)
    bk.set_defaults(func=_cmd_basket)

    bf = sub.add_parser(
        "backfill-to-mysql",
        help="One-shot SQLite -> MySQL migration (#1744)",
    )
    bf.add_argument(
        "--source",
        "--from",
        dest="source",
        type=str,
        required=True,
        help="Source SQLite DB path (typically ~/.portfolio_importer/positions.db)",
    )
    bf.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts without writing to MySQL",
    )
    bf.add_argument(
        "--user-id",
        dest="user_id",
        default=None,
        help="If set, only backfill snapshots for this user_id",
    )
    bf.set_defaults(func=_cmd_backfill_to_mysql)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
