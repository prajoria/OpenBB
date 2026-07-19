"""discover.py — enumerate downloaded broker exports.

Metadata-only. Never opens or reads file contents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Filename convention:
#   Portfolio_Positions_<Date>[_<user_id>].csv
# where user_id (if present) is the tagger's short label suffix.
_TAGGED_SUFFIX_RE = re.compile(r"_(?P<user>[A-Za-z0-9.-]{1,64})$")


@dataclass(frozen=True)
class CsvEntry:
    path: Path
    size_bytes: int
    line_count: int
    user_id: str | None  # inferred from filename suffix, may be None


def _infer_user_id(stem: str) -> str | None:
    m = _TAGGED_SUFFIX_RE.search(stem)
    return m.group("user") if m else None


def _line_count(path: Path) -> int:
    """Count lines without loading the whole file into a Python str list."""
    n = 0
    with path.open("rb") as f:
        for _ in f:
            n += 1
    return n


def find_csvs(root: Path, *, recursive: bool = True) -> list[CsvEntry]:
    """Return all .csv files under ``root``, sorted by mtime desc.

    - Skips hidden files and non-.csv files.
    - Attaches metadata only: size, line count, inferred user_id from
      filename. Does NOT read cell content.
    """
    root = Path(root)
    if not root.is_dir():
        return []

    pattern = "**/*.csv" if recursive else "*.csv"
    entries: list[CsvEntry] = []
    for p in root.glob(pattern):
        if not p.is_file() or p.name.startswith("."):
            continue
        try:
            size = p.stat().st_size
            lines = _line_count(p)
        except OSError:
            continue
        entries.append(
            CsvEntry(
                path=p,
                size_bytes=size,
                line_count=lines,
                user_id=_infer_user_id(p.stem),
            )
        )
    entries.sort(key=lambda e: e.path.stat().st_mtime, reverse=True)
    return entries
