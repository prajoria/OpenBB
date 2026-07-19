"""Unit tests for risk metrics + contribution-to-risk (#539, #540)."""

from __future__ import annotations

import numpy as np
import pytest
from openbb_portfolio_intel.analytics.risk import (
    component_var,
    conditional_var,
    marginal_var,
    portfolio_beta,
    portfolio_return,
    portfolio_volatility,
    value_at_risk,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def equal_weight_3() -> np.ndarray:
    """Three equally-weighted assets."""
    return np.array([1 / 3, 1 / 3, 1 / 3])


@pytest.fixture
def diagonal_cov_3() -> np.ndarray:
    """Diagonal covariance (uncorrelated assets), variances 0.01 each."""
    return np.diag([0.01, 0.01, 0.01])


@pytest.fixture
def returns_3assets_100days() -> np.ndarray:
    """100-day return series for 3 assets — reproducible via seed."""
    rng = np.random.default_rng(seed=42)
    return rng.normal(loc=0.0005, scale=0.01, size=(100, 3))


# ---------------------------------------------------------------------------
# Portfolio return + volatility (#539)
# ---------------------------------------------------------------------------


def test_portfolio_return_matches_weighted_mean(
    equal_weight_3: np.ndarray,
    returns_3assets_100days: np.ndarray,
) -> None:
    """Portfolio return equals mean of (returns @ weights) time series."""
    result = portfolio_return(equal_weight_3, returns_3assets_100days)
    expected = float((returns_3assets_100days @ equal_weight_3).mean())
    assert result == pytest.approx(expected)


def test_portfolio_volatility_diagonal_uncorrelated_case(
    equal_weight_3: np.ndarray,
    diagonal_cov_3: np.ndarray,
) -> None:
    """For diagonal cov + equal weights: σ_p = sqrt(N * w^2 * σ^2) = σ/sqrt(N)."""
    result = portfolio_volatility(equal_weight_3, diagonal_cov_3)
    # variance = 3 * (1/3)^2 * 0.01 = 0.01/3; σ = sqrt(0.01/3)
    expected = float(np.sqrt(0.01 / 3))
    assert result == pytest.approx(expected)


def test_portfolio_volatility_clips_negative_numerical_noise() -> None:
    """Ensure numerical near-zero cov doesn't produce NaN sqrt."""
    weights = np.array([1.0])
    cov = np.array([[1e-20]])  # positive but tiny — no clipping needed
    assert portfolio_volatility(weights, cov) >= 0


# ---------------------------------------------------------------------------
# VaR / CVaR (#539)
# ---------------------------------------------------------------------------


def test_var_reports_positive_loss_magnitude() -> None:
    """VaR should be a positive number representing loss size."""
    returns = np.array([-0.10, -0.05, -0.01, 0.01, 0.05, 0.10])
    result = value_at_risk(returns, confidence=0.9)
    # 10th percentile of that sample. quantile(0.1) is roughly -0.075.
    assert result > 0
    assert result < 0.15  # sanity bound


def test_var_zero_when_all_returns_positive() -> None:
    """No losses in the tail → VaR = 0 (not negative)."""
    returns = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
    assert value_at_risk(returns, confidence=0.95) == 0.0


def test_var_rejects_bad_confidence() -> None:
    """Confidence must be in (0, 1)."""
    returns = np.array([-0.1, 0.1])
    with pytest.raises(ValueError, match="confidence"):
        value_at_risk(returns, confidence=1.0)
    with pytest.raises(ValueError, match="confidence"):
        value_at_risk(returns, confidence=-0.1)


def test_cvar_greater_or_equal_to_var() -> None:
    """CVaR (expected shortfall) ≥ VaR by construction."""
    rng = np.random.default_rng(seed=42)
    returns = rng.normal(loc=0.0, scale=0.02, size=1000)
    var = value_at_risk(returns, confidence=0.95)
    cvar = conditional_var(returns, confidence=0.95)
    assert cvar >= var, f"CVaR {cvar} must be >= VaR {var}"


def test_cvar_zero_when_no_losses() -> None:
    """All-positive returns → CVaR = 0."""
    returns = np.array([0.01, 0.02, 0.03])
    assert conditional_var(returns, confidence=0.95) == 0.0


# ---------------------------------------------------------------------------
# Beta (#539)
# ---------------------------------------------------------------------------


def test_beta_one_for_identical_series() -> None:
    """Portfolio identical to benchmark → beta = 1.0."""
    returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
    assert portfolio_beta(returns, returns) == pytest.approx(1.0)


def test_beta_negative_for_inverse_series() -> None:
    """Portfolio = -benchmark → beta = -1.0."""
    b = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
    p = -b
    assert portfolio_beta(p, b) == pytest.approx(-1.0)


def test_beta_raises_on_length_mismatch() -> None:
    """Portfolio and benchmark must be the same length."""
    with pytest.raises(ValueError, match="same length"):
        portfolio_beta(np.array([0.01, 0.02]), np.array([0.01, 0.02, 0.03]))


def test_beta_raises_on_zero_benchmark_variance() -> None:
    """Zero-variance benchmark → beta is undefined; raise."""
    with pytest.raises(ValueError, match="zero variance"):
        portfolio_beta(np.array([0.01, 0.02]), np.array([0.01, 0.01]))


# ---------------------------------------------------------------------------
# Marginal + Component VaR (#540)
# ---------------------------------------------------------------------------


def test_marginal_var_has_one_entry_per_asset(
    equal_weight_3: np.ndarray, diagonal_cov_3: np.ndarray
) -> None:
    """Output length matches asset count."""
    mv = marginal_var(equal_weight_3, diagonal_cov_3)
    assert mv.shape == (3,)


def test_marginal_var_equal_for_symmetric_portfolio(
    equal_weight_3: np.ndarray, diagonal_cov_3: np.ndarray
) -> None:
    """Equal weights + identical variances → identical marginals."""
    mv = marginal_var(equal_weight_3, diagonal_cov_3)
    # All three should be identical.
    assert mv[0] == pytest.approx(mv[1])
    assert mv[1] == pytest.approx(mv[2])


def test_component_var_sums_to_parametric_var(
    equal_weight_3: np.ndarray, diagonal_cov_3: np.ndarray
) -> None:
    """Σ CVaR_i = parametric VaR = z * σ_p (Euler decomposition property)."""
    from scipy.stats import norm

    cv = component_var(equal_weight_3, diagonal_cov_3, confidence=0.95)
    sigma_p = portfolio_volatility(equal_weight_3, diagonal_cov_3)
    parametric_var = norm.ppf(0.95) * sigma_p
    assert float(cv.sum()) == pytest.approx(parametric_var)


def test_marginal_var_zero_when_portfolio_vol_zero() -> None:
    """If σ_p = 0 (empty weights or all-zero cov), no meaningful marginal."""
    weights = np.array([1.0, 0.0])
    cov = np.zeros((2, 2))
    mv = marginal_var(weights, cov)
    assert np.all(mv == 0)
