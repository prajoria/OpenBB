"""Integration test for the live Analysis → factor-score bridge (component 10.5).

Exercises the *real* :func:`make_analysis_score_provider` wired to
:func:`default_run_analysis`, which runs the single-symbol ``Analysis``
pipeline against the live ``fmp_cached`` provider. Marked ``integration`` and
skipped cleanly when ``Analysis`` is not importable or the ``fmp_cached`` data
source is unreachable, so the default unit suite stays hermetic and offline.

The unit-level behavior of the bridge (the phase blend, weight overrides,
missing-phase handling, feeding ``factor_tilt``) is covered with a mocked
``run_analysis`` in ``tests/unit/test_factor_tilt.py``; this file only proves the
real wiring produces a finite score for a large, well-covered symbol.

See ``docs/designs/backtest-design/10-strategy-library.md`` §3.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

# The single-symbol pipeline lives in the repo-root ``Analysis`` package; put it
# on the path so ``default_run_analysis``'s lazy ``import stock_analysis`` works.
_ANALYSIS_DIR = Path(__file__).resolve().parents[5] / "Analysis"
if _ANALYSIS_DIR.is_dir() and str(_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_ANALYSIS_DIR))


def _analysis_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("stock_analysis") is not None
    except Exception:  # noqa: BLE001 - any failure means "skip integration"
        return False


def _fmp_cached_available() -> bool:
    try:
        from openbb_fmp_cached.utils.database import execute_query

        execute_query("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 - any failure means "skip integration"
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _analysis_available(), reason="Analysis package not importable"),
    pytest.mark.skipif(not _fmp_cached_available(), reason="fmp_cached data source unreachable"),
]


def test_live_bridge_produces_finite_score_for_msft():
    import pandas as pd
    from openbb_backtest.strategies.analysis_bridge import (
        default_run_analysis,
        make_analysis_score_provider,
    )

    provider = make_analysis_score_provider(run_analysis=default_run_analysis)
    score = provider("MSFT", pd.Timestamp("2021-01-13"))

    assert isinstance(score, float)
    assert math.isfinite(score)


def test_live_bridge_feeds_factor_tilt_rank():
    import pandas as pd
    from openbb_backtest.strategies.analysis_bridge import (
        default_run_analysis,
        make_analysis_score_provider,
    )
    from openbb_backtest.strategies.factor_tilt import FactorTilt

    class _Market:
        @property
        def now(self) -> pd.Timestamp:
            return pd.Timestamp("2021-01-13")

    provider = make_analysis_score_provider(run_analysis=default_run_analysis)
    ranks = FactorTilt(symbols=["MSFT", "AAPL"], score_provider=provider).rank(_Market())

    assert set(ranks.index) == {"MSFT", "AAPL"}
    assert ranks.notna().all()
