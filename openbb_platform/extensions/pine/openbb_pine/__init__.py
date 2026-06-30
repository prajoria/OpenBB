"""openbb-pine - Pine Script compatibility extension for OpenBB Platform.

Runtime is vendored PyneCore (Apache-2.0) at ``third_party/pynecore/src``,
shadowed by a PyPI install of ``pynesys-pynecore`` if present. See PRD section 4.4
and D2 section 1.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

__all__ = ["__version__", "PINE_VERSION"]
__version__ = "0.1.0"  # PRD section 11.2
PINE_VERSION = "6"  # PRD section 13.1

# Path: openbb_pine/__init__.py -> parents[0] = openbb_pine,
# [1] = pine (extension dir), [2] = extensions, [3] = openbb_platform, [4] = repo root.
_VENDOR_SRC = (
    Path(__file__).resolve().parents[4] / "third_party" / "pynecore" / "src"
)


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
