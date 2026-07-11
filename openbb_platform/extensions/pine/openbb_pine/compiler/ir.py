"""Deprecated shim: openbb_pine.compiler.ir

Real implementation moved to :mod:`pyne_compiler.compiler.ir` during the Pine extraction
(E3, bd-rbf). Attribute access through this shim emits a
:class:`DeprecationWarning`; the returned object is identical to the one
in the real module. Removable in v0.next+1.
"""
from __future__ import annotations

import warnings as _warnings

import pyne_compiler.compiler.ir as _new

_DEPRECATION_MSG = (
    "openbb_pine.compiler.ir is deprecated; import from pyne_compiler.compiler.ir "
    "instead. This shim will be removed in the next feature release."
)


def __getattr__(name: str):
    try:
        value = getattr(_new, name)
    except AttributeError as exc:
        raise AttributeError(
            f"module 'openbb_pine.compiler.ir' has no attribute {name!r}"
        ) from exc
    _warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    return value


def __dir__():
    return sorted(set(dir(_new)) | {"__getattr__", "__dir__"})
