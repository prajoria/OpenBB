"""Sys.path bridge for the submodule-vendored pynecore deployment.

When openbb-fork uses ``third_party/pynecore/`` as a git submodule (not a
pip-installed package), pynecore is not on sys.path by default. This
module prepends ``<submodule>/src`` so ``import pynecore`` resolves.

Idempotent: safe to call multiple times.
No-op when pynecore is already importable (the happy path once pynecore
is pip-installed alongside pyne_compiler).

Post-E2 this file moves to ``src/pyne_compiler/runtime/pynecore_bridge.py``.
The E3 refactor makes ``openbb_pine.__init__`` delegate here instead of
owning the sys.path insertion directly.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def is_pynecore_installed() -> bool:
    """True when ``import pynecore`` would succeed without our path manipulation."""
    return importlib.util.find_spec("pynecore") is not None


def _submodule_src_dir() -> Path:
    """Return the path to ``third_party/pynecore/src`` relative to this file's repo root."""
    # runtime/pynecore_bridge.py -> runtime/ -> openbb_pine/ -> pine/ -> extensions/
    # -> openbb_platform/ -> repo-root
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "third_party" / "pynecore" / "src"
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        "pynecore_bridge: could not locate third_party/pynecore/src relative to "
        f"{here}. Ensure the pynecore submodule is initialized."
    )


def install_pynecore_path() -> None:
    """Prepend the pynecore submodule's ``src/`` to ``sys.path`` if pynecore isn't installed.

    Idempotent: repeated calls have no effect after the first successful insert.
    No-op when pynecore is already importable.
    """
    if is_pynecore_installed():
        return
    src_dir = str(_submodule_src_dir())
    if src_dir in sys.path:
        return  # already inserted, don't duplicate
    sys.path.insert(0, src_dir)


__all__ = ["install_pynecore_path", "is_pynecore_installed"]
