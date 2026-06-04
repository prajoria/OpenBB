"""Pytest config: make ``openbb_backtest`` importable from source pre-install.

Until the extension is installed editable, add the package root to ``sys.path``
so unit tests run against the source tree.
"""

import os
import sys

_PKG_ROOT = os.path.dirname(__file__)
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)
