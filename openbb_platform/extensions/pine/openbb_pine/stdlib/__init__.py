"""Pine stdlib bridges (Phase 1 S-beads).

Thin delegating wrappers around the vendored PyneCore ``pynecore.lib.*``
namespace. Each submodule mirrors a Pine namespace (``ta``, ``math``,
``input``, ...) and re-exports the subset of builtins that the S-beads have
lifted into the openbb-pine surface.

Why a bridge layer at all when PyneCore already exposes everything? Two
reasons per D1 §3.1 + PRD §3.2:

1. **Compile-time contract**: the compiler's C3 type checker looks up each
   call against :mod:`openbb_pine.compiler.builtin_signatures`. When a bridge
   lands, the corresponding stub entry flips from ``notes="STUB"`` to
   ``notes="IMPLEMENTED"`` so future maintainers can grep the delta.
2. **Runtime dispatch stability**: PyneCore's public API is Apache-2.0
   vendored code we may version-bump; the bridge is our stability seam.
   Signature drift shows up as a bridge test failure long before a wild-
   corpus regression.

Every bridge is a **one-liner delegation** — the numerics live in PyneCore.
Error handling stays out of the bridge because C3 already enforces argument
qualifiers via :data:`openbb_pine.compiler.builtin_signatures.BUILTIN_SIGNATURES`.
"""

from __future__ import annotations

__all__ = ["math", "ta"]

# Bridges are attribute-accessed via ``openbb_pine.stdlib.ta.sma`` etc.
# Import is lazy at module level so a missing PyneCore (dev-env quirk)
# fails on first *use* with a clear import trace rather than at package
# import time.
from openbb_pine.stdlib import math  # noqa: E402  (re-export)
from openbb_pine.stdlib import ta  # noqa: E402  (re-export)
