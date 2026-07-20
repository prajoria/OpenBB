"""Unit tests for /portfolio_intel/smart_money.rollup (#527)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from openbb_portfolio_intel.models import (
    SmartMoneyRollupResult,
)
from openbb_portfolio_intel.routers.smart_money_router import rollup


def _mk_insider(symbol: str, direction: int, weight: float) -> MagicMock:
    """Insider-transaction row (Form 4 shape). +ve amount = buy."""
    row = MagicMock()
    row.symbol = symbol
    # Insider fetcher usually exposes 'transaction_type' + 'amount' or 'shares'
    row.transaction_type = "P-Purchase" if direction > 0 else "S-Sale"
    row.shares = weight
    return row


def _mk_thirteen_f(symbol: str, direction: int, weight: float) -> MagicMock:
    """13F holding-change row."""
    row = MagicMock()
    row.symbol = symbol
    row.change = weight if direction >= 0 else -weight
    return row


def _mk_senate(symbol: str, direction: int, weight: float) -> MagicMock:
    """Senate disclosure row."""
    row = MagicMock()
    row.symbol = symbol
    row.transaction_type = "Purchase" if direction > 0 else "Sale"
    row.amount = weight
    return row


def _mk_response(rows: list[MagicMock]) -> MagicMock:
    resp = MagicMock()
    resp.results = rows
    return resp


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_rollup_happy_path_multi_source() -> None:
    """AAPL: insider-buy + 13F-buy + senate-buy → strong positive composite."""

    def _dispatch(kind, **_kwargs):
        if kind == "insider":
            return _mk_response([_mk_insider("AAPL", 1, 1000)])
        if kind == "form_13f":
            return _mk_response([_mk_thirteen_f("AAPL", 1, 5000)])
        if kind == "senate":
            return _mk_response([_mk_senate("AAPL", 1, 2000)])
        return _mk_response([])

    with patch(
        "openbb_portfolio_intel.routers.smart_money_router._fetch_signals",
        side_effect=_dispatch,
    ):
        obj = rollup(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            window_days=90,
            provider="fmp_cached",
        )
    res = obj.results
    assert isinstance(res, SmartMoneyRollupResult)
    assert "AAPL" in res.by_symbol
    aapl = res.by_symbol["AAPL"]
    assert aapl.composite > 0, "3 buy signals should produce positive composite"
    assert aapl.signal_count == 3
    assert len(res.top_conviction) >= 1
    assert res.top_conviction[0].symbol == "AAPL"


def test_rollup_portfolio_scoped_filter() -> None:
    """Signals for out-of-basket symbols are dropped."""

    def _dispatch(kind, **_kwargs):
        if kind == "insider":
            return _mk_response(
                [
                    _mk_insider("AAPL", 1, 100),
                    _mk_insider("TSLA", 1, 500),  # not in basket
                ]
            )
        return _mk_response([])

    with patch(
        "openbb_portfolio_intel.routers.smart_money_router._fetch_signals",
        side_effect=_dispatch,
    ):
        obj = rollup(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            window_days=90,
            provider="fmp_cached",
        )
    res = obj.results
    assert "AAPL" in res.by_symbol
    assert "TSLA" not in res.by_symbol


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_rollup_empty_basket_raises() -> None:
    """Empty basket is a config error (portfolio-intel route needs symbols)."""
    with pytest.raises(ValueError, match=r"empty|at least one"):
        rollup(basket=[], window_days=90, provider="fmp_cached")


def test_rollup_negative_window_raises() -> None:
    """window_days must be a positive lookback (0 and negative rejected)."""
    with pytest.raises(ValueError, match=r"window_days"):
        rollup(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            window_days=0,
            provider="fmp_cached",
        )
    with pytest.raises(ValueError, match=r"window_days"):
        rollup(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            window_days=-5,
            provider="fmp_cached",
        )


def test_rollup_negative_top_n_raises() -> None:
    """top_n must be positive."""
    with pytest.raises(ValueError, match=r"top_n"):
        rollup(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            window_days=90,
            top_n=0,
            provider="fmp_cached",
        )


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_rollup_source_failure_degrades_partial_result() -> None:
    """A fetch failure for one source → warning + partial result."""

    def _dispatch(kind, **_kwargs):
        if kind == "insider":
            raise RuntimeError("simulated 401")
        if kind == "form_13f":
            return _mk_response([_mk_thirteen_f("AAPL", 1, 1000)])
        return _mk_response([])

    with patch(
        "openbb_portfolio_intel.routers.smart_money_router._fetch_signals",
        side_effect=_dispatch,
    ):
        obj = rollup(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            window_days=90,
            provider="fmp_cached",
        )
    res = obj.results
    assert "AAPL" in res.by_symbol
    assert any("insider" in w.lower() for w in res.warnings)


def test_rollup_all_sources_empty_returns_empty_result() -> None:
    """No signals → empty by_symbol + empty top_conviction (no crash)."""
    with patch(
        "openbb_portfolio_intel.routers.smart_money_router._fetch_signals",
        return_value=_mk_response([]),
    ):
        obj = rollup(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            window_days=90,
            provider="fmp_cached",
        )
    res = obj.results
    assert res.by_symbol == {}
    assert res.top_conviction == []


# ---------------------------------------------------------------------------
# Determinism + envelope shape
# ---------------------------------------------------------------------------


def test_rollup_response_envelope_is_bare_obbject() -> None:
    """OBBject wraps SmartMoneyRollupResult (no double-envelope)."""
    with patch(
        "openbb_portfolio_intel.routers.smart_money_router._fetch_signals",
        return_value=_mk_response([]),
    ):
        obj = rollup(
            basket=[{"symbol": "AAPL", "weight": Decimal("1")}],
            window_days=90,
            provider="fmp_cached",
        )
    assert hasattr(obj, "results")
    assert isinstance(obj.results, SmartMoneyRollupResult)
    assert not hasattr(obj.results, "results")


def test_rollup_top_n_bounds_result() -> None:
    """top_n=2 with 5 buy signals → only 2 entries in top_conviction."""

    def _dispatch(kind, **_kwargs):
        if kind == "insider":
            return _mk_response(
                [
                    _mk_insider("A", 1, 100),
                    _mk_insider("B", 1, 200),
                    _mk_insider("C", 1, 300),
                    _mk_insider("D", 1, 400),
                    _mk_insider("E", 1, 500),
                ]
            )
        return _mk_response([])

    basket = [{"symbol": s, "weight": Decimal("0.2")} for s in "ABCDE"]
    with patch(
        "openbb_portfolio_intel.routers.smart_money_router._fetch_signals",
        side_effect=_dispatch,
    ):
        obj = rollup(
            basket=basket,
            window_days=90,
            top_n=2,
            provider="fmp_cached",
        )
    res = obj.results
    assert len(res.top_conviction) == 2
    # Highest-conviction (largest weight) should be E
    assert res.top_conviction[0].symbol == "E"
