"""Unit tests for the backtest hand-off contract (#561).

Tests the shape / conversion / validation surface. The actual paper-side
persistence lives in the paper-trading subsystem (#544-548).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from openbb_portfolio_intel.handoff import (
    BacktestExport,
    PaperFill,
    PaperSide,
    build_export,
    verify_exportable,
)
from openbb_portfolio_intel.handoff.backtest_export import _backtest_trade_available


def _fill(
    *,
    symbol: str = "AAPL",
    ts: datetime | None = None,
    qty: Decimal = Decimal("10"),
    price: Decimal = Decimal("100"),
    commission: Decimal = Decimal("0"),
    slippage: Decimal = Decimal("0"),
) -> PaperFill:
    return PaperFill(
        timestamp=ts or datetime(2026, 7, 1, 9, 30),
        symbol=symbol,
        quantity=qty,
        price=price,
        commission=commission,
        slippage=slippage,
    )


# ---------------------------------------------------------------------------
# PaperSide.from_signed_quantity
# ---------------------------------------------------------------------------


def test_side_infers_buy_from_positive_qty() -> None:
    assert PaperSide.from_signed_quantity(Decimal("10")) is PaperSide.BUY


def test_side_infers_sell_from_negative_qty() -> None:
    assert PaperSide.from_signed_quantity(Decimal("-5")) is PaperSide.SELL


def test_side_rejects_zero_qty() -> None:
    with pytest.raises(ValueError, match=r"zero quantity"):
        PaperSide.from_signed_quantity(Decimal("0"))


# ---------------------------------------------------------------------------
# verify_exportable (R7.11 mutation checks per rule)
# ---------------------------------------------------------------------------


def test_verify_happy_path_passes() -> None:
    verify_exportable([_fill()])


def test_verify_raises_on_empty_symbol() -> None:
    with pytest.raises(ValueError, match=r"symbol is empty"):
        verify_exportable([_fill(symbol="")])


def test_verify_raises_on_zero_qty() -> None:
    with pytest.raises(ValueError, match=r"quantity is zero"):
        verify_exportable([_fill(qty=Decimal("0"))])


def test_verify_raises_on_nan_price() -> None:
    with pytest.raises(ValueError, match=r"price is not finite"):
        verify_exportable([_fill(price=Decimal("NaN"))])


def test_verify_raises_on_infinite_price() -> None:
    with pytest.raises(ValueError, match=r"price is not finite"):
        verify_exportable([_fill(price=Decimal("Infinity"))])


def test_verify_raises_on_negative_commission() -> None:
    with pytest.raises(ValueError, match=r"commission"):
        verify_exportable([_fill(commission=Decimal("-0.01"))])


def test_verify_raises_on_negative_slippage() -> None:
    with pytest.raises(ValueError, match=r"slippage"):
        verify_exportable([_fill(slippage=Decimal("-0.005"))])


# ---------------------------------------------------------------------------
# build_export — JSON fallback (always available)
# ---------------------------------------------------------------------------


def test_build_export_forces_json_fallback() -> None:
    fills = [
        _fill(symbol="AAPL", qty=Decimal("10"), ts=datetime(2026, 7, 1, 9, 30)),
        _fill(symbol="MSFT", qty=Decimal("-5"), ts=datetime(2026, 7, 1, 10, 0)),
    ]
    exp = build_export(fills, account_id="ACC-001", force_json_fallback=True)
    assert isinstance(exp, BacktestExport)
    assert exp.format == "json_dict"
    assert exp.account_id == "ACC-001"
    assert len(exp.trades) == 2
    assert any("openbb-backtest not available" in w for w in exp.warnings)
    # JSON shape: string-encoded Decimals, ISO timestamps, side enum value
    first = exp.trades[0]
    assert first["symbol"] == "AAPL"
    assert first["side"] == "BUY"
    assert first["quantity"] == "10"
    assert first["price"] == "100"
    second = exp.trades[1]
    assert second["side"] == "SELL"
    assert second["quantity"] == "5"  # absolute value


def test_build_export_orders_by_timestamp_then_symbol() -> None:
    """Deterministic order — same input, same output."""
    fills = [
        _fill(symbol="ZZZZ", ts=datetime(2026, 7, 1, 12, 0)),
        _fill(symbol="AAAA", ts=datetime(2026, 7, 1, 10, 0)),
        _fill(symbol="MMMM", ts=datetime(2026, 7, 1, 10, 0)),
    ]
    exp = build_export(fills, account_id="ACC", force_json_fallback=True)
    symbols = [t["symbol"] for t in exp.trades]
    # AAAA (10:00) then MMMM (10:00, symbol-tiebreak) then ZZZZ (12:00)
    assert symbols == ["AAAA", "MMMM", "ZZZZ"]


def test_build_export_empty_fills_produces_empty_trade_list() -> None:
    exp = build_export([], account_id="ACC", force_json_fallback=True)
    assert exp.trades == []
    assert exp.format == "json_dict"


def test_build_export_deterministic_bytes() -> None:
    """Same fills twice → identical trade list."""
    fills = [
        _fill(symbol="A", qty=Decimal("1"), ts=datetime(2026, 7, 1, 9, 30)),
        _fill(symbol="B", qty=Decimal("-1"), ts=datetime(2026, 7, 1, 10, 0)),
    ]
    e1 = build_export(fills, account_id="X", force_json_fallback=True)
    e2 = build_export(fills, account_id="X", force_json_fallback=True)
    assert e1.trades == e2.trades


# ---------------------------------------------------------------------------
# build_export — bad input surfaces via verify_exportable
# ---------------------------------------------------------------------------


def test_build_export_calls_verify_exportable() -> None:
    """A bad fill fails at build_export time, not at consumer time."""
    fills = [_fill(qty=Decimal("0"))]
    with pytest.raises(ValueError, match=r"quantity is zero"):
        build_export(fills, account_id="ACC", force_json_fallback=True)


# ---------------------------------------------------------------------------
# _backtest_trade_available — feature-flag probe
# ---------------------------------------------------------------------------


def test_backtest_trade_available_returns_bool() -> None:
    """Just returns a bool without raising, regardless of install state."""
    result = _backtest_trade_available()
    assert isinstance(result, bool)


def test_build_export_uses_json_when_backtest_missing() -> None:
    """When backtest ext is unavailable, format is 'json_dict' + warning."""
    with patch(
        "openbb_portfolio_intel.handoff.backtest_export._backtest_trade_available",
        return_value=False,
    ):
        exp = build_export([_fill()], account_id="ACC")
    assert exp.format == "json_dict"
    assert any("openbb-backtest not available" in w for w in exp.warnings)


def test_build_export_uses_native_when_backtest_available() -> None:
    """When backtest ext is available, format is 'backtest_trade' with no warning."""
    if not _backtest_trade_available():
        pytest.skip(
            "openbb-backtest not installed in this venv — native path untestable"
        )
    exp = build_export([_fill()], account_id="ACC")
    assert exp.format == "backtest_trade"
    assert exp.warnings == []
    # First trade should be an openbb_backtest.models.Trade instance
    from openbb_backtest.models import Trade

    assert isinstance(exp.trades[0], Trade)
    assert exp.trades[0].symbol == "AAPL"


# ---------------------------------------------------------------------------
# Envelope shape identity
# ---------------------------------------------------------------------------


def test_backtest_export_is_frozen() -> None:
    exp = build_export([_fill()], account_id="ACC", force_json_fallback=True)
    with pytest.raises(Exception):
        exp.format = "something_else"  # type: ignore[misc]


def test_paper_fill_is_frozen() -> None:
    fill = _fill()
    with pytest.raises(Exception):
        fill.quantity = Decimal("999")  # type: ignore[misc]
