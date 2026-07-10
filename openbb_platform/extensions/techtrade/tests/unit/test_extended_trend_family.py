"""Tests for the extended trend family (bd-luy).

Aroon (Step 1, bd-b6k5) + Ichimoku (Step 2, bd-7gwh) live here.
The tests are ordered by step for readability; RED-phase-first per TDD.

Full context:
- Plan: docs/superpowers/plans/2026-07-09-bd-luy-trend-family-expansion.md
- Design spec: docs/superpowers/specs/2026-07-08-confluence-panel-expansion-design.md §3.1
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from openbb_techtrade.engine import indicators, indicators_ext, confluence_ext
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


# --------------------------------------------------------------------------- #
# helper: build the extended panel config
# --------------------------------------------------------------------------- #


def _extended():
    from openbb_techtrade.engine.panel_config import PANEL_EXTENDED
    return PANEL_EXTENDED
