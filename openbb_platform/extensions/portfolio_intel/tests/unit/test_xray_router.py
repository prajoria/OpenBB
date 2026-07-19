"""Unit tests for the /portfolio/intel/xray route (#541).

All offline — the ``obb.etf.holdings`` call is patched at the router seam
so no live network / fmp_cached call is made. The one integration smoke
is marked ``@pytest.mark.integration``.

Design: docs/superpowers/specs/2026-07-19-xray-route-design.md
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from openbb_portfolio_intel.models import (
    ConcentrationSummary,
    XRayLookThroughResult,
)
from openbb_portfolio_intel.routers.xray_router import (
    look_through,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _mk_holdings(
    rows: list[tuple[str, float, str | None, str | None]],
) -> list[MagicMock]:
    """Build a list of MagicMock EtfHoldingsData rows.

    Each tuple: (symbol, weight_fraction, sector, country).
    """
    out: list[MagicMock] = []
    for symbol, weight, sector, country in rows:
        row = MagicMock()
        row.symbol = symbol
        row.weight = weight
        row.sector = sector
        row.country = country
        out.append(row)
    return out


def _mk_response(rows: list[MagicMock]) -> MagicMock:
    """Wrap rows into an OBBject-like response with ``.results`` attr."""
    resp = MagicMock()
    resp.results = rows
    return resp


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_single_etf_basket_unwraps_to_underlyings() -> None:
    """100% SPY basket → mocked SPY holdings unwrap; effective weights correct."""
    spy_rows = _mk_holdings(
        [
            ("AAPL", 0.5, "Tech", "US"),
            ("MSFT", 0.3, "Tech", "US"),
            ("NVDA", 0.2, "Semi", "US"),
        ]
    )

    def _fake_holdings(symbol: str, provider: str | None = None) -> MagicMock:
        if symbol == "SPY":
            return _mk_response(spy_rows)
        return _mk_response([])

    with patch(
        "openbb_portfolio_intel.routers.xray_router._fetch_holdings",
        side_effect=_fake_holdings,
    ):
        obj = look_through(
            basket=[{"symbol": "SPY", "weight": Decimal("1")}],
            provider="fmp_cached",
        )
    result = obj.results
    assert isinstance(result, XRayLookThroughResult)
    # Underlyings are the SPY constituents
    assert set(result.effective.keys()) == {"AAPL", "MSFT", "NVDA"}
    assert result.effective["AAPL"] == pytest.approx(0.5)
    assert result.effective["MSFT"] == pytest.approx(0.3)
    assert result.effective["NVDA"] == pytest.approx(0.2)
    assert result.depth_reached == 1
    # Sector rollup matches
    assert result.sector_rollup["Tech"] == pytest.approx(0.8)
    assert result.sector_rollup["Semi"] == pytest.approx(0.2)


def test_mixed_basket_etf_plus_single_stock() -> None:
    """60% SPY + 40% GOOG (non-ETF) — SPY unwraps, GOOG passes through terminal."""
    spy_rows = _mk_holdings(
        [
            ("AAPL", 0.5, "Tech", "US"),
            ("MSFT", 0.5, "Tech", "US"),
        ]
    )

    def _fake(symbol: str, provider: str | None = None) -> MagicMock:
        return _mk_response(spy_rows if symbol == "SPY" else [])

    with patch(
        "openbb_portfolio_intel.routers.xray_router._fetch_holdings",
        side_effect=_fake,
    ):
        obj = look_through(
            basket=[
                {"symbol": "SPY", "weight": Decimal("0.6")},
                {"symbol": "GOOG", "weight": Decimal("0.4")},
            ],
            provider="fmp_cached",
        )
    result = obj.results
    # SPY 60% * 50% each = 30% AAPL, 30% MSFT. GOOG 40% terminal.
    assert result.effective["AAPL"] == pytest.approx(0.3)
    assert result.effective["MSFT"] == pytest.approx(0.3)
    assert result.effective["GOOG"] == pytest.approx(0.4)
    assert sum(result.effective.values()) == pytest.approx(1.0)


def test_nested_etf_of_etf() -> None:
    """FOF → SPY → 2 stocks; depth_reached = 2, effective is the terminals."""
    fof_rows = _mk_holdings([("SPY", 1.0, None, None)])
    spy_rows = _mk_holdings(
        [
            ("AAPL", 0.5, "Tech", "US"),
            ("MSFT", 0.5, "Tech", "US"),
        ]
    )

    def _fake(symbol: str, provider: str | None = None) -> MagicMock:
        return _mk_response({"FOF": fof_rows, "SPY": spy_rows}.get(symbol, []))

    with patch(
        "openbb_portfolio_intel.routers.xray_router._fetch_holdings",
        side_effect=_fake,
    ):
        obj = look_through(
            basket=[{"symbol": "FOF", "weight": Decimal("1")}],
            provider="fmp_cached",
        )
    result = obj.results
    assert result.depth_reached == 2
    assert result.effective["AAPL"] == pytest.approx(0.5)
    assert result.effective["MSFT"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Error paths (R7.11-friendly — revert guard, confirm failure)
# ---------------------------------------------------------------------------


def test_empty_basket_raises() -> None:
    """Explicit empty-basket guard fires with a clear message."""
    with pytest.raises(ValueError, match=r"empty|at least one"):
        look_through(basket=[], provider="fmp_cached")


def test_weights_not_summing_to_one_raises() -> None:
    """Sum-to-1 invariant propagated from xray.look_through."""
    with patch(
        "openbb_portfolio_intel.routers.xray_router._fetch_holdings",
        return_value=_mk_response([]),
    ), pytest.raises(ValueError, match=r"sum|1"):
        look_through(
            basket=[
                {"symbol": "AAPL", "weight": Decimal("0.3")},
                {"symbol": "MSFT", "weight": Decimal("0.3")},
            ],
            provider="fmp_cached",
        )


def test_negative_weight_raises() -> None:
    """Shorts are not supported in this cut (matches What-If #904)."""
    with pytest.raises(ValueError, match=r"negative|short"):
        look_through(
            basket=[
                {"symbol": "AAPL", "weight": Decimal("1.5")},
                {"symbol": "MSFT", "weight": Decimal("-0.5")},
            ],
            provider="fmp_cached",
        )


# ---------------------------------------------------------------------------
# Failure-mode: fetcher raises for a symbol
# ---------------------------------------------------------------------------


def test_holdings_fetch_failure_treated_as_unresolved() -> None:
    """If obb.etf.holdings raises for a symbol, it enters `unresolved` + warning."""

    def _fake(symbol: str, provider: str | None = None) -> MagicMock:
        if symbol == "BROKEN":
            raise RuntimeError("simulated provider outage")
        return _mk_response([])

    with patch(
        "openbb_portfolio_intel.routers.xray_router._fetch_holdings",
        side_effect=_fake,
    ):
        obj = look_through(
            basket=[
                {"symbol": "BROKEN", "weight": Decimal("0.5")},
                {"symbol": "AAPL", "weight": Decimal("0.5")},
            ],
            provider="fmp_cached",
        )
    result = obj.results
    # BROKEN kept at face value
    assert result.effective["BROKEN"] == pytest.approx(0.5)
    assert "BROKEN" in result.unresolved
    assert any("BROKEN" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Sector-rollup unknown bucket
# ---------------------------------------------------------------------------


def test_single_stock_basket_rolls_up_as_unknown_sector() -> None:
    """Non-ETF singletons have no attribute row → '(unknown)' sector."""
    with patch(
        "openbb_portfolio_intel.routers.xray_router._fetch_holdings",
        return_value=_mk_response([]),
    ):
        obj = look_through(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            provider="fmp_cached",
        )
    result = obj.results
    assert result.effective["AAPL"] == pytest.approx(1.0)
    assert result.sector_rollup.get("(unknown)") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Concentration invariants
# ---------------------------------------------------------------------------


def test_single_holding_concentration_maxed_out() -> None:
    """100% one-stock basket → hhi = 1.0, effective_n = 1.0, top1 = 1.0."""
    with patch(
        "openbb_portfolio_intel.routers.xray_router._fetch_holdings",
        return_value=_mk_response([]),
    ):
        obj = look_through(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            provider="fmp_cached",
        )
    c = obj.results.concentration
    assert isinstance(c, ConcentrationSummary)
    assert c.hhi == pytest.approx(1.0)
    assert c.effective_n == pytest.approx(1.0)
    assert c.top1 == pytest.approx(1.0)


def test_equal_weight_basket_concentration() -> None:
    """3 equal holdings → hhi = 3 * (1/3)^2 = 1/3, effective_n = 3."""
    with patch(
        "openbb_portfolio_intel.routers.xray_router._fetch_holdings",
        return_value=_mk_response([]),
    ):
        w = Decimal("1") / Decimal("3")
        obj = look_through(
            basket=[
                {"symbol": "AAPL", "weight": w},
                {"symbol": "MSFT", "weight": w},
                {"symbol": "NVDA", "weight": Decimal("1") - 2 * w},
            ],
            provider="fmp_cached",
        )
    c = obj.results.concentration
    assert c.hhi == pytest.approx(1 / 3, rel=1e-3)
    assert c.effective_n == pytest.approx(3.0, rel=1e-3)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism_same_input_same_output() -> None:
    """Route is deterministic — same inputs, same outputs (tolerance-based)."""
    with patch(
        "openbb_portfolio_intel.routers.xray_router._fetch_holdings",
        return_value=_mk_response(
            _mk_holdings(
                [
                    ("AAPL", 0.6, "Tech", "US"),
                    ("MSFT", 0.4, "Tech", "US"),
                ]
            )
        ),
    ):
        basket = [{"symbol": "SPY", "weight": Decimal("1")}]
        r1 = look_through(basket=basket, provider="fmp_cached").results
        r2 = look_through(basket=basket, provider="fmp_cached").results
    assert r1.effective == r2.effective
    assert r1.sector_rollup == r2.sector_rollup


# ---------------------------------------------------------------------------
# Response shape guard
# ---------------------------------------------------------------------------


def test_response_envelope_is_obbject_wrapping_xray_result() -> None:
    """Route returns OBBject[XRayLookThroughResult] — not raw dict, not double-wrapped."""
    with patch(
        "openbb_portfolio_intel.routers.xray_router._fetch_holdings",
        return_value=_mk_response([]),
    ):
        obj = look_through(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            provider="fmp_cached",
        )
    # OBBject envelope with .results, not .results.results
    assert hasattr(obj, "results")
    assert isinstance(obj.results, XRayLookThroughResult)
    assert not hasattr(obj.results, "results")


# ---------------------------------------------------------------------------
# Live integration smoke (skipped without keys)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_live_xray_look_through_spy_via_obb() -> None:
    """End-to-end via obb.etf.holdings hitting real fmp_cached issuer tier."""
    from openbb import obb

    obj = obb.portfolio_intel.xray.look_through(
        basket=[{"symbol": "SPY", "weight": 1.0}],
        provider="fmp_cached",
    )
    result = obj.results
    assert (
        len(result.effective) > 400
    ), f"expected >400 SPY underlyings, got {len(result.effective)}"
    total = sum(result.effective.values())
    assert 0.99 < total < 1.01, f"effective weights sum to {total}, expected ~1.0"
