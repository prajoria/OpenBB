"""Tests for openbb_pine.testing.canonical_bars — spec §5.

The whole point of canonical_bars is that the bytes we hash today match
the bytes we hash tomorrow, regardless of pandas/pyarrow versions or
DataFrame column order. Every test here is a byte-level assertion.

R7.7 discipline: every load-bearing test has a reverse-verify variant —
perturb the input, confirm the hash changes; restore, confirm it
restores. If a perturbation does NOT change the hash, that's a bug in
the canonicalization, not the test.
"""

from __future__ import annotations

import hashlib

import pytest

from openbb_pine.testing.canonical_bars import (
    canonicalize_bars,
    sha256_bars,
)

# Fixed record shape used across tests. Represents a 3-bar AAPL slice
# with realistic values — not hand-crafted mocks (R7.1) but a
# small deterministic recording that exercises every canonicalization
# rule (date sort, column order, decimal rounding, int volume).
_SAMPLE = [
    {
        "date": "2025-01-03",
        "open": 243.6,
        "high": 244.18,
        "low": 241.89,
        "close": 243.36,
        "volume": 44368996,
    },
    {
        "date": "2025-01-02",
        "open": 248.93,
        "high": 249.10,
        "low": 241.82,
        "close": 243.85,
        "volume": 55740731,
    },
    {
        "date": "2025-01-06",
        "open": 244.31,
        "high": 247.33,
        "low": 243.20,
        "close": 245.00,
        "volume": 40289320,
    },
]


# ---------------------------------------------------------------------------
# canonicalize_bars — structural properties
# ---------------------------------------------------------------------------


def test_output_is_bytes():
    """Spec §5 hashes over bytes, not str — return type must be bytes."""
    out = canonicalize_bars(_SAMPLE)
    assert isinstance(out, bytes)


def test_sorts_by_date_ascending():
    """Spec §5.1: sort by `date` ascending. Input above is 03, 02, 06
    — output must be 02, 03, 06.
    """
    out = canonicalize_bars(_SAMPLE).decode("utf-8")
    lines = out.split("\n")
    # First line is header; then dates
    assert lines[0].startswith("date,")
    assert lines[1].startswith("2025-01-02T"), lines
    assert lines[2].startswith("2025-01-03T"), lines
    assert lines[3].startswith("2025-01-06T"), lines


def test_column_order_is_fixed():
    """Spec §5.2: header must be exactly `date,open,high,low,close,volume`."""
    out = canonicalize_bars(_SAMPLE).decode("utf-8")
    header = out.split("\n", 1)[0]
    assert header == "date,open,high,low,close,volume"


def test_date_becomes_utc_iso_midnight():
    """Spec §5.3: dates render as UTC ISO with T00:00:00+00:00 suffix."""
    out = canonicalize_bars(_SAMPLE).decode("utf-8")
    lines = out.split("\n")
    assert lines[1].startswith("2025-01-02T00:00:00+00:00,"), lines[1]


def test_ohlc_rounded_to_6dp():
    """Spec §5.4: OHLC rendered as strings with 6 decimal places.

    248.93 → "248.930000". A pandas repr might emit "248.93" or
    "248.9300000000001"; we normalize.
    """
    out = canonicalize_bars(_SAMPLE).decode("utf-8")
    lines = out.split("\n")
    # Line for 2025-01-02: date,open=248.93,high=249.10,low=241.82,close=243.85,volume=55740731
    parts = lines[1].split(",")
    assert parts[1] == "248.930000", parts
    assert parts[2] == "249.100000", parts
    assert parts[3] == "241.820000", parts
    assert parts[4] == "243.850000", parts


def test_volume_is_int_no_decimals():
    """Spec §5.5: volume rendered as int string. `55740731.0` → `55740731`."""
    records = [{**_SAMPLE[0], "volume": 12345678.0}]
    out = canonicalize_bars(records).decode("utf-8")
    line = out.split("\n")[1]
    assert line.endswith(",12345678"), line
    assert ".0" not in line.split(",")[-1]


def test_row_terminator_is_lf_not_crlf():
    r"""Spec §5.6: row terminator MUST be `\n`, never `\r\n`.

    This is the exact bug that made the license-verifier hash unstable
    across Windows/Linux. Test explicitly for the absence of \r.
    """
    out = canonicalize_bars(_SAMPLE)
    assert b"\r" not in out


def test_no_trailing_newline_on_last_row():
    """Spec §5.7: no trailing newline after the last data row.

    A trailing newline would produce a different hash than the same
    content without one — the ambiguity is what canonicalization
    eliminates.
    """
    out = canonicalize_bars(_SAMPLE)
    assert not out.endswith(b"\n"), "output must not end with a newline"


def test_empty_input_raises():
    """Zero-record inputs are almost always a bug (R7.3 loud empties).

    Silent empty canonicalization would hash the header alone and
    silently pass a fixture that had zero bars — devastating.
    """
    with pytest.raises(ValueError, match=r"(?i)empty|no records"):
        canonicalize_bars([])


def test_missing_required_column_raises():
    """Every row must have all six required keys. A missing key
    silently defaulting to empty-string would silently change the hash.
    """
    bad = [{**_SAMPLE[0]}]
    del bad[0]["volume"]
    with pytest.raises((KeyError, ValueError), match=r"(?i)volume"):
        canonicalize_bars(bad)


# ---------------------------------------------------------------------------
# Idempotency + determinism
# ---------------------------------------------------------------------------


def test_deterministic_across_calls():
    """Same input → byte-identical output. This is the whole
    reproducibility promise of the hybrid design.
    """
    a = canonicalize_bars(_SAMPLE)
    b = canonicalize_bars(_SAMPLE)
    assert a == b


def test_input_order_does_not_matter():
    """Regardless of input row order, output is sorted by date. So
    two shufflings of the same records produce byte-identical output.
    """
    reordered = [_SAMPLE[2], _SAMPLE[0], _SAMPLE[1]]
    assert canonicalize_bars(_SAMPLE) == canonicalize_bars(reordered)


def test_extra_columns_are_dropped():
    """Provider frames often carry extra columns (adjClose, vwap,
    change). Only the six spec columns feed the hash — others must be
    dropped, not carried through as extra CSV fields.
    """
    with_extras = [{**r, "adjClose": r["close"], "vwap": 244.0} for r in _SAMPLE]
    assert canonicalize_bars(_SAMPLE) == canonicalize_bars(with_extras)


# ---------------------------------------------------------------------------
# sha256_bars — thin wrapper, but the API consumers depend on
# ---------------------------------------------------------------------------


def test_sha256_bars_returns_hex_string_of_expected_length():
    """SHA-256 hex digest is 64 chars."""
    h = sha256_bars(_SAMPLE)
    assert isinstance(h, str)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_sha256_bars_matches_manual_computation():
    """The wrapper must actually hash canonicalize_bars output — not
    hash some other representation. Anchoring the wrapper to the exact
    two-step computation catches accidental drift where sha256_bars
    starts hashing something else.
    """
    expected = hashlib.sha256(canonicalize_bars(_SAMPLE)).hexdigest()
    assert sha256_bars(_SAMPLE) == expected


# ---------------------------------------------------------------------------
# R7.7 reverse-verification — perturbation MUST change the hash
# ---------------------------------------------------------------------------


class TestReverseVerify:
    """Every load-bearing property of canonicalization gets a
    perturbation test. If a perturbation does NOT change the hash,
    that's a bug in canonicalization (the property isn't actually
    load-bearing), not the test.
    """

    def _baseline(self) -> str:
        return sha256_bars(_SAMPLE)

    def test_perturbed_price_changes_hash(self):
        """Change one close by $0.01, hash MUST change.

        If it didn't, the canonicalization would be dropping precision
        that we're supposed to preserve — silent data loss.
        """
        perturbed = [{**r} for r in _SAMPLE]
        perturbed[0]["close"] = perturbed[0]["close"] + 0.01
        assert sha256_bars(perturbed) != self._baseline()

    def test_perturbed_volume_changes_hash(self):
        """Change one volume by 1 share, hash MUST change."""
        perturbed = [{**r} for r in _SAMPLE]
        perturbed[0]["volume"] = perturbed[0]["volume"] + 1
        assert sha256_bars(perturbed) != self._baseline()

    def test_perturbed_date_changes_hash(self):
        """Change one date by 1 day, hash MUST change."""
        perturbed = [{**r} for r in _SAMPLE]
        perturbed[0]["date"] = "2025-01-04"
        assert sha256_bars(perturbed) != self._baseline()

    def test_dropped_row_changes_hash(self):
        """Remove one row, hash MUST change. A canonicalization that
        silently ignored row count would pass a fixture with missing
        bars — the exact drift bug we want to catch.
        """
        perturbed = _SAMPLE[:2]
        assert sha256_bars(perturbed) != self._baseline()

    def test_sub_6dp_precision_still_captured(self):
        """A change smaller than 6dp is beyond our stated precision;
        we deliberately truncate it. But a change AT the 6dp boundary
        MUST be captured.

        This proves the rounding is exactly 6dp, not 5 or 7.
        """
        perturbed = [{**r} for r in _SAMPLE]
        # 0.000001 delta — exactly the 6dp boundary
        perturbed[0]["close"] = perturbed[0]["close"] + 0.000001
        assert sha256_bars(perturbed) != self._baseline()

    def test_beyond_6dp_precision_ignored(self):
        """A change strictly below 6dp precision (7dp+) must NOT
        change the hash — that's what the rounding is for. Catches
        floating-point noise that would otherwise produce spurious
        drift failures.
        """
        perturbed = [{**r} for r in _SAMPLE]
        perturbed[0]["close"] = perturbed[0]["close"] + 1e-9
        assert sha256_bars(perturbed) == self._baseline()
