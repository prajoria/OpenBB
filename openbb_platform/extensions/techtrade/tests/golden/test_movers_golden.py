"""Golden-fixture regression lock for the top-mover ranking engine (#71, #70).

Runs the pure, deterministic ``rank_movers`` over a fixed candidate set and locks
the resulting ``MoverList`` against a committed golden JSON within ``DEFAULT_TOL``.
Carries the ``golden`` marker. Regenerate intentionally after a *reviewed* change
with ``TECHTRADE_REGEN_GOLDEN=1`` -- never blindly. This both proves the harness
end to end and guards #70's ranking output.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from openbb_techtrade.engine.movers import rank_movers
from openbb_techtrade.testing import assert_matches_golden

pytestmark = pytest.mark.golden

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_AS_OF = date(2024, 1, 12)
_CANDIDATES = [
    {"symbol": "AAA", "pct_change": 0.012, "volume": 1_000},
    {"symbol": "BBB", "pct_change": 0.051, "volume": 2_500},
    {"symbol": "CCC", "pct_change": 0.034, "volume": 1_750},
    {"symbol": "DDD", "pct_change": -0.020, "volume": 3_200},
    {"symbol": "EEE", "pct_change": 0.051, "volume": 900},
]


def _snapshot():
    ml = rank_movers("Information Technology", _AS_OF, _CANDIDATES, metric="pct_change")
    return ml.model_dump()


def test_rank_movers_matches_golden():
    assert_matches_golden("movers_pct_change", _snapshot(), fixture_dir=_FIXTURE_DIR)


def test_rank_movers_is_deterministic():
    assert _snapshot() == _snapshot()
