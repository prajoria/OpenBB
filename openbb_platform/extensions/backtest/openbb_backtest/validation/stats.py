"""Sharpe-ratio overfitting statistics (component 08, §2).

Closed-form, pure-scalar implementations of the Bailey & López de Prado
anti-overfitting toolkit, **re-implemented from the public papers** — never from
``mlfinlab`` (its Commons-Clause license is restricted, license rule §08):

- :func:`probabilistic_sharpe` (PSR) — Bailey & López de Prado, *The Sharpe Ratio
  Efficient Frontier* (J. of Risk, 2012); higher-moment variance after Lo, *The
  Statistics of Sharpe Ratios* (FAJ, 2002).
- :func:`deflated_sharpe` (DSR) — Bailey & López de Prado, *The Deflated Sharpe
  Ratio* (J. of Portfolio Mgmt, 2014): PSR taken against the *expected maximum*
  Sharpe of ``n_trials`` independent trials, countering selection bias from the
  component-04 parameter sweep.
- :func:`min_backtest_length` (MinBTL) — Bailey, Borwein, López de Prado & Zhu,
  *Pseudo-Mathematics and Financial Charlatanism* (Notices of the AMS, 2014):
  the backtest length below which an over-fit Sharpe is statistically expected.

Design policy:

- **Pure & deterministic:** every function maps scalar moments
  (``sr``/``skew``/``kurt``/``n_obs``/``n_trials``) to a scalar; identical inputs
  always yield identical outputs, with no global state or RNG.
- **Lazy scipy seam:** only the DSR expected-max benchmark needs scipy's inverse
  normal CDF; PSR uses the stdlib (``math.erf``) normal CDF and MinBTL is pure
  ``math``, so the module imports — and PSR/MinBTL run — with scipy absent.
- **Validation:** non-physical inputs (too few observations, non-positive trial
  count / target Sharpe, a degenerate non-positive Sharpe-variance term) raise
  :class:`ValueError` rather than returning a silently-wrong number.

See ``docs/designs/backtest-design/08-validation.md`` §2.
"""

from __future__ import annotations

import math

#: Euler–Mascheroni constant γ, used in the expected-maximum-of-N-Gaussians
#: bracket of Bailey & López de Prado (2014), eq. for E[max].
_EULER_MASCHERONI = 0.5772156649015329


def probabilistic_sharpe(
    sr: float,
    sr_benchmark: float,
    skew: float,
    kurt: float,
    n_obs: int,
) -> float:
    r"""Probabilistic Sharpe Ratio: ``P(true SR > sr_benchmark)``.

    Implements Bailey & López de Prado (2012)::

        PSR(SR*) = Φ( (SR̂ − SR*)·√(n − 1)
                       / √(1 − γ₃·SR̂ + (γ₄ − 1)/4 · SR̂²) )

    where ``SR̂`` (``sr``) and ``SR*`` (``sr_benchmark``) are per-observation
    Sharpe ratios, ``γ₃`` (``skew``) and ``γ₄`` (``kurt``, non-excess: 3 for a
    normal) are the return moments, and ``n_obs`` is the sample length. The
    higher-moment denominator is Lo's (2002) Sharpe standard error. When ``SR̂ ==
    SR*`` the numerator is 0, so the result is ``Φ(0) == 0.5`` exactly.

    Parameters
    ----------
    sr
        Observed (per-observation) Sharpe ratio ``SR̂``.
    sr_benchmark
        Benchmark Sharpe ratio ``SR*`` to test against (often ``0``).
    skew
        Return skewness ``γ₃``.
    kurt
        Return kurtosis ``γ₄`` (non-excess; ``3`` is normal).
    n_obs
        Number of return observations (must be ``≥ 2``).

    Returns
    -------
    float
        Probability in ``[0, 1]`` that the true Sharpe exceeds ``sr_benchmark``.

    Raises
    ------
    ValueError
        If ``n_obs < 2`` or the Sharpe-variance term is non-positive (a
        moment/Sharpe combination that admits no real standard error).
    """
    if n_obs < 2:
        raise ValueError(f"n_obs must be >= 2 to estimate Sharpe variance, got {n_obs}")
    variance_term = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if variance_term <= 0.0:
        raise ValueError(
            "Sharpe-variance term 1 - skew*SR + (kurt-1)/4*SR^2 must be positive, "
            f"got {variance_term} (implausible moment/Sharpe combination)"
        )
    z = (sr - sr_benchmark) * math.sqrt(n_obs - 1.0) / math.sqrt(variance_term)
    return _norm_cdf(z)


def deflated_sharpe(
    sr: float,
    n_trials: int,
    skew: float,
    kurt: float,
    n_obs: int,
) -> float:
    r"""Deflated Sharpe Ratio: PSR against the expected maximum of ``n_trials``.

    Implements Bailey & López de Prado (2014): the observed Sharpe is judged not
    against zero but against the Sharpe one would expect to obtain *by chance* as
    the best of ``n_trials`` independent trials, so a high Sharpe found by a wide
    parameter sweep is correctly deflated::

        DSR = PSR( SR* = E[max Sharpe over n_trials] )

    With ``n_trials == 1`` the expected-max benchmark is ``0``, so DSR reduces to
    :func:`probabilistic_sharpe` at ``sr_benchmark=0``. The cross-trial Sharpe
    variance is taken as unity (the standardized convention matching the signature
    in ``docs/designs/backtest-design/08-validation.md`` §2), so the benchmark is
    :func:`_expected_max_sharpe`.

    Parameters
    ----------
    sr
        Observed (per-observation) Sharpe ratio of the selected configuration.
    n_trials
        Number of independent trials/configurations searched (``≥ 1``); the
        component-04 sweep count feeds this.
    skew, kurt, n_obs
        Return moments and sample length, forwarded to :func:`probabilistic_sharpe`.

    Returns
    -------
    float
        Probability in ``[0, 1]`` that the true Sharpe exceeds the expected
        best-of-``n_trials`` Sharpe (i.e. survives multiple-testing deflation).

    Raises
    ------
    ValueError
        If ``n_trials < 1`` (or via :func:`probabilistic_sharpe` for ``n_obs``).
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")
    expected_max = _expected_max_sharpe(n_trials)
    return probabilistic_sharpe(sr, expected_max, skew, kurt, n_obs)


def min_backtest_length(target_sr: float, n_trials: int) -> float:
    r"""Minimum backtest length (years) to trust an annualized ``target_sr``.

    Implements the Bailey, Borwein, López de Prado & Zhu (2014) approximation::

        MinBTL ≈ 2·ln(n_trials) / target_sr²

    Below this many years of (annualized) data, the expected maximum Sharpe from
    ``n_trials`` trials reaches ``target_sr`` purely by overfitting — so a backtest
    shorter than ``MinBTL`` cannot statistically distinguish skill from selection.
    Scales as the inverse square of the target Sharpe and grows with ``ln`` of the
    trial count.

    Parameters
    ----------
    target_sr
        Target *annualized* Sharpe ratio (must be ``> 0``).
    n_trials
        Number of independent trials/configurations searched (``≥ 1``).

    Returns
    -------
    float
        Minimum backtest length in years.

    Raises
    ------
    ValueError
        If ``target_sr <= 0`` or ``n_trials < 1``.
    """
    if target_sr <= 0.0:
        raise ValueError(f"target_sr must be positive, got {target_sr}")
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")
    return 2.0 * math.log(n_trials) / (target_sr * target_sr)


# --- internal helpers -----------------------------------------------------


def _norm_cdf(x: float) -> float:
    """Standard-normal CDF Φ via the stdlib error function (no scipy needed)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _expected_max_sharpe(n_trials: int) -> float:
    r"""Expected maximum of ``n_trials`` i.i.d. standard-normal Sharpe estimates.

    Bailey & López de Prado (2014) bracket the expected maximum between two
    extreme-value quantiles, weighted by the Euler–Mascheroni constant γ::

        E[max] ≈ (1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e))

    A single trial (``N == 1``) cannot exceed its own mean, so this is ``0`` by
    definition (and avoids the ``Φ⁻¹(0) = −∞`` degeneracy). The inverse normal CDF
    ``Φ⁻¹`` is taken from scipy, imported lazily so the pure PSR/MinBTL paths need
    no scipy.
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")
    if n_trials == 1:
        return 0.0
    ppf = _norm_ppf()
    gamma = _EULER_MASCHERONI
    upper = ppf(1.0 - 1.0 / n_trials)
    lower = ppf(1.0 - 1.0 / (n_trials * math.e))
    return float((1.0 - gamma) * upper + gamma * lower)


def _norm_ppf():
    """Return scipy's standard-normal inverse CDF ``Φ⁻¹`` (lazy scipy seam).

    Imported here (not at module top) so importing this module — and running the
    stdlib-only PSR/MinBTL functions — never requires scipy. Raises an actionable
    :class:`ImportError` if scipy is genuinely absent when DSR is invoked.
    """
    try:
        from scipy.stats import norm
    except Exception as exc:  # ModuleNotFoundError, or stubbed None in sys.modules
        raise ImportError(
            "the Deflated Sharpe Ratio requires scipy for the inverse normal CDF "
            "but it is not installed. Install it with: pip install scipy"
        ) from exc
    return norm.ppf
