"""Unit tests for openbb_sec.utils.bulk_url_discovery (#99 T4).

All offline. Coverage:
- Real SEC HTML fixture -> >=1 quarter parsed
- Empty/reorganized fixture -> ``BulkDiscoveryEmpty`` raised LOUDLY
  (the #97 v1 silent-empty regression guard, codified in Q-A Resolution)
- L2 compliance: every HTTP call routed through ``sec_http.get``
- Whitespace/encoding tolerance + URL format validation
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from openbb_sec.utils.bulk_url_discovery import (
    NPORT_DATA_SETS_URL,
    BulkDiscoveryEmpty,
    discover_quarter_zips,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fake_response(text: str, status_code: int = 200) -> MagicMock:
    """Build a MagicMock response whose .text is the fixture HTML."""
    response = MagicMock(status_code=status_code, text=text)
    response.raise_for_status.return_value = None
    return response


def _populated_html() -> str:
    """Real-shape SEC data-sets page HTML."""
    return (FIXTURES / "sec_nport_data_sets_page.html").read_text(encoding="utf-8")


def _empty_html() -> str:
    """Reorganized SEC page with NO ZIP links — the #97 regression-guard fixture."""
    return (FIXTURES / "sec_nport_data_sets_page_empty.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: real fixture -> >=1 quarter parsed
# ---------------------------------------------------------------------------


def test_discover_quarter_zips_parses_real_html_fixture():
    """Saved fixture HTML -> >=1 quarter found (smoke + structural sanity)."""
    with patch(
        "openbb_sec.utils.bulk_url_discovery.get",
        return_value=_fake_response(_populated_html()),
    ):
        quarters = discover_quarter_zips()
    # The fixture has 9 quarters (2024Q1..2026Q1)
    assert len(quarters) == 9
    assert "2026Q1" in quarters
    assert "2025Q4" in quarters
    assert "2024Q1" in quarters


# ---------------------------------------------------------------------------
# Test 2: the raise-loudly empty guard (the central regression test)
# ---------------------------------------------------------------------------


def test_discover_quarter_zips_raises_on_empty_fixture():
    """Empty/reorganized HTML -> BulkDiscoveryEmpty, NOT {} silently.

    This is the #97 v1 silent-empty regression guard. If this test ever
    becomes a ``return {}`` style assertion, the loud failure mode is gone
    and we re-introduce the silent-zero-holdings cache poisoning.
    """
    with patch(
        "openbb_sec.utils.bulk_url_discovery.get",
        return_value=_fake_response(_empty_html()),
    ), pytest.raises(BulkDiscoveryEmpty, match="No quarter-ZIP links found"):
        discover_quarter_zips()


# ---------------------------------------------------------------------------
# Test 3: L2 compliance — sec_http.get is the chokepoint
# ---------------------------------------------------------------------------


def test_discover_quarter_zips_uses_sec_http_get_for_l2_compliance():
    """Every HTTP call MUST flow through sec_http.get for L2 User-Agent enforcement."""
    with patch(
        "openbb_sec.utils.bulk_url_discovery.get",
        return_value=_fake_response(_populated_html()),
    ) as mock_get:
        discover_quarter_zips()
    mock_get.assert_called_once()
    # The default URL is the SEC data-sets page
    called_url = mock_get.call_args.args[0]
    assert called_url == NPORT_DATA_SETS_URL


# ---------------------------------------------------------------------------
# Test 4: tolerates whitespace + minor HTML variants
# ---------------------------------------------------------------------------


def test_discover_quarter_zips_tolerates_extra_whitespace():
    """Whitespace inside <a> tags, mixed case, etc. should still parse."""
    funky_html = """
<html><body>
<p>
  <a   href = "  /files/dera/data/form-n-port-data-sets/2025q4_nport_p.zip  ">
     2025 Q4 archive
  </a>
</p>
<p>
  <A HREF="https://www.sec.gov/files/dera/data/form-n-port-data-sets/2025Q3_NPORT_P.zip">2025Q3</A>
</p>
</body></html>
"""
    with patch(
        "openbb_sec.utils.bulk_url_discovery.get",
        return_value=_fake_response(funky_html),
    ):
        quarters = discover_quarter_zips()
    assert "2025Q4" in quarters
    assert "2025Q3" in quarters


# ---------------------------------------------------------------------------
# Test 5: keys match YYYYQn format
# ---------------------------------------------------------------------------


def test_discover_quarter_zips_returns_quarter_keys_in_yyyy_qn_format():
    """Every key matches the strict YYYYQn pattern."""
    import re as _re

    with patch(
        "openbb_sec.utils.bulk_url_discovery.get",
        return_value=_fake_response(_populated_html()),
    ):
        quarters = discover_quarter_zips()
    pattern = _re.compile(r"^\d{4}Q[1-4]$")
    for key in quarters:
        assert pattern.match(key), f"key {key!r} does not match YYYYQn"


# ---------------------------------------------------------------------------
# Test 6: every URL value is https://www.sec.gov/...
# ---------------------------------------------------------------------------


def test_discover_quarter_zips_url_values_are_https_sec_gov():
    """Every returned URL is HTTPS + on the sec.gov host (relative URLs resolved)."""
    with patch(
        "openbb_sec.utils.bulk_url_discovery.get",
        return_value=_fake_response(_populated_html()),
    ):
        quarters = discover_quarter_zips()
    for key, url in quarters.items():
        assert url.startswith("https://www.sec.gov/"), (
            f"{key} -> {url} is not HTTPS sec.gov (relative-URL resolution broken?)"
        )
        assert url.endswith(".zip"), f"{key} -> {url} should end in .zip"


# ---------------------------------------------------------------------------
# Bonus regression: first-seen wins on duplicate quarters
# ---------------------------------------------------------------------------


def test_discover_quarter_zips_first_seen_wins_on_duplicate_quarter():
    """If the page has 2 hrefs for the same quarter, take the first (deterministic)."""
    dup_html = """
<html><body>
  <a href="/files/dera/data/form-n-port-data-sets/2025q4_nport_p.zip">first</a>
  <a href="/archive/2025q4_nport_p.zip">second (archive)</a>
</body></html>
"""
    with patch(
        "openbb_sec.utils.bulk_url_discovery.get",
        return_value=_fake_response(dup_html),
    ):
        quarters = discover_quarter_zips()
    assert quarters["2025Q4"].endswith("/files/dera/data/form-n-port-data-sets/2025q4_nport_p.zip")


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
