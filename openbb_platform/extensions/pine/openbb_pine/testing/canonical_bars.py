"""Canonical bars serialization for the hybrid-fixture-suite hash gate.

Implements the byte-exact serialization from
docs/superpowers/specs/2026-07-20-pine-hybrid-fixture-suite-design.md §5.

The core promise: two calls with the same records — regardless of input
row order, extra provider-emitted columns, or float representation
noise below 6dp — produce byte-identical output. This byte-stability
is what makes the ``bars_sha256`` field in provenance.json a
meaningful drift detector.

This module is shared by:

- ``Tools/pine/capture_bars_provenance.py`` (D2.3): computes the hash
  at fixture-capture time.
- ``openbb_pine.tests.conformance_strategy.conftest`` (D2.5): recomputes
  the hash at test time and asserts it matches the recorded value.

Both consumers MUST import from this module — never re-implement the
serialization. Drift between capture and test would silently invalidate
every fixture.
"""

from __future__ import annotations

import datetime as _dt
import hashlib

# Column order is FROZEN. Consumers depend on this exact ordering; do
# not reorder for stylistic reasons. See spec §5.2.
_COLUMNS = ("date", "open", "high", "low", "close", "volume")

# Spec §5.4: OHLC rounded to 6 dp — matches Pine's `syminfo.pricescale`
# precision for equities. Do not change without a spec bump.
_OHLC_DP = 6


def _canonicalize_date(value: object) -> str:
    """Return the spec §5.3 date format: `YYYY-MM-DDT00:00:00+00:00`.

    Accepts ``date``, ``datetime``, or a string. Strings must be
    ISO-parseable to a date; datetimes are stripped to their date
    component (bar-close semantics — a daily bar keys off the trading
    date, not the intraday timestamp).
    """
    if isinstance(value, _dt.datetime):
        d = value.date()
    elif isinstance(value, _dt.date):
        d = value
    elif isinstance(value, str):
        # datetime.fromisoformat accepts "YYYY-MM-DD" and
        # "YYYY-MM-DDT..." — for the latter, keep only the date.
        try:
            d = _dt.date.fromisoformat(value[:10])
        except ValueError as e:
            raise ValueError(f"Cannot parse date from {value!r}: {e}") from e
    else:
        raise TypeError(
            f"date must be str, date, or datetime — got {type(value).__name__}"
        )
    return f"{d.isoformat()}T00:00:00+00:00"


def _canonicalize_price(value: object, column: str) -> str:
    """Return the spec §5.4 price format: fixed 6 decimal places."""
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"{column} must be numeric — got {value!r} ({type(value).__name__})"
        ) from e
    # `{:.6f}` uses banker's rounding on the tie, which is what we want
    # for stability across languages. Python's default float repr is
    # NOT stable across versions; the format string IS.
    return f"{f:.{_OHLC_DP}f}"


def _canonicalize_volume(value: object) -> str:
    """Return the spec §5.5 volume format: integer string, no decimals."""
    try:
        # Some providers emit volume as float (e.g. 55740731.0);
        # coerce to int for canonical form. Any fractional part is a
        # provider bug (share counts are integers) and we drop it here.
        i = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"volume must be numeric — got {value!r} ({type(value).__name__})"
        ) from e
    return str(i)


def canonicalize_bars(records: list[dict]) -> bytes:
    r"""Serialize bars records to canonical UTF-8 bytes per spec §5.

    Args:
        records: A list of dicts, each with keys
            ``{date, open, high, low, close, volume}``. Extra keys are
            silently dropped (spec §5 — provider frames may carry
            adjClose/vwap/etc. that must not affect the hash).

    Returns:
        UTF-8 bytes ready to feed into a hashlib digest. Format:

        - Header line: ``date,open,high,low,close,volume``
        - Data lines: sorted by date ascending, one bar per line,
          fields comma-separated, no trailing whitespace.
        - Row terminator: ``\n`` (never ``\r\n``, regardless of OS).
        - No trailing newline after the last row.

    Raises:
        ValueError: if ``records`` is empty (R7.3 loud empties — a
            silent zero-record hash would pass a broken fixture) or if
            any row is missing a required column.
        TypeError: if a date field has an unrecognized type.
    """
    if not records:
        raise ValueError(
            "canonicalize_bars received empty records list — "
            "a zero-bar fixture is always a bug (R7.3 loud empties)"
        )

    # Sort by raw date field. Canonicalize the date AFTER sorting so
    # comparison is on the original ISO string / date object — either
    # sorts lexicographically the same way as chronologically.
    sorted_records = sorted(records, key=lambda r: str(r.get("date", "")))

    lines: list[str] = [",".join(_COLUMNS)]
    for r in sorted_records:
        # Fail loudly on missing keys (R7.3) rather than silently
        # substituting empty strings.
        missing = [c for c in _COLUMNS if c not in r]
        if missing:
            raise ValueError(f"bar record missing required columns {missing!r}: {r!r}")
        line = ",".join(
            [
                _canonicalize_date(r["date"]),
                _canonicalize_price(r["open"], "open"),
                _canonicalize_price(r["high"], "high"),
                _canonicalize_price(r["low"], "low"),
                _canonicalize_price(r["close"], "close"),
                _canonicalize_volume(r["volume"]),
            ]
        )
        lines.append(line)

    # LF-only terminator per spec §5.6. Do NOT use `os.linesep` or
    # writer classes that inject CRLF on Windows — that's exactly the
    # bug the license-verifier fix worked around.
    return "\n".join(lines).encode("utf-8")


def sha256_bars(records: list[dict]) -> str:
    """SHA-256 hex digest of :func:`canonicalize_bars` output.

    This is the value that lands in ``provenance.json.bars_source.bars_sha256``.
    Callers should never re-implement — always go through this function
    so the capture-time and test-time hashes are computed identically.

    Args:
        records: See :func:`canonicalize_bars`.

    Returns:
        64-character lowercase hex string.
    """
    return hashlib.sha256(canonicalize_bars(records)).hexdigest()
