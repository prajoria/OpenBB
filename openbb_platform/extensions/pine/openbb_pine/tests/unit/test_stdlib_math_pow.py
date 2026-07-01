"""Tests for :mod:`openbb_pine.stdlib.math.pow` bridge (bead 0e9.5.50).

Wave 5B-5 part 1. Two-arg ``base ** exponent`` — trivial delegation.
"""

from __future__ import annotations

from openbb_pine import _coverage_manifest
from openbb_pine.compiler import compile_pine
from openbb_pine.compiler.builtin_signatures import BUILTIN_SIGNATURES
from openbb_pine.stdlib import math as stdlib_math


def test_pow_bridge_is_importable_and_callable() -> None:
    assert hasattr(stdlib_math, "pow")
    assert callable(stdlib_math.pow)


def test_pow_squaring() -> None:
    """The most common usage — squaring a value."""
    assert stdlib_math.pow(2, 2) == 4
    assert stdlib_math.pow(3, 2) == 9


def test_pow_cubing() -> None:
    """Integer exponent > 2 works."""
    assert stdlib_math.pow(2, 3) == 8


def test_pow_fractional_exponent() -> None:
    """Fractional exponent — equivalent to nth root."""
    assert stdlib_math.pow(9, 0.5) == 3.0


def test_pow_of_zero_exponent_is_one() -> None:
    """Any non-zero base ** 0 == 1."""
    assert stdlib_math.pow(5, 0) == 1


def test_math_pow_signature_registered_and_implemented() -> None:
    sig = BUILTIN_SIGNATURES.get("math.pow")
    assert sig is not None
    assert sig.notes == "IMPLEMENTED"


def test_math_pow_in_coverage_manifest() -> None:
    assert "math.pow" in _coverage_manifest.BUILTINS_IMPLEMENTED


def test_math_pow_compiles_via_compile_pine() -> None:
    src = (
        "//@version=6\n"
        "indicator(\"math_pow_test\", overlay=false)\n"
        "plot(math.pow(close, 2), title=\"pow_val\")\n"
    )
    mod = compile_pine(src)
    assert "math.pow" in mod.builtins_used
