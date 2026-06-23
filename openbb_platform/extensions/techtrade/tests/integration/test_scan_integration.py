"""Integration / acceptance test for the #79 scan orchestrator (PRD §9.2, design §5).

THE acceptance gate of #79. A small OFFLINE multi-sector universe is seeded through the injectable
``candidate_fetcher`` / ``signal_fetcher`` / ``level_fetcher`` / ``bars=`` seams, so the
cross-segment determinism assertion runs in CI with no API key and no network. A second, live smoke
exercises the real chain over ``fmp_cached`` and skips cleanly when credentials / data are absent
(mirrors the movers / signals integration resilience).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from openbb_techtrade.engine.scan import scan_segments
from openbb_techtrade.models import MoverSignal, TradePlan
from openbb_techtrade.testing import to_jsonable

pytestmark = pytest.mark.integration

_AS_OF = date(2024, 1, 12)
_ENTRY = Decimal("121.40")
_ATR = 1.90


def _signal(symbol: str, segment: str, score: float) -> MoverSignal:
    direction = "long" if score >= 0.4 else "short" if score <= -0.4 else "flat"
    return MoverSignal(
        symbol=symbol, segment=segment, as_of=_AS_OF, score=score,
        direction=direction, votes=[], rank_in_segment=1,
    )


def _candidate_fetcher(as_of=None, calendar="XNYS", needs_ohlcv=False, **kwargs):
    # segment-blind: the same two movers surface in every sector
    return [
        {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
        {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
    ]


def _signal_fetcher(symbols=None, segment=None, *, preset="trend_follow", as_of=None):
    # AAA strong long, BBB strong short -> distinct |score| per symbol, same in each sector
    scores = {"AAA": 0.90, "BBB": -0.55}
    return [_signal(s, segment, scores[s]) for s in (symbols or []) if s in scores]


def _level_fetcher(symbol: str, *, as_of: date):
    return _ENTRY, _ATR


def _bars() -> dict[str, list]:
    win = [
        {"open": Decimal("121.40"), "high": Decimal("122"), "low": Decimal("120.0"),
         "close": Decimal("121"), "volume": Decimal("1000000"),
         "timestamp": "2024-01-16T21:00:00+00:00"},
        {"open": Decimal("119"), "high": Decimal("120"), "low": Decimal("117.00"),
         "close": Decimal("118"), "volume": Decimal("1000000"),
         "timestamp": "2024-01-17T21:00:00+00:00"},
    ]
    return {"AAA": win, "BBB": win}


def _scan():
    return scan_segments(
        metric="pct_change", top_n=5, as_of=_AS_OF, simulate=True,
        candidate_fetcher=_candidate_fetcher, signal_fetcher=_signal_fetcher,
        level_fetcher=_level_fetcher, bars=_bars(),
    )


def test_scan_ranks_across_sectors_deterministically():
    """Assert scan spans >1 sector, is |score|-ranked, byte-deterministic, and fills are present."""
    plans = _scan()
    assert plans, "offline scan returned no plans"
    assert all(isinstance(p, TradePlan) for p in plans)
    # (a) cross-segment: plans span more than one sector
    assert len({p.segment for p in plans}) > 1
    # (b) ranked: the total-order key is non-decreasing down the list
    keys = [(-round(abs(p.signal.score), 9), p.symbol, p.segment) for p in plans]
    assert keys == sorted(keys)
    # (c) deterministic: a second identical scan is byte-identical
    assert to_jsonable(plans) == to_jsonable(_scan())
    # (d) fills present (L6) and look-ahead-free (every fill stamped strictly after as_of)
    assert all(p.simulated_fills for p in plans)
    assert all(f.timestamp.date() > _AS_OF for p in plans for f in p.simulated_fills)


def test_scan_simulate_false_matches_offline_ranking_order():
    """Assert simulate=False yields the same ranking order (pre-fill rank independence, C3)."""
    with_fills = _scan()
    no_fills = scan_segments(
        metric="pct_change", top_n=5, as_of=_AS_OF, simulate=False,
        candidate_fetcher=_candidate_fetcher, signal_fetcher=_signal_fetcher,
        level_fetcher=_level_fetcher,
    )
    assert [(p.symbol, p.segment) for p in with_fills] == [(p.symbol, p.segment) for p in no_fills]


def test_scan_live_smoke_shape_only():
    """Assert the live chain returns shape-valid ranked plans, or skip on missing creds/data."""
    try:
        plans = scan_segments(metric="pct_change", top_n=2, simulate=False)
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on creds / network
        pytest.skip(f"Live scan unavailable: {exc}")
    assert isinstance(plans, list)
    assert all(isinstance(p, TradePlan) for p in plans)
    assert len({p.segment for p in plans}) <= 11
    keys = [(-round(abs(p.signal.score), 9), p.symbol, p.segment) for p in plans]
    assert keys == sorted(keys)
