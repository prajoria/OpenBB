"""Deprecated shim: openbb_pine.runtime._data_provider_stub -> pynecore.providers.provider.

The E0-era ``_DataProviderStub`` ABC was superseded by the real
:class:`pynecore.providers.provider.Provider` when the pynecore submodule
gained a first-class Provider interface (bd-r9m / E0.2). Post-bd-579 this
module is a ``sys.modules`` alias to
:mod:`pynecore.providers.provider`, so
``openbb_pine.runtime._data_provider_stub._DataProviderStub`` resolves to
:class:`pynecore.providers.provider.Provider`. Scheduled for removal in
v0.next+1 per Pine Extraction Design §13.5.
"""
from __future__ import annotations

import sys as _sys
import warnings as _warnings

from pynecore.providers import provider as _new

# Backwards-compat name: the pre-extraction stub called the ABC
# ``_DataProviderStub``; pynecore's real class is ``Provider``. Bind both
# names on the aliased module so ``from ..._data_provider_stub import
# _DataProviderStub`` continues to work.
_new._DataProviderStub = _new.Provider  # type: ignore[attr-defined]

_warnings.warn(
    "openbb_pine.runtime._data_provider_stub is deprecated; import "
    "pynecore.providers.provider.Provider instead. This shim will be "
    "removed in the next feature release.",
    DeprecationWarning,
    stacklevel=2,
)

_sys.modules[__name__] = _new
