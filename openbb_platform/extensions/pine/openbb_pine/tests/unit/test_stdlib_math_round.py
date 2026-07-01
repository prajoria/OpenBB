"""Tests for :mod:`openbb_pine.stdlib.math.round` bridge (bead 0e9.5.49).

Wave 5B-5 part 1. Pine's ``math.round`` takes an optional ``precision``
(the un-supplied form rounds to the nearest integer). The bridge accepts
``precision=None`` and forwards to PyneCore's single- or two-arg form.
"""

from __future__ import annotations

from openbb_pine import _coverage_manifest
from openbb_pine.compiler import compile_pine
from openbb_pine.compiler.builtin_signatures import BUILTIN_SIGNATURES
from openbb_pine.stdlib import math as stdlib_math


def test_round_bridge_is_importable_and_callable() -> None:
    assert hasattr(stdlib_math, "round")
    assert callable(stdlib_math.round)


def test_round_default_precision_rounds_to_int() -> None:
    """No precision -> rounds to nearest integer (banker's rounding)."""
    # 100.4 -> 100, 100.6 -> 101, ties -> even bucket
    assert stdlib_math.round(100.4) == 100
    assert stdlib_math.round(100.6) == 101


def test_round_ties_to_even_bankers_rounding() -> None:
    """Python's built-in round is banker's — 100.5 -> 100 (even), 101.5 -> 102."""
    assert stdlib_math.round(100.5) == 100
    assert stdlib_math.round(101.5) == 102


def test_round_with_precision() -> None:
    """Explicit precision passes through to PyneCore."""
    assert stdlib_math.round(3.14159, 2) == 3.14
    assert stdlib_math.round(3.14159, 3) == 3.142


def test_math_round_signature_registered_and_implemented() -> None:
    sig = BUILTIN_SIGNATURES.get("math.round")
    assert sig is not None
    assert sig.notes == "IMPLEMENTED"


def test_math_round_in_coverage_manifest() -> None:
    assert "math.round" in _coverage_manifest.BUILTINS_IMPLEMENTED


def test_math_round_compiles_via_compile_pine() -> None:
    src = (
        "//@version=6\n"
        "indicator(\"math_round_test\", overlay=false)\n"
        "plot(math.round(close), title=\"round_val\")\n"
    )
    mod = compile_pine(src)
    assert "math.round" in mod.builtins_used


def test_math_round_with_precision_compiles_via_compile_pine() -> None:
    """Two-arg form (precision) still compiles cleanly."""
    src = (
        "//@version=6\n"
        "indicator(\"math_round_prec_test\", overlay=false)\n"
        "plot(math.round(close, 2), title=\"round_val\")\n"
    )
    mod = compile_pine(src)
    assert "math.round" in mod.builtins_used
