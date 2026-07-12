"""Baseline IC report for the classic 7 votes (bd-7ct.11, bd-aut).

For every classic vote (ema_cross, macd_hist, rsi, stoch_cross, bb_pctb,
obv_slope, cmf) × every basket symbol (NVDA, PG, XOM, PLTR, SPY),
compute a rolling-window vote series and its 5-day forward IC.

**This is the baseline every family PR (bd-luy/40v/z43/alj) must beat.**
Each new indicator must show an IC delta > 0 on at least K of N basket
symbols (K/N thresholds TBD in the family PR reviews). The baseline is
persisted as ``tests/golden/panel_eval/classic_baseline_ic.json`` and
diffed against on future runs.

Runs against the recorded basket fixture (bd-8ah) — skips if the fixture
is absent so a bare env doesn't fail collection.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from openbb_techtrade.engine import confluence, indicators
from openbb_techtrade.engine.panel_eval import (
    DEFAULT_FORWARD_BARS,
    compute_information_coefficient,
)
from openbb_techtrade.testing import assert_matches_golden

from tests.fixtures import load_basket

# Golden snapshot location (per the #71 harness convention).
GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "panel_eval"
GOLDEN_FILE = GOLDEN_DIR / "classic_baseline_ic.json"

# Minimum bars needed to compute all classic votes reliably. RSI-14 has
# 13 warm-up NaN, EMA-50 has 49, Bollinger-20 has 19 — 100 is a safe floor.
# Then the rolling window starts here.
MIN_BARS: int = 100


def _panel_at(symbol: str, df: pd.DataFrame, i: int):
    """Build IndicatorPanel using the last i+1 bars of df."""
    ohlcv_slice = df.iloc[: i + 1]
    records = ohlcv_slice.reset_index().to_dict(orient="records")
    return indicators.build_indicator_panel(
        symbol=symbol,
        as_of=ohlcv_slice.index[-1].date() if hasattr(ohlcv_slice.index[-1], "date") else date.today(),
        ohlcv_rows=records,
    )


def _classic_vote_series(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    """For each bar i in [MIN_BARS, len(df)), compute the panel + all
    classic votes; return a DataFrame indexed on date, columns = vote names.

    This is O(N × build_panel_cost) — ~1100 bars × ~40ms = ~45s per symbol.
    For 5 symbols = ~4 minutes. That's acceptable for a
    generate-baseline-once test; it runs when the baseline needs
    regenerating (TECHTRADE_REGEN_GOLDEN=1) and simply asserts against
    the frozen JSON otherwise.
    """
    rows = []
    dates = []
    for i in range(MIN_BARS, len(df)):
        panel = _panel_at(symbol, df, i)
        votes = (
            confluence.trend_votes(panel)
            + confluence.momentum_votes(panel)
            + confluence.volatility_votes(panel)
            + confluence._volume_votes(panel)
        )
        row = {v.name: v.vote for v in votes}
        rows.append(row)
        dates.append(df.index[i])
    return pd.DataFrame(rows, index=pd.DatetimeIndex(dates))


def _forward_returns(df: pd.DataFrame) -> pd.Series:
    """Simple close-to-close pct_change, shifted forward N bars later
    inside compute_information_coefficient itself. Returns the raw
    per-bar return series here — the IC primitive does the shift."""
    return df["close"].pct_change()


@pytest.mark.integration
def test_baseline_ic_report_matches_golden(tmp_path):
    """Generate the IC baseline table for every (symbol × classic vote)
    pair and diff against the frozen golden snapshot.

    Marked ``integration`` (per CLAUDE.md convention) because it takes
    ~3-4 minutes end-to-end — deselected from the default fast suite
    (``pytest -m "not integration"``) and only runs when the baseline
    is being regenerated or explicitly verified. Family PRs (bd-luy et
    al) run it too and compare THEIR delta to the golden baseline.

    Regenerate the golden with:
        TECHTRADE_REGEN_GOLDEN=1 pytest openbb_platform/extensions/techtrade/tests/unit/test_panel_eval_baseline.py -m integration
    """
    basket = load_basket()
    baseline = {}

    for symbol in sorted(basket):
        df = basket[symbol].sort_index()
        if len(df) < MIN_BARS + DEFAULT_FORWARD_BARS + 10:
            baseline[symbol] = {"_skipped": f"only {len(df)} bars"}
            continue

        vote_frame = _classic_vote_series(symbol, df)
        forward_returns = _forward_returns(df)

        symbol_result = {}
        for vote_name in vote_frame.columns:
            ic_result = compute_information_coefficient(
                votes=vote_frame[vote_name],
                returns=forward_returns,
                forward_bars=DEFAULT_FORWARD_BARS,
            )
            # Round to 4dp — enough resolution to detect regression,
            # not enough to jitter on numerical noise across environments.
            symbol_result[vote_name] = {
                "coefficient": round(ic_result.coefficient, 4)
                if not np.isnan(ic_result.coefficient) else None,
                "n_samples": ic_result.n_samples,
            }
        baseline[symbol] = symbol_result

    # Print a summary the reviewer can read in the test output.
    print("\n=== CLASSIC PANEL BASELINE IC (5d forward) ===")
    print(f"{'symbol':<8} {'vote':<20} {'ic':>8}  {'n':>5}")
    for symbol, votes in baseline.items():
        if "_skipped" in votes:
            print(f"{symbol:<8} SKIPPED: {votes['_skipped']}")
            continue
        for vote_name, stats in votes.items():
            ic = stats["coefficient"]
            ic_str = f"{ic:+.4f}" if ic is not None else "NaN"
            print(f"{symbol:<8} {vote_name:<20} {ic_str:>8}  {stats['n_samples']:>5}")

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    assert_matches_golden(
        name="classic_baseline_ic",
        payload=baseline,
        fixture_dir=GOLDEN_DIR,
    )
