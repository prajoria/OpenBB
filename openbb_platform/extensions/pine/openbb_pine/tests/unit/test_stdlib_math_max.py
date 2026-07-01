"""Tests for :mod:`openbb_pine.stdlib.math.max` bridge (bead 0e9.5.47).

Wave 5B-5 part 1. Pine's ``math.max`` is N-ary — variable-length arg list
— matching PyneCore's ``*numbers`` signature. Locks:

* Bridge accepts 2 args (pairwise) and 3+ args (N-ary).
* Compile-time contract: ``math.max`` in ``BUILTIN_SIGNATURES``,
  flagged IMPLEMENTED, and in the coverage manifest.
* End-to-end compile via :func:`compile_pine`.
"""

from __future__ import annotations

from openbb_pine import _coverage_manifest
from openbb_pine.compiler import compile_pine
from openbb_pine.compiler.builtin_signatures import BUILTIN_SIGNATURES
from openbb_pine.stdlib import math as stdlib_math


def test_max_bridge_is_importable_and_callable() -> None:
    assert hasattr(stdlib_math, "max")
    assert callable(stdlib_math.max)


def test_max_pairwise() -> None:
    """Two-arg case — the common Pine usage."""
    assert stdlib_math.max(3, 5) == 5
    assert stdlib_math.max(5, 3) == 5


def test_max_n_ary_four_args() -> None:
    """N-ary form — Pine ``math.max(a, b, c, d)``."""
    assert stdlib_math.max(1, 2, 3, 4) == 4


def test_max_n_ary_seven_args() -> None:
    """Larger N-ary form to exercise the ``*numbers`` splat."""
    assert stdlib_math.max(2, 5, 1, 8, 3, 6, 4) == 8


def test_math_max_signature_registered_and_implemented() -> None:
    sig = BUILTIN_SIGNATURES.get("math.max")
    assert sig is not None
    assert sig.notes == "IMPLEMENTED"


def test_math_max_in_coverage_manifest() -> None:
    assert "math.max" in _coverage_manifest.BUILTINS_IMPLEMENTED


def test_math_max_compiles_pairwise_via_compile_pine() -> None:
    """Pairwise form compiles cleanly."""
    src = (
        "//@version=6\n"
        "indicator(\"math_max_test\", overlay=false)\n"
        "plot(math.max(close, open), title=\"max_val\")\n"
    )
    mod = compile_pine(src)
    assert "math.max" in mod.builtins_used


def test_math_max_compiles_n_ary_via_compile_pine() -> None:
    """N-ary form (4 args) still compiles — the stub signature is 2-ary but
    C3 tolerates trailing positionals for stub-only checks."""
    src = (
        "//@version=6\n"
        "indicator(\"math_max_nary_test\", overlay=false)\n"
        "plot(math.max(close, open, high, low), title=\"max_val\")\n"
    )
    mod = compile_pine(src)
    assert "math.max" in mod.builtins_used
