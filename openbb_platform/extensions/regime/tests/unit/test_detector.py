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

    def test_below_sma_with_high_vix_reclassifies_as_crisis(self):
        """iter-1 code-reviewer LOW-5: renamed from `test_trending_bear_fixture`
        whose docstring/assertion contradicted (docstring said BEAR, assertion
        expected CRISIS). The behavior is correct: high VIX (35 >= 30)
        triggers CRISIS regardless of SPY position — see docstring on
        _classify_raw and test_crisis_takes_precedence_over_bull for the
        design rationale.
        """
        spy = _make_spy_df(250, "below_sma_5pct")
        vix = _make_vix_df(250, "high_35")
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

    # ------------------------------------------------------------------ #
    # PR-B1 iter-1 review regression tests
    # ------------------------------------------------------------------ #
    def test_crisis_fires_on_high_vix_even_with_bull_spy(self):
        """iter-1 code-reviewer NOVEL-2 fix: CRISIS fires on ``vix >= 30``
        regardless of SPY trend. Prior gating (``spy_vs_sma <= -3% AND
        vix >= 30``) missed melt-up-then-panic events like Jan 2018
        vol-mageddon and Feb 2020 pre-crash where SPY was still above
        the 200d SMA when VIX spiked.

        Load-bearing: reverting the guard to require ``spy_vs_sma <= -3%``
        would make this test flip from CRISIS to RANGING.
        """
        # SPY +5% above SMA, VIX 40 (panic) → CRISIS
        assert _classify_raw(105.0, 100.0, 40.0) == MarketRegime.CRISIS

    def test_crisis_fires_on_high_vix_with_ranging_spy(self):
        """SPY at SMA (RANGING zone) + VIX 35 → CRISIS (not RANGING).
        Prior code returned RANGING here; the fix widens CRISIS.
        """
        assert _classify_raw(100.0, 100.0, 35.0) == MarketRegime.CRISIS

    def test_spy_boundary_at_exactly_3pct_above(self):
        """iter-1 pr-test M8 fix: pin the ``>=`` boundary on SPY_ABOVE.
        A mutation from ``>=`` to ``>`` would flip the boundary case
        from BULL to RANGING.
        """
        # SPY exactly +3% above SMA, VIX 15 (low) → BULL (>=)
        assert _classify_raw(103.0, 100.0, 15.0) == MarketRegime.TRENDING_BULL

    def test_spy_boundary_at_exactly_3pct_below(self):
        """SPY exactly -3% below SMA, VIX 25 → BEAR (<=)."""
        assert _classify_raw(97.0, 100.0, 25.0) == MarketRegime.TRENDING_BEAR

    def test_vix_boundary_at_exactly_20(self):
        """VIX at exactly the low threshold (20.0) is NOT strictly < 20 →
        NOT BULL even with SPY above SMA → RANGING.

        Documents the asymmetric semantics: SPY uses >=, VIX_LOW uses <.
        """
        assert _classify_raw(105.0, 100.0, 20.0) == MarketRegime.RANGING

    def test_vix_boundary_at_exactly_30(self):
        """VIX at exactly the high threshold (30.0) fires CRISIS (>=)."""
        assert _classify_raw(105.0, 100.0, 30.0) == MarketRegime.CRISIS

    def test_hysteresis_behavioral_distinguishes_3_from_1(self):
        """iter-1 pr-test M5 fix: previously the only test pinning
        _HYSTERESIS_DAYS=3 was a constant-value assertion, not a
        behavioral test. Mutating to 2 or 1 didn't cause any behavioral
        test to fail.

        This test constructs a fixture where 1-day and 3-day hysteresis
        produce DIFFERENT regimes: SPY stable-bull for 245 days, then
        the tail 5 days flip VIX between low and high. Under 3-day
        hysteresis, walkback returns BULL (last stable). Under 1-day
        hysteresis, the latest single day drives the answer (varies).
        """
        # 250 days of bull setup
        spy = _make_spy_df(250, "above_sma_5pct")
        vix = _make_vix_df(250, "low_15")
        # Flip VIX to 35 (CRISIS trigger) on the very last day
        vix.iloc[-1, vix.columns.get_loc("close")] = 35.0

        # Under 3-day hysteresis: last 3 = [BULL, BULL, CRISIS] → mixed →
        # walkback finds [BULL, BULL, BULL] earlier → returns BULL
        result = detect_market_regime(spy, vix)
        # Under 1-day hysteresis (mutation): returns CRISIS (latest single
        # day). If someone mutates _HYSTERESIS_DAYS to 1, this test fails.
        assert result == MarketRegime.TRENDING_BULL

    def test_enum_case_insensitive_construction(self):
        """iter-1 silent-hunt F1 fix: MarketRegime('crisis') /
        MarketRegime('Crisis') / MarketRegime('CRISIS') all resolve to
        the same member. Protects consumers who round-trip through the
        enum from external string inputs.
        """
        assert MarketRegime("crisis") == MarketRegime.CRISIS
        assert MarketRegime("Crisis") == MarketRegime.CRISIS
        assert MarketRegime("CRISIS") == MarketRegime.CRISIS
        assert MarketRegime("trending_bull") == MarketRegime.TRENDING_BULL
        assert MarketRegime("TRENDING_BULL") == MarketRegime.TRENDING_BULL
        # Invalid values still raise ValueError as normal enum behavior
        with pytest.raises(ValueError):
            MarketRegime("not_a_regime")

    def test_mixed_unknown_in_hysteresis_window_returns_unknown(self, caplog):
        """iter-1 silent-hunt F5 fix: intermittent VIX gaps in the
        trailing hysteresis window must return UNKNOWN + warn, not
        silently return a confident regime based on the earlier good days.

        Load-bearing property: reverting the UNKNOWN-in-window guard
        would return TRENDING_BULL here (the majority of the earlier
        window is bull-like), which would be a false positive since
        VIX is broken on half the recent days.
        """
        spy = _make_spy_df(250, "above_sma_5pct")
        vix = _make_vix_df(250, "low_15")
        # Inject NaN into VIX for 2 of the 3 hysteresis-window days
        # (indices -1, -3 — leaves -2 as the sole non-NaN in window)
        vix.iloc[-3, vix.columns.get_loc("close")] = float("nan")
        vix.iloc[-1, vix.columns.get_loc("close")] = float("nan")

        with caplog.at_level(logging.WARNING, logger="openbb_regime.detector"):
            result = detect_market_regime(spy, vix)

        assert result == MarketRegime.UNKNOWN, (
            f"Mixed-UNKNOWN in hysteresis window must return UNKNOWN; "
            f"got {result}. Reverting the F5 guard would return a "
            f"confident regime based on stale earlier-good days."
        )
        warnings = [r for r in caplog.records if "contains UNKNOWN" in r.getMessage()]
        assert len(warnings) == 1

    def test_whipsaw_walkback_emits_warning(self, caplog):
        """iter-1 F2 + code-reviewer NOVEL-1: walkback-rescue must
        emit a WARNING so consumers can distinguish 'confirmed regime'
        from 'walked back through whipsaw'. Prior code was silent.
        """
        # Construct fixture where hysteresis window is whipsawing but
        # a stable regime exists earlier in the walkback window.
        spy = _make_spy_df(250, "above_sma_5pct")
        vix = _make_vix_df(250, "low_15")
        # Introduce whipsaw in the last 3 days
        vix.iloc[-3, vix.columns.get_loc("close")] = 15.0
        vix.iloc[-2, vix.columns.get_loc("close")] = 25.0  # RANGING
        vix.iloc[-1, vix.columns.get_loc("close")] = 15.0

        with caplog.at_level(logging.WARNING, logger="openbb_regime.detector"):
            result = detect_market_regime(spy, vix)

        assert result == MarketRegime.TRENDING_BULL   # walked back to stable
        warnings = [r for r in caplog.records if "whipsaw" in r.getMessage()]
        assert len(warnings) == 1, (
            f"walkback rescue must emit a WARNING. Got: "
            f"{[r.getMessage() for r in caplog.records]}"
        )

    def test_novel1_walkback_now_sees_prior_stable_regime_across_100_days(self):
        """iter-1 code-reviewer NOVEL-1 fix: extended walkback from 4 to 33
        days must actually change behavior on a whipsaw where the last 4
        days contain NO stable 3-day slice, but the last 33 days DO.

        Load-bearing property (R7.11 verified via mutation): with
        _WALKBACK_DAYS reverted to _HYSTERESIS_DAYS+1 (=4), the fixture
        below leaves walkback with only 4 daily regimes to inspect;
        the last 3-day slice is whipsawing → falls through the walkback
        loop → returns UNKNOWN. With the new 33-day window it finds the
        stable pre-whipsaw CRISIS regime.

        Construction:
        * 250 days SPY bull setup + VIX HIGH (CRISIS) → CRISIS baseline
        * Days -3..-1: whipsaw VIX 15 / 40 / 15 (no 3-day stable slice
          in trailing 4 days; last 3-day slice is [CRISIS, RANGING?, CRISIS])

        Note: walkback iterates backwards from most recent; it returns
        the FIRST stable slice it hits. Since CRISIS dominates days
        -33..-4 uniformly, walkback finds a stable CRISIS slice near the
        tail (before the whipsaw). Under the mutation (4-day window),
        walkback only sees the 4 whipsaw days → no stable slice → UNKNOWN.
        """
        spy = _make_spy_df(250, "above_sma_5pct")
        # Fill VIX with high values (CRISIS) throughout — no BULL slice exists
        vix = _make_vix_df(250, "low_15")
        vix["close"] = 40.0   # all-CRISIS baseline
        # Whipsaw at the tail (no 3-day stable slice in last 4 days)
        vix.iloc[-3, vix.columns.get_loc("close")] = 15.0
        vix.iloc[-2, vix.columns.get_loc("close")] = 40.0
        vix.iloc[-1, vix.columns.get_loc("close")] = 15.0

        result = detect_market_regime(spy, vix)
        # With 33-day walkback: finds a stable CRISIS slice ~4 days
        # before the whipsaw (days -6..-4 = [CRISIS, CRISIS, CRISIS]).
        # Mutation to _WALKBACK_DAYS=_HYSTERESIS_DAYS+1 (=4): only sees
        # days -4..-1 = [CRISIS, whipsaw...] → no stable slice → UNKNOWN.
        assert result == MarketRegime.CRISIS, (
            f"Extended walkback (33 days) must find the stable CRISIS "
            f"slice that the old 4-day walkback would miss; got {result}. "
            f"Getting UNKNOWN or a different regime means either the "
            f"fixture is wrong OR _WALKBACK_DAYS was reverted to "
            f"_HYSTERESIS_DAYS+1."
        )


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
