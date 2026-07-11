"""Tests for :mod:`openbb_pine.stdlib.math.abs` bridge (bead 0e9.5.46).

Wave 5B-5 part 1. Pins the bridge wiring + compile-time contract; the
numerical semantics ride on the conformance fixture
(``tests/conformance/math/abs.pine`` + ``abs.csv``).
"""

from __future__ import annotations

from openbb_pine import _coverage_manifest
from pyne_compiler.compiler import compile_pine
from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES
from openbb_pine.stdlib import math as stdlib_math


def test_abs_bridge_is_importable_and_callable() -> None:
    assert hasattr(stdlib_math, "abs")
    assert callable(stdlib_math.abs)


def test_abs_of_positive_is_identity() -> None:
    """Basic sanity — the delegation preserves positive values."""
    assert stdlib_math.abs(3.5) == 3.5


def test_abs_of_negative_flips_sign() -> None:
    """Basic sanity — negatives become positive."""
    assert stdlib_math.abs(-2.5) == 2.5


def test_abs_of_zero_is_zero() -> None:
    """Boundary — zero remains zero."""
    assert stdlib_math.abs(0) == 0


def test_math_abs_signature_registered_and_implemented() -> None:
    sig = BUILTIN_SIGNATURES.get("math.abs")
    assert sig is not None
    assert sig.notes == "IMPLEMENTED"


def test_math_abs_in_coverage_manifest() -> None:
    assert "math.abs" in _coverage_manifest.BUILTINS_IMPLEMENTED


def test_math_abs_compiles_via_compile_pine() -> None:
    src = (
        "//@version=6\n"
        "indicator(\"math_abs_test\", overlay=false)\n"
        "plot(math.abs(close - open), title=\"abs_val\")\n"
    )
    mod = compile_pine(src)
    assert "math.abs" in mod.builtins_used
