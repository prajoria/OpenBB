"""Pine ``math.*`` builtin bridges to :mod:`pynecore.lib.math`.

Ships the 7 Phase-1 ``math.*`` builtins per PRD §3.2:

* :func:`sum` — rolling Kahan sum over ``length`` bars (stateful; PyneCore's
  ``@pyne`` transformer promotes the persistent buffer at import time).
* :func:`abs` — absolute value.
* :func:`max` — N-ary maximum (Pine ``math.max(a, b, ...)`` accepts a
  variable-length arg list; we forward via ``*numbers``).
* :func:`min` — N-ary minimum, same shape as :func:`max`.
* :func:`round` — bankers' rounding with optional precision.
* :func:`pow` — ``base ** exponent``.
* :func:`sqrt` — principal square root (returns ``NA`` on negative input,
  matching PyneCore's ``sqrt``).

All bridges are thin one-line delegations: the numerics live in PyneCore
(Apache-2.0). Rationale for the bridge layer at all is in the stdlib
package docstring (:mod:`openbb_pine.stdlib`).

Design notes
------------

* PyneCore's ``math.round``/``math.max``/``math.min``/``math.abs``/``math.sqrt``
  shadow Python builtins by name, which is exactly the Pine convention. Our
  bridge preserves the shadowing so that ``openbb_pine.stdlib.math.abs``
  matches the Pine identifier verbatim — a maintainer never has to remember
  a rename.
* ``math.sum`` is stateful (Kahan-summation with per-bar buffer). PyneCore
  registers the ``@pyne`` decorator on the module the transformer sees;
  our bridge forwards to the PyneCore symbol so the state machinery still
  wires up at import time in the emitted user script. The bridge itself is
  **not** ``@pyne``-decorated — the user's compiled script imports directly
  from ``pynecore.lib.math`` (see codegen's namespace-import map), and the
  bridge exists as the stability seam per D1 §3.1 / PRD §3.2.

Clean-room posture (PRD §2.1): no TradingView / PyneComp source was
consulted while authoring these bridges.
"""

from __future__ import annotations

# Absolute import + underscored alias: we do NOT want ``math`` in the module
# namespace (would collide with the module's own name at attribute access
# time). ``_pyne_math`` is the single delegation target.
from pynecore.lib import math as _pyne_math

__all__ = [
    "sum",
    "abs",
    "max",
    "min",
    "round",
    "pow",
    "sqrt",
]


# noinspection PyShadowingBuiltins
def sum(source, length: int):
    """Pine ``math.sum`` — rolling Kahan sum of ``source`` over ``length`` bars.

    Delegates to :func:`pynecore.lib.math.sum`, which uses persistent state
    to maintain a numerically-stable rolling accumulator (see the
    ``@pyne``-decorated implementation in ``pynecore.lib._math_stateful``).
    Warm-up returns ``NA`` until ``length`` bars have been observed.
    """
    return _pyne_math.sum(source, length)


# noinspection PyShadowingBuiltins
def abs(number):
    """Pine ``math.abs`` — absolute value.

    Forwards to :func:`pynecore.lib.math.abs`. Propagates ``NA`` unchanged.
    """
    return _pyne_math.abs(number)


# noinspection PyShadowingBuiltins
def max(*numbers):
    """Pine ``math.max`` — N-ary maximum.

    Pine accepts a variable-length arg list (``math.max(a, b, ..., z)``); the
    bridge forwards ``*numbers`` verbatim so the calling convention matches
    both PyneCore and the Pine reference. Propagates ``NA`` when any arg
    is ``NA``.
    """
    return _pyne_math.max(*numbers)


# noinspection PyShadowingBuiltins
def min(*numbers):
    """Pine ``math.min`` — N-ary minimum (see :func:`max` for the shape)."""
    return _pyne_math.min(*numbers)


# noinspection PyShadowingBuiltins
def round(number, precision=None):
    """Pine ``math.round`` — bankers' rounding with optional ``precision``.

    ``precision`` is optional; when omitted PyneCore rounds to the nearest
    integer. We pass through only when supplied so PyneCore's own default
    handling (``NA(int)`` sentinel) applies.
    """
    if precision is None:
        return _pyne_math.round(number)
    return _pyne_math.round(number, precision)


# noinspection PyShadowingBuiltins
def pow(base, exponent):
    """Pine ``math.pow`` — ``base ** exponent``.

    Delegates to :func:`pynecore.lib.math.pow`. Propagates ``NA`` on either
    operand.
    """
    return _pyne_math.pow(base, exponent)


def sqrt(number):
    """Pine ``math.sqrt`` — principal square root.

    Delegates to :func:`pynecore.lib.math.sqrt`. Returns ``NA(float)`` on
    negative input (matching PyneCore's behavior) rather than raising, so
    a warm-up bar with negative reading does not crash the emitted script.
    """
    return _pyne_math.sqrt(number)
