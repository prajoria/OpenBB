"""Reset Jupyter notebooks for check-in — strip state, keep outputs.

Per CLAUDE.md "Notebook check-in hygiene" (§X): before committing any
`.ipynb`, notebook-side state must be reset so re-executions in a fresh
kernel produce the same disk artifact. This script does the minimum
required strip without destroying the recorded outputs that
`test_notebooks_portfolio_smoke.py` verifies:

**Strips (deterministic)**
- Every code cell's `execution_count` → `None`
- `metadata.execution` (per-cell timing captured by nbclient)
- Top-level `metadata.language_info.version` (matches the kernel we
  happened to run against, not the reader's)
- Top-level `metadata.widgets` (Jupyter Lab widget state — leaks
  workspace-local IDs)

**Preserves**
- Every code cell's `outputs` list (readers browsing on GitHub see
  results without running anything; the smoke test enforces this)
- Markdown cells verbatim
- `cell_type`, `source`, `id`, and reader-visible metadata

Run before every `git commit` that touches a notebook:

    python scripts/reset_notebooks_for_checkin.py notebooks/portfolio/*.ipynb

or, pointed at a directory:

    python scripts/reset_notebooks_for_checkin.py --dir notebooks/portfolio/

Exit code 0 = clean; 1 = any file rewritten (informational, not an error);
2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _strip_cell(cell: dict) -> bool:
    """Return True if the cell was modified."""
    changed = False
    if cell.get("cell_type") == "code":
        if cell.get("execution_count") is not None:
            cell["execution_count"] = None
            changed = True
        meta = cell.setdefault("metadata", {})
        if "execution" in meta:
            del meta["execution"]
            changed = True
    return changed


def _strip_notebook(path: Path) -> bool:
    """Rewrite ``path`` in place if any state needed stripping."""
    text = path.read_text(encoding="utf-8")
    nb = json.loads(text)
    changed = False

    for cell in nb.get("cells", []):
        if _strip_cell(cell):
            changed = True

    meta = nb.setdefault("metadata", {})
    lang = meta.get("language_info")
    if isinstance(lang, dict) and "version" in lang:
        del lang["version"]
        changed = True
    if "widgets" in meta:
        del meta["widgets"]
        changed = True

    if changed:
        # Preserve trailing newline convention Jupyter uses.
        path.write_text(
            json.dumps(nb, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return changed


def _iter_notebook_paths(inputs: list[str], recursive_dir: str | None) -> list[Path]:
    paths: list[Path] = []
    if recursive_dir:
        paths.extend(sorted(Path(recursive_dir).rglob("*.ipynb")))
    for x in inputs:
        p = Path(x)
        if p.is_dir():
            paths.extend(sorted(p.rglob("*.ipynb")))
        else:
            paths.append(p)
    # Skip anything under .ipynb_checkpoints/ or .notebook_state/
    return [
        p for p in paths
        if ".ipynb_checkpoints" not in p.parts and ".notebook_state" not in p.parts
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="*", help="Notebook files or directories")
    parser.add_argument("--dir", dest="recursive_dir", default=None,
                        help="Recurse into this directory (glob *.ipynb)")
    parser.add_argument("--check", action="store_true",
                        help="Exit non-zero if any file would be rewritten "
                             "(does NOT modify anything). Useful in pre-commit hooks.")
    args = parser.parse_args(argv)

    paths = _iter_notebook_paths(args.paths, args.recursive_dir)
    if not paths:
        print("no notebook paths given", file=sys.stderr)
        return 2

    would_change: list[Path] = []
    for p in paths:
        if not p.is_file():
            print(f"skip: {p} not a file", file=sys.stderr)
            continue
        if args.check:
            # Simulate without writing.
            text = p.read_text(encoding="utf-8")
            nb = json.loads(text)
            dirty = False
            for cell in nb.get("cells", []):
                if cell.get("cell_type") == "code" and cell.get("execution_count") is not None:
                    dirty = True
                    break
                if isinstance(cell.get("metadata"), dict) and "execution" in cell["metadata"]:
                    dirty = True
                    break
            meta = nb.get("metadata", {})
            lang = meta.get("language_info", {}) if isinstance(meta, dict) else {}
            if isinstance(lang, dict) and "version" in lang:
                dirty = True
            if isinstance(meta, dict) and "widgets" in meta:
                dirty = True
            if dirty:
                would_change.append(p)
        else:
            if _strip_notebook(p):
                would_change.append(p)

    if args.check:
        if would_change:
            print("Notebooks with unstripped state (run without --check to fix):")
            for p in would_change:
                print(f"  {p}")
            return 1
        return 0

    if would_change:
        print(f"Stripped state from {len(would_change)} notebook(s):")
        for p in would_change:
            print(f"  {p}")
    else:
        print("All notebooks already clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
