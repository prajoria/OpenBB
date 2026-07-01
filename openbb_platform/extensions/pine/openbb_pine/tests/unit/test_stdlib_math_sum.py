"""Tests for :mod:`openbb_pine.stdlib.math.sum` bridge (bead 0e9.5.45).

Wave 5B-5 part 1 — the rolling-sum bridge is the only stateful entry in
the ``math.*`` batch (Kahan summation with per-bar persistent window).
The bridge itself is a one-line delegation; these tests exist to lock:

1. The bridge is importable via the ``openbb_pine.stdlib.math`` namespace.
2. Its signature (`(source, length: int)`) matches
   :data:`openbb_pine.compiler.builtin_signatures.BUILTIN_SIGNATURES["math.sum"]`.
3. The signature entry is marked ``notes="IMPLEMENTED"`` so the bridge
   audit trail stays honest.
4. ``math.sum`` appears in
   :data:`openbb_pine._coverage_manifest.BUILTINS_IMPLEMENTED`.
5. A Pine v6 script using ``math.sum(close, N)`` compiles cleanly end-to-end
   via :func:`compile_pine` (T1 allowlist gate accepts the emit).

Numerical correctness lives in the conformance suite
(``tests/conformance/math/sum.pine`` + ``sum.csv``), not here — this is
the wiring test.
"""

from __future__ import annotations

import inspect

from openbb_pine import _coverage_manifest
from openbb_pine.compiler import compile_pine
from openbb_pine.compiler.builtin_signatures import BUILTIN_SIGNATURES
from openbb_pine.stdlib import math as stdlib_math


# ---------------------------------------------------------------------------
# Bridge wiring
# ---------------------------------------------------------------------------


def test_sum_bridge_is_importable() -> None:
    """``openbb_pine.stdlib.math.sum`` exists and is callable."""
    assert hasattr(stdlib_math, "sum")
    assert callable(stdlib_math.sum)


def test_sum_bridge_signature_matches_pine_shape() -> None:
    """The bridge takes ``(source, length: int)`` — Pine's ``math.sum`` shape."""
    sig = inspect.signature(stdlib_math.sum)
    params = list(sig.parameters)
    assert params == ["source", "length"], (
        f"expected ['source', 'length'], got {params}"
    )
    # ``from __future__ import annotations`` in the bridge module means the
    # annotation is stored as the STRING ``"int"`` rather than the type
    # object; either form is acceptable — what matters is the caller sees
    # something that reads as ``int``.
    length_param = sig.parameters["length"]
    annotation = length_param.annotation
    assert annotation in (int, "int"), (
        f"length must be annotated int, got {annotation!r}"
    )


def test_sum_delegates_to_pynecore_lib_math_sum() -> None:
    """The bridge target is :func:`pynecore.lib.math.sum`."""
    from pynecore.lib import math as pyne_math

    # The bridge body is a one-liner ``return _pyne_math.sum(source, length)``;
    # verify the target function still exists in PyneCore so a version-bump
    # of the vendored substrate is caught here rather than by conformance.
    assert hasattr(pyne_math, "sum")
    assert callable(pyne_math.sum)


# ---------------------------------------------------------------------------
# Compile-time contract
# ---------------------------------------------------------------------------


def test_math_sum_signature_registered_and_implemented() -> None:
    """``math.sum`` is a registered builtin flagged IMPLEMENTED."""
    sig = BUILTIN_SIGNATURES.get("math.sum")
    assert sig is not None, "math.sum missing from BUILTIN_SIGNATURES"
    assert sig.notes == "IMPLEMENTED", (
        f'math.sum notes = {sig.notes!r}, expected "IMPLEMENTED"'
    )


def test_math_sum_in_coverage_manifest() -> None:
    """The name is in the frozen coverage manifest — L0.5 counts it."""
    assert "math.sum" in _coverage_manifest.BUILTINS_IMPLEMENTED


def test_math_sum_compiles_via_compile_pine() -> None:
    """A minimal v6 script using ``math.sum`` compiles cleanly.

    Locks: (a) C3 resolves the call, (b) codegen emits the
    ``pynecore.lib.math`` import, (c) T1 allowlist accepts the emit.
    """
    src = (
        "//@version=6\n"
        "indicator(\"math_sum_test\", overlay=false)\n"
        "plot(math.sum(close, 5), title=\"sum5\")\n"
    )
    mod = compile_pine(src)
    assert "math.sum" in mod.builtins_used
    assert "from pynecore.lib import" in mod.source
    assert "math" in mod.source
