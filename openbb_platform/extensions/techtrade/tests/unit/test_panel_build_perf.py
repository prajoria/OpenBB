"""Wall-clock benchmark for build_indicator_panel (bd-7ct.9, bd-107).

Design spec §D7 asserts panel-build p95 <= 100ms per symbol on the standard
mock. This test enforces that budget so a future family PR that inadvertently
adds an O(N) or network-blocking path fails fast.

Both classic AND extended paths measured, since bd-7ct's promise is that
extended is byte-identical to classic today (pass-through stubs → same
wall-clock).
"""

from __future__ import annotations

import time
from datetime import date

import numpy as np
import pandas as pd
import pytest

from openbb_techtrade.engine import indicators
from openbb_techtrade.engine.panel_config import PANEL_CLASSIC, PANEL_EXTENDED

# Wall-clock budget (design spec §D7). Chosen so a 55-symbol scan across
# 11 sectors × 5 movers each stays sub-6s per full scan cycle.
BUDGET_P95_MS: float = 100.0

# Sample size: enough to compute a stable p95 without making the test
# expensive itself. 30 iterations × ~40ms = ~1.2s wall-clock for the test.
N_ITERATIONS: int = 30


def _make_ohlcv_records(n: int = 100) -> list[dict]:
    """Reuses the same synthetic OHLCV fixture as test_extended_pass_through."""
    import pandas_ta_classic  # noqa: F401 - registers .ta

    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100.0 + np.arange(n) * 0.5
    df = pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1_000_000.0) + np.arange(n) * 100,
        },
        index=dates,
    )
    df.columns = [c.lower() for c in df.columns]
    return df.reset_index(names="timestamp").to_dict(orient="records")


@pytest.fixture(scope="module")
def ohlcv_records():
    return _make_ohlcv_records(100)


def _measure_p95(records: list[dict], panel_config, n: int = N_ITERATIONS) -> float:
    """Return the p95 wall-clock in milliseconds across ``n`` builds."""
    as_of = date(2024, 5, 20)
    # Warm up once (imports, JIT, etc.) so measurements are steady-state
    indicators.build_indicator_panel(
        symbol="TEST", as_of=as_of, ohlcv_rows=records, panel_config=panel_config,
    )
    times_ms = []
    for _ in range(n):
        t0 = time.perf_counter()
        indicators.build_indicator_panel(
            symbol="TEST", as_of=as_of, ohlcv_rows=records, panel_config=panel_config,
        )
        times_ms.append((time.perf_counter() - t0) * 1000)
    return float(np.percentile(times_ms, 95))


class TestPanelBuildPerf:
    """Enforce the §D7 wall-clock budget on both classic and extended paths.

    All tests here marked ``integration`` because per-percentile timing
    is inherently flaky under CI concurrent load. In the default fast
    suite (``pytest -m "not integration"``) they're deselected — run
    them explicitly during Phase 5 quality checks or when suspecting a
    perf regression.
    """
    pytestmark = pytest.mark.integration

    def test_classic_p95_within_budget(self, ohlcv_records):
        """Baseline: classic path must stay under the budget."""
        p95 = _measure_p95(ohlcv_records, PANEL_CLASSIC)
        assert p95 <= BUDGET_P95_MS, (
            f"classic panel-build p95 = {p95:.1f}ms exceeds budget "
            f"{BUDGET_P95_MS}ms. Investigate what got slower before "
            f"raising the budget."
        )

    def test_extended_p95_within_budget(self, ohlcv_records):
        """Extended path (pass-through stubs today) should match classic;
        family PRs will add ~5-10ms per new indicator, so the budget
        may need revisiting when bd-luy/40v/z43/alj land."""
        p95 = _measure_p95(ohlcv_records, PANEL_EXTENDED)
        assert p95 <= BUDGET_P95_MS, (
            f"extended panel-build p95 = {p95:.1f}ms exceeds budget "
            f"{BUDGET_P95_MS}ms. In bd-7ct this should match classic "
            f"(pass-through). When family PRs land, expect ~5-10ms per "
            f"new indicator; revisit the budget then."
        )

    def test_extended_not_materially_slower_than_classic(self, ohlcv_records):
        """Cross-check: extended panel isn't pathologically slower than
        classic. bd-luy shipped Aroon + Ichimoku (real computation, not
        pass-through), so extended is expected to be ~1.5-2.5x classic
        on the trend leg. We enforce ≤3x as the "something's very wrong"
        ceiling; a genuine perf regression trips this."""
        classic_p95 = _measure_p95(ohlcv_records, PANEL_CLASSIC)
        extended_p95 = _measure_p95(ohlcv_records, PANEL_EXTENDED)
        # Guard against zero-baseline weirdness on ultra-fast runs
        if classic_p95 < 5.0:
            pytest.skip(
                f"classic p95 {classic_p95:.2f}ms too small to measure "
                f"relative dispatch overhead reliably"
            )
        ratio = extended_p95 / classic_p95
        assert ratio <= 3.0, (
            f"extended p95 {extended_p95:.1f}ms is {ratio:.2f}x classic "
            f"{classic_p95:.1f}ms. bd-luy adds Aroon+Ichimoku so ratio > 1 "
            f"is expected, but >3x means something regressed."
        )
