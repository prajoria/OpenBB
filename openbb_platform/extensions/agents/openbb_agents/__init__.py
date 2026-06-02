"""OpenBB Agents extension — Google ADK agents on top of OpenBB platform.

sys.path bootstrap: injects fmp_cached provider so DatabaseConfig is importable
without requiring it to be a fully installed package.
"""

import sys
from pathlib import Path

# --- sys.path bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[4]  # …/extensions/agents/openbb_agents -> repo root

_INJECT = [
    "openbb_platform/providers/fmp_cached",
    "openbb_platform/core",
    "portfolio_app/src",
]

for _rel in _INJECT:
    _p = str(_REPO_ROOT / _rel)
    if _p not in sys.path:
        sys.path.insert(0, _p)
