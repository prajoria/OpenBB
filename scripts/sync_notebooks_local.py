"""Sync notebooks/ -> notebooks_local/ for personal-data / kernel-restart
runs (#1460 defense-in-depth).

CLAUDE.md rule: **All local Run All / manual validation happens in
`notebooks_local/`, NEVER in the committed `notebooks/` tree.** This
script mirrors the committed source into the sandbox so a fresh
walkthrough can start there without touching the tracked copy.

Design:
- **One-way, additive.** Copies `notebooks/portfolio/**` and
  `notebooks/portfolio_yfinance/**` into `notebooks_local/portfolio/`
  and `notebooks_local/portfolio_yfinance/`. Never reads from
  `notebooks_local/` back into `notebooks/` — that direction is
  manual, per-file, with explicit review.
- **Preserves outputs on the destination side.** If a local sandbox
  copy already has real portfolio positions baked into outputs, we
  do NOT overwrite it silently; existing files with newer mtime win
  unless `--overwrite` is passed. Rationale: the operator may have
  a long-lived local run they don't want clobbered by a `git pull`.
- **Never syncs backwards.** The reverse — pulling redacted outputs
  back into `notebooks/` — must be a deliberate, per-file `cp` with
  the operator explicitly running
  `scripts/reset_notebooks_for_checkin.py` first. No automation.

Usage:
    python scripts/sync_notebooks_local.py            # additive sync
    python scripts/sync_notebooks_local.py --dry-run  # report only
    python scripts/sync_notebooks_local.py --overwrite  # force clobber

Exit code 0 always (this is a convenience, not a gate).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_TREES = [
    REPO_ROOT / "notebooks" / "portfolio",
    REPO_ROOT / "notebooks" / "portfolio_yfinance",
]
DST_ROOT = REPO_ROOT / "notebooks_local"


def _copy(src: Path, dst: Path, *, overwrite: bool, dry: bool) -> str:
    """Return one of: 'copied', 'updated', 'skipped-newer', 'unchanged'."""
    if not dst.exists():
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return "copied"
    src_mtime = src.stat().st_mtime
    dst_mtime = dst.stat().st_mtime
    if dst_mtime >= src_mtime and not overwrite:
        return "skipped-newer"
    if src_mtime == dst_mtime and src.stat().st_size == dst.stat().st_size:
        return "unchanged"
    if not dry:
        shutil.copy2(src, dst)
    return "updated"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Force clobber of destination even if newer. Use ONLY when you "
            "have verified the local sandbox does not contain unshipped "
            "personal-data outputs you want to keep."
        ),
    )
    args = parser.parse_args(argv)

    counts: dict[str, int] = {
        "copied": 0,
        "updated": 0,
        "skipped-newer": 0,
        "unchanged": 0,
    }

    for src_root in SRC_TREES:
        if not src_root.exists():
            continue
        rel_base = src_root.relative_to(REPO_ROOT / "notebooks")
        for src in sorted(src_root.rglob("*")):
            if src.is_dir():
                continue
            if ".ipynb_checkpoints" in src.parts:
                continue
            # Skip local sandbox scratchpads inside the source tree (shouldn't
            # exist, but be defensive).
            if ".notebook_state" in src.parts:
                continue
            rel = src.relative_to(src_root)
            dst = DST_ROOT / rel_base / rel
            outcome = _copy(src, dst, overwrite=args.overwrite, dry=args.dry_run)
            counts[outcome] += 1
            if outcome in {"copied", "updated"}:
                print(f"  {outcome:>13}  {dst.relative_to(REPO_ROOT)}")

    verb = "would" if args.dry_run else "did"
    print(
        f"\n{verb}: copied={counts['copied']} "
        f"updated={counts['updated']} "
        f"skipped-newer={counts['skipped-newer']} "
        f"unchanged={counts['unchanged']}"
    )
    if counts["skipped-newer"]:
        print(
            "  (--skipped-newer files kept because local mtime is newer. "
            "Pass --overwrite to force clobber; verify you have no local PII first.)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
