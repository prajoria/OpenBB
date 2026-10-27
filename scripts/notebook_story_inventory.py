"""Source-only inventory of the notebook story corpus (#2211, N01).

Reads tracked notebooks as JSON, never as kernels: no notebook is executed or
imported, and saved outputs, execution counts and metadata are ignored. Each
story gets a source fingerprint over its ordered ``(cell_type, source_text)``
code and Markdown pairs, plus statically extracted call and import symbols
with one-based notebook cell positions. Source parse failures become explicit
diagnostics that name the cell position and error kind, never the cell text;
reviewed defects are classified in ``KNOWN_SOURCE_DEFECTS`` and anything else
is reported as unclassified.

Usage::

    python scripts/notebook_story_inventory.py --root notebooks \
        --check docs/cross_repo_workflow/notebook-mcp-story-inventory.csv

The command prints a JSON report and exits 1 when sources drift from the
reviewed inventory or an unclassified diagnostic appears.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

# Story folder -> (family root, provider variant). Both Portfolio folders tell
# the same stories with different providers, so they share a family.
STORY_FOLDERS: dict[str, tuple[str, str]] = {
    "portfolio": ("portfolio", "portfolio"),
    "portfolio_yfinance": ("portfolio", "free-provider"),
    "techtrade": ("techtrade", "techtrade"),
}

# Reviewed source defects, keyed by (path relative to the corpus root,
# one-based notebook cell position). Classifying a defect keeps it visible in
# the inventory without failing the drift check; it is never rewritten here.
KNOWN_SOURCE_DEFECTS: dict[tuple[str, int], str] = {
    ("techtrade/02-morning-scan.ipynb", 7): "narrative-in-code",
}

INVENTORY_PATH_PREFIX = "notebooks/"
_STORY_NUMBER = re.compile(r"^(\d{2})-")
_IPYTHON_LINE = re.compile(r"^\s*[%!]")


class NotebookInventoryError(ValueError):
    """Raised when a notebook cannot be inventoried safely."""


@dataclass(frozen=True)
class CellReference:
    """Safe symbols for one notebook cell, at its one-based position."""

    position: int
    cell_type: str
    calls: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceDiagnostic:
    """A code cell that could not be parsed statically."""

    position: int
    kind: str
    detail: str
    classification: str | None = None


@dataclass(frozen=True)
class NotebookSource:
    """Source-only identity of one notebook story."""

    path: str
    story_id: str
    family: str
    variant: str
    source_sha256: str
    code_cells: int
    markdown_cells: int
    cells: tuple[CellReference, ...]
    diagnostics: tuple[SourceDiagnostic, ...]

    @property
    def unclassified_diagnostics(self) -> tuple[SourceDiagnostic, ...]:
        """Diagnostics no reviewer has classified yet."""
        return tuple(d for d in self.diagnostics if d.classification is None)


@dataclass(frozen=True)
class Lineage:
    """Where the inventoried checkout sits relative to the integration base."""

    branch: str | None
    upstream: str | None
    head_sha: str
    base_ref: str
    base_sha: str | None


def _cell_source(cell: dict) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else str(source)


def source_fingerprint(pairs: Sequence[tuple[str, str]]) -> str:
    """Hash ordered ``(cell_type, source_text)`` pairs.

    The compact, non-ASCII-escaped JSON encoding matches the 2026-10-03 audit
    inventory, so audit hashes stay comparable.
    """
    payload = json.dumps(
        [[cell_type, text] for cell_type, text in pairs],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dotted_name(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or not parts:
        return None
    return ".".join([node.id, *reversed(parts)])


def _parse_code(text: str) -> ast.Module:
    # IPython magics and shell escapes are not Python; blank them so line
    # numbers stay aligned while the fingerprint still covers the raw text.
    lines = ["" if _IPYTHON_LINE.match(line) else line for line in text.splitlines()]
    return ast.parse("\n".join(lines))


def _code_reference(position: int, text: str) -> CellReference | SourceDiagnostic:
    try:
        tree = _parse_code(text)
    except SyntaxError as error:
        return SourceDiagnostic(
            position=position,
            kind="syntax_error",
            detail=f"line {error.lineno}",
        )
    calls: set[str] = set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted_name(node.func)
            if name:
                calls.add(name)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return CellReference(
        position=position,
        cell_type="code",
        calls=tuple(sorted(calls)),
        imports=tuple(sorted(imports)),
    )


def _story_identity(relative: str) -> tuple[str, str, str]:
    folder, _, filename = relative.partition("/")
    if folder not in STORY_FOLDERS or "/" in filename:
        raise NotebookInventoryError(
            f"{relative}: notebook is outside a reviewed story folder"
        )
    match = _STORY_NUMBER.match(filename)
    if match is None:
        raise NotebookInventoryError(f"{relative}: name lacks a two-digit story number")
    family_root, variant = STORY_FOLDERS[folder]
    number = match.group(1)
    return f"{folder}/{number}", f"{family_root}/{number}", variant


def inventory_notebook(path: Path, root: Path) -> NotebookSource:
    """Inventory one notebook without reading its outputs or metadata."""
    relative = path.relative_to(root).as_posix()
    story_id, family, variant = _story_identity(relative)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        cells = document["cells"]
        if not isinstance(cells, list):
            raise TypeError("cells is not a list")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise NotebookInventoryError(
            f"{relative}: not a readable notebook ({type(error).__name__})"
        ) from None
    pairs = []
    references = []
    diagnostics = []
    code_cells = markdown_cells = 0
    for position, cell in enumerate(cells, start=1):
        cell_type = cell.get("cell_type") if isinstance(cell, dict) else None
        if cell_type not in ("code", "markdown"):
            continue
        text = _cell_source(cell)
        pairs.append((cell_type, text))
        if cell_type == "markdown":
            markdown_cells += 1
            references.append(CellReference(position=position, cell_type="markdown"))
            continue
        code_cells += 1
        result = _code_reference(position, text)
        if isinstance(result, SourceDiagnostic):
            diagnostics.append(
                SourceDiagnostic(
                    position=result.position,
                    kind=result.kind,
                    detail=result.detail,
                    classification=KNOWN_SOURCE_DEFECTS.get((relative, position)),
                )
            )
            references.append(CellReference(position=position, cell_type="code"))
        else:
            references.append(result)
    return NotebookSource(
        path=relative,
        story_id=story_id,
        family=family,
        variant=variant,
        source_sha256=source_fingerprint(pairs),
        code_cells=code_cells,
        markdown_cells=markdown_cells,
        cells=tuple(references),
        diagnostics=tuple(diagnostics),
    )


def inventory_notebooks(root: Path) -> list[NotebookSource]:
    """Inventory every story notebook under ``root``, ordered by path."""
    root = Path(root)
    paths = sorted(
        path for path in root.rglob("*.ipynb") if ".ipynb_checkpoints" not in path.parts
    )
    return [inventory_notebook(path, root) for path in paths]


def compare_with_inventory(
    sources: Sequence[NotebookSource], inventory_csv: Path
) -> list[str]:
    """List stories that differ from the reviewed inventory CSV."""
    with Path(inventory_csv).open(encoding="utf-8", newline="") as stream:
        reviewed = {
            row["notebook_path"]: row["source_sha256"] for row in csv.DictReader(stream)
        }
    current = {
        f"{INVENTORY_PATH_PREFIX}{source.path}": source.source_sha256
        for source in sources
    }
    problems = []
    for path in sorted(set(reviewed) | set(current)):
        if path not in current:
            problems.append(f"missing: {path}")
        elif path not in reviewed:
            problems.append(f"unreviewed: {path}")
        elif current[path] != reviewed[path]:
            problems.append(f"changed: {path}")
    return problems


def _git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def repository_lineage(repo: Path, base_ref: str = "origin/portfolio") -> Lineage:
    """Record branch, upstream, head and merge-base SHAs independently."""
    head = _git(repo, "rev-parse", "HEAD")
    if head is None:
        raise NotebookInventoryError("repository HEAD cannot be resolved")
    branch = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    base = _git(repo, "merge-base", "HEAD", base_ref)
    return Lineage(
        branch=branch,
        upstream=upstream,
        head_sha=head,
        base_ref=base_ref,
        base_sha=base,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Print the inventory report; exit 1 on drift or unclassified defects."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("notebooks"))
    parser.add_argument("--check", type=Path, help="reviewed inventory CSV")
    args = parser.parse_args(argv)
    try:
        sources = inventory_notebooks(args.root)
    except NotebookInventoryError as error:
        print(json.dumps({"error": str(error)}))  # noqa: T201
        return 1
    drift = compare_with_inventory(sources, args.check) if args.check else []
    unclassified = [
        {"path": source.path, **asdict(diagnostic)}
        for source in sources
        for diagnostic in source.unclassified_diagnostics
    ]
    report = {
        "stories": len(sources),
        "families": len({source.family for source in sources}),
        "variants": sorted({source.variant for source in sources}),
        "classified_diagnostics": [
            {"path": source.path, **asdict(diagnostic)}
            for source in sources
            for diagnostic in source.diagnostics
            if diagnostic.classification is not None
        ],
        "unclassified_diagnostics": unclassified,
        "drift": drift,
    }
    print(json.dumps(report, indent=2, sort_keys=True))  # noqa: T201
    return 1 if drift or unclassified else 0


if __name__ == "__main__":
    sys.exit(main())
