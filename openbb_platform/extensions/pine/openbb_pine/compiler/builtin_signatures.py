"""Deprecated shim: openbb_pine.compiler.builtin_signatures -> pyne_compiler.compiler.builtin_signatures.

Real implementation lives at :mod:`pyne_compiler.compiler.builtin_signatures` after the Pine
extraction (bd-rbf epic; bd-9bh made pyne_compiler self-contained;
bd-579 reduced this file from a fat copy to a ``sys.modules`` alias
shim). Post-alias, ``openbb_pine.compiler.builtin_signatures is pyne_compiler.compiler.builtin_signatures`` — attribute reads,
writes, and :func:`monkeypatch.setattr` all target the real module.
Scheduled for removal in v0.next+1 per Pine Extraction Design §13.5.
"""
from __future__ import annotations

import sys as _sys
import warnings as _warnings

import pyne_compiler.compiler.builtin_signatures as _new

_warnings.warn(
    "openbb_pine.compiler.builtin_signatures is deprecated; import from pyne_compiler.compiler.builtin_signatures instead. "
    "This shim will be removed in the next feature release.",
    DeprecationWarning,
    stacklevel=2,
)

# Aliasing must happen at import time so subsequent
# ``import openbb_pine.compiler.builtin_signatures`` returns the real module. Because Python
# is currently executing this file, ``sys.modules["openbb_pine.compiler.builtin_signatures"]``
# is the half-initialized shim; we overwrite it in-place. This is the
# same pattern used by common backport shims (e.g. six, urllib3).
_sys.modules[__name__] = _new
