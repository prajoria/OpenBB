"""Unit tests for ``validation/stats.py`` (component 08, §2 overfitting stats).

Covers the three Bailey & López de Prado closed-form, pure-scalar statistics —
:func:`probabilistic_sharpe` (PSR), :func:`deflated_sharpe` (DSR), and
:func:`min_backtest_length` (MinBTL) — re-implemented from the public papers
(*The Sharpe Ratio Efficient Frontier*, 2012; *The Deflated Sharpe Ratio*, 2014;
*Pseudo-Mathematics and Financial Charlatanism*, 2014). No ``mlfinlab`` (its
Commons-Clause license is restricted), so these tests pin the behavioural
contract — exact anchors, monotonicity, the ``N=1`` reduction, the expected-max
bracket, input validation and determinism — directly against the literature.

Anchor note: the canonical PSR variance uses Lo's ``(γ4 − 1)/4`` higher-moment
term, so for a *normal* return stream (skew 0, kurtosis 3) ``PSR(0.5,…,n=25)``
is ``≈ 0.98954`` (the Lo ``+½·SR²`` inflation is retained), not the
Gaussian-baseline ``0.9928`` an implementation gets by dropping that term.

See ``docs/designs/backtest-design/08-validation.md`` §2.
"""

from __future__ import annotations

import math
import subprocess
import sys
import textwrap

import numpy as np
import pytest

_BACKTEST_ROOT = __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.dirname(__file__))
)


def _normal_psr_args(sr: float = 0.5, n: int = 25) -> tuple:
    """Args tuple for a *normal* return stream: ``(sr, 0, skew=0, kurt=3, n)``."""
    return (sr, 0.0, 0.0, 3.0, n)


# ---- PSR: anchors --------------------------------------------------------


def test_psr_is_one_half_when_observed_equals_benchmark():
    from openbb_backtest.validation.stats import probabilistic_sharpe

    # SR̂ == SR* ⇒ numerator 0 ⇒ Φ(0) == 0.5 exactly, for any moments/length.
    assert probabilistic_sharpe(0.0, 0.0, 0.0, 3.0, 25) == 0.5
    assert probabilistic_sharpe(0.7, 0.7, -1.2, 9.0, 250) == 0.5


def test_psr_canonical_normal_anchor():
    from openbb_backtest.validation.stats import probabilistic_sharpe

    # Canonical Lo/Bailey–LdP value with the (γ4−1)/4 term (normal: skew0 kurt3):
    #   z = 0.5·√24 / √(1 + ½·0.25) = 2.30940 ⇒ Φ(z) = 0.98954.
    # (The bead's ~0.9928 anchor drops Lo's +½·SR² normal inflation.)
    assert probabilistic_sharpe(*_normal_psr_args(0.5, 25)) == pytest.approx(
        0.98954, abs=1e-4
    )


# ---- PSR: monotonicity ---------------------------------------------------


def test_psr_increases_with_observed_sharpe():
    from openbb_backtest.validation.stats import probabilistic_sharpe

    lo = probabilistic_sharpe(*_normal_psr_args(0.4, 25))
    hi = probabilistic_sharpe(*_normal_psr_args(0.6, 25))
    assert hi > lo


def test_psr_increases_with_sample_length():
    from openbb_backtest.validation.stats import probabilistic_sharpe

    short = probabilistic_sharpe(*_normal_psr_args(0.5, 25))
    long = probabilistic_sharpe(*_normal_psr_args(0.5, 100))
    assert long > short


def test_psr_increases_with_skewness():
    from openbb_backtest.validation.stats import probabilistic_sharpe

    # Positive skew shrinks the variance term ⇒ larger z ⇒ higher PSR.
    neg = probabilistic_sharpe(0.5, 0.0, -0.5, 3.0, 25)
    pos = probabilistic_sharpe(0.5, 0.0, 0.5, 3.0, 25)
    assert pos > neg


def test_psr_decreases_with_kurtosis():
    from openbb_backtest.validation.stats import probabilistic_sharpe

    # Fatter tails inflate the variance term ⇒ smaller z ⇒ lower PSR.
    thin = probabilistic_sharpe(0.5, 0.0, 0.0, 3.0, 25)
    fat = probabilistic_sharpe(0.5, 0.0, 0.0, 8.0, 25)
    assert fat < thin


# ---- PSR: validation + determinism ---------------------------------------


def test_psr_rejects_too_few_observations():
    from openbb_backtest.validation.stats import probabilistic_sharpe

    with pytest.raises(ValueError):
        probabilistic_sharpe(0.5, 0.0, 0.0, 3.0, 1)


def test_psr_rejects_degenerate_variance_term():
    from openbb_backtest.validation.stats import probabilistic_sharpe

    # 1 − skew·SR + (kurt−1)/4·SR² = 1 − 5·2 + ½·4 = −7 ⇒ non-positive variance.
    with pytest.raises(ValueError):
        probabilistic_sharpe(2.0, 0.0, 5.0, 3.0, 25)


def test_psr_is_deterministic():
    from openbb_backtest.validation.stats import probabilistic_sharpe

    a = probabilistic_sharpe(0.5, 0.1, 0.3, 4.0, 60)
    b = probabilistic_sharpe(0.5, 0.1, 0.3, 4.0, 60)
    assert a == b


# ---- DSR: reduction, monotonicity, expected-max bracket ------------------


def test_dsr_with_one_trial_reduces_to_psr_at_zero_benchmark():
    from openbb_backtest.validation.stats import deflated_sharpe, probabilistic_sharpe

    # N=1 ⇒ expected-max benchmark is 0 ⇒ DSR == PSR(SR*=0).
    dsr = deflated_sharpe(0.6, 1, 0.2, 4.0, 120)
    psr0 = probabilistic_sharpe(0.6, 0.0, 0.2, 4.0, 120)
    assert dsr == pytest.approx(psr0)


def test_dsr_decreases_as_trial_count_grows():
    from openbb_backtest.validation.stats import deflated_sharpe

    # More trials ⇒ higher expected-max benchmark ⇒ harder to beat ⇒ lower DSR.
    few = deflated_sharpe(3.0, 10, 0.0, 3.0, 250)
    many = deflated_sharpe(3.0, 100, 0.0, 3.0, 250)
    assert many < few


def test_expected_max_sharpe_brackets_true_value_within_five_percent():
    from openbb_backtest.validation.stats import _expected_max_sharpe

    rng = np.random.default_rng(7)
    draws = rng.standard_normal((200_000, 1))
    for n_trials in (10, 50, 100):
        approx = _expected_max_sharpe(n_trials)
        cols = rng.standard_normal((200_000, n_trials))
        true_emax = float(cols.max(axis=1).mean())
        assert approx == pytest.approx(true_emax, rel=0.05)
    assert draws.shape == (200_000, 1)  # sanity: rng consumed deterministically


def test_expected_max_sharpe_is_zero_for_single_trial():
    from openbb_backtest.validation.stats import _expected_max_sharpe

    assert _expected_max_sharpe(1) == 0.0


def test_dsr_rejects_non_positive_trial_count():
    from openbb_backtest.validation.stats import deflated_sharpe

    with pytest.raises(ValueError):
        deflated_sharpe(0.6, 0, 0.0, 3.0, 120)


def test_dsr_is_deterministic():
    from openbb_backtest.validation.stats import deflated_sharpe

    a = deflated_sharpe(2.0, 25, 0.1, 5.0, 200)
    b = deflated_sharpe(2.0, 25, 0.1, 5.0, 200)
    assert a == b


# ---- MinBTL: scaling, monotonicity, validation ---------------------------


def test_min_backtest_length_scales_as_inverse_sharpe_squared():
    from openbb_backtest.validation.stats import min_backtest_length

    base = min_backtest_length(1.0, 100)
    # Halving the target SR quadruples the required length (1/SR²).
    assert min_backtest_length(0.5, 100) == pytest.approx(4.0 * base)
    # Doubling the target SR quarters it.
    assert min_backtest_length(2.0, 100) == pytest.approx(0.25 * base)


def test_min_backtest_length_grows_with_trial_count():
    from openbb_backtest.validation.stats import min_backtest_length

    assert min_backtest_length(1.0, 10) < min_backtest_length(1.0, 100)


def test_min_backtest_length_matches_closed_form():
    from openbb_backtest.validation.stats import min_backtest_length

    # MinBTL ≈ 2·ln(N) / SR_target²  (years, SR_target annualized).
    assert min_backtest_length(1.5, 50) == pytest.approx(
        2.0 * math.log(50) / 1.5**2
    )


def test_min_backtest_length_rejects_non_positive_target_sharpe():
    from openbb_backtest.validation.stats import min_backtest_length

    with pytest.raises(ValueError):
        min_backtest_length(0.0, 100)
    with pytest.raises(ValueError):
        min_backtest_length(-0.3, 100)


def test_min_backtest_length_rejects_non_positive_trial_count():
    from openbb_backtest.validation.stats import min_backtest_length

    with pytest.raises(ValueError):
        min_backtest_length(1.0, 0)


def test_min_backtest_length_is_deterministic():
    from openbb_backtest.validation.stats import min_backtest_length

    assert min_backtest_length(0.8, 64) == min_backtest_length(0.8, 64)


# ---- lazy-import guard ---------------------------------------------------


def test_stats_module_imports_and_runs_pure_paths_without_scipy():
    """Importing the module + PSR/MinBTL must not need scipy (lazy seam).

    Only the DSR expected-max benchmark pulls scipy's ``norm.ppf``; PSR uses the
    stdlib normal CDF and MinBTL is pure ``math``, so both run with scipy absent.
    """
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {_BACKTEST_ROOT!r})
        sys.modules["scipy"] = None
        sys.modules["scipy.stats"] = None
        from openbb_backtest.validation.stats import (
            probabilistic_sharpe,
            min_backtest_length,
        )
        assert probabilistic_sharpe(0.0, 0.0, 0.0, 3.0, 25) == 0.5
        assert min_backtest_length(1.0, 100) > 0.0
        print("OK", round(min_backtest_length(1.0, 100), 6))
        """
    )
    # Fixed self-authored script via the current interpreter — the S603 precondition.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
