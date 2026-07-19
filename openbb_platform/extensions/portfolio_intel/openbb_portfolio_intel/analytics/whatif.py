"""What-If diff engine (#558) — stateless portfolio analytics preview.

Composes the pure-math substrate in :mod:`openbb_portfolio_intel.analytics.xray`
and :mod:`openbb_portfolio_intel.analytics.risk` to answer: *"If I apply these
candidate trades to my portfolio, what happens to my exposure, concentration,
and risk metrics — right now, in memory, without touching any table?"*

This is the analytical counterpart to Paper Trading. Where paper trading
persists a shadow book and simulates forward-time fills, What-If is a
synchronous, one-shot re-computation of the analytics against a
hypothetically-modified position vector.

Design: ``docs/superpowers/specs/2026-07-19-whatif-diff-engine-design.md``.

Scope narrowed vs the original design (deferred to follow-up issues):

- **Self-financing only** (see #903). Buys are implicitly funded by
  proportionally shrinking every other holding — the projected weights
  renormalize to 1.0. Cash-funded and named-sell-funded models require a
  cash line that this cut does not model. Every diff carries a
  ``self-financing`` warning to remind callers.
- **No shorts** (see #904). Any delta that drives projected qty < 0 raises
  ``ValueError``. Signed rollups + gross-weight concentration are a
  separate design change.
- **Parametric VaR/CVaR** (finding 9.6). What-If reports parametric
  (Gaussian) VaR/CVaR because only that variant admits the Euler
  component-sum identity. This is a *first-order* estimate under a
  static-covariance assumption (finding 9.4) — it does not re-estimate
  forward covariance, so it can *understate* the risk of a big
  concentrating trade.
- **All diff arithmetic in ``float``** (finding 9.5). ``Decimal`` inputs
  are coerced at the boundary; ``MetricDiff`` fields are
  ``float | None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np
from scipy.stats import norm

from openbb_portfolio_intel.analytics.risk import (
    component_var,
    portfolio_beta,
    portfolio_volatility,
)
from openbb_portfolio_intel.analytics.xray import (
    Holding,
    effective_n,
    herfindahl_hirschman,
    look_through,
    rollup_by,
)

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositionQty:
    """One row of the current book, in signed shares.

    Note
    ----
    Initial ship rejects negative qty entering the projected side. A
    negative qty in the *current* book is accepted only if the delta
    brings it back to zero or positive (rare hedge unwinds); otherwise
    ``run_whatif`` raises. Full short support is tracked in #904.
    """

    symbol: str
    qty: Decimal


@dataclass(frozen=True)
class Delta:
    """A candidate trade against the current book.

    ``delta_qty`` is signed and additive. Buy = positive, sell = negative.
    Close-a-position = ``-current_qty``. Flip-to-short (past zero into
    negative territory) is rejected in the initial cut (see #904).
    """

    symbol: str
    delta_qty: Decimal


@dataclass
class MarketData:
    """Read-only bundle of everything the analytics need.

    The router (a separate issue) builds this from ``fmp_cached``; What-If
    is agnostic to the source and never fetches.
    """

    prices: dict[str, Decimal]
    holdings_provider: dict[str, list[Holding]]
    attribute_provider: dict[str, Holding]
    returns: np.ndarray  # (T, N)
    returns_symbols: list[str]  # len N
    cov: np.ndarray  # (N, N)
    benchmark_returns: np.ndarray  # (T,)


@dataclass(frozen=True)
class MetricDiff:
    """One row in the diff view.

    Shape matches PRD §15: ``{metric, current, projected, delta}``. When
    a side is unavailable, that side is ``None`` and ``delta`` is ``None``.
    All arithmetic is float; ``Decimal`` inputs are coerced at the boundary.
    """

    metric: str
    current: float | None
    projected: float | None
    delta: float | None


@dataclass(frozen=True)
class WhatIfDiff:
    """Categorized diff, one flat list per category.

    Each category maps to a widget section. Flat inside categories so
    downstream rendering is a for-loop; categorized across categories so
    the widget doesn't have to parse metric-name prefixes.
    """

    exposure_diffs: list[MetricDiff] = field(default_factory=list)
    sector_diffs: list[MetricDiff] = field(default_factory=list)
    country_diffs: list[MetricDiff] = field(default_factory=list)
    concentration_diffs: list[MetricDiff] = field(default_factory=list)
    risk_diffs: list[MetricDiff] = field(default_factory=list)
    contribution_diffs: list[MetricDiff] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


# Sentinel used in warnings and PR body — makes it grep-able.
_SELF_FINANCING_WARNING = (
    "self-financing assumption: buys are implicitly funded by proportionally "
    "trimming other holdings (see #903 for cash-line follow-up)"
)


def run_whatif(
    positions: list[PositionQty],
    deltas: list[Delta],
    market_data: MarketData,
) -> WhatIfDiff:
    """Compute the What-If diff for ``deltas`` applied to ``positions``.

    Pure function. No I/O. Deterministic up to floating-point tolerance.

    Raises
    ------
    ValueError
        - If any symbol in ``positions`` or ``deltas`` is missing from
          ``market_data.prices`` (router should have caught this).
        - If any projected qty is negative (short — see #904).
        - If every projected qty is zero (fully liquidated — analytics
          have no meaning on an empty book).
        - If ``market_data`` shape invariants don't hold (cov not
          ``(N, N)`` for ``N = len(returns_symbols)``, ``returns.shape[1]
          != N``, or ``benchmark_returns`` length mismatches ``returns``).
    """
    _validate_market_data_shapes(market_data)
    warnings: list[str] = [_SELF_FINANCING_WARNING]

    current_qty = {p.symbol: p.qty for p in positions}
    delta_qty = {d.symbol: d.delta_qty for d in deltas}
    # Union of symbols we'll touch — both sides of the diff.
    all_symbols = set(current_qty) | set(delta_qty)

    _validate_prices_present(all_symbols, market_data.prices)

    projected_qty: dict[str, Decimal] = {}
    for sym in all_symbols:
        pq = current_qty.get(sym, Decimal("0")) + delta_qty.get(sym, Decimal("0"))
        if pq < 0:
            raise ValueError(
                f"{sym}: projected qty is negative ({pq}) — short positions "
                "are not supported in this cut (see #904)."
            )
        if pq == 0 and sym in current_qty and current_qty[sym] > 0:
            warnings.append(f"{sym} delta closes position (qty → 0)")
        projected_qty[sym] = pq

    # Compute market values, then weights.
    current_values = {s: current_qty.get(s, Decimal("0")) * market_data.prices[s]
                      for s in all_symbols}
    projected_values = {s: projected_qty[s] * market_data.prices[s]
                        for s in all_symbols}

    current_total = sum(current_values.values(), Decimal("0"))
    projected_total = sum(projected_values.values(), Decimal("0"))

    if projected_total == 0:
        raise ValueError(
            "projected book is empty (fully liquidated); analytics have no "
            "meaning — call this only on a non-empty projected book."
        )
    # Current book may be empty (all-new-positions delta scenario). Guard.
    if current_total == 0:
        current_weights: dict[str, Decimal] = {}
    else:
        current_weights = {s: v / current_total for s, v in current_values.items() if v > 0}

    projected_weights = {s: v / projected_total for s, v in projected_values.items() if v > 0}

    # Look-through both sides.
    current_effective = _look_through_or_empty(current_weights, market_data.holdings_provider)
    projected_effective = _look_through_or_empty(projected_weights, market_data.holdings_provider)

    # Build the six diff categories.
    diff = WhatIfDiff(warnings=warnings)

    _fill_exposure_diffs(diff, current_effective, projected_effective)
    _fill_rollup_diffs(
        diff.sector_diffs, current_effective, projected_effective,
        market_data.attribute_provider, "sector",
    )
    _fill_rollup_diffs(
        diff.country_diffs, current_effective, projected_effective,
        market_data.attribute_provider, "country",
    )
    _fill_concentration_diffs(diff, current_effective, projected_effective)
    _fill_risk_and_contrib_diffs(
        diff, current_weights, projected_weights, market_data,
    )

    return diff


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_market_data_shapes(md: MarketData) -> None:
    n = len(md.returns_symbols)
    if md.cov.shape != (n, n):
        raise ValueError(
            f"cov shape {md.cov.shape} does not match "
            f"(len(returns_symbols), len(returns_symbols)) = ({n}, {n})"
        )
    if md.returns.ndim != 2 or md.returns.shape[1] != n:
        raise ValueError(
            f"returns shape {md.returns.shape} incompatible with "
            f"returns_symbols (len {n})"
        )
    if md.benchmark_returns.shape[0] != md.returns.shape[0]:
        raise ValueError(
            f"benchmark_returns length {md.benchmark_returns.shape[0]} does "
            f"not match returns time dimension {md.returns.shape[0]}"
        )
    # NaN in cov / returns / benchmark_returns silently poisons every
    # downstream numpy computation (var_95 comes back NaN with no warning).
    # Fail loud at the boundary — upstream data drift shouldn't produce
    # clean-looking WhatIfDiff rows.
    if n > 0 and np.isnan(md.cov).any():
        raise ValueError("cov contains NaN — refuse to compute risk on poisoned data")
    if md.returns.size and np.isnan(md.returns).any():
        raise ValueError("returns contains NaN — refuse to compute risk on poisoned data")
    if md.benchmark_returns.size and np.isnan(md.benchmark_returns).any():
        raise ValueError("benchmark_returns contains NaN — refuse to compute risk on poisoned data")


def _validate_prices_present(symbols: set[str], prices: dict[str, Decimal]) -> None:
    missing = symbols - prices.keys()
    if missing:
        raise ValueError(
            f"prices missing for symbol(s): {sorted(missing)} — router "
            "should have populated MarketData.prices for every book/delta symbol"
        )


def _look_through_or_empty(
    weights: dict[str, Decimal],
    holdings_provider: dict[str, list[Holding]],
) -> dict[str, Decimal]:
    """Wrap :func:`xray.look_through`, tolerating an empty input book."""
    if not weights:
        return {}
    portfolio = [Holding(symbol=s, weight=w) for s, w in weights.items()]
    return look_through(portfolio, holdings_provider).effective


def _fill_exposure_diffs(
    diff: WhatIfDiff,
    current: dict[str, Decimal],
    projected: dict[str, Decimal],
) -> None:
    symbols = sorted(set(current) | set(projected))
    for sym in symbols:
        c = float(current[sym]) if sym in current else 0.0
        p = float(projected[sym]) if sym in projected else 0.0
        diff.exposure_diffs.append(
            MetricDiff(metric=sym, current=c, projected=p, delta=p - c)
        )


def _fill_rollup_diffs(
    dst: list[MetricDiff],
    current: dict[str, Decimal],
    projected: dict[str, Decimal],
    attribute_provider: dict[str, Holding],
    attribute: str,
) -> None:
    c_roll = rollup_by(current, attribute_provider, attribute) if current else {}
    p_roll = rollup_by(projected, attribute_provider, attribute) if projected else {}
    keys = sorted(set(c_roll) | set(p_roll))
    for k in keys:
        c = float(c_roll.get(k, Decimal("0")))
        p = float(p_roll.get(k, Decimal("0")))
        dst.append(MetricDiff(metric=k, current=c, projected=p, delta=p - c))


def _fill_concentration_diffs(
    diff: WhatIfDiff,
    current: dict[str, Decimal],
    projected: dict[str, Decimal],
) -> None:
    def _hhi_en(exp: dict[str, Decimal]) -> tuple[float, float]:
        if not exp:
            return 0.0, 0.0
        h = float(herfindahl_hirschman(exp))
        en = float(effective_n(Decimal(str(h)))) if h > 0 else 0.0
        return h, en

    def _topk(exp: dict[str, Decimal], k: int) -> float:
        if not exp:
            return 0.0
        sorted_w = sorted((float(w) for w in exp.values()), reverse=True)
        return float(sum(sorted_w[:k]))

    c_hhi, c_en = _hhi_en(current)
    p_hhi, p_en = _hhi_en(projected)
    diff.concentration_diffs.append(
        MetricDiff(metric="hhi", current=c_hhi, projected=p_hhi, delta=p_hhi - c_hhi)
    )
    diff.concentration_diffs.append(
        MetricDiff(metric="effective_n", current=c_en, projected=p_en, delta=p_en - c_en)
    )
    for k in (1, 5, 10):
        c = _topk(current, k)
        p = _topk(projected, k)
        diff.concentration_diffs.append(
            MetricDiff(metric=f"top{k}", current=c, projected=p, delta=p - c)
        )


def _fill_risk_and_contrib_diffs(
    diff: WhatIfDiff,
    current_weights: dict[str, Decimal],
    projected_weights: dict[str, Decimal],
    md: MarketData,
) -> None:
    def _side(
        weights: dict[str, Decimal],
    ) -> tuple[float | None, float | None, float | None, float | None, dict[str, float]]:
        """Return (vol, var_95, cvar_95, beta, {symbol: component_var}).

        If **any** book symbol is missing from ``md.returns_symbols``, all
        aggregate rows return None. Silently dropping the missing weight
        from ``w`` would produce partial-book risk numbers that look
        clean but understate the true variance — the caller has no
        signal that ~1/N of the book's contribution is missing. Only
        return numbers when the returns matrix fully covers the book.
        """
        if not weights:
            return None, None, None, None, {}
        # Refuse to compute aggregate risk if the returns matrix doesn't
        # cover every book symbol. Per-symbol contribution rows stay
        # per-symbol None below.
        missing_on_side = set(weights) - set(md.returns_symbols)
        if missing_on_side:
            return None, None, None, None, {}
        w = np.zeros(len(md.returns_symbols))
        for i, s in enumerate(md.returns_symbols):
            if s in weights:
                w[i] = float(weights[s])
        if w.sum() == 0:
            return None, None, None, None, {}
        vol = portfolio_volatility(w, md.cov)
        # Parametric VaR (Gaussian) — matches component_var's assumption.
        z = float(norm.ppf(0.95))
        var_95 = z * vol
        # Parametric CVaR — mean of the truncated normal tail.
        # E[X | X < -z] = phi(z) / (1 - Phi(z)), then scale by sigma.
        cvar_95 = float(norm.pdf(z) / (1 - norm.cdf(z))) * vol
        # Beta needs the portfolio return series, not weights.
        port_ts = md.returns @ w
        beta = portfolio_beta(port_ts, md.benchmark_returns)
        comp = component_var(w, md.cov, confidence=0.95)
        return vol, var_95, cvar_95, beta, dict(zip(md.returns_symbols, comp.tolist()))

    def _both_none_warn(sym: str) -> MetricDiff:
        return MetricDiff(metric=sym, current=None, projected=None, delta=None)

    # Emit warnings for book symbols missing from returns_symbols. When
    # this set is non-empty, aggregate risk rows will be None for BOTH
    # sides (the missing-symbol data drift affects current and projected
    # identically; None keeps the diff apples-to-apples).
    book_symbols = set(current_weights) | set(projected_weights)
    missing = book_symbols - set(md.returns_symbols)
    for m in sorted(missing):
        diff.warnings.append(
            f"{m}: no returns/covariance data — aggregate risk rows "
            "(volatility/var_95/cvar_95/beta) and this symbol's contribution "
            "row are None"
        )

    c_vol, c_var, c_cvar, c_beta, c_comp = _side(current_weights)
    p_vol, p_var, p_cvar, p_beta, p_comp = _side(projected_weights)

    diff.risk_diffs.append(_row("volatility", c_vol, p_vol))
    diff.risk_diffs.append(_row("var_95", c_var, p_var))
    diff.risk_diffs.append(_row("cvar_95", c_cvar, p_cvar))
    diff.risk_diffs.append(_row("beta", c_beta, p_beta))

    # Contribution: one row per symbol in the union of both sides' returns_symbols
    # intersect book. Book symbols not in returns_symbols get all-None rows.
    contrib_syms = sorted(book_symbols & set(md.returns_symbols))
    for sym in contrib_syms:
        c = c_comp.get(sym)
        p = p_comp.get(sym)
        diff.contribution_diffs.append(_row(sym, c, p))
    for sym in sorted(missing):
        diff.contribution_diffs.append(_both_none_warn(sym))


def _row(metric: str, c: float | None, p: float | None) -> MetricDiff:
    delta = None if (c is None or p is None) else p - c
    return MetricDiff(metric=metric, current=c, projected=p, delta=delta)
