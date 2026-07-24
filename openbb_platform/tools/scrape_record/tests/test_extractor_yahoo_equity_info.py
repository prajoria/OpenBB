"""Tests for the Yahoo equity-info extractor (sub-epic #1374 / PR-1)."""

from __future__ import annotations

import json

import pytest
from scrape_record.config import load_config, snapshot_path
from scrape_record.extract import apply_extractor


@pytest.fixture
def msft_snapshot():
    cfg = load_config()
    p = snapshot_path(cfg, "yahoo_equity_info", "MSFT")
    assert p.exists(), f"missing fixture: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def test_extract_returns_symbol_and_name(msft_snapshot):
    out = apply_extractor("yahoo_equity_info", msft_snapshot["raw"])
    assert out["symbol"] == "MSFT"
    assert out["name"] == "Microsoft Corporation"
    assert out["short_name"] == "Microsoft"


def test_extract_returns_sector_industry(msft_snapshot):
    out = apply_extractor("yahoo_equity_info", msft_snapshot["raw"])
    assert out["sector"] == "Technology"
    assert out["industry"] == "Software - Infrastructure"


def test_extract_returns_business_summary(msft_snapshot):
    out = apply_extractor("yahoo_equity_info", msft_snapshot["raw"])
    assert "Microsoft" in out["long_business_summary"]
    assert out["website"] == "https://www.microsoft.com"


def test_extract_unwraps_employees(msft_snapshot):
    out = apply_extractor("yahoo_equity_info", msft_snapshot["raw"])
    assert out["full_time_employees"] == 221000


def test_extract_handles_empty_result():
    out = apply_extractor(
        "yahoo_equity_info",
        {"symbol": "XYZ", "quoteSummary": {"result": [], "error": None}},
    )
    assert out["symbol"] == "XYZ"


def test_committed_extracted_matches_extractor(msft_snapshot):
    from_raw = apply_extractor("yahoo_equity_info", msft_snapshot["raw"])
    committed = msft_snapshot["extracted"]
    for k in ("symbol", "sector", "industry", "website", "full_time_employees"):
        assert from_raw.get(k) == committed.get(k), f"mismatch on {k}"


def test_extract_passthrough_shape():
    out = apply_extractor(
        "yahoo_equity_info",
        {"symbol": "AAPL", "sector": "Technology", "captured_at": "2026-07-24T00:00:00Z"},
    )
    assert out["symbol"] == "AAPL"
    assert out["sector"] == "Technology"
