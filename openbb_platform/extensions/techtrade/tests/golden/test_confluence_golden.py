"""Golden-score regression lock for the confluence engine (#74, #71 harness, PRD §12).

Builds a MoverSignal from a fixed bullish hand-built IndicatorPanel (the same
``_gold_panel`` literal the unit suite hand-derives to score 0.8832) and locks the
full signal -- composite score AND every IndicatorVote (family / name / vote /
weight) -- against a committed golden JSON within DEFAULT_TOL. Carries the
``golden`` marker. Regenerate intentionally after a *reviewed* change with
TECHTRADE_REGEN_GOLDEN=1 -- never blindly.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from openbb_techtrade.engine.confluence import build_signal
from openbb_techtrade.models import IndicatorPanel
from openbb_techtrade.testing import assert_matches_golden

pytestmark = pytest.mark.golden

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_AS_OF = date(2024, 1, 12)


def _gold_panel() -> IndicatorPanel:
    """Build the bullish reference panel locked by the golden fixture."""
    return IndicatorPanel(
        symbol="GOLD",
        as_of=_AS_OF,
        trend={"macd_hist": 0.85, "adx": 28.0, "ema_fast": 121.5, "ema_slow": 117.0, "ema_cross": 4.5},
        momentum={"rsi": 64.0, "stoch_k": 80.0, "stoch_d": 72.0},
        volatility={"bb_pctb": 0.92, "atr": 3.1, "kc_upper": 124.0, "kc_lower": 116.0},
        volume={"obv_slope": 12.0, "cmf": 0.18},
        candles={"cdl_engulfing": 1},
    )


def _snapshot() -> dict:
    """Return the JSON-able MoverSignal snapshot for the golden comparison."""
    return build_signal(_gold_panel(), "Information Technology", rank_in_segment=1).model_dump()


def test_confluence_signal_matches_golden():
    """Assert the full MoverSignal (score + votes) matches the committed golden fixture."""
    assert_matches_golden("confluence_signal_golden", _snapshot(), fixture_dir=_FIXTURE_DIR)


def test_confluence_signal_is_deterministic():
    """Assert two builds of the same panel produce an identical signal snapshot."""
    assert _snapshot() == _snapshot()
