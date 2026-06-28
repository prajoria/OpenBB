"""Unit tests for openbb_fmp_cached.models.etf_holdings_issuer (#97 T4).

All offline -- the synthetic SSGA fixture XLSX is generated in-test, and
requests.get is patched so no live network call is made.

The fixture layout mirrors the live SSGA workbook layout confirmed by
the T1 spike (design doc §0.4): header row at index 4, columns
Name|Ticker|Identifier|SEDOL|Weight|Sector|Shares Held|Local Currency,
weight as percentage-decimal (divide by 100), Identifier = 9-char CUSIP.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import openpyxl
import pytest


def _build_ssga_fixture_workbook(path: Path) -> None:
    """Build a tiny SSGA-shaped XLSX. Mirrors live XLK layout from T1 spike.

    Rows 0-3: metadata; row 4: header; rows 5+: data including 1 cash row
    and 1 dash-only row to exercise the parser's skip logic.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "holdings"
    # 4 metadata rows
    ws.append(["Fund Name:", "Technology Select Sector SPDR Fund"])
    ws.append(["Ticker Symbol:", "XLK"])
    ws.append(["Holdings:", "As of 25-Jun-2026"])
    ws.append([])
    # Header row (index 4)
    ws.append([
        "Name", "Ticker", "Identifier", "SEDOL",
        "Weight", "Sector", "Shares Held", "Local Currency",
    ])
    # Data rows (3 real holdings)
    ws.append(["NVIDIA CORP", "NVDA", "67066G104", "2379504",
               14.79788, "-", 90692271.0, "USD"])
    ws.append(["APPLE INC", "AAPL", "037833100", "2046251",
               12.613907, "-", 54995918.0, "USD"])
    ws.append(["MICROSOFT CORP", "MSFT", "594918104", "2588173",
               8.180864, "-", 27815318.0, "USD"])
    # Cash row (parser must skip — name contains "CASH")
    ws.append(["USD CASH", "-", "-", "-",
               0.05, "-", 0, "USD"])
    # Dash-only row (parser must skip — ticker is "-")
    ws.append(["-", "-", "-", "-",
               "-", "-", "-", "-"])
    wb.save(path)


@pytest.fixture
def ssga_fixture_path(tmp_path: Path) -> Path:
    """Build a tiny SSGA-shaped fixture XLSX in a tmp dir; return its path."""
    p = tmp_path / "ssga_xlk_sample.xlsx"
    _build_ssga_fixture_workbook(p)
    return p


# ---------------------------------------------------------------------------
# _parse_ssga_xlsx
# ---------------------------------------------------------------------------


def test_parse_ssga_xlsx_yields_three_real_holdings(ssga_fixture_path):
    """3 real rows + cash + dash-only = 3 returned."""
    from openbb_fmp_cached.models.etf_holdings_issuer import _parse_ssga_xlsx
    rows = _parse_ssga_xlsx(ssga_fixture_path.read_bytes(), ticker="XLK")
    assert len(rows) == 3
    assert [r["symbol"] for r in rows] == ["NVDA", "AAPL", "MSFT"]


def test_parse_ssga_xlsx_skips_cash_rows(ssga_fixture_path):
    """USD CASH name is excluded."""
    from openbb_fmp_cached.models.etf_holdings_issuer import _parse_ssga_xlsx
    rows = _parse_ssga_xlsx(ssga_fixture_path.read_bytes(), ticker="XLK")
    assert all((r.get("name") or "").upper() != "USD CASH" for r in rows)


def test_parse_ssga_xlsx_skips_dash_only_rows(ssga_fixture_path):
    """Ticker '-' is excluded."""
    from openbb_fmp_cached.models.etf_holdings_issuer import _parse_ssga_xlsx
    rows = _parse_ssga_xlsx(ssga_fixture_path.read_bytes(), ticker="XLK")
    assert all(r["symbol"] != "-" for r in rows)


def test_parse_ssga_xlsx_normalizes_weight_percent_to_fraction(ssga_fixture_path):
    """SSGA writes weight as 14.79788 (%); parser must return ~0.148."""
    from openbb_fmp_cached.models.etf_holdings_issuer import _parse_ssga_xlsx
    rows = _parse_ssga_xlsx(ssga_fixture_path.read_bytes(), ticker="XLK")
    nvda = next(r for r in rows if r["symbol"] == "NVDA")
    assert 0.14 < nvda["weight"] < 0.15


def test_parse_ssga_xlsx_extracts_cusip_from_identifier(ssga_fixture_path):
    """The Identifier column is the 9-char CUSIP."""
    from openbb_fmp_cached.models.etf_holdings_issuer import _parse_ssga_xlsx
    rows = _parse_ssga_xlsx(ssga_fixture_path.read_bytes(), ticker="XLK")
    aapl = next(r for r in rows if r["symbol"] == "AAPL")
    assert aapl["cusip"] == "037833100"


def test_parse_ssga_xlsx_extracts_shares(ssga_fixture_path):
    """Shares Held column is read as a float."""
    from openbb_fmp_cached.models.etf_holdings_issuer import _parse_ssga_xlsx
    rows = _parse_ssga_xlsx(ssga_fixture_path.read_bytes(), ticker="XLK")
    aapl = next(r for r in rows if r["symbol"] == "AAPL")
    assert aapl["shares"] == 54995918.0


def test_parse_ssga_xlsx_extracts_name(ssga_fixture_path):
    """Name column is preserved verbatim (stripped)."""
    from openbb_fmp_cached.models.etf_holdings_issuer import _parse_ssga_xlsx
    rows = _parse_ssga_xlsx(ssga_fixture_path.read_bytes(), ticker="XLK")
    aapl = next(r for r in rows if r["symbol"] == "AAPL")
    assert aapl["name"] == "APPLE INC"


def test_parse_ssga_xlsx_sets_data_source_tag(ssga_fixture_path):
    """Every parsed row carries data_source='issuer_ssga' for tier attribution."""
    from openbb_fmp_cached.models.etf_holdings_issuer import _parse_ssga_xlsx
    rows = _parse_ssga_xlsx(ssga_fixture_path.read_bytes(), ticker="XLK")
    assert all(r["data_source"] == "issuer_ssga" for r in rows)


def test_parse_ssga_xlsx_empty_content_returns_empty():
    """Bad bytes don't crash; return []."""
    from openbb_fmp_cached.models.etf_holdings_issuer import _parse_ssga_xlsx
    assert _parse_ssga_xlsx(b"", ticker="XLK") == []


# ---------------------------------------------------------------------------
# ISSUER_REGISTRY
# ---------------------------------------------------------------------------


def test_issuer_registry_has_all_eleven_spdrs():
    """All 11 GICS sector SPDRs (techtrade scan universe) are registered."""
    from openbb_fmp_cached.models.etf_holdings_issuer import ISSUER_REGISTRY
    for t in ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK",
              "XLP", "XLRE", "XLU", "XLV", "XLY"):
        assert t in ISSUER_REGISTRY, f"{t} missing from ISSUER_REGISTRY"
        spec = ISSUER_REGISTRY[t]
        assert spec.issuer_id == "issuer_ssga"
        assert t.lower() in spec.url
        assert spec.url.startswith("https://www.ssga.com/")


# ---------------------------------------------------------------------------
# fetch_issuer_holdings
# ---------------------------------------------------------------------------


def test_fetch_issuer_holdings_unknown_ticker_returns_empty_no_http():
    """Unknown ETF -> [] without making any HTTP call."""
    from openbb_fmp_cached.models.etf_holdings_issuer import fetch_issuer_holdings
    fake_http = MagicMock()
    fake_http.get.side_effect = AssertionError("must NOT be called for unknown")
    assert fetch_issuer_holdings("BOGUS", http=fake_http) == []
    fake_http.get.assert_not_called()


def test_fetch_issuer_holdings_http_error_returns_empty():
    """Network failure -> [] (never raises)."""
    from openbb_fmp_cached.models.etf_holdings_issuer import fetch_issuer_holdings
    fake_http = MagicMock()
    fake_http.get.side_effect = ConnectionError("DNS down")
    assert fetch_issuer_holdings("XLK", http=fake_http) == []


def test_fetch_issuer_holdings_404_returns_empty():
    """4xx response -> [] (never raises)."""
    from openbb_fmp_cached.models.etf_holdings_issuer import fetch_issuer_holdings
    response = MagicMock(status_code=404)
    response.raise_for_status.side_effect = Exception("404 Not Found")
    fake_http = MagicMock()
    fake_http.get.return_value = response
    assert fetch_issuer_holdings("XLK", http=fake_http) == []


def test_fetch_issuer_holdings_happy_path_returns_rows(ssga_fixture_path):
    """200 + valid SSGA workbook -> parsed rows with data_source tag."""
    from openbb_fmp_cached.models.etf_holdings_issuer import fetch_issuer_holdings
    fake_http = MagicMock()
    response = MagicMock(status_code=200)
    response.content = ssga_fixture_path.read_bytes()
    response.raise_for_status.return_value = None
    fake_http.get.return_value = response
    rows = fetch_issuer_holdings("XLK", http=fake_http)
    assert len(rows) == 3
    assert all(r["data_source"] == "issuer_ssga" for r in rows)
    # URL hit was the SPDR XLK template
    called_url = fake_http.get.call_args.args[0]
    assert "holdings-daily-us-en-xlk.xlsx" in called_url


def test_fetch_issuer_holdings_uppercases_input(ssga_fixture_path):
    """`xlk` (lowercase) resolves to the same XLK ISSUER_REGISTRY entry."""
    from openbb_fmp_cached.models.etf_holdings_issuer import fetch_issuer_holdings
    fake_http = MagicMock()
    response = MagicMock(status_code=200)
    response.content = ssga_fixture_path.read_bytes()
    response.raise_for_status.return_value = None
    fake_http.get.return_value = response
    rows = fetch_issuer_holdings("xlk", http=fake_http)
    assert len(rows) == 3
