"""Tests for the Yahoo bond-ETF holdings extractor (#1000).

Runs against the checked-in BND fixture — no Playwright needed.
"""

from __future__ import annotations

import json

import pytest
from scrape_record.config import load_config, snapshot_path
from scrape_record.extract import apply_extractor, verify_snapshot


@pytest.fixture
def bnd_snapshot():
    """Read the checked-in BND snapshot from disk."""
    cfg = load_config()
    p = snapshot_path(cfg, "yahoo_bond_etf_holdings", "BND")
    assert p.exists(), f"missing fixture: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def test_extract_returns_etf_symbol_and_name(bnd_snapshot):
    """etf_symbol + etf_name round-trip from raw."""
    out = apply_extractor("yahoo_bond_etf_holdings", bnd_snapshot["raw"])
    assert out["etf_symbol"] == "BND"
    assert "Vanguard" in (out["etf_name"] or "")


def test_extract_flattens_holdings(bnd_snapshot):
    """Each holding row is normalized with snake_case keys."""
    out = apply_extractor("yahoo_bond_etf_holdings", bnd_snapshot["raw"])
    assert len(out["holdings"]) == 5
    for h in out["holdings"]:
        assert set(h.keys()) == {
            "symbol",
            "issuer",
            "coupon",
            "maturity",
            "weight",
            "ytm",
            "rating",
        }
    # First row is a Treasury with expected coupon
    first = out["holdings"][0]
    assert first["issuer"] == "United States Treasury Note/Bond"
    assert first["coupon"] == 4.5
    assert first["ytm"] == 4.32


def test_extract_carries_portfolio_rollups(bnd_snapshot):
    """Average YTM + duration surface at the top level."""
    out = apply_extractor("yahoo_bond_etf_holdings", bnd_snapshot["raw"])
    assert out["portfolio_avg_ytm"] == 4.85
    assert out["portfolio_duration_years"] == 6.2


def test_extract_carries_sector_and_credit_breakdowns(bnd_snapshot):
    """Sector + credit-quality breakdowns preserved as dicts."""
    out = apply_extractor("yahoo_bond_etf_holdings", bnd_snapshot["raw"])
    assert out["sector_weights"]["Treasury"] == pytest.approx(0.42)
    assert out["credit_quality_breakdown"]["AAA"] == pytest.approx(0.68)


def test_extract_handles_empty_holdings():
    """Empty top_holdings list yields empty holdings + None roll-ups."""
    out = apply_extractor(
        "yahoo_bond_etf_holdings",
        {"etf_symbol": "XYZ", "top_holdings": []},
    )
    assert out["etf_symbol"] == "XYZ"
    assert out["holdings"] == []
    assert out["portfolio_avg_ytm"] is None


def test_extract_tolerates_missing_optional_fields():
    """Rows with only issuer + weight (no coupon/maturity/etc.) still parse."""
    out = apply_extractor(
        "yahoo_bond_etf_holdings",
        {
            "etf_symbol": "XYZ",
            "top_holdings": [{"issuer": "Some Bond", "weight": 0.5}],
        },
    )
    assert out["holdings"][0]["issuer"] == "Some Bond"
    assert out["holdings"][0]["coupon"] is None
    assert out["holdings"][0]["ytm"] is None


def test_verify_snapshot_returns_ok(bnd_snapshot):
    """verify_snapshot dry-run reports ok=True."""
    result = verify_snapshot("yahoo_bond_etf_holdings", bnd_snapshot["raw"])
    assert result["ok"] is True
    assert "holdings" in result["keys"]


def test_committed_bnd_snapshot_extracted_matches_extractor(bnd_snapshot):
    """The `extracted` in the checked-in BND snapshot must round-trip."""
    from_raw = apply_extractor("yahoo_bond_etf_holdings", bnd_snapshot["raw"])
    committed = bnd_snapshot["extracted"]
    assert set(from_raw.keys()) == set(committed.keys())
    assert len(from_raw["holdings"]) == len(committed["holdings"])
    assert from_raw["etf_symbol"] == committed["etf_symbol"]
    assert from_raw["portfolio_avg_ytm"] == committed["portfolio_avg_ytm"]
