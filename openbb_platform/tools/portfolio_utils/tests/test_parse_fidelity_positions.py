"""Unit tests for ``portfolio_utils/parse_fidelity_positions.py`` parsing helpers.

These tests use no real account numbers or holdings — only synthetic inputs —
to satisfy the privacy requirements in
``openbb_platform/tools/portfolio_utils/docs_orig/portfolio_basket_privacy_strategy.md``.
"""

import os
import sys

import pytest

# Make the portfolio_utils inner package importable.
_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "portfolio_utils"
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from parse_fidelity_positions import (  # noqa: E402
    parse_currency,
    parse_percent,
    parse_quantity,
    mask_account_number,
)


class TestParseCurrency:
    """``parse_currency`` has a well-defined string -> float contract."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("$10,423.20", 10423.20),
            ("+$5,104.47", 5104.47),
            ("-$183.70", -183.70),
            ("($605.38)", -605.38),
            ("--", 0.0),
            ("N/A", 0.0),
            ("", 0.0),
            ("garbage", 0.0),
        ],
    )
    def test_parse_currency(self, raw, expected):
        assert parse_currency(raw) == pytest.approx(expected)


class TestParsePercent:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("+95.97%", 95.97),
            ("-100%", -100.0),
            ("0%", 0.0),
            ("--", 0.0),
            ("", 0.0),
        ],
    )
    def test_parse_percent(self, raw, expected):
        assert parse_percent(raw) == pytest.approx(expected)


class TestParseQuantity:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("40", 40.0),
            ("6.506", 6.506),
            ("10,000", 10000.0),
            ("--", 0.0),
            ("", 0.0),
        ],
    )
    def test_parse_quantity(self, raw, expected):
        assert parse_quantity(raw) == pytest.approx(expected)


class TestMaskAccountNumber:
    """Account numbers must be masked at extraction time (privacy)."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Z12345678", "****5678"),
            ("123-456-789", "****6789"),
            ("12", "****"),
            ("", ""),
        ],
    )
    def test_mask(self, raw, expected):
        assert mask_account_number(raw) == expected

    def test_mask_never_leaks_full_number(self):
        masked = mask_account_number("987654321")
        assert "98765" not in masked
        assert masked == "****4321"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
