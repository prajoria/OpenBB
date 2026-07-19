"""Portfolio risk metrics + contribution-to-risk (#539, #540).

Shared math with ``Analysis/stock_analysis.py`` in spirit — this module
implements the portfolio-level rollups (VaR, CVaR, volatility, beta,
marginal + component VaR) that the widgets and analytics routes consume.

All functions operate on numpy arrays / plain dicts. No pandas required
at the call boundary so the analytics routes stay lightweight.

Design notes:
- All returns / weights use ``float`` (not Decimal) because numpy is the
  natural fit for covariance math and shrinkage. Decimal is reserved for
  cash / order math (fills, cost basis).
- VaR sign convention: **loss is positive**. VaR(0.95) = 0.03 means "we
  expect losses ≥ 3% on 5% of days" — matches quantstats / pyfolio.
- Time horizon is implicit in the input returns. If you pass daily
  returns, VaR is a daily VaR. Scale in the caller with sqrt-T.

Issues shipped:
- #539  Portfolio risk metrics (shared math with Analysis/)
- #540  Contribution-to-risk (marginal + component VaR)
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

# ---------------------------------------------------------------------------
# Portfolio risk metrics (#539)
# ---------------------------------------------------------------------------


def portfolio_return(weights: np.ndarray, returns: np.ndarray) -> float:
    """Weighted-average portfolio return.

    Parameters
    ----------
    weights : (N,) array
        Portfolio weights (should sum to ~1.0; not enforced here).
    returns : (T, N) array
        T time-series observations for N assets.

    Returns
    -------
    float
        Mean portfolio return across the T observations.
    """
    port_ts = returns @ weights  # (T,) time series of portfolio returns
    return float(port_ts.mean())


def portfolio_volatility(weights: np.ndarray, cov: np.ndarray) -> float:
    """Portfolio volatility from a covariance matrix.

    Parameters
    ----------
    weights : (N,) array
    cov : (N, N) array
        Asset return covariance matrix (same time-scale as inputs).

    Returns
    -------
    float
        sqrt(w^T Σ w) — portfolio std-dev in the return's units.
    """
    variance = float(weights @ cov @ weights)
    if variance < 0:
        # Numerical noise can push tiny values slightly negative; clip.
        variance = 0.0
    return float(np.sqrt(variance))


def value_at_risk(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Historical VaR at ``confidence`` level.

    Parameters
    ----------
    returns : (T,) array
        Time series of portfolio returns.
    confidence : float
        Typically 0.95 or 0.99. VaR is the |quantile at (1-confidence)|.

    Returns
    -------
    float
        Loss magnitude (positive). VaR=0.03 means "5% chance of losing ≥ 3%".

    Raises
    ------
    ValueError
        If confidence is not in (0, 1) or returns is empty.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1); got {confidence}")
    if len(returns) == 0:
        raise ValueError("returns must be non-empty")
    q = np.quantile(returns, 1 - confidence)
    # VaR reports loss magnitude — flip sign of the negative quantile.
    return float(-q) if q < 0 else 0.0


def conditional_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Return the expected shortfall / CVaR — mean loss beyond VaR.

    "Given we're in the worst (1-confidence) of days, what's the average loss?"
    Always ≥ VaR by construction (or equal when the tail is degenerate).

    Parameters
    ----------
    returns : (T,) array
    confidence : float
        Same convention as ``value_at_risk``.

    Returns
    -------
    float
        Expected loss magnitude in the tail (positive).
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1); got {confidence}")
    if len(returns) == 0:
        raise ValueError("returns must be non-empty")
    q = np.quantile(returns, 1 - confidence)
    tail = returns[returns <= q]
    if len(tail) == 0:
        return 0.0
    return float(-tail.mean()) if tail.mean() < 0 else 0.0


def portfolio_beta(
    portfolio_returns: np.ndarray, benchmark_returns: np.ndarray
) -> float:
    """Beta of portfolio vs benchmark: cov(p, b) / var(b).

    Parameters
    ----------
    portfolio_returns : (T,) array
    benchmark_returns : (T,) array

    Returns
    -------
    float
        Beta. 1.0 = moves with benchmark; 0.5 = half sensitivity; -1.0 = inverse.
    """
    if len(portfolio_returns) != len(benchmark_returns):
        raise ValueError(
            "portfolio and benchmark return series must be the same length"
        )
    if len(portfolio_returns) < 2:
        raise ValueError("need at least 2 observations to compute covariance")
    bench_var = float(np.var(benchmark_returns, ddof=1))
    if bench_var == 0:
        raise ValueError("benchmark has zero variance; beta undefined")
    cov = float(np.cov(portfolio_returns, benchmark_returns, ddof=1)[0, 1])
    return cov / bench_var


# ---------------------------------------------------------------------------
# Contribution-to-risk (#540)
# ---------------------------------------------------------------------------


def marginal_var(
    weights: np.ndarray,
    cov: np.ndarray,
    confidence: float = 0.95,
) -> np.ndarray:
    """Marginal VaR contribution per asset.

    Parametric VaR under a normal-returns assumption:
      MVaR_i = z * (Σw)_i / σ_p

    where z is the (1-confidence) standard-normal quantile magnitude
    and σ_p is portfolio volatility. Interpretation: "if I add ε of
    weight to asset i, VaR increases by ε * MVaR_i approximately."

    Parameters
    ----------
    weights : (N,) array
    cov : (N, N) array
    confidence : float

    Returns
    -------
    (N,) array
        Marginal VaR per asset. Positive = adds risk when weight
        increases; negative = hedge asset (weight-up reduces VaR).
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1); got {confidence}")
    sigma_p = portfolio_volatility(weights, cov)
    if sigma_p == 0:
        return np.zeros_like(weights, dtype=float)
    # Standard-normal quantile magnitude (positive).
    from scipy.stats import norm  # pylint: disable=import-outside-toplevel

    z = float(norm.ppf(confidence))
    sigma_wi = cov @ weights  # (N,) — covariance of each asset with portfolio
    return z * sigma_wi / sigma_p


def component_var(
    weights: np.ndarray,
    cov: np.ndarray,
    confidence: float = 0.95,
) -> np.ndarray:
    """Component VaR — Euler-decomposition of total VaR into per-asset shares.

    CVaR_i = w_i * MVaR_i, and Σ CVaR_i = total parametric VaR.

    Positive values are the asset's share of total portfolio risk (in
    the same units as VaR). Sums to total VaR by construction.

    Parameters
    ----------
    weights : (N,) array
    cov : (N, N) array
    confidence : float

    Returns
    -------
    (N,) array
        Component VaR per asset. Sum equals parametric VaR of the portfolio.
    """
    mvar = marginal_var(weights, cov, confidence)
    return weights * mvar


# ---------------------------------------------------------------------------
# Decimal-friendly convenience wrappers (for callers passing Decimal weights).
# ---------------------------------------------------------------------------


def _to_float_array(decimals: list[Decimal]) -> np.ndarray:
    """Convert a list of Decimal weights to a float numpy array."""
    return np.array([float(d) for d in decimals], dtype=float)
