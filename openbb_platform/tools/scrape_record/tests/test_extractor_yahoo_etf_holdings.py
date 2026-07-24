"""Tests for the Yahoo ETF-holdings extractor (sub-epic #1374 / PR-1)."""

from __future__ import annotations

import json

import pytest
from scrape_record.config import load_config, snapshot_path
from scrape_record.extract import apply_extractor


@pytest.fixture
def qqq_snapshot():
    cfg = load_config()
    p = snapshot_path(cfg, "yahoo_etf_holdings", "QQQ")
    assert p.exists(), f"missing fixture: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def test_extract_returns_etf_symbol(qqq_snapshot):
    out = apply_extractor("yahoo_etf_holdings", qqq_snapshot["raw"])
    assert out["etf_symbol"] == "QQQ"
    assert "QQQ" in (out["etf_name"] or "")


def test_extract_flattens_holdings(qqq_snapshot):
    out = apply_extractor("yahoo_etf_holdings", qqq_snapshot["raw"])
    assert len(out["holdings"]) == 5
    for h in out["holdings"]:
        assert set(h.keys()) == {"symbol", "name", "weight"}
    assert out["holdings"][0]["symbol"] == "AAPL"
    assert out["holdings"][0]["weight"] == pytest.approx(0.089)


def test_extract_returns_sector_weights(qqq_snapshot):
    out = apply_extractor("yahoo_etf_holdings", qqq_snapshot["raw"])
    assert out["sector_weights"]["technology"] == pytest.approx(0.51)
    total = sum(out["sector_weights"].values())
    assert total == pytest.approx(1.0, abs=0.01)


def test_extract_handles_empty_holdings():
    out = apply_extractor(
        "yahoo_etf_holdings",
        {"symbol": "XYZ", "quoteSummary": {"result": [{"topHoldings": {"holdings": []}}]}},
    )
    assert out["holdings"] == []


def test_committed_extracted_matches_extractor(qqq_snapshot):
    from_raw = apply_extractor("yahoo_etf_holdings", qqq_snapshot["raw"])
    committed = qqq_snapshot["extracted"]
    assert from_raw["etf_symbol"] == committed["etf_symbol"]
    assert len(from_raw["holdings"]) == len(committed["holdings"])
    assert from_raw["sector_weights"] == committed["sector_weights"]


def test_extract_passthrough_shape():
    out = apply_extractor(
        "yahoo_etf_holdings",
        {"etf_symbol": "SPY", "holdings": [{"symbol": "AAPL", "weight": 0.07}]},
    )
    assert out["etf_symbol"] == "SPY"
    assert len(out["holdings"]) == 1
    assert out["holdings"][0]["symbol"] == "AAPL"
