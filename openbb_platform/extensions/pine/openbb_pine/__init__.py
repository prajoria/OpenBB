"""openbb-pine - Pine Script compatibility extension for OpenBB Platform.

Runtime is vendored PyneCore (Apache-2.0) at ``third_party/pynecore/src``,
shadowed by a PyPI install of ``pynesys-pynecore`` if present. See PRD section 4.4
and D2 section 1.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

__all__ = [
    "__version__",
    "PINE_VERSION",
    "_load_bundled_widgets",
]
__version__ = "0.1.0"  # PRD section 11.2
PINE_VERSION = "6"  # PRD section 13.1

# Path: openbb_pine/__init__.py -> parents[0] = openbb_pine,
# [1] = pine (extension dir), [2] = extensions, [3] = openbb_platform, [4] = repo root.
_VENDOR_SRC = (
    Path(__file__).resolve().parents[4] / "third_party" / "pynecore" / "src"
)

# Canonical location for the bundled-widget catalog. Kept as a module-level
# constant so both the P2 widget helper (:func:`_load_bundled_widgets`) and
# the P3 MCP registration hook (:mod:`openbb_pine.mcp_tools`) point at the
# same file — signature-drift on the catalog schema shows up as one break,
# not two.
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_WIDGETS_JSON = _ASSETS_DIR / "widgets.json"


def _install_pynecore_path() -> str | None:
    """Install the vendored PyneCore on sys.path lazily and guarded.

    Returns the inserted path string, or None if a PyPI ``pynesys-pynecore``
    install already wins. Idempotent: re-importing the extension does not
    insert the same path twice.
    """
    if importlib.util.find_spec("pynecore") is not None:
        return None  # PyPI install (or prior insert) wins
    if not _VENDOR_SRC.is_dir():
        raise ImportError(
            f"openbb-pine: PyneCore is neither installed (`pip install "
            f"pynesys-pynecore`) nor present at {_VENDOR_SRC!s}. See PRD section 4.4."
        )
    src = str(_VENDOR_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)
    return src


_VENDOR_INSERTED: str | None = _install_pynecore_path()


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
