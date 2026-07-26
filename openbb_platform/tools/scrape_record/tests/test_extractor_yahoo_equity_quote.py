"""Tests for the Yahoo equity-quote extractor (sub-epic #1374 / PR-1)."""

from __future__ import annotations

import pytest
from scrape_record.extract import apply_extractor, verify_snapshot

from ._fixtures import fixture_path, load_fixture


@pytest.fixture
def msft_snapshot():
    p = fixture_path("yahoo_equity_quote", "MSFT")
    assert p.exists(), f"missing fixture: {p}"
    return load_fixture("yahoo_equity_quote", "MSFT")


def test_extract_returns_symbol_and_price(msft_snapshot):
    out = apply_extractor("yahoo_equity_quote", msft_snapshot["raw"])
    assert out["symbol"] == "MSFT"
    assert out["last_price"] == 450.12
    assert out["name"] == "Microsoft Corporation"


def test_extract_flattens_ohlc(msft_snapshot):
    out = apply_extractor("yahoo_equity_quote", msft_snapshot["raw"])
    assert out["open"] == 449.00
    assert out["high"] == 451.50
    assert out["low"] == 447.80
    assert out["previous_close"] == 448.20


def test_extract_unwraps_marketcap(msft_snapshot):
    out = apply_extractor("yahoo_equity_quote", msft_snapshot["raw"])
    assert out["market_cap"] == 3350000000000


def test_extract_handles_empty_result():
    out = apply_extractor(
        "yahoo_equity_quote",
        {"symbol": "XYZ", "quoteSummary": {"result": [], "error": None}},
    )
    assert out["symbol"] == "XYZ"


def test_verify_snapshot_ok(msft_snapshot):
    result = verify_snapshot("yahoo_equity_quote", msft_snapshot["raw"])
    assert result["ok"] is True
    assert "last_price" in result["keys"]


def test_committed_extracted_matches_extractor(msft_snapshot):
    """R7.11: `extracted` block on disk must round-trip from raw."""
    from_raw = apply_extractor("yahoo_equity_quote", msft_snapshot["raw"])
    committed = msft_snapshot["extracted"]
    for k in ("symbol", "name", "last_price", "market_cap", "captured_at"):
        assert from_raw.get(k) == committed.get(k), f"mismatch on {k}"


def test_extract_passthrough_shape():
    """Pre-flattened input (no quoteSummary key) works too."""
    out = apply_extractor(
        "yahoo_equity_quote",
        {"symbol": "AAPL", "last_price": 200.0, "captured_at": "2026-07-24T00:00:00Z"},
    )
    assert out["symbol"] == "AAPL"
    assert out["last_price"] == 200.0
