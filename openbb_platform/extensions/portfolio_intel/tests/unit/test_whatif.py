"""Unit tests for the What-If diff engine (#558).

Pure-function tests, hand-built inputs, no fixtures beyond in-line dicts
and numpy arrays. Design: docs/superpowers/specs/2026-07-19-whatif-diff-engine-design.md

Scope narrowed vs original design (see PR body + #903, #904):
- **Self-financing only** — no cash line; projected weights renormalize to 1.0.
- **No short positions** — `projected_qty < 0` raises ValueError.
- **Parametric VaR** — the What-If risk row uses parametric (Gaussian)
  VaR/CVaR so the Euler component-sum identity holds. Historical VaR is
  what `risk.value_at_risk` computes and is NOT what What-If reports.
"""

from __future__ import annotations

import math
from decimal import Decimal

import numpy as np
import pytest
from openbb_portfolio_intel.analytics.whatif import (
    Delta,
    MarketData,
    MetricDiff,
    PositionQty,
    WhatIfDiff,
    run_whatif,
)
from openbb_portfolio_intel.analytics.xray import Holding

# ---------------------------------------------------------------------------
# Fixture builders (small helpers, not pytest fixtures — kept local + explicit)
# ---------------------------------------------------------------------------


def _md(
    prices: dict[str, Decimal],
    *,
    attribute_provider: dict[str, Holding] | None = None,
    holdings_provider: dict[str, list[Holding]] | None = None,
    returns_symbols: list[str] | None = None,
    returns: np.ndarray | None = None,
    cov: np.ndarray | None = None,
    benchmark_returns: np.ndarray | None = None,
) -> MarketData:
    """Build a MarketData with sensible defaults for the given prices."""
    syms = list(prices.keys()) if returns_symbols is None else returns_symbols
    T = 100
    rng = np.random.default_rng(seed=7)
    if returns is None:
        returns = rng.normal(loc=0.0005, scale=0.01, size=(T, len(syms)))
    if cov is None:
        cov = (
            np.cov(returns, rowvar=False, ddof=1)
            if len(syms) > 1
            else np.array([[0.0001]])
        )
    if benchmark_returns is None:
        benchmark_returns = rng.normal(loc=0.0004, scale=0.008, size=T)
    if attribute_provider is None:
        attribute_provider = {
            s: Holding(symbol=s, weight=Decimal("1"), sector="Tech", country="US")
            for s in syms
        }
    if holdings_provider is None:
        holdings_provider = {}
    return MarketData(
        prices=prices,
        holdings_provider=holdings_provider,
        attribute_provider=attribute_provider,
        returns=returns,
        returns_symbols=syms,
        cov=cov,
        benchmark_returns=benchmark_returns,
    )


def _base_book() -> tuple[list[PositionQty], MarketData]:
    """3-position equally-priced book — 100 shares each of AAPL/MSFT/NVDA."""
    positions = [
        PositionQty(symbol="AAPL", qty=Decimal("100")),
        PositionQty(symbol="MSFT", qty=Decimal("100")),
        PositionQty(symbol="NVDA", qty=Decimal("100")),
    ]
    prices = {
        "AAPL": Decimal("100"),
        "MSFT": Decimal("100"),
        "NVDA": Decimal("100"),
    }
    attribute_provider = {
        "AAPL": Holding(
            symbol="AAPL", weight=Decimal("1"), sector="Tech", country="US"
        ),
        "MSFT": Holding(
            symbol="MSFT", weight=Decimal("1"), sector="Tech", country="US"
        ),
        "NVDA": Holding(
            symbol="NVDA", weight=Decimal("1"), sector="Semi", country="US"
        ),
    }
    md = _md(prices, attribute_provider=attribute_provider)
    return positions, md


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_happy_path_buy_delta_shifts_weights_and_sector() -> None:
    """A buy delta increases the bought symbol's weight and its sector."""
    positions, md = _base_book()
    deltas = [Delta(symbol="NVDA", delta_qty=Decimal("100"))]

    diff = run_whatif(positions, deltas, md)

    assert isinstance(diff, WhatIfDiff)
    # NVDA exposure should be higher post-trade.
    nvda_row = _by_metric(diff.exposure_diffs, "NVDA")
    assert nvda_row.current is not None and nvda_row.projected is not None
    assert nvda_row.projected > nvda_row.current
    assert nvda_row.delta > 0
    # Semi sector rises (NVDA is Semi).
    semi_row = _by_metric(diff.sector_diffs, "Semi")
    assert semi_row.delta > 0
    # Tech sector drops (AAPL+MSFT diluted by pro-rata renormalization).
    tech_row = _by_metric(diff.sector_diffs, "Tech")
    assert tech_row.delta < 0


# ---------------------------------------------------------------------------
# 2. Empty deltas
# ---------------------------------------------------------------------------


def test_empty_deltas_produces_zero_delta_diff() -> None:
    """No deltas → every projected == current, no warnings."""
    positions, md = _base_book()

    diff = run_whatif(positions, [], md)

    for row in diff.exposure_diffs:
        assert math.isclose(row.delta, 0.0, abs_tol=1e-12)
    # Only the standing self-financing note; no per-symbol warnings.
    assert not any("closes position" in w for w in diff.warnings)
    assert not any("no returns" in w for w in diff.warnings)


# ---------------------------------------------------------------------------
# 3. Close position
# ---------------------------------------------------------------------------


def test_close_position_removes_symbol_and_warns() -> None:
    """delta_qty = -current_qty → symbol removed from projected weight rows."""
    positions, md = _base_book()
    deltas = [Delta(symbol="AAPL", delta_qty=Decimal("-100"))]

    diff = run_whatif(positions, deltas, md)

    aapl = _by_metric(diff.exposure_diffs, "AAPL")
    # AAPL had non-zero current; projected must be exactly 0.0 (removed from book).
    assert aapl.current > 0
    assert aapl.projected == 0.0
    assert any("AAPL" in w and "closes position" in w for w in diff.warnings)


# ---------------------------------------------------------------------------
# 4. Short reject (scope-cut, follow-up: #904)
# ---------------------------------------------------------------------------


def test_flip_to_short_raises_valueerror() -> None:
    """Initial ship rejects negative projected qty — deferred to #904."""
    positions, md = _base_book()
    deltas = [Delta(symbol="AAPL", delta_qty=Decimal("-150"))]  # closes + shorts 50

    with pytest.raises(ValueError, match=r"short"):
        run_whatif(positions, deltas, md)


# ---------------------------------------------------------------------------
# 5. New symbol via delta
# ---------------------------------------------------------------------------


def test_new_symbol_via_delta_appears_in_projected_only() -> None:
    """Buying a symbol not in the current book yields a new-position row."""
    positions, md = _base_book()
    # Extend market data with a 4th symbol.
    md = MarketData(
        prices={**md.prices, "GOOG": Decimal("150")},
        holdings_provider=md.holdings_provider,
        attribute_provider={
            **md.attribute_provider,
            "GOOG": Holding(
                symbol="GOOG", weight=Decimal("1"), sector="Tech", country="US"
            ),
        },
        returns=np.hstack([md.returns, md.returns[:, :1] * 0.9]),
        returns_symbols=md.returns_symbols + ["GOOG"],
        cov=np.pad(md.cov, ((0, 1), (0, 1)), mode="constant"),
        benchmark_returns=md.benchmark_returns,
    )
    # Fix the padded cov diagonal so it's positive.
    md.cov[-1, -1] = 0.0002

    deltas = [Delta(symbol="GOOG", delta_qty=Decimal("50"))]
    diff = run_whatif(positions, deltas, md)

    goog = _by_metric(diff.exposure_diffs, "GOOG")
    assert goog.current == 0.0 or goog.current is None
    assert goog.projected > 0


# ---------------------------------------------------------------------------
# 6. Symbol missing from returns matrix
# ---------------------------------------------------------------------------


def test_symbol_missing_from_returns_matrix_degrades_risk_row() -> None:
    """Xray unaffected, risk row emits None + warning."""
    positions, md = _base_book()
    # Remove NVDA from returns_symbols (and shrink cov+returns to match).
    keep = [i for i, s in enumerate(md.returns_symbols) if s != "NVDA"]
    md = MarketData(
        prices=md.prices,
        holdings_provider=md.holdings_provider,
        attribute_provider=md.attribute_provider,
        returns=md.returns[:, keep],
        returns_symbols=[md.returns_symbols[i] for i in keep],
        cov=md.cov[np.ix_(keep, keep)],
        benchmark_returns=md.benchmark_returns,
    )

    diff = run_whatif(positions, [Delta(symbol="AAPL", delta_qty=Decimal("10"))], md)

    # Xray row for NVDA is still present.
    assert _by_metric(diff.exposure_diffs, "NVDA") is not None
    # Contribution row for NVDA is None-None-None.
    nvda_contrib = _by_metric(diff.contribution_diffs, "NVDA")
    assert nvda_contrib.current is None and nvda_contrib.projected is None
    # AGGREGATE risk rows are None on both sides — silently reporting
    # partial-book variance would mislead the user (only ~2/3 of book
    # covered by returns matrix, and there's no visual signal at that row).
    for metric in ("volatility", "var_95", "cvar_95", "beta"):
        row = _by_metric(diff.risk_diffs, metric)
        assert row.current is None, f"{metric}.current should be None"
        assert row.projected is None, f"{metric}.projected should be None"
        assert row.delta is None, f"{metric}.delta should be None"
    assert any("NVDA" in w for w in diff.warnings)


def test_partial_returns_coverage_does_not_leak_partial_book_variance() -> None:
    """Reverse-verification for R7.11: even a single-symbol drop must yield None risk.

    If we compute risk on the covered subset (silently), the returned var_95
    would be a plausible non-None float that the caller cannot distinguish
    from a valid full-book VaR. This test catches that regression.
    """
    positions, md = _base_book()
    # Two-symbol book, one-symbol returns matrix — max partial-coverage scenario.
    positions = positions[:2]  # AAPL + MSFT only
    keep = [i for i, s in enumerate(md.returns_symbols) if s == "AAPL"]
    md = MarketData(
        prices=md.prices,
        holdings_provider=md.holdings_provider,
        attribute_provider=md.attribute_provider,
        returns=md.returns[:, keep],
        returns_symbols=[md.returns_symbols[i] for i in keep],
        cov=md.cov[np.ix_(keep, keep)],
        benchmark_returns=md.benchmark_returns,
    )
    diff = run_whatif(positions, [], md)
    var_row = _by_metric(diff.risk_diffs, "var_95")
    assert var_row.current is None
    assert var_row.projected is None


# ---------------------------------------------------------------------------
# 7. Missing price
# ---------------------------------------------------------------------------


def test_missing_price_raises_valueerror_naming_symbol() -> None:
    """Router should have caught this; failing loud names the offending symbol."""
    positions, md = _base_book()
    md = MarketData(
        prices={k: v for k, v in md.prices.items() if k != "NVDA"},
        holdings_provider=md.holdings_provider,
        attribute_provider=md.attribute_provider,
        returns=md.returns,
        returns_symbols=md.returns_symbols,
        cov=md.cov,
        benchmark_returns=md.benchmark_returns,
    )
    with pytest.raises(ValueError, match=r"NVDA"):
        run_whatif(positions, [], md)


# ---------------------------------------------------------------------------
# 8. Fully-liquidated projected book
# ---------------------------------------------------------------------------


def test_fully_liquidated_book_raises() -> None:
    """Analytics on an empty projected book have no meaning."""
    positions, md = _base_book()
    deltas = [
        Delta(symbol="AAPL", delta_qty=Decimal("-100")),
        Delta(symbol="MSFT", delta_qty=Decimal("-100")),
        Delta(symbol="NVDA", delta_qty=Decimal("-100")),
    ]
    with pytest.raises(ValueError, match=r"empty|liquidated"):
        run_whatif(positions, deltas, md)


# ---------------------------------------------------------------------------
# 9. Weight normalization invariant
# ---------------------------------------------------------------------------


def test_projected_weights_sum_to_one_within_tolerance() -> None:
    """Self-financing renormalization keeps the projected weight sum at 1.0."""
    positions, md = _base_book()
    deltas = [Delta(symbol="AAPL", delta_qty=Decimal("37"))]
    diff = run_whatif(positions, deltas, md)

    total = sum(r.projected for r in diff.exposure_diffs if r.projected is not None)
    assert math.isclose(total, 1.0, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 10. HHI monotonicity
# ---------------------------------------------------------------------------


def test_concentrating_into_one_name_raises_hhi() -> None:
    """Buying so much of one name that it dominates the book raises HHI."""
    positions, md = _base_book()
    # Buy 10,000 shares of NVDA at $100 → dominates the $30k book.
    deltas = [Delta(symbol="NVDA", delta_qty=Decimal("10000"))]
    diff = run_whatif(positions, deltas, md)

    hhi = _by_metric(diff.concentration_diffs, "hhi")
    en = _by_metric(diff.concentration_diffs, "effective_n")
    assert hhi.projected > hhi.current
    assert en.projected < en.current


# ---------------------------------------------------------------------------
# 11. Component-VaR sums to parametric VaR
# ---------------------------------------------------------------------------


def test_component_var_sums_to_parametric_var() -> None:
    """The Euler identity holds under parametric VaR (Gaussian assumption)."""
    positions, md = _base_book()
    diff = run_whatif(positions, [], md)  # no deltas — current == projected

    comp_sum = sum(
        r.projected for r in diff.contribution_diffs if r.projected is not None
    )
    var_row = _by_metric(diff.risk_diffs, "var_95")
    assert var_row.projected is not None
    assert math.isclose(comp_sum, var_row.projected, rel_tol=1e-6, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 12. ETF unwrap through look_through
# ---------------------------------------------------------------------------


def test_etf_delta_affects_underlying_exposures() -> None:
    """A delta on an ETF affects underlying single-security exposures."""
    positions = [
        PositionQty(symbol="SPY", qty=Decimal("100")),
        PositionQty(symbol="AAPL", qty=Decimal("100")),
    ]
    prices = {"SPY": Decimal("400"), "AAPL": Decimal("200")}
    attribute_provider = {
        "AAPL": Holding(
            symbol="AAPL", weight=Decimal("1"), sector="Tech", country="US"
        ),
        "MSFT": Holding(
            symbol="MSFT", weight=Decimal("1"), sector="Tech", country="US"
        ),
    }
    holdings_provider = {
        "SPY": [
            Holding(symbol="AAPL", weight=Decimal("0.6")),
            Holding(symbol="MSFT", weight=Decimal("0.4")),
        ],
    }
    md = _md(
        prices,
        attribute_provider=attribute_provider,
        holdings_provider=holdings_provider,
        returns_symbols=["SPY", "AAPL"],
    )
    deltas = [Delta(symbol="SPY", delta_qty=Decimal("50"))]

    diff = run_whatif(positions, deltas, md)

    # AAPL underlying exposure shifts because SPY holds AAPL.
    aapl_underlying = _by_metric(diff.exposure_diffs, "AAPL")
    assert aapl_underlying.projected != aapl_underlying.current
    # MSFT appears only as an SPY underlying — should have projected > 0.
    msft_underlying = _by_metric(diff.exposure_diffs, "MSFT")
    assert msft_underlying.projected > 0


# ---------------------------------------------------------------------------
# 13. Determinism (tolerance-based, not byte-identical — 9.7 addressed)
# ---------------------------------------------------------------------------


def test_determinism_tolerance_based() -> None:
    """Two runs on identical inputs produce equal outputs within fp tolerance (finding 9.7)."""
    positions, md = _base_book()
    deltas = [Delta(symbol="NVDA", delta_qty=Decimal("10"))]
    d1 = run_whatif(positions, deltas, md)
    d2 = run_whatif(positions, deltas, md)

    for a, b in zip(d1.risk_diffs, d2.risk_diffs):
        assert a.metric == b.metric
        assert _isclose_or_both_none(a.projected, b.projected)
        assert _isclose_or_both_none(a.current, b.current)


# ---------------------------------------------------------------------------
# 14. Missing sector/country attribute → "(unknown)" bucket
# ---------------------------------------------------------------------------


def test_missing_sector_rolls_up_as_unknown() -> None:
    """Symbols without a sector/country attribute land in the '(unknown)' bucket."""
    positions, md = _base_book()
    # Wipe NVDA's attribute so it rolls up as unknown.
    md = MarketData(
        prices=md.prices,
        holdings_provider=md.holdings_provider,
        attribute_provider={
            k: v for k, v in md.attribute_provider.items() if k != "NVDA"
        },
        returns=md.returns,
        returns_symbols=md.returns_symbols,
        cov=md.cov,
        benchmark_returns=md.benchmark_returns,
    )
    diff = run_whatif(positions, [], md)
    # "(unknown)" bucket in sector rollup carries NVDA's weight.
    unknown = _by_metric(diff.sector_diffs, "(unknown)")
    assert unknown is not None


# ---------------------------------------------------------------------------
# 15. Beta shape guard — mismatched length propagates ValueError
# ---------------------------------------------------------------------------


def test_beta_shape_mismatch_propagates() -> None:
    """Underlying risk.portfolio_beta length check propagates as ValueError."""
    positions, md = _base_book()
    md = MarketData(
        prices=md.prices,
        holdings_provider=md.holdings_provider,
        attribute_provider=md.attribute_provider,
        returns=md.returns,
        returns_symbols=md.returns_symbols,
        cov=md.cov,
        benchmark_returns=md.benchmark_returns[:50],  # wrong length
    )
    with pytest.raises(ValueError):
        run_whatif(positions, [], md)


# ---------------------------------------------------------------------------
# 16. Shape/PSD guards (finding 9.8)
# ---------------------------------------------------------------------------


def test_cov_shape_mismatch_raises() -> None:
    """MarketData shape guard fails loud on cov/returns_symbols mismatch (finding 9.8)."""
    positions, md = _base_book()
    md = MarketData(
        prices=md.prices,
        holdings_provider=md.holdings_provider,
        attribute_provider=md.attribute_provider,
        returns=md.returns,
        returns_symbols=md.returns_symbols,
        cov=np.zeros((2, 2)),  # wrong shape (should be 3x3)
        benchmark_returns=md.benchmark_returns,
    )
    with pytest.raises(ValueError, match=r"cov"):
        run_whatif(positions, [], md)


def test_nan_in_cov_raises_loud() -> None:
    """NaN in cov silently poisons var_95/component_var — refuse at the boundary."""
    positions, md = _base_book()
    cov = md.cov.copy()
    cov[0, 0] = np.nan
    md = MarketData(
        prices=md.prices,
        holdings_provider=md.holdings_provider,
        attribute_provider=md.attribute_provider,
        returns=md.returns,
        returns_symbols=md.returns_symbols,
        cov=cov,
        benchmark_returns=md.benchmark_returns,
    )
    with pytest.raises(ValueError, match=r"NaN"):
        run_whatif(positions, [], md)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _by_metric(rows: list[MetricDiff], name: str) -> MetricDiff | None:
    for r in rows:
        if r.metric == name:
            return r
    return None


def _isclose_or_both_none(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
