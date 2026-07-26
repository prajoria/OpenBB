"""scrape-record CLI — record / replay / list / config / verify.

Usage examples::

    scrape-record record yahoo_options_chain --symbol AAPL
    scrape-record replay yahoo_options_chain --symbol AAPL
    scrape-record list
    scrape-record verify yahoo_options_chain --symbol AAPL
    scrape-record config
"""

# pylint: disable=unused-argument

from __future__ import annotations

import argparse
import json
import sys

from scrape_record.config import ConfigError, load_config, snapshot_path
from scrape_record.extract import verify_snapshot
from scrape_record.record import (
    RecordError,
    SnapshotEnvelope,
    load_snapshot,
    run_recording,
)
from scrape_record.replay import run_replay
from scrape_record.store import SnapshotStore


def _cmd_config(args: argparse.Namespace) -> int:
    cfg = load_config()
    print(cfg.summary())
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    cfg = load_config()
    print(f"[record] {args.name} / {args.symbol}")
    print(f"[record] snapshot -> {snapshot_path(cfg, args.name, args.symbol)}")
    out = run_recording(cfg, args.name, args.symbol, also_extract=not args.no_extract)
    print(f"[record] wrote {out} ({out.stat().st_size} bytes)")
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    cfg = load_config()
    out = run_replay(cfg, args.name, args.symbol, also_extract=not args.no_extract)
    print(f"[replay] refreshed {out}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    cfg = load_config()
    if not cfg.snapshots_dir.exists():
        print(f"[list] snapshots_dir does not exist yet: {cfg.snapshots_dir}")
        return 0
    rows = []
    for name_dir in sorted(cfg.snapshots_dir.iterdir()):
        if not name_dir.is_dir():
            continue
        for snap in sorted(name_dir.glob("*.json")):
            rows.append((name_dir.name, snap.stem, snap.stat().st_size))
    if not rows:
        print("[list] no snapshots on disk")
        return 0
    print(f"{'recording':<40} {'symbol':<12} {'bytes':>10}")
    for name, sym, size in rows:
        print(f"{name:<40} {sym:<12} {size:>10}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    cfg = load_config()
    env = load_snapshot(cfg, args.name, args.symbol)
    result = verify_snapshot(args.name, env.raw)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def _cmd_migrate(args: argparse.Namespace) -> int:
    """Import every legacy ``snapshots/**/*.json`` into the user-local DB.

    Idempotent (upserts on ``(name, symbol)``). Files that fail to parse
    are kept in place and reported with ``provenance: needs-review``.
    """
    cfg = load_config()
    root = cfg.snapshots_dir
    if not root.exists():
        print(f"[migrate] snapshots_dir does not exist: {root} — nothing to do.")
        return 0

    files = sorted(root.glob("*/*.json"))
    if not files:
        print(f"[migrate] no legacy JSON snapshots under {root} — nothing to do.")
        return 0

    print(
        f"[migrate] {'DRY RUN — ' if args.dry_run else ''}"
        f"importing {len(files)} legacy files -> {cfg.db_path}"
    )

    ok = 0
    bad: list[tuple[Path, str]] = []
    store = None
    if not args.dry_run:
        store = SnapshotStore(cfg.db_path)
    try:
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                env = SnapshotEnvelope(**data)
            except Exception as exc:  # pylint: disable=broad-except
                bad.append((path, str(exc)))
                continue
            if store is not None:
                store.upsert(env)
            ok += 1
    finally:
        if store is not None:
            store.close()

    print(f"[migrate] imported: {ok} / {len(files)}")
    if bad:
        print(
            f"[migrate] {len(bad)} file(s) failed to parse (kept in place, "
            "provenance: needs-review):"
        )
        for path, err in bad:
            print(f"  - {path.relative_to(cfg.repo_root)}: {err}")
    return 1 if bad else 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argparse parser."""
    p = argparse.ArgumentParser(
        prog="scrape-record",
        description="Record/replay/correct browser scrapes for offline provider snapshots.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_config = sub.add_parser("config", help="Print resolved config paths.")
    p_config.set_defaults(func=_cmd_config)

    p_record = sub.add_parser("record", help="Run a recording; save the snapshot.")
    p_record.add_argument("name", help="Recording name (matches recordings/<name>.py)")
    p_record.add_argument(
        "--symbol", required=True, help="Symbol/instrument to capture"
    )
    p_record.add_argument(
        "--no-extract",
        action="store_true",
        help="Skip running the extractor after capture; store raw only.",
    )
    p_record.set_defaults(func=_cmd_record)

    p_replay = sub.add_parser("replay", help="Alias of `record` — refresh a snapshot.")
    p_replay.add_argument("name")
    p_replay.add_argument("--symbol", required=True)
    p_replay.add_argument("--no-extract", action="store_true")
    p_replay.set_defaults(func=_cmd_replay)

    p_list = sub.add_parser("list", help="List all snapshots on disk.")
    p_list.set_defaults(func=_cmd_list)

    p_verify = sub.add_parser(
        "verify", help="Dry-run an extractor against an existing snapshot."
    )
    p_verify.add_argument("name")
    p_verify.add_argument("--symbol", required=True)
    p_verify.set_defaults(func=_cmd_verify)

    p_migrate = sub.add_parser(
        "migrate",
        help="Import legacy snapshots/**/*.json into the user-local DB.",
    )
    p_migrate.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be imported without writing the DB.",
    )
    p_migrate.set_defaults(func=_cmd_migrate)

    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (ConfigError, RecordError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
