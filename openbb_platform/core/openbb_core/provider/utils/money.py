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
* ``--``, ``N/A``, empty, ``None`` — sentinels, return ``Decimal("0")``
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Literal

# One regex removes all non-numeric characters (letters, currency symbols,
# whitespace, commas, parentheses, +) — keeping only digits, minus, and
# decimal point. This is a superset of what each of the 3 sibling sites
# strips, so no valid input from any of them gets rejected.
_STRIP_RE = re.compile(r"[+$,()A-Za-z\s]")

_SENTINELS = frozenset({"--", "N/A", ""})

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
        full list. ``None``, empty, and sentinels (``--``, ``N/A``) all
        return ``Decimal("0")`` regardless of ``on_error`` mode.
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
        * If ``on_error="raise"`` and the input cannot be parsed.
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
    of ``(`` or a leading ``-``. The abs(numeric) computation strips any
    remaining minus sign after regex cleanup, so ``-($10.00)`` correctly
    yields ``Decimal("-10.00")`` (negative once, not sign-doubled).
    """
    # Argument validation on the mode itself — fail fast on typos.
    if on_error not in ("raise", "zero"):
        raise ValueError(
            f"parse_currency: on_error must be 'raise' or 'zero', got {on_error!r}"
        )

    # None and sentinel handling — always zero, in either mode.
    if value is None:
        return Decimal("0")

    stripped = value.strip()
    if stripped in _SENTINELS:
        return Decimal("0")

    # Determine sign BEFORE stripping non-numeric chars — otherwise the
    # regex would remove parentheses and we'd lose the negativity hint.
    negative = stripped.startswith("-") or "(" in stripped

    # Strip everything that isn't a digit, minus, or decimal point.
    cleaned = _STRIP_RE.sub("", stripped)

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
