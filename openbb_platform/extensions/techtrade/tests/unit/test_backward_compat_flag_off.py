"""Backward-compat AC-1 golden invariance suite (bd-7ct.8, bd-73s).

**The single most important test in the bd-7ct foundation PR.** Proves
that with ``use_extended_confluence_panel=False`` (the default), every
observable of the pipeline is byte-identical to the pre-bd-7ct state.

If any test in this file flips red on a future PR without an explicit
acceptance criterion change, the flag-off path has drifted — the exact
scenario the design spec §D1 says must not happen.

**Golden fixture:** frozen panel + signal snapshots for NVDA / PG /
SPY at a specific date (2025-06-16), computed on the recorded basket
(bd-7ct.7 / bd-8ah). Regeneration requires ``TECHTRADE_REGEN_GOLDEN=1``
and reviewer approval — the frozen values are the reference every
downstream family PR compares against for classic-path invariance.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from openbb_techtrade.engine import confluence, indicators
from openbb_techtrade.engine.panel_config import (
    PANEL_CLASSIC,
    PANEL_EXTENDED,
    PanelConfig,
)
from openbb_techtrade.testing import assert_matches_golden

from ..fixtures import load_basket

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "flag_off_invariance"

# Fixed as-of dates to anchor the golden. Picked after the recorded fixture
# start dates (some symbols like NVDA start mid-2021 due to fmp_cached data
# range) and give ~4 years of history for stable indicators.
#
# **bd-tnz (2026-07-11)** adds a second date in a distinct volatility regime
# (2022-06-16 was mid-bear on SPY, VIX elevated) so that a regression that
# only surfaces in one regime — e.g. a change in how the extended path
# handles high-vol readings — cannot silently pass the AC-1 gate. Bull-era
# 2025-06-16 golden stays as the primary anchor; the 2022-06-16 golden is
# additive coverage.
AS_OF = date(2025, 6, 16)
AS_OF_BEAR = date(2022, 6, 16)


def _panel_for(symbol: str, basket: dict, as_of: date = AS_OF) -> object:
    """Build a classic panel for `symbol` at the given `as_of` date."""
    df = basket[symbol].sort_index()
    # Slice to as-of; the parquet may or may not include this exact bar,
    # so use the last available bar <= as_of.
    df_thru = df[df.index.date <= as_of]
    if len(df_thru) < 100:
        pytest.skip(
            f"insufficient bars for {symbol} through {as_of} "
            f"(only {len(df_thru)})"
        )
    records = df_thru.reset_index().to_dict(orient="records")
    return indicators.build_indicator_panel(
        symbol=symbol,
        as_of=df_thru.index[-1].date(),
        ohlcv_rows=records,
    )


def _panel_to_dict(panel) -> dict:
    """Serialise IndicatorPanel to a plain dict for golden comparison.

    **``candles`` intentionally omitted:** pandas-ta-classic's
    candlestick pattern detection depends on which subset of
    ``cdl_*`` names are registered at call time, which varies by test
    ordering (module-level state in the pandas-ta accessor). Making
    the golden depend on ``candles`` produces flaky assertions that
    only fire under specific test-execution orderings. Since the four
    directional families (trend/momentum/volatility/volume) are what
    the confluence panel expansion actually touches, restricting the
    golden to those four keys is both sufficient AND stable.
    """
    return {
        "symbol": panel.symbol,
        "as_of": panel.as_of.isoformat(),
        "trend": {k: v for k, v in panel.trend.items()},
        "momentum": {k: v for k, v in panel.momentum.items()},
        "volatility": {k: v for k, v in panel.volatility.items()},
        "volume": {k: v for k, v in panel.volume.items()},
    }


def _signal_to_dict(sig) -> dict:
    """Serialise MoverSignal to a plain dict."""
    return {
        "symbol": sig.symbol,
        "segment": sig.segment,
        "as_of": sig.as_of.isoformat(),
        "score": sig.score,
        "direction": sig.direction,
        "rank_in_segment": sig.rank_in_segment,
        "votes": [
            {
                "family": v.family, "name": v.name,
                "vote": v.vote, "weight": v.weight,
            }
            for v in sig.votes
        ],
    }


class TestPanelInvarianceFlagOff:
    """The classic-panel bytes for each basket symbol at the anchor date
    must never change without deliberate golden regen. Every family PR
    (bd-luy/40v/z43/alj) runs these tests — flag-off invariance is the
    line they must not cross.

    iter-1 pr-test M2: extended from 3/5 basket coverage (NVDA/PG/SPY)
    to the full 5/5 (adds XOM cyclical + PLTR recent-IPO). A regression
    that only shows on XOM or PLTR was previously invisible.
    """

    @pytest.mark.parametrize("symbol", ["NVDA", "PG", "XOM", "PLTR", "SPY"])
    def test_classic_panel_matches_golden(self, symbol):
        basket = load_basket()
        panel = _panel_for(symbol, basket)
        assert_matches_golden(
            name=f"panel_{symbol}_2025-06-16",
            payload=_panel_to_dict(panel),
            fixture_dir=GOLDEN_DIR,
        )


class TestSignalInvarianceFlagOff:
    """Same guarantee at the signal layer: classic score + votes for each
    basket symbol at the anchor date must be byte-identical."""

    @pytest.mark.parametrize("symbol", ["NVDA", "PG", "XOM", "PLTR", "SPY"])
    def test_classic_signal_matches_golden(self, symbol):
        basket = load_basket()
        panel = _panel_for(symbol, basket)
        signal = confluence.build_signal(panel, segment="TEST_SECTOR")
        assert_matches_golden(
            name=f"signal_{symbol}_2025-06-16",
            payload=_signal_to_dict(signal),
            fixture_dir=GOLDEN_DIR,
        )


# ---------------------------------------------------------------------------
# bd-tnz: second-date golden (2022-06-16, bear regime)
# ---------------------------------------------------------------------------
#
# The primary 2025-06-16 goldens cover a bull-tape / low-vol regime.
# A regression that only surfaces in a different regime (e.g. a change
# in how the panel handles VIX-elevated / bear-market conditions) would
# pass every 2025 test. This second anchor at 2022-06-16 (mid-2022 bear
# on SPY, VIX in the top decile of its 5y distribution) gives regime
# coverage without requiring a full multi-date matrix.
#
# **Bead scope was minimum SPY only**; expanded to the same 5-symbol
# basket for consistency with the primary goldens. If regen cost ever
# becomes an issue, narrow to SPY per the original bead scope.


class TestPanelInvarianceFlagOffBearRegime:
    """bd-tnz: classic-panel invariance at 2022-06-16 (bear regime).

    Same contract as TestPanelInvarianceFlagOff but anchored in a
    volatility regime distinct from the primary 2025-06-16 golden.
    Any classic-path drift that's regime-dependent (silent handling
    change on high-VIX inputs, bear-tape indicator artifact, etc.)
    trips this gate.

    R7.11 discipline: goldens regenerated by running
    ``TECHTRADE_REGEN_GOLDEN=1 pytest <this-file>`` and reviewing the
    resulting json diffs before commit — never regen without eyeballing.
    """

    @pytest.mark.parametrize("symbol", ["NVDA", "PG", "XOM", "SPY"])  # PLTR IPO'd 2020; may be thin at 2022-06-16
    def test_classic_panel_matches_golden_bear(self, symbol):
        basket = load_basket()
        panel = _panel_for(symbol, basket, as_of=AS_OF_BEAR)
        assert_matches_golden(
            name=f"panel_{symbol}_2022-06-16",
            payload=_panel_to_dict(panel),
            fixture_dir=GOLDEN_DIR,
        )


class TestSignalInvarianceFlagOffBearRegime:
    """bd-tnz: signal invariance at 2022-06-16 (bear regime)."""

    @pytest.mark.parametrize("symbol", ["NVDA", "PG", "XOM", "SPY"])
    def test_classic_signal_matches_golden_bear(self, symbol):
        basket = load_basket()
        panel = _panel_for(symbol, basket, as_of=AS_OF_BEAR)
        signal = confluence.build_signal(panel, segment="TEST_SECTOR")
        assert_matches_golden(
            name=f"signal_{symbol}_2022-06-16",
            payload=_signal_to_dict(signal),
            fixture_dir=GOLDEN_DIR,
        )


class TestExtendedMatchesClassicToday:
    """After bd-luy (trend family shipped), the extended trend panel adds
    Aroon + Ichimoku keys on top of classic. The invariant relaxes from
    strict equality to SUBSET: classic keys ⊆ extended keys, and every
    shared key carries the same value. Momentum / volatility / volume
    remain byte-identical (still pass-through pending bd-40v/z43/alj)."""

    @pytest.mark.parametrize("symbol", ["NVDA", "PG", "XOM", "PLTR", "SPY"])
    def test_extended_signal_equals_classic_today(self, symbol):
        basket = load_basket()
        panel_classic = indicators.build_indicator_panel(
            symbol=symbol,
            as_of=basket[symbol].index[-1].date(),
            ohlcv_rows=basket[symbol].reset_index().to_dict(orient="records"),
            panel_config=PANEL_CLASSIC,
        )
        panel_extended = indicators.build_indicator_panel(
            symbol=symbol,
            as_of=basket[symbol].index[-1].date(),
            ohlcv_rows=basket[symbol].reset_index().to_dict(orient="records"),
            panel_config=PANEL_EXTENDED,
        )
        # Trend family: SUBSET (bd-luy shipped Aroon + Ichimoku).
        assert set(panel_classic.trend.keys()).issubset(
            set(panel_extended.trend.keys())
        )
        for k, v in panel_classic.trend.items():
            assert panel_extended.trend[k] == v, (
                f"{symbol}: shared trend key '{k}' drifted"
            )
        # Other families still byte-identical (still pass-through).
        assert panel_classic.momentum == panel_extended.momentum
        assert panel_classic.volatility == panel_extended.volatility
        assert panel_classic.volume == panel_extended.volume

        # Signal-layer note: since extended adds directional votes,
        # scores WILL diverge. Verify build_signal STILL RUNS on both
        # (no shape errors) rather than asserting equal scores.
        sig_classic = confluence.build_signal(
            panel_classic, segment="TEST", panel_config=PANEL_CLASSIC,
        )
        sig_extended = confluence.build_signal(
            panel_extended, segment="TEST", panel_config=PANEL_EXTENDED,
        )
        assert sig_classic.score is not None
        assert sig_extended.score is not None
        # Classic votes must be a subsequence of extended votes.
        classic_names = [v.name for v in sig_classic.votes]
        extended_names = [v.name for v in sig_extended.votes]
        assert set(classic_names).issubset(set(extended_names)), (
            f"{symbol}: extended votes must include all classic votes; "
            f"missing={set(classic_names) - set(extended_names)}"
        )


class TestConstructedPanelConfigWorks:
    """R7.11: pinning the sentinel constants isn't the same as pinning
    ``PanelConfig(panel="classic")`` construction from string values.
    Both paths must produce the same behavior."""

    def test_constructed_classic_equals_sentinel(self):
        basket = load_basket()
        panel_via_sentinel = indicators.build_indicator_panel(
            symbol="NVDA",
            as_of=basket["NVDA"].index[-1].date(),
            ohlcv_rows=basket["NVDA"].reset_index().to_dict(orient="records"),
            panel_config=PANEL_CLASSIC,
        )
        panel_via_construct = indicators.build_indicator_panel(
            symbol="NVDA",
            as_of=basket["NVDA"].index[-1].date(),
            ohlcv_rows=basket["NVDA"].reset_index().to_dict(orient="records"),
            panel_config=PanelConfig(panel="classic"),
        )
        assert panel_via_sentinel == panel_via_construct
