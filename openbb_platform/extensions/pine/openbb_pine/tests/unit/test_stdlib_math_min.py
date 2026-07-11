"""Tests for :mod:`openbb_pine.stdlib.math.min` bridge (bead 0e9.5.48).

Wave 5B-5 part 1. N-ary form parallels :mod:`test_stdlib_math_max`.
"""

from __future__ import annotations

from openbb_pine import _coverage_manifest
from pyne_compiler.compiler import compile_pine
from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES
from openbb_pine.stdlib import math as stdlib_math


def test_min_bridge_is_importable_and_callable() -> None:
    assert hasattr(stdlib_math, "min")
    assert callable(stdlib_math.min)


def test_min_pairwise() -> None:
    """Two-arg case — the common Pine usage."""
    assert stdlib_math.min(3, 5) == 3
    assert stdlib_math.min(5, 3) == 3


def test_min_n_ary_four_args() -> None:
    """N-ary form — Pine ``math.min(a, b, c, d)``."""
    assert stdlib_math.min(1, 2, 3, 4) == 1


def test_min_n_ary_seven_args() -> None:
    """Larger N-ary form to exercise the ``*numbers`` splat."""
    assert stdlib_math.min(2, 5, 1, 8, 3, 6, 4) == 1


def test_math_min_signature_registered_and_implemented() -> None:
    sig = BUILTIN_SIGNATURES.get("math.min")
    assert sig is not None
    assert sig.notes == "IMPLEMENTED"


def test_math_min_in_coverage_manifest() -> None:
    assert "math.min" in _coverage_manifest.BUILTINS_IMPLEMENTED


def test_math_min_compiles_pairwise_via_compile_pine() -> None:
    src = (
        "//@version=6\n"
        "indicator(\"math_min_test\", overlay=false)\n"
        "plot(math.min(close, open), title=\"min_val\")\n"
    )
    mod = compile_pine(src)
    assert "math.min" in mod.builtins_used


def test_math_min_compiles_n_ary_via_compile_pine() -> None:
    """N-ary form (4 args) still compiles — the stub signature is 2-ary but
    C3 tolerates trailing positionals for stub-only checks."""
    src = (
        "//@version=6\n"
        "indicator(\"math_min_nary_test\", overlay=false)\n"
        "plot(math.min(close, open, high, low), title=\"min_val\")\n"
    )
    mod = compile_pine(src)
    assert "math.min" in mod.builtins_used
