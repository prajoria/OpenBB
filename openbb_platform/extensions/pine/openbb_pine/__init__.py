"""openbb-pine - Pine Script compatibility extension for OpenBB Platform.

Runtime is vendored PyneCore (Apache-2.0) at ``third_party/pynecore/src``,
shadowed by a PyPI install of ``pynesys-pynecore`` if present. See PRD section 4.4
and D2 section 1.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "__version__",
    "PINE_VERSION",
    "_load_bundled_widgets",
    "_load_bundled_strategies",
]
__version__ = "0.1.0"  # PRD section 11.2
PINE_VERSION = "6"  # PRD section 13.1

# Canonical location for the bundled-widget catalog. Kept as a module-level
# constant so both the P2 widget helper (:func:`_load_bundled_widgets`) and
# the P3 MCP registration hook (:mod:`openbb_pine.mcp_tools`) point at the
# same file — signature-drift on the catalog schema shows up as one break,
# not two.
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_WIDGETS_JSON = _ASSETS_DIR / "widgets.json"
# Sibling of _WIDGETS_JSON — same convention. Absent by design at #588
# landing; populated by the widgets bead (#587) with bundled strategy
# entries (rsi_reversal, sma_crossover, ...). The /pine/strategies/list
# endpoint reads through :func:`_load_bundled_strategies` so pre-#587
# callers see an empty list plus a PineStrategyCatalogEmpty warning
# rather than a 500.
_STRATEGIES_JSON = _ASSETS_DIR / "strategies.json"


def _install_pynecore_path() -> None:
    """Delegate to :func:`openbb_pine.runtime.pynecore_bridge.install_pynecore_path`.

    Historic entry point retained so callers importing this private name
    from earlier revisions of the module keep working. The actual sys.path
    logic now lives in :mod:`openbb_pine.runtime.pynecore_bridge`, which
    will migrate to ``pyne_compiler`` in E2 (see Pine Extraction Design §6.E0.5).
    """
    # pylint: disable-next=import-outside-toplevel  # intentional deferred import (pre-existing, predates #588)
    from openbb_pine.runtime.pynecore_bridge import install_pynecore_path

    install_pynecore_path()


_install_pynecore_path()  # module-load-time invocation preserved


def _load_bundled_widgets() -> dict[str, dict[str, Any]]:
    """Load the bundled Workspace-widget catalog from ``assets/widgets.json``.

    Returns a mapping from widget id (e.g. ``"pine_bollinger_bands"``) to
    the widget's full spec dict. Returns an empty dict when the file is
    absent so callers (catalog router, MCP registration hook) degrade
    gracefully during scaffold-phase development.

    Notes
    -----
    * The read is intentionally NOT cached at module import time — the
      widgets.json is small and callers are on cold paths (server startup,
      MCP registration). A per-call read keeps live-reload dev workflows
      honest.
    * The parse is strict JSON (no comments, trailing commas rejected).
    * A malformed widgets.json raises :class:`ValueError` up to the caller
      — dropping the widget catalog silently would mask an incident.
    """
    if not _WIDGETS_JSON.is_file():
        return {}
    payload = json.loads(_WIDGETS_JSON.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(
            f"openbb-pine: {_WIDGETS_JSON} top-level type must be an object, "
            f"got {type(payload).__name__}"
        )
    return payload


def _load_bundled_strategies() -> dict[str, dict[str, Any]]:
    """Load the bundled-strategy catalog from ``assets/strategies.json``.

    Sibling of :func:`_load_bundled_widgets` — same behavior, contract, and
    failure mode. Returns an empty dict when the file is absent so callers
    (``/pine/strategies/list``) degrade gracefully during scaffold-phase
    development (bundled strategies land with #587).

    Notes
    -----
    * Not cached — matches ``_load_bundled_widgets`` so live-reload dev
      workflows stay honest.
    * Strict JSON parse; a malformed top-level (non-object) raises
      :class:`ValueError` rather than silently returning ``{}`` — silently
      dropping the catalog would mask an incident.
    """
    if not _STRATEGIES_JSON.is_file():
        return {}
    payload = json.loads(_STRATEGIES_JSON.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(
            f"openbb-pine: {_STRATEGIES_JSON} top-level type must be an object, "
            f"got {type(payload).__name__}"
        )
    return payload
