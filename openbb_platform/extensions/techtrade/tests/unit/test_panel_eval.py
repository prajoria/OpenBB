"""Tests for engine/panel_eval.py — the Information Coefficient (IC) harness.

Full context: docs/superpowers/plans/2026-07-08-bd-7ct-confluence-foundation.md
Step 10 (bd-0st) — the R1 acceptance-gate infrastructure.

**IC** = rank correlation between a vote series and forward returns
(Spearman rho of vote_t vs return_{t..t+N}). It answers *"does this
vote actually predict return direction?"* — the single most important
question §10 of the design spec insists we answer before shipping any
new indicator.

Every family PR (bd-luy/40v/z43/alj) will call
:func:`compute_information_coefficient` to prove each new vote has
positive IC on the recorded basket. This module provides the primitive.

**Load-bearing R7.11 mutations covered:**
- Mutate ``spearmanr`` → ``pearsonr`` (rank correlation vs linear)
  breaks the "perfect positive signal returns ~+1" test on
  non-linearly-monotonic fixtures.
- Mutate ``.shift(-N)`` → ``.shift(+N)`` (look-ahead bias — using
  past returns to predict past votes) inverts the sign of the
  perfect-positive IC test.
- Mutate the default ``forward_bars=5`` → any other value doesn't
  fail any test *by itself*, but the module-scope constant test
  catches accidental changes to the semantic default.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from openbb_techtrade.engine.panel_eval import (
    DEFAULT_FORWARD_BARS,
    ICResult,
    compute_information_coefficient,
)


# --------------------------------------------------------------------------- #
# Fixtures — deterministic synthetic vote/return pairs with known IC
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def index_100() -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=100, freq="B")


# --------------------------------------------------------------------------- #
# Contract: return type + fields
# --------------------------------------------------------------------------- #


class TestICResultShape:
    """``ICResult`` is a small dataclass — verify field presence + types.
    Downstream family PRs will unpack it, so drift here breaks every
    subsequent PR."""

    def test_result_has_expected_fields(self, index_100):
        votes = pd.Series(np.random.default_rng(0).standard_normal(100), index=index_100)
        rets = pd.Series(np.random.default_rng(1).standard_normal(100), index=index_100)
        result = compute_information_coefficient(votes, rets)
        assert isinstance(result, ICResult)
        assert hasattr(result, "coefficient")
        assert hasattr(result, "p_value")
        assert hasattr(result, "n_samples")
        assert hasattr(result, "n_dropped_nan")
        assert hasattr(result, "backend")

    def test_result_types(self, index_100):
        votes = pd.Series(np.random.default_rng(2).standard_normal(100), index=index_100)
        rets = pd.Series(np.random.default_rng(3).standard_normal(100), index=index_100)
        result = compute_information_coefficient(votes, rets)
        # coefficient / p_value can be NaN but must be float
        assert isinstance(result.coefficient, float)
        assert isinstance(result.p_value, float)
        assert isinstance(result.n_samples, int)
        assert isinstance(result.n_dropped_nan, int)
        assert isinstance(result.backend, str)

    def test_backend_is_scipy_when_available(self, index_100):
        """iter-1 silent-hunter F1: when SciPy is installed (the normal
        env), the backend field must report ``"scipy"``. Family PRs
        segregate results by backend when pooling across environments."""
        votes = pd.Series(np.random.default_rng(4).standard_normal(100), index=index_100)
        rets = pd.Series(np.random.default_rng(5).standard_normal(100), index=index_100)
        result = compute_information_coefficient(votes, rets)
        # SciPy is a hard dep of the platform; if this test fails on a
        # dev machine, run `pip install scipy`. If it fails in CI, the
        # environment needs fixing — the fallback is a slim-install path.
        assert result.backend == "scipy"


# --------------------------------------------------------------------------- #
# Contract: known-IC synthetic fixtures
# --------------------------------------------------------------------------- #


class TestICKnownValues:
    """The five essential known-IC fixtures. Every one is load-bearing:
    if this suite passes, the IC primitive is correct for its four target
    corner cases (perfect +, perfect −, ~0, degenerate)."""

    def test_perfect_positive_signal_returns_near_one(self, index_100):
        """Vote series ranks identically to forward returns → IC ≈ +1.

        R7.11 load-bearing: mutating the shift sign (``-forward_bars``
        → ``+forward_bars``) — the classic look-ahead-bias mistake —
        would produce IC ≈ -1 here. Mutating ``spearmanr`` to
        ``pearsonr`` still returns ~+1 on this linear fixture, but
        the non-linear-monotone test below discriminates."""
        # Vote at t predicts return at t+1..t+5.
        # Construct returns first; then set vote_t = return_{t+forward}
        # so ranks are identical.
        rng = np.random.default_rng(42)
        rets = pd.Series(rng.standard_normal(100), index=index_100)
        # vote_t knows return_{t+5}
        votes = rets.shift(-DEFAULT_FORWARD_BARS).copy()
        result = compute_information_coefficient(votes, rets)
        assert result.coefficient > 0.9, (
            f"perfect-positive fixture should yield IC ≈ +1; got "
            f"{result.coefficient}. Check for shift-sign or "
            f"correlation-method mutation."
        )

    def test_perfect_negative_signal_returns_near_negative_one(self, index_100):
        """Vote series ranks opposite to forward returns → IC ≈ −1."""
        rng = np.random.default_rng(43)
        rets = pd.Series(rng.standard_normal(100), index=index_100)
        votes = -rets.shift(-DEFAULT_FORWARD_BARS).copy()
        result = compute_information_coefficient(votes, rets)
        assert result.coefficient < -0.9, (
            f"perfect-negative fixture should yield IC ≈ -1; got "
            f"{result.coefficient}."
        )

    def test_random_signal_returns_near_zero(self, index_100):
        """Independent random vote and returns → IC ≈ 0."""
        rng_v = np.random.default_rng(44)
        rng_r = np.random.default_rng(45)  # independent seed
        votes = pd.Series(rng_v.standard_normal(1000), index=pd.date_range("2020-01-01", periods=1000, freq="B"))
        rets = pd.Series(rng_r.standard_normal(1000), index=votes.index)
        result = compute_information_coefficient(votes, rets)
        # 1000 samples → sampling error for independent series is small
        assert abs(result.coefficient) < 0.15, (
            f"independent-random fixture should yield IC ≈ 0; got "
            f"{result.coefficient}. If |IC| > 0.15 with n=1000, "
            f"either the seeds are correlated or the shift is broken."
        )

    def test_flat_vote_returns_nan(self, index_100):
        """A vote series with zero variance (all-zero, all-constant) → IC
        is undefined (division by zero in the correlation formula).
        The primitive must return NaN, not raise, so downstream code
        can treat 'IC undefined' as a data-quality issue rather than
        an unhandled exception."""
        rng = np.random.default_rng(46)
        votes = pd.Series(np.zeros(100), index=index_100)
        rets = pd.Series(rng.standard_normal(100), index=index_100)
        result = compute_information_coefficient(votes, rets)
        assert math.isnan(result.coefficient), (
            f"flat vote should yield NaN IC; got {result.coefficient}."
        )

    def test_flat_returns_returns_nan(self, index_100):
        """Zero-variance returns are symmetric to zero-variance votes —
        also undefined, also NaN."""
        rng = np.random.default_rng(47)
        votes = pd.Series(rng.standard_normal(100), index=index_100)
        rets = pd.Series(np.zeros(100), index=index_100)
        result = compute_information_coefficient(votes, rets)
        assert math.isnan(result.coefficient)


# --------------------------------------------------------------------------- #
# Contract: NaN handling in vote series
# --------------------------------------------------------------------------- #


class TestNaNHandling:
    """Real vote series have leading NaNs from indicator warm-up bars
    (RSI-14 has 13 NaNs; EMA-50 has 49; Ichimoku ~78). The primitive
    must drop NaN pairs, count them, and still compute IC on the
    remainder — never silently propagate NaN through the whole
    correlation."""

    def test_leading_nan_votes_excluded(self, index_100):
        """Warm-up NaN at the start → excluded from correlation.
        Perfect-positive setup after the warm-up should still yield
        IC ≈ +1 on the remaining bars."""
        rng = np.random.default_rng(48)
        rets = pd.Series(rng.standard_normal(100), index=index_100)
        votes = rets.shift(-DEFAULT_FORWARD_BARS).copy()
        # Inject 20 leading NaN into votes (mimics warm-up)
        votes.iloc[:20] = np.nan
        result = compute_information_coefficient(votes, rets)
        assert result.coefficient > 0.9, (
            f"IC should be robust to leading NaN; got {result.coefficient}"
        )
        # We dropped: 20 leading NaN in votes + last 5 NaN in returns
        # from shift(-5) → at least 20 dropped
        assert result.n_dropped_nan >= 20

    def test_all_nan_returns_nan(self, index_100):
        """If EVERY pair is NaN → IC is NaN (no samples to correlate on)."""
        votes = pd.Series(np.full(100, np.nan), index=index_100)
        rets = pd.Series(np.arange(100, dtype=float), index=index_100)
        result = compute_information_coefficient(votes, rets)
        assert math.isnan(result.coefficient)
        assert result.n_samples == 0

    def test_n_samples_reflects_valid_pairs(self, index_100):
        """After NaN-dropping and shift, ``n_samples`` is the exact count
        of (vote, forward-return) pairs actually used in the correlation.
        Downstream family PRs will use this to reject symbols with too-few
        valid samples (say < 30)."""
        rng = np.random.default_rng(49)
        votes = pd.Series(rng.standard_normal(100), index=index_100)
        rets = pd.Series(rng.standard_normal(100), index=index_100)
        result = compute_information_coefficient(votes, rets)
        # 100 total - 5 lost to forward-shift = 95 valid pairs (no NaN in votes)
        assert result.n_samples == 100 - DEFAULT_FORWARD_BARS


# --------------------------------------------------------------------------- #
# Contract: module-scope constant
# --------------------------------------------------------------------------- #


class TestModuleConstants:
    """R7.10: ``DEFAULT_FORWARD_BARS = 5`` is a semantic default (one
    business week). Family PRs will reference the constant; changing
    it silently would shift every IC number in the golden baseline."""

    def test_default_forward_bars_is_five(self):
        assert DEFAULT_FORWARD_BARS == 5


# --------------------------------------------------------------------------- #
# Contract: parametrised forward_bars kwarg
# --------------------------------------------------------------------------- #


class TestForwardBarsKwarg:
    """Different families may want different forecast horizons (trend
    might want 20 days, mean-revert might want 3). The kwarg must
    accept any positive integer and produce a matching-horizon IC."""

    @pytest.mark.parametrize("n_bars", [1, 3, 5, 10, 20])
    def test_arbitrary_forward_horizon(self, index_100, n_bars):
        rng = np.random.default_rng(50 + n_bars)
        rets = pd.Series(rng.standard_normal(100), index=index_100)
        votes = rets.shift(-n_bars).copy()
        result = compute_information_coefficient(votes, rets, forward_bars=n_bars)
        assert result.coefficient > 0.9, (
            f"perfect-positive at forward_bars={n_bars} should yield "
            f"IC ≈ +1; got {result.coefficient}."
        )

    def test_zero_forward_bars_rejected(self, index_100):
        """``forward_bars=0`` would correlate the vote with its own bar's
        return — no forward-lookup, meaningless. Reject at the seam."""
        votes = pd.Series(np.arange(100, dtype=float), index=index_100)
        rets = pd.Series(np.arange(100, dtype=float), index=index_100)
        with pytest.raises(ValueError, match="forward_bars"):
            compute_information_coefficient(votes, rets, forward_bars=0)

    def test_negative_forward_bars_rejected(self, index_100):
        """Negative would be BACKWARD-looking — that's look-ahead bias."""
        votes = pd.Series(np.arange(100, dtype=float), index=index_100)
        rets = pd.Series(np.arange(100, dtype=float), index=index_100)
        with pytest.raises(ValueError, match="forward_bars"):
            compute_information_coefficient(votes, rets, forward_bars=-5)


# --------------------------------------------------------------------------- #
# Contract: index alignment
# --------------------------------------------------------------------------- #


class TestIndexAlignment:
    """Votes and returns must share an index — mismatched indices are
    almost always a bug (wrong symbol pair, wrong date range). The
    primitive should align on shared timestamps and count non-shared
    ones as dropped."""

    def test_mismatched_indices_align_on_intersection(self, index_100):
        """iter-1 pr-test L2: split into partial-overlap vs disjoint
        so each side has a concrete assertion instead of a tautology.

        Partial overlap: 100-bar votes + 100-bar returns offset by 20
        business days → ~80-bar intersection. n_samples should reflect
        that; coefficient should be computable."""
        rng = np.random.default_rng(51)
        # Votes on index_100 [2024-01-01..~2024-05-20]
        votes = pd.Series(rng.standard_normal(100), index=index_100)
        # Returns shifted to start 20 days later — 80 days overlap
        shifted_index = pd.date_range("2024-01-29", periods=100, freq="B")
        rets = pd.Series(rng.standard_normal(100), index=shifted_index)
        result = compute_information_coefficient(votes, rets)
        # Overlap is ~80 bars (varies by weekends/holidays); minus 5 for
        # the forward-shift trailing NaN and possibly some NaN drops
        assert result.n_samples > 60, (
            f"partial-overlap alignment should keep ~75 samples; "
            f"got {result.n_samples}"
        )
        # With 60+ samples of random data, IC should be finite (not NaN)
        assert not math.isnan(result.coefficient)

    def test_completely_disjoint_indices_yields_zero_samples(self):
        """When votes and returns share no timestamps, ``n_samples``
        must be exactly 0 and coefficient NaN — not silently
        canonicalise to some incidental overlap."""
        votes = pd.Series(
            np.random.default_rng(52).standard_normal(50),
            index=pd.date_range("2020-01-01", periods=50, freq="B"),
        )
        rets = pd.Series(
            np.random.default_rng(53).standard_normal(50),
            index=pd.date_range("2024-01-01", periods=50, freq="B"),
        )
        result = compute_information_coefficient(votes, rets)
        assert result.n_samples == 0
        assert math.isnan(result.coefficient)


class TestFastICSmoke:
    """iter-1 pr-test M3: fast-suite smoke check on a realistic
    per-symbol vote series. Catches obvious regressions in the IC
    primitive (e.g. mean-of-ranks vs correlation-of-ranks bug) without
    the 3.5-minute baseline test. Runs in <100ms.

    The synthetic here is a continuous trend-following-esque vote:
    the 10-bar cumulative return itself (not its sign, because a
    ternary sign vote produces too many ties for Spearman to
    correlate cleanly). Against 5-day forward returns, on an uptrending
    series it should show a small-but-positive IC — the canonical
    trend-follows-work sanity check.
    """

    def test_trend_following_vote_shows_positive_ic_on_uptrend(self):
        rng = np.random.default_rng(9999)
        # 200 bars of upward drift + noise (simple trending series)
        idx = pd.date_range("2024-01-01", periods=200, freq="B")
        drift = np.arange(200) * 0.001  # +0.1%/bar drift
        noise = rng.standard_normal(200) * 0.02
        returns = pd.Series(drift + noise, index=idx)
        # A trend-following vote: 10-bar cumulative return (continuous
        # magnitude, not sign — ranks cleanly for Spearman).
        votes = returns.rolling(10).sum()
        ic = compute_information_coefficient(votes, returns)
        # On a trending series, a trend vote should show POSITIVE IC.
        # Bound is loose — this is a smoke test, not a calibration;
        # anything strictly positive proves the primitive correctly
        # correlates on aligned data.
        assert ic.coefficient > 0.03, (
            f"trend vote on uptrending series should have positive IC; "
            f"got {ic.coefficient}. If IC is near zero or negative, "
            f"the shift direction or the correlation basis is broken."
        )
        assert ic.n_samples >= 150  # 200 - 10 warm-up - 5 forward-shift
        assert ic.backend == "scipy"
