#!/usr/bin/env python
r"""Widget registry drift guard for the VS Code Trading Terminal PRD.

Generates the Appendix A widget matrix as a Markdown table from a
widgets.json manifest, and optionally verifies that the PRD's checked-in
Appendix A section is up to date with the current widget registry.

Usage
-----
Generate a Markdown table from a static manifest and print to stdout::

    python scripts/generate_widget_matrix.py path/to/widgets.json

Generate from a live widget backend::

    python scripts/generate_widget_matrix.py --from-live http://127.0.0.1:6900

Verify the PRD's Appendix A matches the manifest (exit non-zero on drift)::

    python scripts/generate_widget_matrix.py path/to/widgets.json \\
        --check docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md

Refs #1811, #1807, #1806.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

APPENDIX_HEADER = "## Appendix A — Widget × Panel Mapping"
TABLE_HEADER = "| id | name | type | endpoint | category prefix |"
TABLE_SEP = "|----|------|------|----------|-----------------|"


def load_manifest(source: str) -> dict[str, Any]:
    """Load a widgets manifest from a filesystem path or an HTTP URL."""
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    else:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(
            f"expected widgets manifest to be a JSON object, got {type(data).__name__}"
        )
    return data


def category_prefix(category: str) -> str:
    """Return the leading category token used to bucket widgets."""
    if not category:
        return ""
    head = category.split("/", 1)[0].strip()
    return head or category.strip()


def render_matrix(manifest: dict[str, Any]) -> str:
    """Render a widgets manifest as an Appendix A Markdown table."""
    lines = [TABLE_HEADER, TABLE_SEP]
    for widget_id in sorted(manifest):
        entry = manifest[widget_id] or {}
        name = str(entry.get("name", "")).strip()
        wtype = str(entry.get("type", "")).strip()
        endpoint = str(entry.get("endpoint", "")).strip()
        prefix = category_prefix(str(entry.get("category", "")))
        lines.append(f"| `{widget_id}` | {name} | {wtype} | `{endpoint}` | {prefix} |")
    return "\n".join(lines) + "\n"


def extract_appendix(prd_text: str) -> str:
    """Extract the Appendix A section body from a PRD document."""
    pattern = re.compile(
        rf"^{re.escape(APPENDIX_HEADER)}\s*\n(.*?)(?=^## |\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(prd_text)
    if not match:
        raise ValueError(f"Appendix A header not found: {APPENDIX_HEADER!r}")
    return match.group(1)


def extract_table(section: str) -> str:
    """Extract the widget matrix Markdown table from an Appendix A section."""
    lines = section.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == TABLE_HEADER.strip():
            start = idx
            break
    if start is None:
        raise ValueError("Appendix A widget matrix table header not found")
    end = start
    for idx in range(start, len(lines)):
        if lines[idx].startswith("|"):
            end = idx
        else:
            break
    return "\n".join(lines[start : end + 1]) + "\n"


def check_prd(prd_path: Path, generated: str) -> int:
    """Compare the generated matrix to the PRD's Appendix A table."""
    prd_text = prd_path.read_text(encoding="utf-8")
    section = extract_appendix(prd_text)
    current = extract_table(section)
    if current == generated:
        return 0
    diff = difflib.unified_diff(
        current.splitlines(keepends=True),
        generated.splitlines(keepends=True),
        fromfile=f"{prd_path} (Appendix A)",
        tofile="generated",
    )
    sys.stdout.writelines(diff)
    return 1


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "manifest",
        nargs="?",
        help="Path to widgets.json manifest (omit if --from-live is set).",
    )
    parser.add_argument(
        "--from-live",
        dest="from_live",
        help="HTTP base URL of a running widget backend (e.g. http://127.0.0.1:6900).",
    )
    parser.add_argument(
        "--check",
        dest="check",
        help="Path to the PRD; compare Appendix A vs generated, exit non-zero on drift.",
    )
    return parser


def resolve_source(args: argparse.Namespace) -> str:
    """Resolve the manifest source from CLI arguments."""
    if args.from_live and args.manifest:
        raise SystemExit("error: pass either a manifest path or --from-live, not both")
    if args.from_live:
        base = args.from_live.rstrip("/")
        return f"{base}/widgets.json"
    if args.manifest:
        return args.manifest
    raise SystemExit("error: provide a manifest path or --from-live URL")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = build_parser().parse_args(argv)
    source = resolve_source(args)
    manifest = load_manifest(source)
    generated = render_matrix(manifest)
    if args.check:
        return check_prd(Path(args.check), generated)
    sys.stdout.write(generated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
