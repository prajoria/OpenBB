"""Unit tests for openbb_sec.utils.nport_parser (#99 T3).

All offline + fixture-driven. Coverage:
- Envelope splitting (NPORT-P vs NPORT-P/A detection)
- Filing metadata extraction (CIK, series_id, report_date)
- Holdings extraction (CUSIP/ISIN/LEI all present, ISIN-only, derivative)
- G4 ``derive_holding_key`` waterfall + ``apply_lot_suffix`` determinism
- Graceful failure on malformed input (logs, no raise)
- L11 amendment detection via form-type suffix
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from openbb_sec.utils.nport_parser import (
    apply_lot_suffix,
    derive_holding_key,
    parse_submission_envelope,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _read_fixture(name: str) -> bytes:
    """Read a fixture file as raw bytes (envelopes can be CRLF or LF)."""
    return (FIXTURES / name).read_bytes()


# ---------------------------------------------------------------------------
# Test 1-5: high-level fixture parsing
# ---------------------------------------------------------------------------


def test_parse_minimal_etf_envelope_yields_filing_and_holdings():
    """Fixture 1 -> NportFiling with CIK + 3 holdings."""
    raw = _read_fixture("nport_p_etf_minimal.txt")
    filing, holdings = parse_submission_envelope(
        raw, accession_number="0001234567-26-000001", source="sec_nport_archive"
    )
    assert filing["cik"] == "0000884394"
    assert filing["series_id"] == "S000004310"
    assert filing["is_amendment"] is False
    assert filing["source"] == "sec_nport_archive"
    assert len(holdings) == 3
    # All three are AAPL/MSFT/NVDA — every one has CUSIP, so holding_key == CUSIP
    keys = {h["holding_key"] for h in holdings}
    assert keys == {"037833100", "594918104", "67066G104"}


def test_parse_extracts_cik_and_series_id_from_envelope():
    """G1 fund-key extraction works (powers L10 as-of read helper)."""
    raw = _read_fixture("nport_p_etf_minimal.txt")
    filing, _ = parse_submission_envelope(
        raw, accession_number="X", source="sec_nport_archive"
    )
    # CIK is left-padded to 10 chars (matches thirteen_f_index convention)
    assert filing["cik"] == "0000884394"
    assert filing["series_id"] == "S000004310"
    assert filing["class_id"] == "C000011948"


def test_parse_detects_amendment_from_form_type():
    """Fixture 2 has <TYPE>NPORT-P/A -> is_amendment True (L11)."""
    raw = _read_fixture("nport_p_a_amendment.txt")
    filing, holdings = parse_submission_envelope(
        raw, accession_number="0001234567-26-000002", source="sec_nport_archive"
    )
    assert filing["is_amendment"] is True
    # Amendment retains the same (cik, series_id, period) — that's how L11 supersedes
    assert filing["cik"] == "0000884394"
    assert filing["series_id"] == "S000004310"
    assert filing["report_date"] == date(2025, 12, 31)
    assert len(holdings) == 2


def test_parse_handles_derivative_heavy_filing():
    """Fixture 3 -> derivative_flag=True on the future + swap rows."""
    raw = _read_fixture("nport_p_derivative_heavy.txt")
    _, holdings = parse_submission_envelope(
        raw, accession_number="X", source="sec_nport_bulk"
    )
    assert len(holdings) == 3
    derivative = [h for h in holdings if h.get("derivative_flag")]
    assert len(derivative) == 2  # the future + the swap
    non_derivative = [h for h in holdings if not h.get("derivative_flag")]
    assert len(non_derivative) == 1
    assert non_derivative[0]["cusip"] == "91282CJZ5"


def test_parse_handles_isin_only_holding():
    """Fixture 4: international names with ISIN but no CUSIP -> holding_key = ISIN."""
    raw = _read_fixture("nport_p_no_cusip_isin_only.txt")
    _, holdings = parse_submission_envelope(
        raw, accession_number="X", source="sec_nport_archive"
    )
    assert len(holdings) == 3
    sap = next(h for h in holdings if h["issuer_name"] == "SAP SE")
    assert sap["cusip"] is None
    assert sap["isin"] == "DE0007164600"
    # G4: ISIN is the holding_key when CUSIP is missing
    assert sap["holding_key"] == "DE0007164600"


# ---------------------------------------------------------------------------
# Test 6-9: derive_holding_key waterfall (G4)
# ---------------------------------------------------------------------------


def test_derive_holding_key_prefers_cusip_when_present():
    """G4: CUSIP wins the waterfall regardless of other ids."""
    key = derive_holding_key(
        issuer_name="APPLE INC",
        asset_category="EC",
        cusip="037833100",
        isin="US0378331005",
        lei="HWUPKR0MPOU8FGXBT394",
    )
    assert key == "037833100"


def test_derive_holding_key_falls_back_to_isin():
    """G4: CUSIP None -> ISIN."""
    key = derive_holding_key(
        issuer_name="SAP SE",
        asset_category="EC",
        cusip=None,
        isin="DE0007164600",
        lei="529900D6BF99LW9R2E68",
    )
    assert key == "DE0007164600"


def test_derive_holding_key_falls_back_to_lei():
    """G4: CUSIP and ISIN both None -> LEI."""
    key = derive_holding_key(
        issuer_name="JPMORGAN CHASE BANK NA",
        asset_category="DE",
        cusip=None,
        isin=None,
        lei="549300HKH7SYBT4ZH569",
    )
    assert key == "549300HKH7SYBT4ZH569"


def test_derive_holding_key_falls_back_to_sha1():
    """G4 final fallback: 16-hex-char sha1 of issuer||asset_cat."""
    key = derive_holding_key(
        issuer_name="ACME CAPITAL PARTNERS LP",
        asset_category="DBT",
        cusip=None,
        isin=None,
        lei=None,
    )
    assert len(key) == 16
    assert all(c in "0123456789abcdef" for c in key)
    # Same content -> same key (idempotency)
    assert key == derive_holding_key(
        issuer_name="ACME CAPITAL PARTNERS LP",
        asset_category="DBT",
        cusip=None,
        isin=None,
        lei=None,
    )


def test_derive_holding_key_skips_placeholder_cusips():
    """G4 hygiene: 'N/A', '0', '000000000' do NOT count as a CUSIP."""
    key = derive_holding_key(
        issuer_name="SPX FUTURE MAR2026",
        asset_category="DE",
        cusip="N/A",
        isin=None,
        lei="5493000F4ZO33MV32P92",
    )
    # CUSIP rejected as placeholder -> falls to LEI
    assert key == "5493000F4ZO33MV32P92"


# ---------------------------------------------------------------------------
# Test 10-12: apply_lot_suffix determinism + collision-handling
# ---------------------------------------------------------------------------


def test_apply_lot_suffix_appends_lotN_to_collisions():
    """Three same-key holdings get bare, _lot2, _lot3 in deterministic order."""
    rows = [
        {"holding_key": "ABC123", "issuer_name": "ACME CORP", "cusip": "ABC123"},
        {"holding_key": "ABC123", "issuer_name": "ACME CORP", "cusip": "ABC123"},
        {"holding_key": "ABC123", "issuer_name": "ACME CORP", "cusip": "ABC123"},
    ]
    out = apply_lot_suffix(rows)
    assert {h["holding_key"] for h in out} == {"ABC123", "ABC123_lot2", "ABC123_lot3"}


def test_apply_lot_suffix_is_deterministic_across_parses():
    """Same input set produces same suffixes regardless of input order (G4 idempotency)."""
    rows_ordering_a = [
        {"holding_key": "K1", "issuer_name": "ZZZ"},
        {"holding_key": "K1", "issuer_name": "ZZZ"},
        {"holding_key": "K2", "issuer_name": "AAA"},
    ]
    rows_ordering_b = [
        {"holding_key": "K2", "issuer_name": "AAA"},
        {"holding_key": "K1", "issuer_name": "ZZZ"},
        {"holding_key": "K1", "issuer_name": "ZZZ"},
    ]
    out_a = sorted([h["holding_key"] for h in apply_lot_suffix(rows_ordering_a)])
    out_b = sorted([h["holding_key"] for h in apply_lot_suffix(rows_ordering_b)])
    assert out_a == out_b
    assert out_a == ["K1", "K1_lot2", "K2"]


def test_parse_same_issuer_multiple_lots_round_trip_with_apply_lot_suffix():
    """Fixture 5: 3 lots of ACME under same issuer -> distinct holding_keys after suffix."""
    raw = _read_fixture("nport_p_same_issuer_multiple_lots.txt")
    _, holdings = parse_submission_envelope(
        raw, accession_number="X", source="sec_nport_archive"
    )
    assert len(holdings) == 3
    keys = [h["holding_key"] for h in holdings]
    # All three keys are distinct after lot-suffix
    assert len(set(keys)) == 3
    # Two of the three have the _lotN suffix (the bare key + 2 suffixed)
    suffixed = [k for k in keys if "_lot" in k]
    assert len(suffixed) == 2


# ---------------------------------------------------------------------------
# Test 13-15: graceful failure + source-tag propagation + L10 date parsing
# ---------------------------------------------------------------------------


def test_parse_invalid_envelope_returns_filing_with_empty_holdings_no_raise(caplog):
    """Garbage bytes -> (NportFiling{accession_number, source, is_amendment=False}, []) + WARNING."""
    raw = b"this is not a valid SEC document envelope"
    with caplog.at_level("WARNING"):
        filing, holdings = parse_submission_envelope(
            raw, accession_number="BAD", source="sec_nport_bulk"
        )
    assert filing["accession_number"] == "BAD"
    assert filing["source"] == "sec_nport_bulk"
    assert filing["is_amendment"] is False
    assert holdings == []
    # A WARNING was logged
    assert any("BAD" in rec.message or "no <XML>" in rec.message for rec in caplog.records)


def test_parse_envelope_carries_source_tag_through():
    """Source tag (sec_nport_bulk / sec_nport_archive / sec_nport_submissions) propagates."""
    raw = _read_fixture("nport_p_etf_minimal.txt")
    for source in ("sec_nport_bulk", "sec_nport_archive", "sec_nport_submissions"):
        filing, _ = parse_submission_envelope(raw, accession_number="X", source=source)
        assert filing["source"] == source


def test_parse_extracts_report_date_for_l10():
    """L10: report_date is a date object, not a string (the read helper sorts by it)."""
    raw = _read_fixture("nport_p_etf_minimal.txt")
    filing, _ = parse_submission_envelope(
        raw, accession_number="X", source="sec_nport_archive"
    )
    assert filing["report_date"] == date(2025, 12, 31)
    assert isinstance(filing["report_date"], date)


def test_parse_empty_input_returns_empty_filing(caplog):
    """Zero-byte input -> (filing-with-meta-only, []) + WARNING (no IndexError)."""
    with caplog.at_level("WARNING"):
        filing, holdings = parse_submission_envelope(
            b"", accession_number="EMPTY", source="sec_nport_archive"
        )
    assert filing["accession_number"] == "EMPTY"
    assert holdings == []
    assert any("EMPTY" in rec.message or "empty" in rec.message.lower() for rec in caplog.records)


# ---------------------------------------------------------------------------
# Bonus regression: defusedxml blocks XXE
# ---------------------------------------------------------------------------


def test_parse_rejects_xxe_external_entity_attack():
    """Security: defusedxml swap blocks <!ENTITY xxe SYSTEM 'file:///'> attacks.

    A malicious filer (or compromised intermediary) cannot make the parser
    read files off the local filesystem during ingest.
    """
    malicious_xml = b"""<?xml version="1.0"?>
<!DOCTYPE foo [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<SEC-DOCUMENT>
<TYPE>NPORT-P
<XML>
<root>&xxe;</root>
</XML>
</SEC-DOCUMENT>"""
    # Parser logs a WARNING (defusedxml raises EntitiesForbidden -> ParseError-equivalent)
    # and returns empty holdings — no file content leaks.
    filing, holdings = parse_submission_envelope(
        malicious_xml, accession_number="XXE", source="sec_nport_bulk"
    )
    assert filing["accession_number"] == "XXE"
    assert holdings == []  # parse aborted, no data extracted


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
