r"""Convert bare `#NNNN` issue refs in markdown cells / md files to
full GitHub URLs — one-shot rewrite for #1461.

Rules:
- Only touch `.ipynb` cells with `cell_type == "markdown"` and `.md` files.
- Never touch code cells or notebook `outputs`.
- Regex `(?<![\w/(\[])#(\d{2,5})(?!\w|\])` — skips:
  * `python3.10` / `sha1234` (word char before) — via `\w` in lookbehind
  * URL paths like `.../issues/1234)` (slash before / word after)
  * existing links `[#1234](...)` (bracket before, `]` after)
- Idempotent — a second run finds nothing to rewrite.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]

# Match `#NNNN` (2-5 digits) with strict boundaries.
# Negative lookbehind: skip when `[`, `(`, `/`, or word-char precedes the `#`.
#   `[` catches existing `[#1234](url)` markdown links.
#   `(` catches `(#1234)` fragment usage.
#   `/` catches URL paths (belt-and-suspenders vs the "issues/" prefix check).
#   `\w` catches things like `sha1234` / `python3.10` that already have digits.
# Negative lookahead: skip when `]` follows (existing link's closing bracket).
BARE_REF = re.compile(r"(?<![\w/(\[])#(\d{2,5})(?!\w|\])")
URL_TMPL = "https://github.com/prajoria/OpenBB/issues/{n}"


def _rewrite_text(src: str) -> tuple[str, int]:
    """Replace bare refs in a single markdown string. Return (new_text, count)."""
    count = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal count
        n = m.group(1)
        count += 1
        return f"[#{n}]({URL_TMPL.format(n=n)})"

    new = BARE_REF.sub(_sub, src)
    return new, count


def _rewrite_ipynb(path: Path, dry_run: bool) -> int:
    """Rewrite markdown cells in a .ipynb file. Returns count of replacements."""
    nb = json.loads(path.read_text(encoding="utf-8"))
    total = 0
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "markdown":
            continue
        src = cell.get("source", "")
        if isinstance(src, list):
            new_lines: list[str] = []
            for line in src:
                new_line, c = _rewrite_text(line)
                total += c
                new_lines.append(new_line)
            cell["source"] = new_lines
        elif isinstance(src, str):
            new_src, c = _rewrite_text(src)
            total += c
            cell["source"] = new_src
    if total and not dry_run:
        # Match the style reset_notebooks_for_checkin.py uses.
        path.write_text(
            json.dumps(nb, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return total


def _rewrite_md(path: Path, dry_run: bool) -> int:
    text = path.read_text(encoding="utf-8")
    new, count = _rewrite_text(text)
    if count and not dry_run:
        path.write_text(new, encoding="utf-8")
    return count


def _iter_targets(roots: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.ipynb")):
            if ".ipynb_checkpoints" in p.parts:
                continue
            out.append(p)
        for p in sorted(root.rglob("*.md")):
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts only; do not modify files.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=[
            str(REPO_ROOT / "notebooks" / "portfolio"),
            str(REPO_ROOT / "notebooks" / "portfolio_yfinance"),
        ],
        help="Directories or files to sweep (default: notebooks/portfolio and yfinance).",
    )
    args = parser.parse_args(argv)

    targets: list[Path] = []
    for p in args.paths:
        pp = Path(p)
        if pp.is_file():
            targets.append(pp)
        else:
            targets.extend(_iter_targets([pp]))

    grand_total = 0
    changed_files = 0
    for path in targets:
        if path.suffix == ".ipynb":
            n = _rewrite_ipynb(path, args.dry_run)
        elif path.suffix == ".md":
            n = _rewrite_md(path, args.dry_run)
        else:
            continue
        if n:
            print(f"  {n:4d}  {path.relative_to(REPO_ROOT)}")
            grand_total += n
            changed_files += 1

    verb = "would rewrite" if args.dry_run else "rewrote"
    print(f"\n{verb} {grand_total} bare-ref(s) across {changed_files} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
