"""Tests for scrape_record.yahoo_dom helpers (pure-Python parsers).

The DOM-scrape composers (``scrape_quote`` / ``scrape_profile`` /
``scrape_etf_holdings``) require a live Playwright page — they're
smoke-tested at Daisy's operator run, not in unit tests. Here we
cover the pure parsers only.
"""

from __future__ import annotations

from scrape_record.yahoo_dom import _parse_bignum, _parse_number


def test_parse_number_plain():
    """Plain float parses."""
    assert _parse_number("381.70") == 381.70


def test_parse_number_with_commas():
    """Numbers with thousands-separator commas parse."""
    assert _parse_number("12,345.67") == 12345.67


def test_parse_number_currency():
    """Currency-prefixed numbers ($450.12) parse."""
    assert _parse_number("$450.12") == 450.12


def test_parse_number_signed():
    """Signed / percent-suffixed numbers parse."""
    assert _parse_number("+0.03%") == 0.03
    assert _parse_number("-14.9%") == -14.9


def test_parse_number_empty_fallback():
    """Empty / N/A / '--' inputs return None (not zero)."""
    assert _parse_number("--") is None
    assert _parse_number("N/A") is None
    assert _parse_number(None) is None
    assert _parse_number("") is None


def test_parse_bignum_scales():
    """K/M/B/T suffixes scale correctly."""
    assert _parse_bignum("2.83T") == 2.83e12
    assert _parse_bignum("1.5B") == 1.5e9
    assert _parse_bignum("100M") == 100e6
    assert _parse_bignum("221k") == 221e3


def test_parse_bignum_plain_number():
    """Un-suffixed numbers fall through to _parse_number."""
    # No suffix should return the plain number via _parse_number fallback
    assert _parse_bignum("221000") == 221000


def test_parse_bignum_missing():
    """Empty inputs return None."""
    assert _parse_bignum(None) is None
    assert _parse_bignum("--") is None
    assert _parse_bignum("") is None
