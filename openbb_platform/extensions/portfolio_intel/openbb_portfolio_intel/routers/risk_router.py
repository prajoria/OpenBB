"""Risk-metrics + concentration routes (#528).

Two commands under one subrouter (mirrors backtest's run_router pattern):

- ``obb.portfolio_intel.risk.metrics(basket, returns_source, benchmark_returns, provider)``
  Parametric portfolio-level risk: volatility, VaR(95%), CVaR(95%), beta.
- ``obb.portfolio_intel.risk.concentration(basket, provider)``
  Post-unwrap HHI / effective-N / top-K, delegating ETF unwrap to the
  same helpers used by the xray route (#541).

Composes:
- ``openbb_portfolio_intel.analytics.risk`` for portfolio_volatility + beta
- Parametric VaR/CVaR formulas inline (matches What-If engine's rationale
  #558 §9.6: parametric admits the Euler component-sum identity)
- ``openbb_portfolio_intel.routers.xray_router`` for ``_fetch_holdings`` +
  ``_build_holdings_provider`` + ``_validate_basket`` (module-level reuse;
  not exported public API)

Design: ``docs/superpowers/specs/2026-07-19-risk-concentration-routes-design.md``.

Scope narrowed vs PRD §14 (documented in module docstring):

- **Pre-computed returns_source** — no auto-fetch from
  ``obb.equity.price.historical``. Widget layer pre-computes + caches.
  Follow-up will add auto-fetch overload.
- **Parametric only** — no historical VaR variant. Callers who need
  historical call ``analytics.risk.value_at_risk`` directly.
- **No shorts** — negative weights raise ``ValueError`` (mirrors What-If
  #904).
- **Confidence fixed at 0.95** — follow-up will parameterize.
- **Inline basket only** — no saved-basket table lookup.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import numpy as np
from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from scipy.stats import norm

from openbb_portfolio_intel.analytics.risk import (
    portfolio_beta,
    portfolio_volatility,
)
from openbb_portfolio_intel.analytics.xray import (
    DEFAULT_WEIGHT_TOLERANCE,
    Holding,
    effective_n as _effective_n,
    herfindahl_hirschman as _herfindahl_hirschman,
    look_through as _xray_look_through,
)
from openbb_portfolio_intel.models import (
    BasketPosition,
    ConcentrationSummary,
    RiskMetricsResult,
)
from openbb_portfolio_intel.routers.xray_router import (
    _build_holdings_provider,
    _fetch_holdings,  # noqa: F401  # pylint: disable=unused-import
    _validate_basket,
)

logger = logging.getLogger(__name__)

router = Router(
    prefix="/risk",
    description=(
        "Portfolio-level risk metrics + concentration. Composes analytics.risk "
        "(parametric VaR/CVaR/beta) with xray unwrap for post-effective-weight "
        "concentration."
    ),
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _positions_from_basket(basket: list[dict]) -> list[tuple[str, Decimal]]:
    """Coerce basket dicts to (symbol_upper, Decimal weight) pairs.

    Also runs the same shorts/empty guard as xray_router (via
    ``_validate_basket``), so the two routes reject inputs identically.
    """
    positions = [
        BasketPosition(symbol=str(r["symbol"]), weight=Decimal(str(r["weight"])))
        for r in basket
    ]
    _validate_basket(positions)
    return [(p.symbol.upper(), p.weight) for p in positions]


def _weights_sum_to_one(pairs: list[tuple[str, Decimal]]) -> None:
    """Reject if the basket weights don't sum to ~1.0 (xray tolerance)."""
    total = sum((w for _, w in pairs), Decimal("0"))
    if abs(total - Decimal("1")) > DEFAULT_WEIGHT_TOLERANCE:
        raise ValueError(
            f"basket weights must sum to 1.0 (±{DEFAULT_WEIGHT_TOLERANCE}); "
            f"got {total}. Normalize inputs before calling."
        )


# ---------------------------------------------------------------------------
# /risk/metrics
# ---------------------------------------------------------------------------


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Portfolio risk metrics for a 3-asset basket.",
            code=[
                "from decimal import Decimal",
                "basket = [",
                '    {"symbol": "AAPL", "weight": Decimal("0.5")},',
                '    {"symbol": "MSFT", "weight": Decimal("0.3")},',
                '    {"symbol": "NVDA", "weight": Decimal("0.2")},',
                "]",
                "# widget pre-computes returns_source + benchmark_returns from historicals",
                "obb.portfolio_intel.risk.metrics(basket=basket, returns_source=..., benchmark_returns=...)",
            ],
        ),
    ],
)
def metrics(
    basket: list[dict],
    returns_source: dict,
    benchmark_returns: list[float],
    provider: str | None = None,  # noqa: ARG001  # pylint: disable=unused-argument
) -> OBBject:
    """Parametric portfolio-level risk metrics: volatility, VaR(95%), CVaR(95%), beta.

    All four metrics computed from ``returns_source`` (per-symbol return
    series supplied by the caller) + ``benchmark_returns`` (aligned length).
    Parametric VaR/CVaR only — matches What-If engine (#558 §9.6): only
    parametric admits the Euler component-sum decomposition.

    ``basket`` shape mirrors ``/xray/look_through``: ``list[dict]`` of
    ``{"symbol": str, "weight": float | Decimal}``. Weights are fractions
    of 1.0 (not percentages) summing to ~1.0.

    ``returns_source`` shape: ``{"AAPL": [0.001, -0.002, ...], ...}``.
    Every basket symbol must have an entry; a missing symbol degrades
    ALL aggregate metrics to None (never a partial-book number — matches
    What-If's silent-failure-hunt lesson from #558).

    ``benchmark_returns`` length must match every ``returns_source``
    entry's length.

    Returns
    -------
    OBBject[:class:`~openbb_portfolio_intel.models.RiskMetricsResult`]
        Return type is bare ``OBBject`` at the signature level for OpenBB
        static-generator compatibility (see #541 phase-6 discovery); the
        actual ``.results`` value is always a ``RiskMetricsResult``.

    Raises
    ------
    ValueError
        - Empty basket
        - Negative weight (shorts deferred — mirror #904)
        - Weights don't sum to ~1.0
        - benchmark_returns length ≠ any returns_source entry's length
    """
    pairs = _positions_from_basket(basket)
    _weights_sum_to_one(pairs)

    warnings: list[str] = []

    # Length invariant: benchmark_returns must match returns_source rows.
    for sym, series in returns_source.items():
        if len(series) != len(benchmark_returns):
            raise ValueError(
                f"benchmark_returns length {len(benchmark_returns)} does not "
                f"match returns_source[{sym!r}] length {len(series)}"
            )

    # If any basket symbol is missing from returns_source, degrade to
    # all-None + warning (matches What-If's fail-loud posture from #558).
    missing = [s for s, _ in pairs if s not in returns_source]
    if missing:
        for m in missing:
            warnings.append(f"{m}: not in returns_source — all risk metrics are None")
        return OBBject(results=RiskMetricsResult(warnings=warnings))

    # Assemble aligned weight + returns matrices.
    symbols = [s for s, _ in pairs]
    w = np.array([float(pair[1]) for pair in pairs], dtype=float)
    returns_matrix = np.column_stack([np.array(returns_source[s]) for s in symbols])
    cov = np.cov(returns_matrix, rowvar=False, ddof=1)
    # np.cov collapses to 0-d for single-column input; force 2-d.
    if cov.ndim == 0:
        cov = np.array([[float(cov)]])

    vol = portfolio_volatility(w, cov)
    z = float(norm.ppf(0.95))
    var_95 = z * vol
    # Truncated-normal expected loss beyond VaR: phi(z) / (1 - Phi(z)) * sigma
    cvar_95 = float(norm.pdf(z) / (1 - norm.cdf(z))) * vol

    port_ts = returns_matrix @ w
    beta = portfolio_beta(port_ts, np.asarray(benchmark_returns, dtype=float))

    return OBBject(
        results=RiskMetricsResult(
            volatility=vol,
            var_95=var_95,
            cvar_95=cvar_95,
            beta=beta,
            warnings=warnings,
        )
    )


# ---------------------------------------------------------------------------
# /risk/concentration
# ---------------------------------------------------------------------------


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Concentration on a SPY 60% + AAPL 40% basket after unwrap.",
            code=[
                "from decimal import Decimal",
                "basket = [",
                '    {"symbol": "SPY", "weight": Decimal("0.6")},',
                '    {"symbol": "AAPL", "weight": Decimal("0.4")},',
                "]",
                'result = obb.portfolio_intel.risk.concentration(basket=basket, provider="fmp_cached").results',
                "print(result.hhi, result.effective_n, result.top1)",
            ],
        ),
    ],
)
def concentration(
    basket: list[dict],
    provider: str | None = None,
) -> OBBject:
    """Post-unwrap concentration metrics (HHI + effective-N + top1/5/10).

    Reuses the xray route's ETF-unwrap helpers so the effective weights
    used here match what ``/xray/look_through`` returns. Computes HHI +
    effective-N via the shipped analytics.xray helpers.

    Returns
    -------
    OBBject[:class:`~openbb_portfolio_intel.models.ConcentrationSummary`]
        Bare ``OBBject`` at the signature level (see #541); runtime
        ``.results`` is a ``ConcentrationSummary``.

    Raises
    ------
    ValueError
        Empty basket, or any negative weight.
    """
    pairs = _positions_from_basket(basket)

    unresolved: list[str] = []
    warnings: list[str] = []
    unique = {s for s, _ in pairs}
    holdings_provider, _attribute_provider = _build_holdings_provider(
        unique, provider, unresolved, warnings
    )

    portfolio = [Holding(symbol=s, weight=w) for s, w in pairs]
    lt = _xray_look_through(portfolio, holdings_provider)

    effective = lt.effective
    if not effective:
        return OBBject(
            results=ConcentrationSummary(
                hhi=0.0, effective_n=0.0, top1=0.0, top5=0.0, top10=0.0
            )
        )

    hhi_dec = _herfindahl_hirschman(effective)
    hhi = float(hhi_dec)
    en = float(_effective_n(hhi_dec)) if hhi > 0 else 0.0

    sorted_w = sorted((float(w) for w in effective.values()), reverse=True)

    def _top(k: int) -> float:
        return float(sum(sorted_w[:k]))

    return OBBject(
        results=ConcentrationSummary(
            hhi=hhi,
            effective_n=en,
            top1=_top(1),
            top5=_top(5),
            top10=_top(10),
        )
    )
