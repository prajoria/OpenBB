"""Pytest config: make ``openbb_techtrade`` importable + register markers (#71).

Until the extension is installed editable, add the package root to ``sys.path`` so
unit tests run against the source tree. Also registers the ``golden`` marker used
by the golden-file regression locks (PRD §17).
"""

import os
import sys

_PKG_ROOT = os.path.dirname(__file__)
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)


def pytest_configure(config):
    """Register techtrade-local pytest markers."""
    config.addinivalue_line(
        "markers",
        "golden: regression-locks an output against a committed golden fixture.",
    )
