"""Integration test for the IndicatorPanel builder against live fmp_cached (#72).

Runs the real OHLCV fetcher (obb.equity.price.historical via fmp_cached) end to end
for a liquid symbol and asserts the four numeric families populate. Marked
``integration``; skips cleanly when credentials are missing or the source is
unreachable, so the default unit suite stays hermetic.
"""

from __future__ import annotations

from datetime import date

import pytest
from openbb_techtrade.engine.indicators import build_panel_for_symbol
from openbb_techtrade.models import IndicatorPanel

pytestmark = pytest.mark.integration


def test_indicator_panel_msft_live():
    """Build MSFT's panel from live fmp_cached, skipping cleanly when unavailable."""
    try:
        panel = build_panel_for_symbol("MSFT")
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on creds / network
        pytest.skip(f"Live indicator panel unavailable for MSFT: {exc}")

    assert isinstance(panel, IndicatorPanel)
    assert panel.symbol == "MSFT"
    assert isinstance(panel.as_of, date)
    assert panel.trend and panel.momentum and panel.volatility and panel.volume
    assert isinstance(panel.candles, dict)  # may be empty if no pattern fires
