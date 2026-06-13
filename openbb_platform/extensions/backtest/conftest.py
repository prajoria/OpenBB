"""Pytest config: make ``openbb_backtest`` importable from source pre-install.

Until the extension is installed editable, add the package root to ``sys.path``
so unit tests run against the source tree.
"""

import os
import sys

_PKG_ROOT = os.path.dirname(__file__)
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)


def pytest_configure(config):
    """Register backtest-local markers (C12.1 will formalize the full taxonomy)."""
    config.addinivalue_line(
        "markers",
        "golden: regression-locks an output against a committed golden fixture.",
    )
