"""Tests for the Yahoo options-chain extractor.

These run against the checked-in AAPL snapshot at
``snapshots/yahoo_options_chain/AAPL.json`` — no Playwright required.
"""

from __future__ import annotations

import json

import pytest
from scrape_record.config import load_config, snapshot_path
from scrape_record.extract import (
    ExtractorError,
    apply_extractor,
    load_extractor,
    verify_snapshot,
)


@pytest.fixture
def aapl_snapshot():
    """Read the checked-in AAPL snapshot from disk."""
    cfg = load_config()
    p = snapshot_path(cfg, "yahoo_options_chain", "AAPL")
    assert p.exists(), f"missing fixture: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def test_load_extractor_returns_callable():
    """The Yahoo extractor loads cleanly and exposes `extract`."""
    fn = load_extractor("yahoo_options_chain")
    assert callable(fn)


def test_load_extractor_raises_for_unknown():
    """Unknown extractor name raises ExtractorError with a useful message."""
    with pytest.raises(ExtractorError, match="No extractor module"):
        load_extractor("nonexistent_source_xyz")


def test_extract_produces_symbol_and_spot(aapl_snapshot):
    """Symbol + spot round-trip from raw."""
    out = apply_extractor("yahoo_options_chain", aapl_snapshot["raw"])
    assert out["symbol"] == "AAPL"
    assert out["spot"] == pytest.approx(327.74)


def test_extract_flattens_chains_per_expiry(aapl_snapshot):
    """Every expiry yields one entry with calls + puts lists."""
    out = apply_extractor("yahoo_options_chain", aapl_snapshot["raw"])
    assert len(out["chains"]) == 2
    for chain in out["chains"]:
        assert "expiration_unix" in chain
        assert isinstance(chain["calls"], list)
        assert isinstance(chain["puts"], list)
        for side_list, side_label in ((chain["calls"], "call"), (chain["puts"], "put")):
            for row in side_list:
                assert row["side"] == side_label
                assert "strike" in row
                assert "implied_volatility" in row


def test_extract_atm_iv_term_picks_closest_strike(aapl_snapshot):
    """ATM IV per expiry picks the strike closest to spot (330 for AAPL@327.74)."""
    out = apply_extractor("yahoo_options_chain", aapl_snapshot["raw"])
    for entry in out["atm_iv_term"]:
        assert entry["atm_call"]["strike"] == 330.0
        assert entry["atm_put"]["strike"] == 330.0


def test_extract_atm_iv_term_carries_iv(aapl_snapshot):
    """ATM contract carries an impliedVolatility value."""
    out = apply_extractor("yahoo_options_chain", aapl_snapshot["raw"])
    for entry in out["atm_iv_term"]:
        assert entry["atm_call"]["impliedVolatility"] is not None
        assert entry["atm_put"]["impliedVolatility"] is not None
        # AAPL sample: call IV 0.27-0.30 range, put IV 0.28-0.32
        assert 0.20 <= entry["atm_call"]["impliedVolatility"] <= 0.40


def test_extract_expiries_sorted_chronologically(aapl_snapshot):
    """Chains + atm_iv_term must be sorted by expiration_unix ascending."""
    out = apply_extractor("yahoo_options_chain", aapl_snapshot["raw"])
    chain_exps = [c["expiration_unix"] for c in out["chains"]]
    assert chain_exps == sorted(chain_exps)
    term_exps = [t["expiration_unix"] for t in out["atm_iv_term"]]
    assert term_exps == sorted(term_exps)


def test_extract_handles_missing_spot_gracefully():
    """When spot is None the ATM picker returns None (no crash)."""
    raw = {
        "underlying_symbol": "XYZ",
        "spot_price": None,
        "chains_by_expiry": {
            "1735689600": {
                "expirationDate": 1735689600,
                "calls": [{"strike": 100.0, "impliedVolatility": 0.5}],
                "puts": [{"strike": 100.0, "impliedVolatility": 0.6}],
            }
        },
    }
    out = apply_extractor("yahoo_options_chain", raw)
    assert out["atm_iv_term"][0]["atm_call"] is None
    assert out["atm_iv_term"][0]["atm_put"] is None


def test_extract_handles_empty_chain():
    """Empty chains_by_expiry → empty chains + atm_iv_term lists."""
    out = apply_extractor(
        "yahoo_options_chain",
        {"underlying_symbol": "XYZ", "spot_price": 100.0, "chains_by_expiry": {}},
    )
    assert out["chains"] == []
    assert out["atm_iv_term"] == []
    assert out["symbol"] == "XYZ"


def test_verify_snapshot_returns_ok_summary(aapl_snapshot):
    """verify_snapshot returns ok=True + row count + top-level keys."""
    result = verify_snapshot("yahoo_options_chain", aapl_snapshot["raw"])
    assert result["ok"] is True
    assert result["rows"] > 0  # chains + atm_iv_term contribute rows
    assert "chains" in result["keys"]
    assert "atm_iv_term" in result["keys"]


def test_verify_snapshot_reports_error_gracefully():
    """A raw payload the extractor can't handle produces ok=False, not crash."""
    # Passing a non-dict raw would cause AttributeError inside extract()
    result = verify_snapshot("yahoo_options_chain", None)
    assert result["ok"] is False
    assert "error" in result


def test_committed_aapl_snapshot_extracted_matches_extractor(aapl_snapshot):
    """The `extracted` in the checked-in snapshot must round-trip.

    If someone changes the extractor without regenerating the snapshot,
    this test flags the drift.
    """
    from_raw = apply_extractor("yahoo_options_chain", aapl_snapshot["raw"])
    committed = aapl_snapshot["extracted"]
    # Structural equality on keys + top-level shape
    assert set(from_raw.keys()) == set(committed.keys())
    assert len(from_raw["chains"]) == len(committed["chains"])
    assert len(from_raw["atm_iv_term"]) == len(committed["atm_iv_term"])
    # Symbol + spot exact
    assert from_raw["symbol"] == committed["symbol"]
    assert from_raw["spot"] == committed["spot"]
