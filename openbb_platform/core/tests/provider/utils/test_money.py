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
* Strict by default: unparsable inputs raise ``ValueError``. Existing
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
    """Default strict mode raises ValueError on unparsable input."""
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
    """``-($10)`` style input — negative once, not positive.

    This is a real bug pattern the fidelity variant guards against (uses
    a ``negative`` boolean, not string-based sign inference). Confirms
    the new helper does the same. Doubled-paren nesting like ``(($10))``
    is covered by ``test_parse_currency_nested_parens_do_not_sign_double``.
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


# ---------------------------------------------------------------------------
# QC self-review findings (added after Phase-6 QC pass on the branch)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        # Scientific notation — 'e' gets stripped by the letter regex, silently
        # turning $1e5 (= 100000) into 15 in the old lossy implementation.
        "$1e5",
        # Unit suffixes — Fidelity CSVs include these; silently misparses to 1.5
        # (should raise so caller sees the data corruption).
        "$1.5M",
        "$1K",
        "$1B",
        # Hex-like prefix — 0x10 -> 010 -> 10 silently (should raise).
        "$0x10",
    ],
)
def test_parse_currency_rejects_scientific_and_unit_suffixes(raw: str) -> None:
    """Inputs with 'e', 'K', 'M', 'B', 'x' letters must raise, not silently misparse.

    Regression test for QC finding #2 — the ``[A-Za-z]`` character class in
    the strip regex used to swallow scientific-notation ``e`` and unit
    suffixes ``K``/``M``/``B``/``x`` without complaint, producing values
    off by 3-9 orders of magnitude. This is the worst kind of silent bug:
    the resulting Decimal looks plausible.
    """
    with pytest.raises(ValueError, match="parse"):
        parse_currency(raw)


def test_parse_currency_accepts_usd_suffix_after_fix() -> None:
    """The ``USD`` currency suffix is still accepted (backward compatibility)."""
    # Post-fix, the strip regex only removes whitelisted suffix letters (USD)
    # and rejects everything else. USD suffix must still work.
    assert parse_currency("$492.05 USD") == Decimal("492.05")


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Unicode minus sign U+2212 — Excel and PDF copy-paste use this.
        ("$−100", Decimal("-100")),
        # Fullwidth hyphen-minus U+FF0D.
        ("$－50.00", Decimal("-50.00")),
    ],
)
def test_parse_currency_normalises_unicode_minus(raw: str, expected: Decimal) -> None:
    """Unicode minus variants are normalised to ASCII '-' before sign inference.

    Regression test for QC finding #3 — the old sign check only looked at
    ASCII hyphen ``-``, so ``$−100`` (U+2212, common in Excel exports) was
    parsed as raise/zero instead of ``-100``.
    """
    assert parse_currency(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        # All-letter inputs that used to strip to empty — should now raise
        # in strict mode because they're clearly not numbers.
        "USD",
        "unknown",
        "$USD",
        "$",
    ],
)
def test_parse_currency_all_letter_input_raises(raw: str) -> None:
    """Non-numeric inputs raise in strict mode (was silently returning 0 before).

    Regression test for QC finding #5 — a lone ``USD`` in a money column is
    almost certainly a header row leaking into data. Better to surface the
    problem than silently zero the value.
    """
    with pytest.raises(ValueError, match="parse"):
        parse_currency(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "USD",
        "unknown",
        "$",
    ],
)
def test_parse_currency_all_letter_input_zero_mode_returns_zero(raw: str) -> None:
    """In on_error='zero' mode the same non-numeric inputs return zero (legacy compat)."""
    assert parse_currency(raw, on_error="zero") == Decimal("0")


def test_parse_currency_parenthesised_sentinel_returns_zero() -> None:
    """``(--)`` and ``(N/A)`` inside parens still count as sentinel-zero.

    Regression test for QC finding #7 — the old code set negative=True from
    the paren, then stripped to empty and raised. Now the sentinel check
    strips the parens/whitespace first.
    """
    assert parse_currency("(--)") == Decimal("0")
    assert parse_currency("(N/A)") == Decimal("0")


def test_parse_currency_multiple_decimals_raises() -> None:
    """``$1.2.3`` is unambiguously bad input — must raise in strict mode."""
    with pytest.raises(ValueError, match="parse"):
        parse_currency("$1.2.3")


def test_parse_currency_bare_hyphen_raises() -> None:
    """A lone ``-`` has no magnitude — must raise (not become negative zero)."""
    with pytest.raises(ValueError, match="parse"):
        parse_currency("-")


# ---------------------------------------------------------------------------
# Round-1 review findings (silent-failure-hunter + pr-test-analyzer + code-reviewer)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        # European decimal comma with US thousands comma — ambiguous shape, must reject.
        # $1.234,56 (EU notation for US $1,234.56) used to silently misparse to 1.23456.
        "$1.234,56",
        "1.234,56",
        # Doubled EU thousands — even more corrupted.
        "$1.234.567,89",
    ],
)
def test_parse_currency_rejects_european_decimal_format(raw: str) -> None:
    """European-locale money formatting must raise, not silently misparse 1000×.

    Regression test for silent-failure-hunter finding — the old strip regex
    turned ``$1.234,56`` (EU for US $1,234.56) into ``1.23456`` because
    it stripped the comma as a thousands separator and kept the dot as
    decimal. Now the pre-strip well-formed-US-money check rejects it.
    """
    with pytest.raises(ValueError, match="parse"):
        parse_currency(raw)


@pytest.mark.parametrize(
    "raw",
    [
        # Missing close paren.
        "($1,234.56",
        # Missing open paren.
        "$1,234.56)",
        # Extra unbalanced.
        "(($10.00)",
    ],
)
def test_parse_currency_rejects_unbalanced_parens(raw: str) -> None:
    """Unbalanced parens make sign inference unsafe — must raise.

    Regression test for silent-failure-hunter finding — a single missing
    paren used to silently flip the sign in one direction but not the
    other, producing plausible-looking but wrong values from typos.
    """
    with pytest.raises(ValueError, match="parse|unbalanced"):
        parse_currency(raw)


@pytest.mark.parametrize(
    "raw",
    [
        # Lone paren, no content — obvious corruption, not a sentinel.
        "(",
        ")",
        ")(",
    ],
)
def test_parse_currency_lone_paren_is_not_sentinel(raw: str) -> None:
    """A lone ``(`` or ``)`` is data corruption, not an empty sentinel.

    Regression test for silent-failure-hunter finding — the sentinel
    probe used to collapse ``"("`` to empty via ``strip("()")`` and
    then return Decimal("0"), masking truncated CSV cells.
    """
    with pytest.raises(ValueError, match="parse|unbalanced"):
        parse_currency(raw)


@pytest.mark.parametrize(
    "raw,expected",
    [
        # U+2013 EN DASH — explicitly named in the source translate table.
        ("$–100", Decimal("-100")),
        # U+2014 EM DASH — same.
        ("$—50.00", Decimal("-50.00")),
    ],
)
def test_parse_currency_normalises_en_and_em_dash(raw: str, expected: Decimal) -> None:
    """U+2013 en-dash and U+2014 em-dash normalise to '-' for sign inference.

    Regression test for pr-test-analyzer finding #6 — the source
    translate table names three non-ASCII dashes (U+2212, U+2013, U+2014)
    but only U+2212 was tested. A regression removing '–' or '—' from
    the table would silently pass the entire prior suite.
    """
    assert parse_currency(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Uppercase USD (already tested, kept for parity)
        ("$100 USD", Decimal("100")),
        # Lowercase usd — common in PDF-extracted CSVs
        ("$100 usd", Decimal("100")),
        # Mixed case
        ("$100 Usd", Decimal("100")),
        ("$100 uSD", Decimal("100")),
    ],
)
def test_parse_currency_usd_suffix_is_case_insensitive(
    raw: str, expected: Decimal
) -> None:
    """USD suffix works in any case — the source regex uses re.IGNORECASE.

    Regression test for pr-test-analyzer finding — removing IGNORECASE
    or narrowing to [A-Z]{3} would silently pass the old suite because
    only uppercase was tested.
    """
    assert parse_currency(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # (($10.00)) — doubled parens still mean negative once (boolean flag, not XOR).
        ("(($10.00))", Decimal("-10.00")),
        # Combined leading '-' with doubled parens — still negative once.
        ("((-$10))", Decimal("-10")),
    ],
)
def test_parse_currency_nested_parens_do_not_sign_double(
    raw: str, expected: Decimal
) -> None:
    """Doubled parens keep the negative-flag boolean semantics.

    Regression test for pr-test-analyzer finding — an implementation
    that toggled the sign per paren (XOR) or summed contributions
    would silently pass the ``-($10)`` test but flip doubled parens
    back to positive.
    """
    assert parse_currency(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        # Shapes that fail the pre-strip _WELL_FORMED_US regex (no digit run):
        # zero-mode must return Decimal("0") via the _fail_or_zero path.
        ".",
        "-.",
    ],
)
def test_parse_currency_no_digits_shape_returns_zero(
    raw: str,
) -> None:
    r"""on_error='zero' mode covers no-digits shapes via the well-formed guard.

    ``'.'`` and ``'-.'`` both fail the pre-strip ``_WELL_FORMED_US`` regex
    (which requires at least one digit run) and route through
    ``_fail_or_zero``. This test locks in the zero-mode branch of that
    helper for the no-digits family — the Decimal-raises branch is
    covered separately in
    ``test_parse_currency_double_sign_hits_decimal_invalidoperation``.
    """
    assert parse_currency(raw, on_error="zero") == Decimal("0")


@pytest.mark.parametrize(
    "raw",
    ["n/a", "N/a", "n/A"],
)
def test_parse_currency_sentinel_case_insensitive(raw: str) -> None:
    """Sentinel matching is case-insensitive — 'n/a' is as valid as 'N/A'.

    Regression test for pr-test-analyzer finding — the source comment
    said the sentinel probe is case-insensitive but the frozenset only
    stored 'N/A' (uppercase). Now the probe upper-cases before lookup.
    """
    assert parse_currency(raw) == Decimal("0")


# ---------------------------------------------------------------------------
# Round-2 review findings (silent-failure-hunter + pr-test-analyzer)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        # str.strip('()') is CHARACTER-CLASS based, not matched-pair based, so
        # multiple leading/trailing parens all get stripped. Old code let
        # '()', '()()', '(())', '(N/A)()' all reduce to a sentinel string and
        # silently return Decimal(0) even in on_error='raise' mode.
        "()",
        "()()",
        "(())",
        "( )",
        "(N/A)()",
        # Doubly-wrapped sentinels — docstring promises 'only a SINGLE
        # balanced outer paren pair counts', so these must raise too. Locks
        # in single-pair semantics against a refactor to recursive unwrapping
        # like `while s.startswith('(') and s.endswith(')'): s = s[1:-1]`.
        "((N/A))",
        "((--))",
        "(( -- ))",
    ],
)
def test_parse_currency_multi_paren_wrapping_is_not_sentinel(raw: str) -> None:
    """Only a single balanced outer paren-pair counts for sentinel unwrapping.

    Regression tests for silent-failure-hunter Round-2 and pr-test-analyzer
    Round-3 findings — obvious corruption like ``()`` or ``()()`` used to
    silently return zero because ``str.strip('()')`` treats its argument as
    a character class, not a matched-pair pattern. The new sentinel probe
    strips at most one outer balanced pair AND requires the interior to be
    a non-empty known sentinel — so doubly-wrapped sentinels like ``((N/A))``
    are also rejected as ambiguous/corrupt.
    """
    with pytest.raises(ValueError, match="parse"):
        parse_currency(raw)


def test_parens_are_balanced_helper_rejects_ordering_violations() -> None:
    """``_parens_are_balanced`` uses walking-depth semantics, not count-only.

    Tests the helper DIRECTLY because the public ``parse_currency`` pipeline's
    ``_WELL_FORMED_US`` regex structurally prevents any ordering-violating
    string (``)`` in prefix, ``(`` in suffix) from ever reaching the balance
    check. So a naive ``count('(') == count(')')`` refactor of the helper
    would pass every parse_currency test — but the helper is defense-in-depth
    against future well-formed regex changes, and this test documents that
    intent.
    """
    # pylint: disable=import-outside-toplevel
    from openbb_core.provider.utils.money import _parens_are_balanced

    assert _parens_are_balanced("(())")
    assert _parens_are_balanced("()()")
    assert _parens_are_balanced("")
    assert not _parens_are_balanced(")(")
    assert not _parens_are_balanced("))((")
    assert not _parens_are_balanced("(")
    assert not _parens_are_balanced(")")


@pytest.mark.parametrize(
    "raw",
    [
        # Combined case-fold + paren-strip — properties tested independently
        # in existing tests but not composed.
        "(n/a)",
        " ( -- ) ",
        "(  N/a  )",
    ],
)
def test_parse_currency_paren_wrapped_case_insensitive_sentinel(raw: str) -> None:
    """Paren-wrapping and case-insensitivity compose for sentinel matching.

    Regression test for pr-test-analyzer Round-2 finding — a refactor
    that upper-cased BEFORE stripping outer parens (or vice-versa in a
    way that broke composition) would silently pass the two separate
    tests but fail on the combined case.
    """
    assert parse_currency(raw) == Decimal("0")


def test_parse_currency_negative_zero_collapses_to_positive_zero() -> None:
    """``$-0``, ``($0)`` etc. return unsigned ``Decimal('0')``, not ``Decimal('-0')``.

    Regression test for silent-failure-hunter Round-2 finding — ``-0``
    == ``0`` but ``str(Decimal('-0'))`` is ``'-0'`` and ``.is_signed()``
    is True, so downstream JSON/CSV serialisation or sign-dispatch code
    would see spurious negatives.
    """
    for raw in ("$-0", "($0)", "(-$0.00)", "-$0.00"):
        result = parse_currency(raw)
        assert result == Decimal("0"), f"parse_currency({raw!r}) magnitude"
        assert (
            not result.is_signed()
        ), f"parse_currency({raw!r}) has signed-zero: str={str(result)!r}"


def test_parse_currency_excel_style_dollar_minus_100() -> None:
    """``$-100`` (Excel style — sign after currency symbol) parses correctly.

    Regression test for code-reviewer near-miss — the module docstring
    lists ``$-100`` as a supported format, but no test exercised it.
    A regression that assumed sign must precede the currency symbol
    would silently pass every other test.
    """
    assert parse_currency("$-100") == Decimal("-100")


@pytest.mark.parametrize(
    "raw",
    [
        # '--100' passes the well-formed regex (prefix char class includes '-')
        # but Decimal('--100') raises InvalidOperation because the '-' chars
        # aren't stripped (only '+' is in the strip regex). This is the input
        # shape that actually exercises the try/except at the Decimal() call.
        # Note: '++100' does NOT reach the except — the strip regex removes
        # both '+' chars and Decimal('100') parses fine, so it returns 100.
        "--100",
    ],
)
def test_parse_currency_double_minus_hits_decimal_invalidoperation(
    raw: str,
) -> None:
    """Inputs the well-formed regex accepts but ``Decimal()`` rejects raise ValueError.

    Regression test for pr-test-analyzer Round-2 finding — the earlier
    ``test_parse_currency_regex_accepts_but_decimal_rejects_returns_zero``
    used inputs (``'.'``, ``'-.'``) that actually failed the pre-strip
    well-formed regex and never reached the ``Decimal()`` call. This
    input (``'--100'``) does reach it, so it locks the exception-type
    wrapping (``ValueError`` from ``InvalidOperation``).
    """
    with pytest.raises(ValueError, match="parse"):
        parse_currency(raw)


def test_parse_currency_double_minus_zero_mode_returns_zero() -> None:
    """``--100`` in ``on_error='zero'`` mode returns zero via the InvalidOperation branch."""
    assert parse_currency("--100", on_error="zero") == Decimal("0")
