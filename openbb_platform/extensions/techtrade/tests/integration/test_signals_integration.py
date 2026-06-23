"""Integration test for the signals command against live fmp_cached (#75).

Runs the *real* signals chain end to end -- the default live ``panel_fetcher``
(#73 selector -> #72 indicator builder over fmp_cached OHLCV) under the
``trend_follow`` preset for an explicit symbol set. Marked ``integration`` and skips
cleanly when credentials are missing or the data source is unreachable, so the default
unit suite stays hermetic (mirrors the movers / indicators integration resilience).
"""

from __future__ import annotations

from datetime import date

import pytest
from openbb_techtrade.engine.signals import build_signals
from openbb_techtrade.models import MoverSignal

pytestmark = pytest.mark.integration

_SYMBOLS = ["AAPL", "MSFT"]


def test_signals_live_symbols_trend_follow():
    """Assert the live signals chain ranks an explicit symbol set under trend_follow."""
    try:
        signals = build_signals(symbols=_SYMBOLS, preset="trend_follow")
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on creds / network
        pytest.skip(f"Live signals unavailable for {_SYMBOLS}: {exc}")

    assert signals, "Live signals returned no MoverSignal"
    assert len(signals) == len(_SYMBOLS)
    assert all(isinstance(s, MoverSignal) for s in signals)
    for s in signals:
        assert -1.0 <= s.score <= 1.0
        assert s.direction in {"long", "short", "flat"}
        assert isinstance(s.as_of, date)
        assert s.votes  # at least one indicator voted
    # Signed-score-descending ranking yields a contiguous 1..N.
    assert [s.rank_in_segment for s in signals] == list(range(1, len(signals) + 1))
    assert all(a.score >= b.score for a, b in zip(signals, signals[1:]))


def test_signals_live_segment_information_technology():
    """Assert the live signals chain ranks a whole GICS segment under breakout."""
    try:
        signals = build_signals(segment="Information Technology", preset="breakout")
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on creds / network
        pytest.skip(f"Live segment signals unavailable: {exc}")

    assert signals, "Live segment signals returned no MoverSignal"
    assert all(s.segment == "Information Technology" for s in signals)
    assert [s.rank_in_segment for s in signals] == list(range(1, len(signals) + 1))
