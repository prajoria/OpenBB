"""Unit tests for /portfolio_intel/risk + /concentration routes (#528).

All offline — `_fetch_holdings` and returns computation patched. One
@pytest.mark.integration smoke against live fmp_cached.

Design: docs/superpowers/specs/2026-07-19-risk-concentration-routes-design.md
"""

from __future__ import annotations

from decimal import Decimal
from math import isfinite, sqrt
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from openbb_portfolio_intel.models import (
    ConcentrationSummary,
    RiskMetricsResult,
)
from openbb_portfolio_intel.routers.risk_router import (
    concentration,
    metrics,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _mk_holdings(rows):
    """MagicMock list of EtfHoldingsData-like rows."""
    out = []
    for symbol, weight, sector, country in rows:
        row = MagicMock()
        row.symbol = symbol
        row.weight = weight
        row.sector = sector
        row.country = country
        out.append(row)
    return out


def _mk_response(rows):
    resp = MagicMock()
    resp.results = rows
    return resp


def _synthetic_returns(seed: int, length: int) -> list[float]:
    rng = np.random.default_rng(seed=seed)
    return rng.normal(loc=0.0005, scale=0.012, size=length).tolist()


def _assert_valid_concentration(result: ConcentrationSummary) -> None:
    values = (
        result.hhi,
        result.effective_n,
        result.top1,
        result.top5,
        result.top10,
    )
    assert all(isfinite(value) for value in values)
    assert 0.0 < result.hhi <= 1.0
    assert result.effective_n == pytest.approx(1.0 / result.hhi)
    assert 0.0 < result.top1 <= result.top5 <= result.top10 <= 1.0
    assert result.hhi <= result.top1 <= sqrt(result.hhi) + 1e-12


# ---------------------------------------------------------------------------
# /risk/metrics — happy path
# ---------------------------------------------------------------------------


def test_metrics_happy_path_three_asset_basket() -> None:
    """3-asset basket + hand-built returns → sane vol / var / cvar / beta."""
    basket = [
        {"symbol": "AAPL", "weight": Decimal("0.5")},
        {"symbol": "MSFT", "weight": Decimal("0.3")},
        {"symbol": "NVDA", "weight": Decimal("0.2")},
    ]
    T = 250
    returns_source = {
        "AAPL": _synthetic_returns(1, T),
        "MSFT": _synthetic_returns(2, T),
        "NVDA": _synthetic_returns(3, T),
    }
    benchmark_returns = _synthetic_returns(99, T)

    obj = metrics(
        basket=basket,
        returns_source=returns_source,
        benchmark_returns=benchmark_returns,
    )
    res = obj.results
    assert isinstance(res, RiskMetricsResult)
    assert res.volatility is not None and res.volatility > 0
    assert res.var_95 is not None and res.var_95 > 0
    assert (
        res.cvar_95 is not None and res.cvar_95 >= res.var_95
    ), "CVaR must be ≥ VaR by construction"
    assert res.beta is not None  # any float; unrelated series → beta near 0


def test_metrics_beta_close_to_one_when_portfolio_equals_benchmark() -> None:
    """Portfolio return series ~ benchmark → beta ≈ 1.0."""
    T = 250
    series = _synthetic_returns(42, T)
    basket = [{"symbol": "SPY", "weight": Decimal("1")}]
    obj = metrics(
        basket=basket,
        returns_source={"SPY": series},
        benchmark_returns=series,  # identical
    )
    assert abs(obj.results.beta - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# /risk/metrics — degraded paths
# ---------------------------------------------------------------------------


def test_metrics_missing_returns_for_symbol_returns_none_with_warning() -> None:
    """Basket has a symbol not in returns_source → all metrics None + warning."""
    basket = [
        {"symbol": "AAPL", "weight": Decimal("0.5")},
        {"symbol": "MSFT", "weight": Decimal("0.5")},
    ]
    T = 250
    obj = metrics(
        basket=basket,
        returns_source={"AAPL": _synthetic_returns(1, T)},  # MSFT missing
        benchmark_returns=_synthetic_returns(99, T),
    )
    res = obj.results
    assert res.volatility is None
    assert res.var_95 is None
    assert res.cvar_95 is None
    assert res.beta is None
    assert any("MSFT" in w for w in res.warnings)


def test_metrics_empty_basket_raises() -> None:
    """Explicit empty-basket guard."""
    with pytest.raises(ValueError, match=r"empty|at least one"):
        metrics(
            basket=[],
            returns_source={},
            benchmark_returns=_synthetic_returns(1, 100),
        )


def test_metrics_negative_weight_raises() -> None:
    """Shorts deferred to same follow-up as What-If #904."""
    with pytest.raises(ValueError, match=r"negative|short"):
        metrics(
            basket=[
                {"symbol": "AAPL", "weight": Decimal("1.5")},
                {"symbol": "MSFT", "weight": Decimal("-0.5")},
            ],
            returns_source={
                "AAPL": _synthetic_returns(1, 100),
                "MSFT": _synthetic_returns(2, 100),
            },
            benchmark_returns=_synthetic_returns(99, 100),
        )


def test_metrics_weights_not_summing_to_one_raises() -> None:
    """Sum-to-1 invariant enforced at route boundary."""
    with pytest.raises(ValueError, match=r"sum|1"):
        metrics(
            basket=[
                {"symbol": "AAPL", "weight": Decimal("0.3")},
                {"symbol": "MSFT", "weight": Decimal("0.3")},
            ],
            returns_source={
                "AAPL": _synthetic_returns(1, 100),
                "MSFT": _synthetic_returns(2, 100),
            },
            benchmark_returns=_synthetic_returns(99, 100),
        )


def test_metrics_benchmark_length_mismatch_raises() -> None:
    """Length invariant: benchmark_returns length must match returns_source rows."""
    basket = [{"symbol": "AAPL", "weight": Decimal("1")}]
    with pytest.raises(ValueError, match=r"length|shape|match"):
        metrics(
            basket=basket,
            returns_source={"AAPL": _synthetic_returns(1, 100)},
            benchmark_returns=_synthetic_returns(99, 50),  # too short
        )


def test_metrics_determinism_same_input_same_output() -> None:
    """Route is deterministic — same inputs, same outputs (tol-based)."""
    basket = [{"symbol": "AAPL", "weight": Decimal("1")}]
    kwargs = dict(
        basket=basket,
        returns_source={"AAPL": _synthetic_returns(1, 100)},
        benchmark_returns=_synthetic_returns(99, 100),
    )
    r1 = metrics(**kwargs).results
    r2 = metrics(**kwargs).results
    assert r1.volatility == pytest.approx(r2.volatility)
    assert r1.var_95 == pytest.approx(r2.var_95)
    assert r1.beta == pytest.approx(r2.beta)


# ---------------------------------------------------------------------------
# /risk/concentration
# ---------------------------------------------------------------------------


def test_concentration_single_holding_maxed_out() -> None:
    """100% one-stock basket → hhi=1.0, effective_n=1.0."""
    # Patch at the xray_router seam — that's where _build_holdings_provider
    # (imported by risk_router) actually calls _fetch_holdings from.
    with patch(
        "openbb_portfolio_intel.routers.xray_router._fetch_holdings",
        return_value=_mk_response([]),
    ):
        obj = concentration(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            provider="fmp_cached",
        )
    res = obj.results
    assert isinstance(res, ConcentrationSummary)
    assert res.hhi == pytest.approx(1.0)
    assert res.effective_n == pytest.approx(1.0)
    assert res.top1 == pytest.approx(1.0)


def test_concentration_etf_unwrap_produces_realistic_hhi() -> None:
    """100% SPY (mocked to 4 equal underlyings) → hhi=0.25, effective_n=4."""
    spy_rows = _mk_holdings(
        [
            ("AAPL", 0.25, "Tech", "US"),
            ("MSFT", 0.25, "Tech", "US"),
            ("NVDA", 0.25, "Semi", "US"),
            ("GOOG", 0.25, "Tech", "US"),
        ]
    )
    with patch(
        "openbb_portfolio_intel.routers.xray_router._fetch_holdings",
        side_effect=lambda symbol, provider=None: (
            _mk_response(spy_rows) if symbol == "SPY" else _mk_response([])
        ),
    ):
        obj = concentration(
            basket=[{"symbol": "SPY", "weight": Decimal("1")}],
            provider="fmp_cached",
        )
    res = obj.results
    assert res.hhi == pytest.approx(0.25, rel=1e-3)
    assert res.effective_n == pytest.approx(4.0, rel=1e-3)


def test_concentration_empty_basket_raises() -> None:
    """Explicit empty-basket guard."""
    with pytest.raises(ValueError, match=r"empty|at least one"):
        concentration(basket=[], provider="fmp_cached")


def test_concentration_negative_weight_raises() -> None:
    """Shorts deferred (same as metrics + xray)."""
    with pytest.raises(ValueError, match=r"negative|short"):
        concentration(
            basket=[
                {"symbol": "AAPL", "weight": Decimal("1.5")},
                {"symbol": "MSFT", "weight": Decimal("-0.5")},
            ],
            provider="fmp_cached",
        )


def test_concentration_determinism() -> None:
    """Two calls on identical input produce identical output."""
    with patch(
        "openbb_portfolio_intel.routers.xray_router._fetch_holdings",
        return_value=_mk_response([]),
    ):
        basket = [{"symbol": "AAPL", "weight": Decimal("1")}]
        r1 = concentration(basket=basket, provider="fmp_cached").results
        r2 = concentration(basket=basket, provider="fmp_cached").results
    assert r1.hhi == pytest.approx(r2.hhi)
    assert r1.effective_n == pytest.approx(r2.effective_n)


# ---------------------------------------------------------------------------
# Integration smoke
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"hhi": float("nan")},
        {"hhi": 0.0},
        {"effective_n": float("inf")},
        {"effective_n": 10.0},
        {"top1": 0.0},
        {"hhi": 0.2, "effective_n": 5.0},
        {"top1": 0.25},
        {"top5": 0.05},
        {"top10": 1.1},
    ],
)
def test_concentration_invariants_reject_malformed_output(overrides) -> None:
    """Non-finite, inconsistent, or impossible concentration values fail."""
    values = {
        "hhi": 0.04,
        "effective_n": 25.0,
        "top1": 0.1,
        "top5": 0.3,
        "top10": 0.5,
    }
    values.update(overrides)

    with pytest.raises(AssertionError):
        _assert_valid_concentration(ConcentrationSummary(**values))


@pytest.mark.integration
def test_live_concentration_spy_via_obb() -> None:
    """End-to-end live: SPY basket via real fmp_cached issuer tier."""
    from openbb import obb

    obj = obb.portfolio_intel.risk.concentration(
        basket=[{"symbol": "SPY", "weight": 1.0}],
        provider="fmp_cached",
    )
    res = obj.results
    _assert_valid_concentration(res)
