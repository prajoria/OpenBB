"""Deprecated re-export shim: openbb_pine.compiler -> pyne_compiler.compiler.

The compile pipeline (lexer/parser/type-checker/codegen/cache/v5-migration)
moved to :mod:`pyne_compiler.compiler` in the Pine extraction (bd-rbf
epic; bd-9bh made pyne_compiler self-contained; bd-579 reduced this
file). Downstream imports like
``from openbb_pine.compiler import compile_pine`` keep working via this
re-export; each leaf submodule
(``openbb_pine.compiler.codegen``, ``openbb_pine.compiler.types`` etc.)
is a ``sys.modules`` alias to its pyne_compiler counterpart, so identity
holds — ``openbb_pine.compiler.codegen.emit is
pyne_compiler.compiler.codegen.emit`` returns True.

We deliberately do NOT ``sys.modules``-alias the package itself: doing
so would leave two live package objects with the same name and confuse
importlib on subsequent submodule loads, breaking the leaf-shim identity
contract.

Scheduled for removal in v0.next+1 per Pine Extraction Design §13.5.
"""
from __future__ import annotations

import warnings as _warnings

from pyne_compiler.compiler import *  # noqa: F401,F403
from pyne_compiler.compiler import (  # noqa: F401
    compile_pine,
    compile_pine_to_program,
    detect_pine_version,
    emit,
    migrate_v5_to_v6,
    parse,
    tokenize,
)

# Mirror the parent package's exported surface so downstream
# `from openbb_pine.compiler import *` matches `from pyne_compiler.compiler import *`.
# Explicit list rather than `from pyne_compiler.compiler import __all__` to
# keep the shim self-documenting and reviewable.
__all__ = [
    "compile_pine",
    "compile_pine_to_program",
    "detect_pine_version",
    "emit",
    "migrate_v5_to_v6",
    "parse",
    "tokenize",
]

_warnings.warn(
    "openbb_pine.compiler is deprecated; import from pyne_compiler.compiler "
    "instead. This re-export shim will be removed in the next feature release.",
    DeprecationWarning,
    stacklevel=2,
)
