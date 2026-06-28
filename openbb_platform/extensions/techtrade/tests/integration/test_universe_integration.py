"""Integration test for the segment universe resolver against live fmp_cached (#69).

Runs the *real* default ETF-holdings fetcher (``obb.etf.holdings`` via fmp_cached)
end to end for the Information Technology sector (XLK). Marked ``integration`` and
skips cleanly when credentials are missing or the data source is unreachable, so the
default unit suite stays hermetic (mirrors the backtest integration resilience).
"""

from __future__ import annotations

import pytest

from openbb_techtrade.engine.universe import resolve_universe
from openbb_techtrade.models import SegmentConfig

pytestmark = pytest.mark.integration


def test_real_etf_holdings_resolve_xlk():
    cfg = SegmentConfig(segment="Information Technology", benchmark_etf="XLK")

    try:
        universe = resolve_universe(cfg)  # live fmp_cached default fetcher
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on creds / network
        pytest.skip(f"Live ETF holdings unavailable for XLK: {exc}")

    # A real sector SPDR resolves to a non-empty, plausible universe.
    assert universe, "XLK resolved to an empty universe"
    assert len(universe) >= 5
    # Plausible, well-formed uppercase tickers.
    assert all(isinstance(sym, str) and sym for sym in universe)
    assert all(sym == sym.upper() for sym in universe)
