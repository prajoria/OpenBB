"""Tests for the extended trend family (bd-luy).

Aroon (Step 1, bd-b6k5) + Ichimoku (Step 2, bd-7gwh) live here.
The tests are ordered by step for readability; RED-phase-first per TDD.

Full context:
- Plan: docs/superpowers/plans/2026-07-09-bd-luy-trend-family-expansion.md
- Design spec: docs/superpowers/specs/2026-07-08-confluence-panel-expansion-design.md §3.1
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from openbb_techtrade.engine import confluence, confluence_ext, indicators, indicators_ext
from openbb_techtrade.engine.indicators import DEFAULT_CONFIG

# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #


def _ohlcv_uptrend(n: int = 100) -> pd.DataFrame:
    """Deterministic uptrend fixture: strictly rising close 100 → 100 + 0.5·n."""
    import pandas_ta_classic  # noqa: F401 - registers .ta accessor

    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100.0 + np.arange(n) * 0.5
    df = pd.DataFrame(
        {
            "open": close - 0.5, "high": close + 1.0, "low": close - 1.0,
            "close": close, "volume": np.full(n, 1_000_000.0),
        },
        index=dates,
    )
    df.columns = [c.lower() for c in df.columns]
    return df


def _ohlcv_downtrend(n: int = 100) -> pd.DataFrame:
    """Deterministic downtrend fixture: strictly falling close."""
    import pandas_ta_classic  # noqa: F401

    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 200.0 - np.arange(n) * 0.5
    df = pd.DataFrame(
        {
            "open": close + 0.5, "high": close + 1.0, "low": close - 1.0,
            "close": close, "volume": np.full(n, 1_000_000.0),
        },
        index=dates,
    )
    df.columns = [c.lower() for c in df.columns]
    return df


# =========================================================================== #
# Step 1 — Aroon [bd-b6k5]
# =========================================================================== #


class TestAroonPanel:
    """Aroon Up/Down/Oscillator must appear in the extended trend panel."""

    def test_aroon_keys_populated_on_uptrend(self):
        df = _ohlcv_uptrend(100)
        result = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        for key in ("aroon_up", "aroon_down", "aroon_osc"):
            assert key in result, f"missing {key}; got keys: {sorted(result)}"
            assert np.isfinite(result[key]), f"{key} = {result[key]!r} not finite"

    def test_aroon_up_in_zero_to_hundred(self):
        df = _ohlcv_uptrend(100)
        result = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        assert 0.0 <= result["aroon_up"] <= 100.0
        assert 0.0 <= result["aroon_down"] <= 100.0

    def test_aroon_osc_in_signed_hundred(self):
        """Aroon oscillator is (Up − Down); bounded to [-100, +100]."""
        df = _ohlcv_uptrend(100)
        result = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        assert -100.0 <= result["aroon_osc"] <= 100.0

    def test_aroon_osc_positive_on_uptrend(self):
        """A strictly monotone uptrend puts the 25-bar high at the current
        bar (recency = 0), the 25-bar low 25 bars back (recency = 25).
        Aroon Up ≈ 100, Aroon Down ≈ 0, oscillator ≈ +100.

        R7.11 load-bearing: mutating `aroon_up - aroon_down` to
        `aroon_down - aroon_up` in the vote-mapper would flip this
        assertion via the downtrend test below."""
        df = _ohlcv_uptrend(100)
        result = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        assert result["aroon_osc"] > 50.0, (
            f"strict uptrend should show strongly positive Aroon oscillator; "
            f"got {result['aroon_osc']}"
        )

    def test_aroon_osc_negative_on_downtrend(self):
        df = _ohlcv_downtrend(100)
        result = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        assert result["aroon_osc"] < -50.0

    def test_aroon_absent_when_history_too_short(self):
        """Aroon(25) needs at least 25 bars for a finite reading. Under
        that, `df.ta.aroon()` returns NaN and the panel key is simply
        not populated (matches existing `_compute_trend` NaN-drop pattern)."""
        df = _ohlcv_uptrend(20)
        result = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        assert "aroon_osc" not in result or np.isfinite(result["aroon_osc"])


class TestAroonExtendedIncludesClassicKeys:
    """The extended trend panel is a SUPERSET of classic. Adding Aroon
    must not remove any classic key (would break bd-7ct.8 subset AC)."""

    def test_classic_keys_still_present(self):
        df = _ohlcv_uptrend(100)
        classic = indicators._compute_trend(df, DEFAULT_CONFIG)
        extended = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        for key in classic:
            assert key in extended, (
                f"classic key {key!r} missing from extended panel; "
                f"subset invariant broken"
            )

    def test_extended_has_more_keys(self):
        df = _ohlcv_uptrend(100)
        classic = indicators._compute_trend(df, DEFAULT_CONFIG)
        extended = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        assert len(extended) > len(classic), (
            f"extended must add keys; classic={len(classic)} "
            f"extended={len(extended)}"
        )


class TestAroonVote:
    """The trend-family vote-mapper emits an `aroon_osc` vote in [-1, +1]."""

    def _panel_from(self, df: pd.DataFrame):
        return indicators.build_indicator_panel(
            symbol="TEST",
            as_of=df.index[-1].date(),
            ohlcv_rows=df.reset_index(names="timestamp").to_dict(orient="records"),
            panel_config=_extended(),
        )

    def test_aroon_vote_emitted_on_extended_path(self):
        panel = self._panel_from(_ohlcv_uptrend(100))
        votes = confluence_ext.trend_votes_ext(panel)
        aroon_votes = [v for v in votes if v.name == "aroon_osc"]
        assert len(aroon_votes) == 1, (
            f"expected exactly one aroon_osc vote; got {len(aroon_votes)}"
        )

    def test_aroon_vote_positive_on_uptrend(self):
        panel = self._panel_from(_ohlcv_uptrend(100))
        votes = confluence_ext.trend_votes_ext(panel)
        aroon_vote = next(v for v in votes if v.name == "aroon_osc")
        assert aroon_vote.vote > 0.5, (
            f"strict uptrend should produce strongly-positive aroon vote; "
            f"got {aroon_vote.vote}"
        )

    def test_aroon_vote_negative_on_downtrend(self):
        panel = self._panel_from(_ohlcv_downtrend(100))
        votes = confluence_ext.trend_votes_ext(panel)
        aroon_vote = next(v for v in votes if v.name == "aroon_osc")
        assert aroon_vote.vote < -0.5

    def test_aroon_vote_bounded_in_signed_unit(self):
        panel = self._panel_from(_ohlcv_uptrend(100))
        votes = confluence_ext.trend_votes_ext(panel)
        aroon_vote = next(v for v in votes if v.name == "aroon_osc")
        assert -1.0 <= aroon_vote.vote <= 1.0

    def test_aroon_vote_family_is_trend(self):
        panel = self._panel_from(_ohlcv_uptrend(100))
        votes = confluence_ext.trend_votes_ext(panel)
        aroon_vote = next(v for v in votes if v.name == "aroon_osc")
        assert aroon_vote.family == "trend"

    def test_aroon_vote_absent_when_history_too_short(self):
        """No panel key → no vote emitted (graceful degrade).

        Uses 24 bars: below Aroon(25)'s lookback so the key is absent,
        but enough for classic panel construction. Verifies the vote-
        mapper handles a missing aroon_osc key by simply not emitting
        the vote."""
        panel = self._panel_from(_ohlcv_uptrend(24))
        assert "aroon_osc" not in panel.trend, (
            "test fixture assumption broken: 24-bar history should NOT "
            "have finite aroon_osc (Aroon length=25)"
        )
        votes = confluence_ext.trend_votes_ext(panel)
        aroon_votes = [v for v in votes if v.name == "aroon_osc"]
        assert aroon_votes == [], (
            f"aroon vote must not emit when panel key is absent; got {aroon_votes}"
        )


class TestAroonDeterminism:
    """Same OHLCV → same vote. Locks the design's determinism contract
    (design §3, 'votes-only narrative; no LLM; same panel + weights →
    same reasoning'). R7.11 mutation-verified: introducing cross-call
    state would flip this."""

    def test_run_twice_same_result(self):
        df = _ohlcv_uptrend(100)
        result_a = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        result_b = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        assert result_a == result_b


# =========================================================================== #
# Step 2 — Ichimoku Cloud [bd-7gwh]
# =========================================================================== #


def _ohlcv_flat_then_up(n_flat: int, n_up: int, base: float = 100.0) -> pd.DataFrame:
    """n_flat bars at `base`, then n_up bars rising by 0.5/bar.

    Used for Ichimoku confirmation-buffer tests: seeds the cloud level
    with a long flat period so the senkou spans stabilize at `base`,
    then breaks upward.
    """
    import pandas_ta_classic  # noqa: F401

    n = n_flat + n_up
    close = np.concatenate([
        np.full(n_flat, base),
        base + np.arange(1, n_up + 1) * 0.5,
    ])
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame(
        {
            "open": close - 0.1, "high": close + 0.2, "low": close - 0.2,
            "close": close, "volume": np.full(n, 1_000_000.0),
        },
        index=dates,
    )
    df.columns = [c.lower() for c in df.columns]
    return df


def _ohlcv_whipsaw(n_flat: int, spike_up_bars: int = 1) -> pd.DataFrame:
    """Long flat period, then a `spike_up_bars`-bar spike above cloud
    that STAYS above cloud for exactly `spike_up_bars` bars (no reversion).

    Discriminating fixture for the 3-bar-confirmation buffer:
    - Under N=1: last bar is above cloud → confirmed_position=+1.
    - Under N=3 and spike_up_bars < 3: last 3 bars are not all above
      cloud (earlier bars sat at cloud level) → confirmed_position != +1.

    This is what R7.11 (CLAUDE.md testing rule) requires: mutating the
    confirmation window must actually change the test outcome, not just
    coincidentally still pass because the fixture reverts to neutral."""
    import pandas_ta_classic  # noqa: F401

    close = np.concatenate([
        np.full(n_flat, 100.0),
        np.full(spike_up_bars, 120.0),
    ])
    n = len(close)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame(
        {
            "open": close - 0.1, "high": close + 0.2, "low": close - 0.2,
            "close": close, "volume": np.full(n, 1_000_000.0),
        },
        index=dates,
    )
    df.columns = [c.lower() for c in df.columns]
    return df


class TestIchimokuResultNormalization:
    """Support current pandas-ta-classic and legacy pandas-ta result shapes."""

    def test_accepts_direct_current_frame(self):
        """Use a direct current-value frame without discarding it."""
        current = pd.DataFrame({"ISA_9": [1.0], "ISB_26": [2.0]})
        assert indicators_ext._ichimoku_current_frame(current) is current

    def test_accepts_legacy_tuple_result(self):
        """Extract current values from the legacy two-frame tuple."""
        current = pd.DataFrame({"ISA_9": [1.0], "ISB_26": [2.0]})
        projection = pd.DataFrame({"ISA_9": [3.0], "ISB_26": [4.0]})
        assert indicators_ext._ichimoku_current_frame((current, projection)) is current

    @pytest.mark.parametrize("result", [None, ("invalid", object())])
    def test_rejects_unsupported_result(self, result):
        """Reject missing and non-frame current values."""
        assert indicators_ext._ichimoku_current_frame(result) is None


class TestIchimokuPanel:
    """Ichimoku panel keys: raw single-bar `ichimoku_price_vs_cloud` (audit)
    AND 3-bar-confirmed `ichimoku_confirmed_position` (vote input)."""

    def test_ichimoku_key_populated_when_history_sufficient(self):
        df = _ohlcv_uptrend(200)
        result = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        assert "ichimoku_price_vs_cloud" in result, (
            f"200-bar history should populate ichimoku_price_vs_cloud; "
            f"got keys: {sorted(result)}"
        )
        assert "ichimoku_confirmed_position" in result

    def test_ichimoku_key_absent_when_history_too_short(self):
        """Ichimoku needs 52 + 26 = 78 bars minimum (senkou span B lookback
        of 52 plus 26-bar forward displacement). Under 78 bars, both keys
        must be absent (graceful degrade per §10 M4)."""
        df = _ohlcv_uptrend(40)
        result = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        assert "ichimoku_price_vs_cloud" not in result
        assert "ichimoku_confirmed_position" not in result

    def test_ichimoku_price_vs_cloud_positive_on_uptrend(self):
        """Strong uptrend puts price above both senkou spans → +1."""
        df = _ohlcv_uptrend(200)
        result = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        assert result["ichimoku_price_vs_cloud"] == 1.0

    def test_ichimoku_price_vs_cloud_negative_on_downtrend(self):
        df = _ohlcv_downtrend(200)
        result = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        assert result["ichimoku_price_vs_cloud"] == -1.0

    def test_ichimoku_confirmed_position_matches_raw_on_stable_trend(self):
        """After 3+ consecutive same-sign bars, the confirmed position
        equals the raw position."""
        df = _ohlcv_uptrend(200)
        result = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        assert result["ichimoku_confirmed_position"] == result["ichimoku_price_vs_cloud"]


class TestIchimokuVote:
    """The trend-family vote-mapper emits an `ichimoku_cloud` vote in [-1, +1]
    reading from `ichimoku_confirmed_position`.

    **bd-hpxh (2026-07-11) note:** the ship config excludes ichimoku_cloud
    from the default vote list due to ρ=0.839 with ema_cross. These tests
    verify the vote MECHANICS work correctly by opting Ichimoku in
    explicitly via ``enabled_extended_votes``. The mechanics are still
    load-bearing for R&D / backtest callers that opt in — they must get
    the same value contract they'd have gotten pre-bd-hpxh."""

    #: bd-hpxh: opt-in for tests that need to verify Ichimoku vote mechanics
    _WITH_ICHIMOKU = frozenset({"aroon_osc", "ichimoku_cloud"})

    def _panel_from(self, df: pd.DataFrame):
        return indicators.build_indicator_panel(
            symbol="TEST",
            as_of=df.index[-1].date(),
            ohlcv_rows=df.reset_index(names="timestamp").to_dict(orient="records"),
            panel_config=_extended(),
        )

    def test_ichimoku_vote_absent_when_key_absent(self):
        panel = self._panel_from(_ohlcv_uptrend(40))
        # Even with Ichimoku opted in, absent panel key → no vote emitted.
        votes = confluence_ext.trend_votes_ext(
            panel, enabled_extended_votes=self._WITH_ICHIMOKU,
        )
        assert [v for v in votes if v.name == "ichimoku_cloud"] == []

    def test_ichimoku_vote_positive_on_sustained_uptrend(self):
        panel = self._panel_from(_ohlcv_uptrend(200))
        votes = confluence_ext.trend_votes_ext(
            panel, enabled_extended_votes=self._WITH_ICHIMOKU,
        )
        vote = next(v for v in votes if v.name == "ichimoku_cloud")
        assert vote.vote == 1.0

    def test_ichimoku_vote_negative_on_sustained_downtrend(self):
        panel = self._panel_from(_ohlcv_downtrend(200))
        votes = confluence_ext.trend_votes_ext(
            panel, enabled_extended_votes=self._WITH_ICHIMOKU,
        )
        vote = next(v for v in votes if v.name == "ichimoku_cloud")
        assert vote.vote == -1.0

    def test_ichimoku_vote_bounded_in_signed_unit(self):
        panel = self._panel_from(_ohlcv_uptrend(200))
        votes = confluence_ext.trend_votes_ext(
            panel, enabled_extended_votes=self._WITH_ICHIMOKU,
        )
        vote = next(v for v in votes if v.name == "ichimoku_cloud")
        assert -1.0 <= vote.vote <= 1.0

    def test_ichimoku_vote_family_is_trend(self):
        panel = self._panel_from(_ohlcv_uptrend(200))
        votes = confluence_ext.trend_votes_ext(
            panel, enabled_extended_votes=self._WITH_ICHIMOKU,
        )
        vote = next(v for v in votes if v.name == "ichimoku_cloud")
        assert vote.family == "trend"


class TestIchimokuConfirmationBuffer:
    """3-bar confirmation buffer (§R.4 M3): a 1-bar or 2-bar spike above/
    below the cloud must NOT flip the vote. Only 3 consecutive same-side
    bars produce a flip.

    R7.11 load-bearing: mutating _ICHIMOKU_CONFIRMATION_BARS from 3 to 1
    must make `test_confirmed_position_ignores_single_bar_whipsaw` fail
    (because then a 1-bar spike WOULD flip the confirmed position)."""

    def test_confirmation_constant_is_three(self):
        """The constant is load-bearing for the confirmation window
        semantics; enforcing its value here catches accidental drift."""
        assert indicators_ext._ICHIMOKU_CONFIRMATION_BARS == 3

    def test_confirmed_position_ignores_single_bar_whipsaw(self):
        """80 bars flat at 100, then 1 bar at 120 (above cloud). The
        last-bar RAW position is +1 (price above cloud). But the 3-bar
        confirmed position must NOT be +1 — only the final bar is above
        cloud; the two prior bars were AT cloud level (raw position = 0).

        R7.11 mutation-verified: under _ICHIMOKU_CONFIRMATION_BARS=1
        the confirmed position WOULD be +1 (identical to raw); under
        =3 it must be != +1 (0 by the neutral-default rule)."""
        df = _ohlcv_whipsaw(n_flat=80, spike_up_bars=1)
        result = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        # Raw position on final bar should be +1 (price=120 > cloud=100)
        assert result.get("ichimoku_price_vs_cloud") == 1.0, (
            f"fixture pre-check: raw position should be +1; "
            f"got {result.get('ichimoku_price_vs_cloud')}"
        )
        # Confirmed position must NOT be +1 — one bar isn't enough
        assert result.get("ichimoku_confirmed_position") != 1.0, (
            f"1-bar whipsaw should not confirm a +1 flip under 3-bar buffer; "
            f"got confirmed_position={result.get('ichimoku_confirmed_position')} "
            f"(this test is R7.11 load-bearing — mutating "
            f"_ICHIMOKU_CONFIRMATION_BARS from 3 to 1 must make this fail)"
        )


class TestIchimokuDeterminism:
    """Same OHLCV → same Ichimoku output. Locks the purity contract."""

    def test_ichimoku_run_twice_same_result(self):
        df = _ohlcv_uptrend(200)
        a = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        b = indicators_ext._compute_trend_ext(df, DEFAULT_CONFIG)
        assert a == b


# --------------------------------------------------------------------------- #
# helper: build the extended panel config
# --------------------------------------------------------------------------- #


def _extended():
    from openbb_techtrade.engine.panel_config import PANEL_EXTENDED
    return PANEL_EXTENDED


# =========================================================================== #
# bd-hpxh — configurable ship-enabled extended trend votes
# =========================================================================== #
#
# Decision: Ichimoku vote drops from the SHIP config (correlation 0.839 vs
# ema_cross exceeded §R.4 M4 ceiling of 0.70). Panel keys still emit so R&D /
# audit code can read the raw Ichimoku signal. A caller can opt Ichimoku back
# into the vote list explicitly for backtests / IC studies.


class TestBdHpxhShipConfigDropsIchimokuVote:
    """The ship config emits `aroon_osc` but NOT `ichimoku_cloud`.
    Panel keys for Ichimoku are still populated for audit."""

    def _panel_from(self, df: pd.DataFrame):
        return indicators.build_indicator_panel(
            symbol="TEST",
            as_of=df.index[-1].date(),
            ohlcv_rows=df.reset_index(names="timestamp").to_dict(orient="records"),
            panel_config=_extended(),
        )

    def test_default_ship_config_omits_ichimoku_vote(self):
        """Default call to trend_votes_ext (no override) must NOT emit an
        ichimoku_cloud vote — even when the panel key is populated
        (which it is on the 200-bar fixture).

        R7.11 load-bearing: mutating SHIP_ENABLED_EXTENDED_TREND_VOTES
        to include 'ichimoku_cloud' would make this test fail."""
        panel = self._panel_from(_ohlcv_uptrend(200))
        # Precondition: panel key IS populated (otherwise the test can't
        # distinguish "skipped by ship config" from "no key to work with").
        assert panel.trend.get("ichimoku_confirmed_position") is not None, (
            "fixture invariant broken: 200-bar uptrend should populate "
            "ichimoku_confirmed_position"
        )
        votes = confluence_ext.trend_votes_ext(panel)
        ichimoku_votes = [v for v in votes if v.name == "ichimoku_cloud"]
        assert ichimoku_votes == [], (
            f"bd-hpxh: ship config must NOT emit ichimoku_cloud vote "
            f"(ρ=0.839 vs ema_cross exceeds §R.4 M4 gate of 0.70). "
            f"Got: {[v.name for v in votes]}"
        )

    def test_default_ship_config_still_emits_aroon(self):
        """Aroon is in the ship config — trend_votes_ext must still emit it."""
        panel = self._panel_from(_ohlcv_uptrend(200))
        votes = confluence_ext.trend_votes_ext(panel)
        aroon_votes = [v for v in votes if v.name == "aroon_osc"]
        assert len(aroon_votes) == 1, (
            f"aroon_osc must still emit in ship config; got: "
            f"{[v.name for v in votes]}"
        )

    def test_ichimoku_panel_keys_still_populated_for_audit(self):
        """The vote is skipped but the panel keys are UNCHANGED — R&D
        code, notebooks, and manual audits can still read
        ichimoku_price_vs_cloud and ichimoku_confirmed_position."""
        panel = self._panel_from(_ohlcv_uptrend(200))
        assert "ichimoku_price_vs_cloud" in panel.trend, (
            "bd-hpxh: panel key ichimoku_price_vs_cloud must still be "
            "populated even when the vote is skipped from ship config"
        )
        assert "ichimoku_confirmed_position" in panel.trend
        # And the values are real signals, not zeros
        assert panel.trend["ichimoku_price_vs_cloud"] == 1.0
        assert panel.trend["ichimoku_confirmed_position"] == 1.0


class TestBdHpxhOverrideCapability:
    """Callers can override the ship config via `enabled_extended_votes`.
    Two use cases: (1) R&D backtest that WANTS ichimoku_cloud in the vote
    list to measure incremental IC, (2) study that WANTS only ichimoku
    (drop aroon_osc for a single-signal isolation test)."""

    def _panel_from(self, df: pd.DataFrame):
        return indicators.build_indicator_panel(
            symbol="TEST",
            as_of=df.index[-1].date(),
            ohlcv_rows=df.reset_index(names="timestamp").to_dict(orient="records"),
            panel_config=_extended(),
        )

    def test_override_can_opt_in_ichimoku(self):
        """Backtest override adds ichimoku_cloud back to the vote list
        alongside aroon_osc. Both extended votes emit; classic votes
        still emit unchanged."""
        panel = self._panel_from(_ohlcv_uptrend(200))
        votes = confluence_ext.trend_votes_ext(
            panel,
            enabled_extended_votes=frozenset({"aroon_osc", "ichimoku_cloud"}),
        )
        vote_names = [v.name for v in votes]
        assert "aroon_osc" in vote_names
        assert "ichimoku_cloud" in vote_names, (
            f"opt-in override must include ichimoku_cloud; got {vote_names}"
        )

    def test_override_can_isolate_ichimoku_only(self):
        """Study override includes only ichimoku_cloud (no aroon_osc).
        The extended votes list contains ichimoku_cloud, not aroon_osc.
        Classic votes are unaffected — override only touches the
        extended (bd-luy-added) vote set."""
        panel = self._panel_from(_ohlcv_uptrend(200))
        votes = confluence_ext.trend_votes_ext(
            panel,
            enabled_extended_votes=frozenset({"ichimoku_cloud"}),
        )
        vote_names = [v.name for v in votes]
        assert "ichimoku_cloud" in vote_names
        assert "aroon_osc" not in vote_names, (
            f"isolation override must exclude aroon_osc; got {vote_names}"
        )

    def test_override_with_empty_set_yields_only_classic_votes(self):
        """Extreme override: empty extended set → only classic votes emit.
        Useful for a pure-classic baseline run under PANEL_EXTENDED config."""
        panel = self._panel_from(_ohlcv_uptrend(200))
        votes = confluence_ext.trend_votes_ext(
            panel,
            enabled_extended_votes=frozenset(),  # nothing extended
        )
        classic_votes = list(confluence.trend_votes(panel))
        assert [v.name for v in votes] == [v.name for v in classic_votes], (
            f"empty override must equal classic votes; got extended="
            f"{[v.name for v in votes]}, classic={[v.name for v in classic_votes]}"
        )

    def test_override_none_uses_ship_config(self):
        """Passing enabled_extended_votes=None (or omitting it) uses the
        default SHIP_ENABLED_EXTENDED_TREND_VOTES — same as no kwarg."""
        panel = self._panel_from(_ohlcv_uptrend(200))
        default_votes = confluence_ext.trend_votes_ext(panel)
        none_votes = confluence_ext.trend_votes_ext(
            panel, enabled_extended_votes=None,
        )
        assert [v.name for v in default_votes] == [v.name for v in none_votes], (
            "enabled_extended_votes=None must equal default (ship config)"
        )


class TestBdHpxhShipConfigConstant:
    """The ship config is a load-bearing module-level constant. Its value
    documents the bd-hpxh decision in code (Ichimoku out, Aroon in) so a
    future reader can trace the semantic through git-blame back to this bead."""

    def test_ship_config_is_frozenset(self):
        """Immutable to prevent runtime mutation defeating the ship gate."""
        assert isinstance(
            confluence_ext.SHIP_ENABLED_EXTENDED_TREND_VOTES, frozenset
        ), "ship config must be a frozenset for immutability"

    def test_ship_config_includes_aroon_osc(self):
        """Aroon shipped in bd-b6k5, passed decorrelation gate."""
        assert "aroon_osc" in confluence_ext.SHIP_ENABLED_EXTENDED_TREND_VOTES

    def test_ship_config_excludes_ichimoku_cloud(self):
        """bd-hpxh: Ichimoku is EXCLUDED from ship config pending decorrelation
        resolution. Adding it back requires either resolving the ρ=0.839
        overlap with ema_cross (drop ema_cross, reweight, etc.) OR an
        explicit design-doc waiver.

        R7.11 load-bearing: this test would flip if someone adds
        'ichimoku_cloud' to SHIP_ENABLED_EXTENDED_TREND_VOTES without
        addressing bd-hpxh. The failure message points them at this bead."""
        assert "ichimoku_cloud" not in confluence_ext.SHIP_ENABLED_EXTENDED_TREND_VOTES, (
            "bd-hpxh (2026-07-11): ichimoku_cloud excluded from ship config "
            "due to |Spearman ρ| = 0.839 with ema_cross on 5y basket (above "
            "§R.4 M4 gate of 0.70). Panel keys still emit for audit. Adding "
            "back requires resolving the decorrelation violation first."
        )
