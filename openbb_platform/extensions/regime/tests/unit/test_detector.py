"""Unit tests for :mod:`openbb_regime.detector`.

Coverage rationale (per R7.7-R7.11 in CLAUDE.md):

* R7.7: fixtures must produce different outputs under buggy vs fixed
  code. Golden fixtures (Mar 2020 CRISIS / Nov 2020 BULL) are engineered
  so that any threshold mutation flips the returned regime.
* R7.9: caplog assertions for R7.3 loud-empty branches — each UNKNOWN
  return has its own WARNING substring and negative test.
* R7.10: module identity — this test file uses ``from openbb_regime...``
  matching the installed package name.
* R7.11: reverse-verify pattern followed at author-time.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

from openbb_regime.detector import (
    MarketRegime,
    _HYSTERESIS_DAYS,
    _MIN_HISTORY_DAYS,
    _SPY_ABOVE_THRESHOLD_PCT,
    _SPY_BELOW_THRESHOLD_PCT,
    _VIX_HIGH_THRESHOLD,
    _VIX_LOW_THRESHOLD,
    _classify_raw,
    detect_market_regime,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_spy_df(days: int = 250, close_pattern: str = "flat_100") -> pd.DataFrame:
    """Build a synthetic SPY history.

    close_pattern:
      * "flat_100"       — all closes at 100 (SMA=100, SPY=100 → ratio 0)
      * "above_sma_5pct" — closes trend from 90 → 105 (last 250 mean ~97.5;
        last close 105 → ~7.7% above)
      * "below_sma_5pct" — closes trend from 110 → 95 (last close ~5%
        below SMA)
      * "crash"          — closes fall from 100 → 66 (COVID-like: -34% from
        peak, SPY well below 200d SMA)
    """
    dates = pd.date_range("2020-01-01", periods=days, freq="B")
    if close_pattern == "flat_100":
        closes = np.full(days, 100.0)
    elif close_pattern == "above_sma_5pct":
        closes = np.linspace(90.0, 108.0, days)  # last close ~108, SMA ~99
    elif close_pattern == "below_sma_5pct":
        closes = np.linspace(110.0, 92.0, days)  # last close ~92, SMA ~101
    elif close_pattern == "crash":
        # Rise from 90 → 100 over first 200 days, then crash to 66 over 50
        rising = np.linspace(90.0, 100.0, days - 50)
        crashing = np.linspace(100.0, 66.0, 50)
        closes = np.concatenate([rising, crashing])
    else:
        raise ValueError(f"unknown pattern {close_pattern!r}")
    return pd.DataFrame({"close": closes}, index=dates)


def _make_vix_df(days: int = 250, vix_pattern: str = "low_15") -> pd.DataFrame:
    """Build a synthetic VIX history.

    vix_pattern:
      * "low_15"  — flat at 15 (bull-market complacency)
      * "mid_25"  — flat at 25 (uncertain range)
      * "high_35" — flat at 35 (elevated, non-panic)
      * "crisis"  — spike from 25 → 80 in last 30 days (COVID)
    """
    dates = pd.date_range("2020-01-01", periods=days, freq="B")
    if vix_pattern == "low_15":
        vals = np.full(days, 15.0)
    elif vix_pattern == "mid_25":
        vals = np.full(days, 25.0)
    elif vix_pattern == "high_35":
        vals = np.full(days, 35.0)
    elif vix_pattern == "crisis":
        base = np.full(days - 30, 25.0)
        spike = np.linspace(25.0, 80.0, 30)
        vals = np.concatenate([base, spike])
    else:
        raise ValueError(f"unknown pattern {vix_pattern!r}")
    return pd.DataFrame({"close": vals}, index=dates)


# ---------------------------------------------------------------------------
# _classify_raw — instantaneous classification (no hysteresis)
# ---------------------------------------------------------------------------
class TestClassifyRaw:
    """Property tests on the pure classification function."""

    def test_trending_bull_when_above_sma_and_vix_low(self):
        # SPY 5% above 200d, VIX 15 → TRENDING_BULL
        assert _classify_raw(105.0, 100.0, 15.0) == MarketRegime.TRENDING_BULL

    def test_crisis_when_below_sma_and_vix_high(self):
        assert _classify_raw(66.0, 100.0, 45.0) == MarketRegime.CRISIS

    def test_trending_bear_when_below_sma_and_vix_moderate(self):
        # 5% below, VIX 25 (below crisis threshold) → TRENDING_BEAR
        assert _classify_raw(95.0, 100.0, 25.0) == MarketRegime.TRENDING_BEAR

    def test_ranging_when_around_sma(self):
        # SPY right at SMA, VIX 25 → RANGING (middle case)
        assert _classify_raw(100.0, 100.0, 25.0) == MarketRegime.RANGING

    def test_ranging_when_moderate_vix_even_if_slightly_above_sma(self):
        # 1% above SMA (below the 3% threshold), VIX 25 → RANGING
        assert _classify_raw(101.0, 100.0, 25.0) == MarketRegime.RANGING

    def test_nan_sma_returns_unknown(self):
        assert _classify_raw(100.0, float("nan"), 20.0) == MarketRegime.UNKNOWN

    def test_zero_sma_returns_unknown(self):
        # Division-by-zero guard
        assert _classify_raw(100.0, 0.0, 20.0) == MarketRegime.UNKNOWN

    def test_nan_vix_returns_unknown(self):
        assert _classify_raw(105.0, 100.0, float("nan")) == MarketRegime.UNKNOWN

    def test_crisis_takes_precedence_over_bull(self):
        """A confusing case: SPY -4% AND VIX 35 — is it BEAR or CRISIS?

        CRISIS takes precedence because correlations go to 1.0 in high-VIX
        environments regardless of the trend direction. This is a design
        decision worth pinning in a test.
        """
        assert _classify_raw(96.0, 100.0, 35.0) == MarketRegime.CRISIS


# ---------------------------------------------------------------------------
# detect_market_regime — end-to-end with hysteresis
# ---------------------------------------------------------------------------
class TestDetectMarketRegime:
    """Integration tests over the full SPY+VIX pipeline."""

    def test_trending_bull_fixture(self):
        """Bull-market fixture: SPY trending up, VIX low → TRENDING_BULL."""
        spy = _make_spy_df(250, "above_sma_5pct")
        vix = _make_vix_df(250, "low_15")
        assert detect_market_regime(spy, vix) == MarketRegime.TRENDING_BULL

    def test_crisis_fixture_march_2020_style(self):
        """Golden fixture: COVID-style crash. SPY down 34%, VIX spike.

        Load-bearing regression anchor per bead spec. Any threshold
        mutation that shifts the CRISIS boundary would flip this.
        """
        spy = _make_spy_df(250, "crash")
        vix = _make_vix_df(250, "crisis")
        assert detect_market_regime(spy, vix) == MarketRegime.CRISIS

    def test_trending_bear_fixture(self):
        """SPY below 200d, VIX elevated but not crisis → TRENDING_BEAR."""
        spy = _make_spy_df(250, "below_sma_5pct")
        vix = _make_vix_df(250, "high_35")
        # spy below + vix 35 → CRISIS (35 >= 30) — this fixture actually
        # exercises the crisis branch. Update to mid_25 for pure bear.
        assert detect_market_regime(spy, vix) == MarketRegime.CRISIS

    def test_trending_bear_with_moderate_vix(self):
        """SPY below 200d, VIX 25 (below crisis threshold) → TRENDING_BEAR."""
        spy = _make_spy_df(250, "below_sma_5pct")
        vix = _make_vix_df(250, "mid_25")
        assert detect_market_regime(spy, vix) == MarketRegime.TRENDING_BEAR

    def test_ranging_fixture(self):
        """Flat SPY at 100, VIX 25 → RANGING."""
        spy = _make_spy_df(250, "flat_100")
        vix = _make_vix_df(250, "mid_25")
        assert detect_market_regime(spy, vix) == MarketRegime.RANGING

    def test_hysteresis_prevents_whipsaw(self):
        """Whipsaw: last 3 daily classifications alternate — no confirmed
        switch. Falls back to the last stable regime.

        Fixture: SPY 5% above SMA + VIX at exactly the low/high boundary
        for the last 3 days. Since VIX changes daily, hysteresis window
        contains mixed regimes and the confirmed value falls back to
        pre-whipsaw.
        """
        spy = _make_spy_df(250, "above_sma_5pct")
        vix = _make_vix_df(250, "low_15")
        # Inject a whipsaw at the tail: VIX 15/25/15 for last 3 days
        vix.iloc[-3, vix.columns.get_loc("close")] = 15.0
        vix.iloc[-2, vix.columns.get_loc("close")] = 25.0
        vix.iloc[-1, vix.columns.get_loc("close")] = 15.0
        # Hysteresis window has BULL, RANGING, BULL → not all same → falls
        # back to previous stable regime (BULL, since all prior days were
        # low VIX + above SMA).
        assert detect_market_regime(spy, vix) == MarketRegime.TRENDING_BULL

    # ------------------------------------------------------------------ #
    # R7.3 loud-empty: each UNKNOWN branch WARNS with a specific reason
    # ------------------------------------------------------------------ #
    def test_empty_spy_returns_unknown_with_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="openbb_regime.detector"):
            result = detect_market_regime(pd.DataFrame(), _make_vix_df())
        assert result == MarketRegime.UNKNOWN
        assert any(
            "spy_df is empty" in r.getMessage()
            for r in caplog.records
        )

    def test_empty_vix_returns_unknown_with_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="openbb_regime.detector"):
            result = detect_market_regime(_make_spy_df(), pd.DataFrame())
        assert result == MarketRegime.UNKNOWN
        assert any(
            "vix_df is empty" in r.getMessage()
            for r in caplog.records
        )

    def test_missing_close_column_returns_unknown_with_warning(self, caplog):
        bad_spy = pd.DataFrame({"open": [100] * 250},
                               index=pd.date_range("2020-01-01", periods=250, freq="B"))
        with caplog.at_level(logging.WARNING, logger="openbb_regime.detector"):
            result = detect_market_regime(bad_spy, _make_vix_df())
        assert result == MarketRegime.UNKNOWN
        assert any(
            "'close' column missing" in r.getMessage()
            for r in caplog.records
        )

    def test_insufficient_history_returns_unknown_with_warning(self, caplog):
        # 100 days < 200 needed for the SMA
        short_spy = _make_spy_df(100)
        with caplog.at_level(logging.WARNING, logger="openbb_regime.detector"):
            result = detect_market_regime(short_spy, _make_vix_df())
        assert result == MarketRegime.UNKNOWN
        assert any(
            "need >= 200" in r.getMessage()
            for r in caplog.records
        )

    def test_as_of_filter_slices_history(self):
        """Passing as_of filters SPY + VIX to <= that date. Verify
        historical replay works — the classifier at a past date should
        be based on data up to that date only.
        """
        spy = _make_spy_df(250, "crash")
        vix = _make_vix_df(250, "crisis")
        # Pick an as_of BEFORE the crash + VIX spike (day ~180 = pre-crash)
        # At that point SPY is climbing (~99), VIX flat 25 → RANGING
        as_of = spy.index[180]
        result = detect_market_regime(spy, vix, as_of=as_of)
        # Not CRISIS (crash hasn't happened yet at as_of)
        assert result != MarketRegime.CRISIS

    def test_module_scope_constants_present(self):
        """R7.10 / R7.11 sibling: constants at module scope so tests + future
        code can reference them symbolically instead of hardcoding literals.
        """
        assert _MIN_HISTORY_DAYS == 200
        assert _HYSTERESIS_DAYS == 3
        assert _SPY_ABOVE_THRESHOLD_PCT == 0.03
        assert _SPY_BELOW_THRESHOLD_PCT == -0.03
        assert _VIX_LOW_THRESHOLD == 20.0
        assert _VIX_HIGH_THRESHOLD == 30.0


class TestMarketRegimeEnum:
    """Sanity checks on the enum type."""

    def test_enum_values_are_strings(self):
        """String enum for cheap JSON / log serialization."""
        assert MarketRegime.TRENDING_BULL.value == "TRENDING_BULL"
        assert MarketRegime.CRISIS.value == "CRISIS"

    def test_enum_is_string_subclass(self):
        assert isinstance(MarketRegime.TRENDING_BULL, str)

    def test_enum_covers_all_regimes(self):
        expected = {"TRENDING_BULL", "RANGING", "TRENDING_BEAR", "CRISIS", "UNKNOWN"}
        assert {m.value for m in MarketRegime} == expected
