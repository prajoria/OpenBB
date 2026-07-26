"""Filename parser for Fidelity-shaped portfolio-positions CSVs.

Convention: ``Portfolio_Positions_<Mon>-<DD>-<YYYY>_<user_id>.csv``. The
`user_id` suffix is optional (older Fidelity exports don't include it);
when absent the caller falls back to the in-file column.
"""

from __future__ import annotations

import re
from datetime import date

_FIDELITY_RE = re.compile(
    r"^Portfolio_Positions_(?P<mon>[A-Za-z]{3})-(?P<dd>\d{2})-(?P<yyyy>\d{4})"
    r"(?:_(?P<user_id>[A-Za-z0-9_.-]{1,64}))?"
    r"\.csv$"
)

_MON_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


class FilenameParseError(ValueError):
    """Raised when a filename does not match the Fidelity convention."""


def parse_fidelity_filename(name: str) -> tuple[date, str | None]:
    """Parse a Fidelity positions CSV filename.

    Returns a ``(snapshot_date, user_id)`` tuple. ``user_id`` is ``None`` if
    the filename doesn't carry one (older Fidelity exports).
    """
    m = _FIDELITY_RE.match(name)
    if not m:
        raise FilenameParseError(
            f"filename does not match Portfolio_Positions_<Mon>-<DD>-<YYYY>[_<user>].csv: {name!r}"
        )
    mon = _MON_MAP.get(m.group("mon").capitalize())
    if mon is None:
        raise FilenameParseError(f"unknown month token in {name!r}: {m.group('mon')!r}")
    try:
        snap = date(int(m.group("yyyy")), mon, int(m.group("dd")))
    except ValueError as exc:
        raise FilenameParseError(f"invalid date in {name!r}: {exc}") from exc
    user_id = m.group("user_id")
    return snap, user_id
