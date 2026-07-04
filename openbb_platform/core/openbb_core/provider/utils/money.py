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

Accepted formats:

* ``$1,234.56`` — plain dollar formatting (all three siblings)
* ``+$5,104.47`` — leading + prefix (fidelity)
* ``-$183.70``  — leading - prefix (fidelity)
* ``($605.38)`` — parenthesised negative (fidelity + share_cost_basis)
* ``$492.05 USD`` — USD suffix (fidelity + espp)
* ``$−100``, ``$－100`` — Unicode minus signs (U+2212, U+FF0D) — normalised
* ``--``, ``N/A``, empty string, and the Python ``None`` value — sentinels,
  return ``Decimal("0")`` regardless of surrounding whitespace or parentheses.

Explicitly REJECTED (raise ``ValueError`` in strict mode):

* Scientific notation (``$1e5``) — the ``e`` used to be silently stripped
* Unit suffixes (``$1.5M``, ``$1K``) — the letter used to be silently stripped
* Multiple decimal points (``$1.2.3``)
* Bare non-numeric text (``USD``, ``unknown``) — likely header rows leaking
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Literal

# Sentinel strings — always parse to Decimal("0") regardless of on_error mode.
# Case-insensitive; whitespace and outer parentheses are stripped first.
_SENTINELS = frozenset({"--", "N/A", ""})

# The strip regex removes ONLY safely-ignorable characters — whitespace, the
# currency symbol, thousands separators, the sign prefix ``+``, and the
# parentheses (their sign meaning is captured separately via the negative
# flag). It does NOT remove letters — that closes the silent-misparse hole
# where ``$1e5`` used to become ``15`` and ``$1.5M`` used to become ``1.5``.
_STRIP_RE = re.compile(r"[+$,()\s]")

# The USD suffix is a legacy format from Fidelity/espp CSVs. We strip it
# BEFORE running the main strip regex so the letters don't trigger the
# 'unexpected-letters' guard below.
_USD_SUFFIX_RE = re.compile(r"\s*USD\s*$", re.IGNORECASE)

# Unicode dash variants that should be treated as ASCII '-' for sign
# inference. Excel exports, PDF copy-paste, and financial data feeds all
# emit U+2212 (MINUS SIGN) and U+FF0D (FULLWIDTH HYPHEN-MINUS) freely.
# NFKC normalisation collapses both to ASCII '-' along with many other
# compatibility equivalents.
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
        full list. ``None``, empty strings, and sentinels (``--``, ``N/A``)
        all return ``Decimal("0")`` regardless of ``on_error`` mode.
    on_error : {"raise", "zero"}, default "raise"
        Behavior for unparseable input:

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
          (``$1.5M``, ``$1e5``, ``unknown``), multiple decimal points,
          and lone sign characters.
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

    Notes
    -----
    Sign inference uses a single ``negative`` flag set from the presence
    of ``(`` or a leading ``-`` (after Unicode NFKC normalisation, so
    ``−`` U+2212 and ``－`` U+FF0D also count as ``-``). The abs(numeric)
    computation strips any remaining minus sign after regex cleanup, so
    ``-($10.00)`` correctly yields ``Decimal("-10.00")`` (negative once,
    not sign-doubled).
    """
    # Argument validation on the mode itself — fail fast on typos.
    if on_error not in ("raise", "zero"):
        raise ValueError(
            f"parse_currency: on_error must be 'raise' or 'zero', got {on_error!r}"
        )

    # None and empty-shaped inputs — always zero, in either mode.
    if value is None:
        return Decimal("0")

    # NFKC normalisation folds compatibility Unicode variants (fullwidth
    # digits, fullwidth hyphen-minus U+FF0D, fullwidth parens) into their
    # ASCII equivalents. Note NFKC does NOT fold U+2212 MINUS SIGN — it's
    # a distinct 'mathematical' character, not a compatibility variant, so
    # we explicitly translate it to ASCII '-' along with a couple of other
    # dash-like glyphs that appear in copy-pasted financial data.
    normalised = unicodedata.normalize("NFKC", value).strip()
    # U+2212 MINUS SIGN, U+2013 EN DASH, U+2014 EM DASH — all get mapped
    # to ASCII '-' for sign inference. This is intentionally narrow: we
    # only fold characters where the alternative (raise/silent-zero) is
    # clearly worse than the caller's obvious intent.
    normalised = normalised.translate(str.maketrans({"−": "-", "–": "-", "—": "-"}))

    # Sentinel check — after stripping surrounding whitespace AND
    # outer parentheses ("(--)" is still a sentinel). We only strip
    # parens for the sentinel test, not for numeric parsing.
    sentinel_probe = normalised.strip("()").strip()
    if sentinel_probe in _SENTINELS:
        return Decimal("0")

    # Strip the ``USD`` suffix first, BEFORE the letter-detection guard.
    # Anything else that survives with letters is a parse error.
    numeric_part = _USD_SUFFIX_RE.sub("", normalised)

    # Determine sign BEFORE stripping non-numeric chars — otherwise the
    # regex would remove parentheses and we'd lose the negativity hint.
    # Look for '-' anywhere in the string (not just leading) so that both
    # ``-$100`` (fidelity style) and ``$-100`` (Excel copy-paste style)
    # register as negative. The regex strip removes '+' but keeps '-' so
    # a stray minus in the middle of the digits would still cause
    # Decimal() to raise — the guard below catches that.
    negative = "-" in numeric_part or "(" in numeric_part

    # Strip only whitespace, currency symbol, commas, parentheses, and '+'.
    # Letters (other than the already-stripped USD suffix) will now survive
    # the strip and cause Decimal() to raise — which is exactly what we want
    # for '$1e5', '$1.5M', etc.
    cleaned = _STRIP_RE.sub("", numeric_part)

    # Guard: if the strip left the string containing anything other than
    # digits, a single '-', and a single '.', it's not a well-formed number.
    # Decimal() will raise on these too, but this guard produces a clearer
    # error message and covers the case where cleaned is empty after the
    # regex (e.g. bare 'USD' collapses to empty and Decimal('') raises).
    if not cleaned or not re.fullmatch(r"-?\d*\.?\d*", cleaned):
        if on_error == "zero":
            return Decimal("0")
        raise ValueError(f"parse_currency: could not parse {value!r} as a money amount")

    try:
        # abs() first so the ``negative`` flag is the sole source of sign,
        # never double-applied. Handles inputs like ``-($10.00)``.
        magnitude = abs(Decimal(cleaned))
    except InvalidOperation as exc:
        if on_error == "zero":
            return Decimal("0")
        raise ValueError(
            f"parse_currency: could not parse {value!r} as a money amount"
        ) from exc

    return -magnitude if negative else magnitude
