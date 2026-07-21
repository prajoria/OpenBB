"""Tests for Tools/pine/capture_bars_provenance.py (spec §7.1).

Real fmp_cached fetches require MySQL + FMP API key and are blocked in
this venv (issue #965). Instead we use the tool's injectable
``fetcher=`` seam — a callable that returns records — so the CLI's
canonicalization / hashing / provenance-writing plumbing can be
verified end-to-end without any live provider dependency.

R7.1 fixture shape: records match the exact 6-key dict shape the
canonical_bars module expects and that ``openbb_fmp_cached``'s
`equity.price.historical` returns (verified by inspection of the
provider's response model). If the provider ever changes shape, both
this test AND the harness break at the same seam — that's the point.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make Tools/pine importable — same pattern as test_reshape_tv_trades.
_TOOLS_PINE_DIR = Path(__file__).resolve().parent.parent / "pine"
sys.path.insert(0, str(_TOOLS_PINE_DIR))

import capture_bars_provenance  # noqa: E402

# Realistic 3-bar shape returned by openbb_fmp_cached.
_MOCK_RECORDS = [
    {
        "date": "2025-01-02",
        "open": 248.93,
        "high": 249.10,
        "low": 241.82,
        "close": 243.85,
        "volume": 55740731,
    },
    {
        "date": "2025-01-03",
        "open": 243.6,
        "high": 244.18,
        "low": 241.89,
        "close": 243.36,
        "volume": 44368996,
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


def _mock_fetcher(**_kwargs):
    """Injectable fetcher — returns fixed records regardless of args.

    Real fetcher receives (symbol, start_date, end_date, adjustment)
    from openbb_fmp_cached. Tests don't care about arg-passing here;
    that's covered separately by the arg-plumbing test below.
    """
    return _MOCK_RECORDS


# ---------------------------------------------------------------------------
# Provenance write / merge
# ---------------------------------------------------------------------------


def test_creates_provenance_json_with_expected_top_level_keys(tmp_path: Path):
    """The CLI emits a provenance.json with the spec §4 schema shape."""
    fixture_dir = tmp_path / "rsi_reversal"
    fixture_dir.mkdir()

    capture_bars_provenance.capture(
        fixture_dir=fixture_dir,
        symbol="NASDAQ:AAPL",
        start="2025-01-01",
        end="2026-07-20",
        timeframe="1D",
        adjustment="splits_only",
        timezone="America/New_York",
        session="regular",
        fetcher=_mock_fetcher,
    )

    prov_path = fixture_dir / "provenance.json"
    assert prov_path.exists()
    prov = json.loads(prov_path.read_text(encoding="utf-8"))

    # Spec §4 requires these top-level keys at minimum.
    assert "$schema_version" in prov
    assert prov["fixture_name"] == "rsi_reversal"
    assert "captured_at" in prov
    assert "bars_source" in prov
    # Wave 1 default — no canary CSVs.
    assert prov["canary_mode"] is False


def test_bars_source_captures_all_parameters_faithfully(tmp_path: Path):
    """Every input parameter round-trips into bars_source. If a caller
    can't tell from provenance.json exactly what was fetched, the file
    is useless for drift diagnosis.
    """
    fixture_dir = tmp_path / "rsi_reversal"
    fixture_dir.mkdir()

    capture_bars_provenance.capture(
        fixture_dir=fixture_dir,
        symbol="NASDAQ:AAPL",
        start="2025-01-01",
        end="2026-07-20",
        timeframe="1D",
        adjustment="splits_only",
        timezone="America/New_York",
        session="regular",
        fetcher=_mock_fetcher,
    )

    prov = json.loads((fixture_dir / "provenance.json").read_text(encoding="utf-8"))
    bs = prov["bars_source"]
    assert bs["provider"] == "fmp_cached"
    assert bs["symbol"] == "NASDAQ:AAPL"
    assert bs["start_date"] == "2025-01-01"
    assert bs["end_date"] == "2026-07-20"
    assert bs["adjustment"] == "splits_only"
    assert bs["timezone"] == "America/New_York"
    assert bs["session"] == "regular"
    assert bs["bars_row_count"] == 3
    assert len(bs["bars_sha256"]) == 64  # SHA-256 hex


def test_hash_matches_canonical_bars_directly(tmp_path: Path):
    """The recorded hash MUST equal what canonical_bars produces on
    the same records. If they diverge, the whole harness→capture
    round-trip is broken.
    """
    from openbb_pine.testing.canonical_bars import sha256_bars

    fixture_dir = tmp_path / "rsi_reversal"
    fixture_dir.mkdir()

    capture_bars_provenance.capture(
        fixture_dir=fixture_dir,
        symbol="NASDAQ:AAPL",
        start="2025-01-01",
        end="2026-07-20",
        timeframe="1D",
        adjustment="splits_only",
        timezone="America/New_York",
        session="regular",
        fetcher=_mock_fetcher,
    )

    prov = json.loads((fixture_dir / "provenance.json").read_text(encoding="utf-8"))
    expected = sha256_bars(_MOCK_RECORDS)
    assert prov["bars_source"]["bars_sha256"] == expected


# ---------------------------------------------------------------------------
# Idempotency (spec §7.1: same window → byte-identical output)
# ---------------------------------------------------------------------------


def test_running_twice_produces_byte_identical_output(tmp_path: Path):
    """Idempotency is the whole reason for canonicalization. If two
    runs of the same window produce different bytes, provenance.json
    can't be checked into git as a stable artifact.
    """
    fixture_dir = tmp_path / "rsi_reversal"
    fixture_dir.mkdir()

    kwargs = dict(
        fixture_dir=fixture_dir,
        symbol="NASDAQ:AAPL",
        start="2025-01-01",
        end="2026-07-20",
        timeframe="1D",
        adjustment="splits_only",
        timezone="America/New_York",
        session="regular",
        fetcher=_mock_fetcher,
        force=True,  # allow overwrite for the second run
    )

    capture_bars_provenance.capture(**kwargs)
    bytes_1 = (fixture_dir / "provenance.json").read_bytes()

    capture_bars_provenance.capture(**kwargs)
    bytes_2 = (fixture_dir / "provenance.json").read_bytes()

    assert (
        bytes_1 == bytes_2
    ), "same-window re-run must produce byte-identical provenance.json"


# ---------------------------------------------------------------------------
# Merge behavior (spec §7.1: merge with existing, refuse overwrite w/o --force)
# ---------------------------------------------------------------------------


def test_refuses_to_overwrite_existing_provenance_without_force(tmp_path: Path):
    """First run creates the file. Second run without --force MUST
    refuse. This prevents accidental in-place edits that lose the
    prior capture's audit trail.
    """
    fixture_dir = tmp_path / "rsi_reversal"
    fixture_dir.mkdir()

    kwargs = dict(
        fixture_dir=fixture_dir,
        symbol="NASDAQ:AAPL",
        start="2025-01-01",
        end="2026-07-20",
        timeframe="1D",
        adjustment="splits_only",
        timezone="America/New_York",
        session="regular",
        fetcher=_mock_fetcher,
    )

    capture_bars_provenance.capture(**kwargs)

    with pytest.raises(FileExistsError, match=r"(?i)provenance|force"):
        capture_bars_provenance.capture(**kwargs)


def test_force_flag_permits_overwrite(tmp_path: Path):
    """With force=True, the second run succeeds — this is the
    intentional escape hatch for accepting a legit fmp_cached refresh.
    """
    fixture_dir = tmp_path / "rsi_reversal"
    fixture_dir.mkdir()

    capture_bars_provenance.capture(
        fixture_dir=fixture_dir,
        symbol="NASDAQ:AAPL",
        start="2025-01-01",
        end="2026-07-20",
        timeframe="1D",
        adjustment="splits_only",
        timezone="America/New_York",
        session="regular",
        fetcher=_mock_fetcher,
    )
    # Force succeeds
    capture_bars_provenance.capture(
        fixture_dir=fixture_dir,
        symbol="NASDAQ:AAPL",
        start="2025-01-01",
        end="2026-07-20",
        timeframe="1D",
        adjustment="splits_only",
        timezone="America/New_York",
        session="regular",
        fetcher=_mock_fetcher,
        force=True,
    )
    # File still exists and is parseable
    prov = json.loads((fixture_dir / "provenance.json").read_text(encoding="utf-8"))
    assert prov["fixture_name"] == "rsi_reversal"


# ---------------------------------------------------------------------------
# Fetcher arg-plumbing (verify the tool passes the right args to the seam)
# ---------------------------------------------------------------------------


def test_fetcher_receives_all_bars_source_parameters(tmp_path: Path):
    """The tool must pass symbol/start/end/adjustment through to the
    fetcher. If it silently defaults any of these, the recorded
    provenance won't match what was actually fetched.
    """
    fixture_dir = tmp_path / "rsi_reversal"
    fixture_dir.mkdir()

    captured_args = {}

    def _capturing_fetcher(**kwargs):
        captured_args.update(kwargs)
        return _MOCK_RECORDS

    capture_bars_provenance.capture(
        fixture_dir=fixture_dir,
        symbol="NASDAQ:AAPL",
        start="2025-01-01",
        end="2026-07-20",
        timeframe="1D",
        adjustment="splits_only",
        timezone="America/New_York",
        session="regular",
        fetcher=_capturing_fetcher,
    )

    assert captured_args["symbol"] == "NASDAQ:AAPL"
    assert captured_args["start_date"] == "2025-01-01"
    assert captured_args["end_date"] == "2026-07-20"
    assert captured_args["adjustment"] == "splits_only"


# ---------------------------------------------------------------------------
# Empty-fetch loud failure (R7.3)
# ---------------------------------------------------------------------------


def test_empty_fetch_raises_loudly(tmp_path: Path):
    """A fetcher returning zero records almost always signals an API
    failure or a bad window (weekend/holiday). Silently emitting a
    provenance.json with a hash-of-empty would pass a broken fixture.
    """
    fixture_dir = tmp_path / "rsi_reversal"
    fixture_dir.mkdir()

    def _empty_fetcher(**_):
        return []

    with pytest.raises(ValueError, match=r"(?i)empty|no records|no bars"):
        capture_bars_provenance.capture(
            fixture_dir=fixture_dir,
            symbol="NASDAQ:AAPL",
            start="2025-01-01",
            end="2026-07-20",
            timeframe="1D",
            adjustment="splits_only",
            timezone="America/New_York",
            session="regular",
            fetcher=_empty_fetcher,
        )


# ---------------------------------------------------------------------------
# JSON format (deterministic, human-readable)
# ---------------------------------------------------------------------------


def test_json_is_sorted_and_indented(tmp_path: Path):
    """Deterministic JSON output — sort_keys + indent — so git diffs
    are stable and human-readable.
    """
    fixture_dir = tmp_path / "rsi_reversal"
    fixture_dir.mkdir()

    capture_bars_provenance.capture(
        fixture_dir=fixture_dir,
        symbol="NASDAQ:AAPL",
        start="2025-01-01",
        end="2026-07-20",
        timeframe="1D",
        adjustment="splits_only",
        timezone="America/New_York",
        session="regular",
        fetcher=_mock_fetcher,
    )

    text = (fixture_dir / "provenance.json").read_text(encoding="utf-8")
    # sort_keys → $schema_version comes first alphabetically among top-level
    # keys ($ sorts before letters in ASCII).
    assert text.startswith("{\n"), "must be indented"
    # No trailing whitespace on lines
    for line in text.split("\n"):
        assert line == line.rstrip(), f"trailing whitespace on line: {line!r}"


# ---------------------------------------------------------------------------
# CLI wrapper
# ---------------------------------------------------------------------------


def test_cli_smoke_passes_args_through(tmp_path: Path, monkeypatch):
    """The CLI entry point argparse-wires all flags into capture()."""
    fixture_dir = tmp_path / "rsi_reversal"
    fixture_dir.mkdir()

    # Monkeypatch the fmp_cached-backed default fetcher to our mock so
    # the CLI runs end-to-end without hitting the network.
    monkeypatch.setattr(
        capture_bars_provenance, "_default_fetcher", lambda **_: _MOCK_RECORDS
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_bars_provenance.py",
            str(fixture_dir),
            "--symbol",
            "NASDAQ:AAPL",
            "--start",
            "2025-01-01",
            "--end",
            "2026-07-20",
            "--timeframe",
            "1D",
            "--adjustment",
            "splits_only",
            "--timezone",
            "America/New_York",
            "--session",
            "regular",
        ],
    )

    exit_code = capture_bars_provenance.main()
    assert exit_code == 0
    assert (fixture_dir / "provenance.json").exists()
