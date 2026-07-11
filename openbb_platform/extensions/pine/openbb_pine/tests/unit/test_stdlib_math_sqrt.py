"""Tests for :mod:`openbb_pine.stdlib.math.sqrt` bridge (bead 0e9.5.51).

Wave 5B-5 part 1. Principal square root — returns ``NA(float)`` on
negative input (PyneCore's convention), not a ``ValueError``.
"""

from __future__ import annotations

from openbb_pine import _coverage_manifest
from pyne_compiler.compiler import compile_pine
from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES
from openbb_pine.stdlib import math as stdlib_math


def test_sqrt_bridge_is_importable_and_callable() -> None:
    assert hasattr(stdlib_math, "sqrt")
    assert callable(stdlib_math.sqrt)


def test_sqrt_of_perfect_square() -> None:
    """Perfect squares — exact integer roots."""
    assert stdlib_math.sqrt(4) == 2.0
    assert stdlib_math.sqrt(9) == 3.0
    assert stdlib_math.sqrt(16) == 4.0


def test_sqrt_of_zero_is_zero() -> None:
    """Boundary — sqrt(0) == 0."""
    assert stdlib_math.sqrt(0) == 0.0


def test_sqrt_of_one_is_one() -> None:
    """Identity — sqrt(1) == 1."""
    assert stdlib_math.sqrt(1) == 1.0


def test_sqrt_of_two_is_irrational_approximation() -> None:
    """Non-perfect square — floating-point approximation."""
    import math as py_math

    assert stdlib_math.sqrt(2) == py_math.sqrt(2)


def test_sqrt_of_negative_returns_na_not_raises() -> None:
    """PyneCore's contract: negative -> ``NA(float)``, never raises.

    A warm-up bar can produce a negative reading (e.g. an incomplete
    variance accumulator); the runtime must NOT crash. The bridge
    inherits this behavior verbatim.
    """
    from pynecore.types.na import NA

    result = stdlib_math.sqrt(-4)
    assert isinstance(result, NA), (
        f"sqrt(-4) should be NA(float), got {result!r}"
    )


def test_math_sqrt_signature_registered_and_implemented() -> None:
    sig = BUILTIN_SIGNATURES.get("math.sqrt")
    assert sig is not None
    assert sig.notes == "IMPLEMENTED"


def test_math_sqrt_in_coverage_manifest() -> None:
    assert "math.sqrt" in _coverage_manifest.BUILTINS_IMPLEMENTED


def test_math_sqrt_compiles_via_compile_pine() -> None:
    src = (
        "//@version=6\n"
        "indicator(\"math_sqrt_test\", overlay=false)\n"
        "plot(math.sqrt(close), title=\"sqrt_val\")\n"
    )
    mod = compile_pine(src)
    assert "math.sqrt" in mod.builtins_used
