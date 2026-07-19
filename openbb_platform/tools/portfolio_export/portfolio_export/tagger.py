"""tagger.py — add `user_id` column + rename downloaded broker CSVs.

Solves the multi-account problem: if you export Positions for multiple
Fidelity logins (or family members), you need to know which export is
whose after they land in the same dated folder. This module:

  1. Reads a broker CSV.
  2. Adds a ``user_id`` column populated with a caller-supplied label.
  3. Writes to ``<original_stem>_<user_id>.csv`` in the same directory
     (or an explicit ``output_path``).
  4. Optionally deletes the untagged original.

Compliance notes
----------------
- Does NOT log or print row content — output is limited to paths, row
  counts, and validation errors. Compliant with the repo-wide
  "never read portfolio data directly" rule.
- ``user_id`` is a caller-supplied short label like ``rashmi`` or
  ``dad`` — NOT a broker username. It is validated against a safe
  character set to keep filenames portable.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

USER_ID_COL = "user_id"

# Safe for filenames + CSV cell content across win/mac/linux + typical shells.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class TaggerError(Exception):
    """Any user-visible failure from the tagger."""


def _validate_user_id(user_id: str) -> None:
    if not isinstance(user_id, str) or not _SAFE_ID_RE.match(user_id):
        raise TaggerError(
            f"user_id must match [A-Za-z0-9_.-]{{1,64}} (got {user_id!r})"
        )


def tag_csv(
    input_path: str | Path,
    user_id: str,
    *,
    output_path: str | Path | None = None,
    delete_original: bool = False,
) -> tuple[Path, int]:
    """Add ``user_id`` column and rewrite. Return ``(output_path, rows_tagged)``.

    - ``rows_tagged`` counts only data rows that match the header
      column count. Trailing blank rows and footer/disclaimer text
      rows (broker CSVs often append them) are written through
      unmodified so the file remains round-trippable.
    - Refuses to overwrite the input, refuses to tag a file that
      already contains a ``user_id`` column (idempotence guard).
    """
    _validate_user_id(user_id)

    input_path = Path(input_path)
    if not input_path.is_file():
        raise TaggerError(f"input not found: {input_path}")

    if output_path is None:
        output_path = input_path.with_name(
            f"{input_path.stem}_{user_id}{input_path.suffix}"
        )
    else:
        output_path = Path(output_path)

    if output_path.resolve() == input_path.resolve():
        raise TaggerError("output_path must differ from input_path")

    rows_tagged = 0
    with input_path.open("r", encoding="utf-8", newline="") as fin:
        reader = csv.reader(fin)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise TaggerError(f"CSV is empty: {input_path}") from exc

        if USER_ID_COL in header:
            raise TaggerError(
                f"{USER_ID_COL!r} column already present in "
                f"{input_path.name}; refusing to double-tag"
            )

        new_header = [*header, USER_ID_COL]
        expected_cols = len(header)

        with output_path.open("w", encoding="utf-8", newline="") as fout:
            writer = csv.writer(fout)
            writer.writerow(new_header)
            for row in reader:
                normalized = _normalize_data_row(row, expected_cols)
                if normalized is not None:
                    writer.writerow([*normalized, user_id])
                    rows_tagged += 1
                else:
                    # Footer / disclaimer / blank rows — passthrough
                    # unmodified. Downstream loaders should filter
                    # these by row length, not by adding a stub id.
                    writer.writerow(row)

    if delete_original:
        input_path.unlink()

    return output_path, rows_tagged


def _normalize_data_row(row: list[str], expected_cols: int) -> list[str] | None:
    """Return the row trimmed to `expected_cols`, or None if it's a footer.

    Broker CSVs commonly append a trailing comma to data rows (giving
    one extra empty cell vs. the header). We tolerate that: if the row
    is exactly one longer than the header AND the last cell is empty,
    we drop the extra cell. Any other length mismatch → treat as
    footer/blank/disclaimer and pass through unmodified.
    """
    n = len(row)
    if n == expected_cols:
        return row
    if n == expected_cols + 1 and row[-1] == "":
        return row[:-1]
    return None
