"""Money-string parsing helpers for OpenBB Core providers.

This module exposes ``parse_currency`` — the canonical helper that supersedes
three divergent copies discovered by the Round 1 QC sweep of this fork:

* ``Tools/parse_fidelity_positions.py::parse_currency``
* ``Tools/load_espp_plan.py::parse_currency``
* ``Tools/share_cost_basis.py::parse_currency``

All three:

1. Return ``float`` instead of ``Decimal`` — losing precision on cents
2. Silently return ``0.0`` on parse errors — masking data corruption
3. Handle overlapping-but-different subsets of currency formats
   (fidelity accepts ``+`` prefix and ``USD`` suffix, share_cost_basis does not)

The canonical helper is a strict superset of every existing site's behavior,
returns ``Decimal`` (not float) to keep money arithmetic exact, and defaults to
raising on parse errors. Existing Tools/ callers migrating in the
``fix/qc-money-decimal-migration`` PR pass ``on_error="zero"`` for
backward compatibility with the silent-fallback pattern.

Accepted formats (US locale — comma is thousands, dot is decimal):

* ``$1,234.56`` — plain dollar formatting (all three siblings)
* ``+$5,104.47`` — leading + prefix (fidelity)
* ``-$183.70``  — leading - prefix (fidelity)
* ``$-100``     — Excel-style trailing sign after currency symbol
* ``($605.38)`` — parenthesised negative (fidelity + share_cost_basis)
* ``$492.05 USD`` — USD suffix (case-insensitive; fidelity + espp)
* ``$−100``, ``$－100``, ``$–100``, ``$—50`` — Unicode dash variants
  (U+2212 MINUS SIGN, U+FF0D FULLWIDTH HYPHEN-MINUS, U+2013 EN DASH,
  U+2014 EM DASH) — all normalised to ASCII ``-`` for sign inference.
* ``--``, ``N/A`` (case-insensitive), empty string, ``None`` — sentinels,
  return ``Decimal("0")``. Balanced-paren wrapping still counts: ``(--)``
  and ``(N/A)`` are sentinels; a lone ``(`` or ``)`` is NOT.

Explicitly REJECTED (raise ``ValueError`` in strict mode):

* Scientific notation (``$1e5``) — ``e`` used to be silently stripped
* Unit suffixes (``$1.5M``, ``$1K``) — letter used to be silently stripped
* European decimal comma (``$1.234,56``) — used to silently misparse to
  ``1.23456``; disambiguation from US thousands comma requires a pre-strip
  well-formed check
* Multiple decimal points (``$1.2.3``)
* Unbalanced parentheses (``($1,234.56`` or ``$1,234.56)``) — sign
  inference would be lossy
* Bare non-numeric text (``USD``, ``unknown``, lone ``(``) — likely
  header rows or corruption leaking into data
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Literal

# Sentinel strings — always parse to Decimal("0") regardless of on_error mode.
# The probe upper-cases + strips balanced outer parens + strips whitespace
# BEFORE lookup, so 'n/a', '(--) ', '  N/A  ' all match.
_SENTINELS = frozenset({"--", "N/A", ""})

# The strip regex removes ONLY safely-ignorable characters — whitespace, the
# currency symbol, thousands separators, the sign prefix ``+``, and the
# parentheses (their sign meaning is captured separately via the negative
# flag). It does NOT remove letters — that closes the silent-misparse hole
# where ``$1e5`` used to become ``15`` and ``$1.5M`` used to become ``1.5``.
_STRIP_RE = re.compile(r"[+$,()\s]")

# The USD suffix is a legacy format from Fidelity/espp CSVs. We strip it
# BEFORE running the well-formed check so the letters don't trigger the
# 'unexpected-letters' guard below. Case-insensitive: PDF-extracted CSVs
# often produce lowercase 'usd'.
_USD_SUFFIX_RE = re.compile(r"\s*USD\s*$", re.IGNORECASE)

# Pre-strip well-formed check: after Unicode / USD-suffix normalisation, the
# ``numeric_part`` must match this shape or we reject. Structure:
#
#   ^ [prefix junk]* digits [.decimal]? [suffix junk]* $
#
# where prefix/suffix junk is any combination of '+', '-', '(', '$', or
# whitespace. Digits must be either:
#   - a US-style thousands-grouped run: 1-3 digits, then (,\d{3})+
#   - or an unfused digit run.
# The decimal part is optional (a single '.' followed by 1+ digits).
#
# Deliberately rejected shapes:
#   - European decimal comma: '1.234,56' (the ,\d{3} rule anchors the
#     comma as a thousands separator; a trailing '56' after the comma
#     would need the fraction after the LAST comma, which the pattern
#     doesn't allow)
#   - Multiple decimal points: '1.2.3' (only one \. before/after digits)
#   - Stray letters: 'USD' has already been removed; any other letter
#     survives to fail this match
#   - Empty numeric run: at least one digit run is required
#
# Balanced-paren consistency (matching count of '(' and ')') is checked
# separately after this regex passes, so patterns like ')(' with matching
# counts but wrong ordering still fail there.
_WELL_FORMED_US = re.compile(
    r"""
    ^
    [+\-\(\$\s]*                  # optional prefix noise: +, -, (, $, ws
    (?:
        \d{1,3}(?:,\d{3})+        # US thousands-grouped run
      | \d+                       # OR bare digit run
    )
    (?:\.\d+)?                    # optional US decimal fraction
    [\)\s]*                       # optional trailing paren / whitespace
    $
    """,
    re.VERBOSE,
)

_OnError = Literal["raise", "zero"]


def parse_currency(
    value: str | None,
    *,
    on_error: _OnError = "raise",
) -> Decimal:
    """Parse a money string into an exact ``Decimal``.

    Parameters
    ----------
    value : str | None
        The money string. Supports the union of formats produced by the
        three Tools/ sibling parsers — see the module docstring for the
        full list. ``None``, empty strings, and sentinels (``--``, ``N/A``,
        case-insensitive) all return ``Decimal("0")`` regardless of the
        ``on_error`` mode.
    on_error : {"raise", "zero"}, default "raise"
        Behavior for unparsable input:

        * ``"raise"`` — raise ``ValueError`` (recommended for new callers,
          surfaces data-quality issues instead of masking them as zero).
        * ``"zero"`` — return ``Decimal("0")`` (matches the existing
          Tools/ callers' behavior; use during migration only).

    Returns
    -------
    Decimal
        The parsed amount. Precision is preserved exactly — e.g.
        ``parse_currency("$1.2345")`` returns ``Decimal("1.2345")``,
        not the float artifact ``1.2344999999999...``.

    Raises
    ------
    ValueError
        * If ``on_error="raise"`` and the input cannot be parsed. This
          includes inputs with letters other than a trailing USD suffix
          (``$1.5M``, ``$1e5``, ``unknown``), European decimal format
          (``$1.234,56``), multiple decimal points, unbalanced
          parentheses, and lone sign characters.
        * If ``on_error`` is not one of the two documented values.
          (This is a caller bug, not a data bug — raise even in "zero"
          mode wouldn't help since the mode itself is unrecognised.)

    Examples
    --------
    Plain formats::

        >>> parse_currency("$10,423.20")
        Decimal('10423.20')
        >>> parse_currency("+$5,104.47")
        Decimal('5104.47')

    Parentheses mean negative::

        >>> parse_currency("($605.38)")
        Decimal('-605.38')

    Sentinels return zero without raising::

        >>> parse_currency("--")
        Decimal('0')
        >>> parse_currency("n/a")
        Decimal('0')

    Notes
    -----
    Sign inference uses a single ``negative`` flag set from the presence
    of ``(`` or any ``-`` character (after Unicode normalisation, so
    ``−`` U+2212, ``–`` U+2013, ``—`` U+2014, and ``－`` U+FF0D all count).
    Doubled parentheses do NOT double-negate — the flag is a boolean, not
    an XOR toggle, so ``(($10.00))`` yields ``Decimal("-10.00")``.
    """
    # Argument validation on the mode itself — fail fast on typos.
    if on_error not in ("raise", "zero"):
        raise ValueError(
            f"parse_currency: on_error must be 'raise' or 'zero', got {on_error!r}"
        )

    # None and empty-shaped inputs — always zero, in either mode.
    if value is None:
        return Decimal("0")

    # Normalise Unicode variants BEFORE any structural check:
    #   1. NFKC folds compatibility variants: fullwidth digits/parens,
    #      U+FF0D fullwidth hyphen-minus. Note NFKC does NOT fold U+2212
    #      MINUS SIGN — U+2212 is semantically the mathematical minus,
    #      not a compatibility equivalent of ASCII '-'.
    #   2. Explicit translate() then handles U+2212, U+2013 EN DASH, and
    #      U+2014 EM DASH — these show up in Excel exports and PDF
    #      copy-paste often enough to warrant the folding.
    normalised = unicodedata.normalize("NFKC", value).strip()
    normalised = normalised.translate(str.maketrans({"−": "-", "–": "-", "—": "-"}))

    # Sentinel check — case-insensitive, whitespace + balanced outer parens
    # stripped. A lone '(' or ')' is data corruption, NOT an empty sentinel,
    # so the balanced-paren guard runs before we strip parens for the probe.
    if _parens_are_balanced(normalised):
        sentinel_probe = normalised.strip("()").strip().upper()
        if sentinel_probe in _SENTINELS:
            return Decimal("0")

    # Strip the ``USD`` suffix first, BEFORE the well-formed check.
    numeric_part = _USD_SUFFIX_RE.sub("", normalised)

    # Pre-strip well-formed shape check — this rejects European decimal
    # format, multiple decimals, and anything with a stray letter. Doing
    # this BEFORE the strip regex is essential: after stripping, EU
    # ``1.234,56`` and US ``1234.56`` are indistinguishable.
    if not _WELL_FORMED_US.match(numeric_part):
        return _fail_or_zero(value, on_error)

    # Balanced-paren check — unbalanced would let sign inference be lossy
    # ('(1234.56' vs '1234.56)' produce opposite signs from equivalent
    # typos). Do this BEFORE the sign flag is computed.
    if not _parens_are_balanced(numeric_part):
        return _fail_or_zero(value, on_error)

    # Determine sign — presence of any '-' or '(' anywhere in the
    # normalised, well-formed input. Boolean flag (not XOR), so nested
    # parens don't sign-double.
    negative = "-" in numeric_part or "(" in numeric_part

    # Strip only whitespace, currency symbol, commas, parentheses, and '+'.
    cleaned = _STRIP_RE.sub("", numeric_part)

    try:
        # abs() first so the ``negative`` flag is the sole source of sign,
        # never double-applied. Handles inputs like ``-($10.00)``.
        magnitude = abs(Decimal(cleaned))
    except InvalidOperation:
        # Defensive: the well-formed regex above should have caught most
        # unparsable shapes, but Decimal() still rejects '.', '-', '-.'
        # which the regex accepts. Route them through the same fail path.
        return _fail_or_zero(value, on_error)

    return -magnitude if negative else magnitude


def _parens_are_balanced(s: str) -> bool:
    """Return True iff parentheses in ``s`` are well-nested (open before close).

    Uses a running depth counter — any point where depth goes negative
    (close without matching open) is invalid, as is any non-zero final
    depth. Rejects ``)(`` and ``)(`` even though their counts are equal.
    """
    depth = 0
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _fail_or_zero(original: str, on_error: _OnError) -> Decimal:
    """Return zero or raise, per the caller's on_error preference.

    Centralised so the error message stays consistent across every
    unparsable code path and the raise/zero decision is made in one place.
    """
    if on_error == "zero":
        return Decimal("0")
    raise ValueError(f"parse_currency: could not parse {original!r} as a money amount")
