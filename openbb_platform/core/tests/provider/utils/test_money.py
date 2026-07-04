"""OpenBB Platform Core provider utils — money-string parsing tests.

Tests for ``parse_currency`` — the canonical helper that supersedes three
divergent copies in Tools/ (parse_fidelity_positions, load_espp_plan,
share_cost_basis). All three sites will be migrated in a follow-up
``fix/qc-money-decimal-migration`` PR.

Key behavioral promises exercised here:

* Returns ``Decimal`` (not float) — prevents new callers from introducing
  float arithmetic on money.
* Understands all sibling formats: ``$1,234.56``, ``+$5,104.47``,
  ``-$183.70``, ``($605.38)``, ``$492.05 USD``.
* Strict by default: unparseable inputs raise ``ValueError``. Existing
  Tools/ callers use ``on_error="zero"`` for backward compatibility.
* Sentinel values (``--``, ``N/A``, empty) return ``Decimal("0")`` without
  raising, in every ``on_error`` mode.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from openbb_core.provider.utils.money import parse_currency

# ---------------------------------------------------------------------------
# Happy-path — every format from the three sibling sites
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Plain dollar formatting (all three sites)
        ("$10,423.20", Decimal("10423.20")),
        ("$2,595.63", Decimal("2595.63")),
        # Leading + prefix (fidelity only)
        ("+$5,104.47", Decimal("5104.47")),
        # Leading - prefix (fidelity only)
        ("-$183.70", Decimal("-183.70")),
        # Parenthesised negatives (fidelity + share_cost_basis)
        ("($605.38)", Decimal("-605.38")),
        # USD suffix (fidelity + espp)
        ("$492.05 USD", Decimal("492.05")),
        ("$2,571.85 USD", Decimal("2571.85")),
        # Integer amounts
        ("$100", Decimal("100")),
        # Leading / trailing whitespace
        ("  $50.00  ", Decimal("50.00")),
        # Zero
        ("$0.00", Decimal("0.00")),
    ],
)
def test_parse_currency_happy_path(raw: str, expected: Decimal) -> None:
    """Every format produced by the three existing parse_currency siblings parses correctly."""
    assert parse_currency(raw) == expected


def test_parse_currency_returns_decimal_not_float() -> None:
    """The return type is Decimal — float would perpetuate the money-precision bug."""
    result = parse_currency("$1.10")
    assert isinstance(result, Decimal)
    # And is exact — Decimal("1.10"), not the float-repr artifact 1.1000000000000001.
    assert str(result) == "1.10"


def test_parse_currency_preserves_precision() -> None:
    """Sub-cent precision (e.g. 4-decimal share prices) is preserved exactly."""
    assert parse_currency("$1.2345") == Decimal("1.2345")


# ---------------------------------------------------------------------------
# Sentinel values — always return Decimal("0") regardless of on_error mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sentinel", ["--", "N/A", "", "   ", "\t"])
def test_parse_currency_sentinels_return_zero(sentinel: str) -> None:
    """Fidelity/espp/share_cost_basis all treat these as 'no value' — zero, not error."""
    assert parse_currency(sentinel) == Decimal("0")


@pytest.mark.parametrize("sentinel", ["--", "N/A", ""])
def test_parse_currency_sentinels_still_zero_in_strict_mode(sentinel: str) -> None:
    """Sentinels are NOT parse errors — strict mode must still accept them."""
    assert parse_currency(sentinel, on_error="raise") == Decimal("0")


def test_parse_currency_none_treated_as_sentinel() -> None:
    """None (from optional CSV columns) is a sentinel — return zero, don't raise."""
    assert parse_currency(None) == Decimal("0")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Error handling — strict (default) vs zero (legacy Tools/ behavior)
# ---------------------------------------------------------------------------


def test_parse_currency_strict_raises_on_garbage() -> None:
    """Default strict mode raises ValueError on unparseable input."""
    with pytest.raises(ValueError, match="parse"):
        parse_currency("not a number")


def test_parse_currency_zero_mode_swallows_garbage() -> None:
    """on_error='zero' matches the existing Tools/ callers' silent-fallback behavior."""
    assert parse_currency("not a number", on_error="zero") == Decimal("0")


def test_parse_currency_zero_mode_swallows_partially_valid() -> None:
    """on_error='zero' also swallows partially-valid inputs like '$abc.def'."""
    assert parse_currency("$abc.def", on_error="zero") == Decimal("0")


def test_parse_currency_unknown_on_error_mode_raises() -> None:
    """Typos in on_error argument fail fast with ValueError, not silent."""
    with pytest.raises(ValueError, match="on_error"):
        parse_currency("$100", on_error="silent")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Sign handling — parenthesis + minus sign must not double-negate
# ---------------------------------------------------------------------------


def test_parse_currency_paren_wins_over_lack_of_sign() -> None:
    """Parentheses always mean negative, even without an explicit minus sign."""
    assert parse_currency("($10.00)") == Decimal("-10.00")


def test_parse_currency_leading_minus_negative() -> None:
    """A leading minus makes the value negative."""
    assert parse_currency("-$10.00") == Decimal("-10.00")


def test_parse_currency_paren_and_minus_do_not_double_negate() -> None:
    """(($10)) or -($10) style input — negative once, not positive.

    This is a real bug pattern the fidelity variant guards against (uses
    a ``negative`` boolean, not string-based sign inference). Confirms
    the new helper does the same.
    """
    assert parse_currency("-($10.00)") == Decimal("-10.00")


# ---------------------------------------------------------------------------
# Currency-symbol tolerance — accept common alternatives without crashing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        # No currency symbol
        ("1,234.56", Decimal("1234.56")),
        # Comma thousands
        ("1,000,000", Decimal("1000000")),
    ],
)
def test_parse_currency_accepts_bare_numbers(raw: str, expected: Decimal) -> None:
    """Bare numeric strings (no $) parse cleanly — common in CSVs."""
    assert parse_currency(raw) == expected
