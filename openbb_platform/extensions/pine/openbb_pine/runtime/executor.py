"""Deprecation shim for the pre-E0.3 executor module — bd-9zb.

Post-E0.3 the executor lives in TWO modules:

* :mod:`openbb_pine.runtime.executor_core` — provider-agnostic core
  (bar loop, snapshot capture, ``_collect_results``). MOVES to
  ``pyne_compiler`` in E2.
* :mod:`openbb_pine.runtime.executor_shell` — openbb-fork wrapper
  (concrete provider instantiation, ``POWERED_BY_FULL`` attribution,
  ``OBBject`` envelope). STAYS in openbb-fork.

This file remains as a **one-release re-export shim** so downstream
callers that still import from ``openbb_pine.runtime.executor`` keep
working across a single deprecation window. The shim:

* Emits a :class:`DeprecationWarning` on import so callers see the
  nudge to migrate to the new home.
* Re-exports every public symbol that the pre-split ``executor.py``
  exposed via its ``__all__`` (``ProviderOrData``, ``run_compiled``)
  PLUS the ``_resolve_data_source`` helper that at least one internal
  caller (the ``test_executor.py`` test module) imports directly. The
  ``is`` identity between the shim's re-exports and the shell's
  originals is preserved so existing patches / mocks against
  ``openbb_pine.runtime.executor.<name>`` continue to work by
  monkey-patching the shell in one direction — with the caveat that
  patching the shim attribute itself will NOT bleed through into
  ``executor_shell`` (patching via the shim is not part of the shim's
  contract; migrate to ``executor_shell.<name>`` instead).

Removal is scheduled for the release after Pine extraction ships
(Pine Extraction Design §13.5). New callers must import from
``executor_shell`` (or ``executor_core`` for the pynecore-facing
runtime) directly.

Clean-room note: I have not viewed TradingView or PyneComp source code.
"""

from __future__ import annotations

import warnings as _warnings

# One-release backwards-compat re-export. Imports are eager so any
# ``from openbb_pine.runtime.executor import run_compiled`` idiom keeps
# working; the ``noqa: F401`` mutes the "imported but unused" lint since
# the re-export IS the whole point of this shim.
from openbb_pine.runtime.executor_core import _collect_results  # noqa: F401
from openbb_pine.runtime.executor_shell import (  # noqa: F401
    ProviderOrData,
    _resolve_data_source,
    run_compiled,
)

_warnings.warn(
    "openbb_pine.runtime.executor is deprecated as of the E0.3 split "
    "(bd-9zb) and will be removed in the release after the Pine extraction "
    "to pynecore ships. Migrate imports to openbb_pine.runtime.executor_shell "
    "(openbb-fork-facing OBBject wrapper) or openbb_pine.runtime.executor_core "
    "(provider-agnostic bar loop; moves to pynecore in E2). See Pine "
    "Extraction Design §13.5.",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = ["ProviderOrData", "run_compiled"]
