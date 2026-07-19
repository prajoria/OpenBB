"""Command-line entry point for portfolio_export."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from portfolio_export.config import ConfigError, load_config
from portfolio_export.record import run_record
from portfolio_export.replay import ReplayError, run_replay
from portfolio_export.tagger import TaggerError, tag_csv


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="portfolio-export",
        description=(
            "Strict record-and-replay for broker web sessions. "
            "Downloads are forced OUTSIDE the source repo."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    rec = sub.add_parser(
        "record",
        help="Open Chromium + Playwright Inspector to record a flow.",
    )
    rec.add_argument("name", help="Recording name (file will be recordings/<name>.py).")
    rec.add_argument(
        "--url",
        required=True,
        help="Initial URL to load in the browser (e.g. https://digital.fidelity.com/).",
    )

    rep = sub.add_parser(
        "replay",
        help="Replay a saved recording deterministically.",
    )
    rep.add_argument("name", help="Recording name to replay (recordings/<name>.py).")
    rep.add_argument(
        "--user",
        "-u",
        default=None,
        help=(
            "Optional short user label (safe chars: [A-Za-z0-9_.-]). "
            "When set, each downloaded .csv is auto-tagged: a `user_id` "
            "column is appended and the file renamed to <stem>_<user>.csv. "
            "Original untagged file is removed."
        ),
    )

    tag = sub.add_parser(
        "tag",
        help=(
            "Add a `user_id` column to an existing broker CSV and rename "
            "it to <stem>_<user>.csv."
        ),
    )
    tag.add_argument("path", help="Path to the CSV to tag.")
    tag.add_argument(
        "--user",
        "-u",
        required=True,
        help="User label (safe chars: [A-Za-z0-9_.-], max 64).",
    )
    tag.add_argument(
        "--output",
        default=None,
        help="Explicit output path (default: <stem>_<user>.csv in same dir).",
    )
    tag.add_argument(
        "--replace",
        action="store_true",
        help="Delete the untagged original after successful tagging.",
    )

    csvs = sub.add_parser(
        "csvs",
        help="List downloaded CSV exports (metadata only).",
    )
    csvs.add_argument(
        "--dir",
        default=None,
        help=(
            "Directory to scan (default: the configured download_dir)."
        ),
    )
    csvs.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only scan the top-level directory, do not recurse.",
    )

    inspect = sub.add_parser(
        "inspect",
        help=(
            "Load a CSV through the Fidelity loader and print schema "
            "+ aggregate counts (never row content). Requires the "
            "[loaders] extra (pandas)."
        ),
    )
    inspect.add_argument("path", help="Path to the CSV to inspect.")

    sub.add_parser("list", help="List available recordings.")
    sub.add_parser("status", help="Show resolved config paths and validation status.")

    return p


def _cmd_list(cfg) -> int:
    def _entries(d):
        if not d.exists():
            return []
        return sorted(
            f.stem for f in d.glob("*.py") if f.name not in {"__init__.py"}
        )

    user = _entries(cfg.user_recordings_dir)
    bundled = _entries(cfg.bundled_recordings_dir)

    print(f"User recordings   ({cfg.user_recordings_dir}):")
    if user:
        for r in user:
            print(f"  {r}")
    else:
        print("  (none)")

    print(f"Bundled examples  ({cfg.bundled_recordings_dir}):")
    if bundled:
        for r in bundled:
            print(f"  {r}")
    else:
        print("  (none)")

    if not user and not bundled:
        print("\nNo recordings found. Run: pe record <name> --url <url>")
    return 0


def _cmd_status(cfg) -> int:
    print(cfg.summary())
    print()
    print("All paths validated OUTSIDE the repo. OK.")
    return 0


def _cmd_tag(args) -> int:
    from pathlib import Path as _P

    try:
        out_path, n = tag_csv(
            args.path,
            args.user,
            output_path=args.output,
            delete_original=args.replace,
        )
    except TaggerError as exc:
        print(f"[tag error] {exc}", file=sys.stderr)
        return 4

    print(f"[tag] wrote        : {out_path}")
    print(f"[tag] rows tagged  : {n}")
    if args.replace:
        print(f"[tag] removed input: {_P(args.path)}")
    return 0


def _cmd_csvs(cfg, args) -> int:
    from pathlib import Path as _P

    from portfolio_export.discover import find_csvs

    root = _P(args.dir) if args.dir else cfg.download_dir
    entries = find_csvs(root, recursive=not args.no_recursive)

    print(f"[csvs] scan root : {root}")
    print(f"[csvs] found     : {len(entries)} file(s)")
    if not entries:
        return 0
    print()
    print(f"{'user_id':<12} {'lines':>7} {'size_kb':>9}  path")
    print("-" * 78)
    for e in entries:
        uid = e.user_id or "(none)"
        kb = e.size_bytes / 1024
        print(f"{uid:<12} {e.line_count:>7} {kb:>9.1f}  {e.path}")
    return 0


def _cmd_inspect(args) -> int:
    from pathlib import Path as _P

    try:
        from portfolio_export.loaders.fidelity import describe, load_positions
    except ImportError as exc:
        print(
            f"[inspect error] pandas not installed. Run:\n"
            f"  pip install -e .[loaders]\n"
            f"(underlying error: {exc})",
            file=sys.stderr,
        )
        return 5

    path = _P(args.path)
    if not path.is_file():
        print(f"[inspect error] file not found: {path}", file=sys.stderr)
        return 4

    try:
        df = load_positions(path)
    except Exception as exc:
        print(
            f"[inspect error] load_positions failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 4

    info = describe(df)
    print(f"[inspect] file  : {path}")
    print(f"[inspect] shape : {info['shape']['rows']} rows x {info['shape']['cols']} cols")
    print("[inspect] columns (name -> dtype):")
    for name, dtype in info["columns"].items():
        print(f"  {name:<30} {dtype}")
    if "accounts" in info:
        print(f"[inspect] accounts : {info['accounts']['count']} distinct")
        for acct, rows in info["accounts"]["rows_per_account"].items():
            print(f"  {acct}: {rows} row(s)")
    if "type_breakdown" in info:
        print("[inspect] type breakdown:")
        for t, rows in info["type_breakdown"].items():
            print(f"  {t}: {rows}")
    if "user_id_values" in info:
        print(f"[inspect] user_id values: {info['user_id_values']}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"[config error] {exc}", file=sys.stderr)
        return 2

    try:
        if args.command == "record":
            return run_record(cfg, args.name, args.url)
        if args.command == "replay":
            return run_replay(cfg, args.name, user_id=args.user)
        if args.command == "list":
            return _cmd_list(cfg)
        if args.command == "status":
            return _cmd_status(cfg)
        if args.command == "tag":
            return _cmd_tag(args)
        if args.command == "csvs":
            return _cmd_csvs(cfg, args)
        if args.command == "inspect":
            return _cmd_inspect(args)
    except ReplayError as exc:
        print(f"[replay error] {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\n[abort] interrupted", file=sys.stderr)
        return 130

    parser.error(f"unknown command: {args.command}")
    return 2  # unreachable, keeps type checkers happy


if __name__ == "__main__":
    raise SystemExit(main())
