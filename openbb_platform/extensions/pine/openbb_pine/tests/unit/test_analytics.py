"""Tests for :mod:`openbb_pine.analytics` — Pine strategy result → openbb-backtest
shape adapter (#589).

Contract per PR body:

* :func:`ingest_pine_strategy(result: OBBject) -> BacktestResult` translates
  a Pine strategy result's ``extra["orders"]`` (list of ``TradeSummary``)
  and ``extra["equity_curve"]`` (list of dicts) into openbb-backtest's
  ``BacktestResult`` shape (``list[Trade] + list[EquityPoint] +
  PerformanceMetrics + BacktestConfig``).
* Round-trip fan-out: each ``TradeSummary`` produces TWO ``Trade`` rows
  (entry = buy or sell, exit = sell or buy) tagged with the same symbol
  and directions matching the round-trip's ``direction`` field.
* Pine's equity_curve entries carry only ``bar_index`` (not a timestamp),
  ``equity``, and ``drawdown``. openbb-backtest's ``EquityPoint`` needs
  ``date`` + ``cash`` + ``exposure``. This adapter fabricates the missing
  fields (deterministic anchor + timedelta for date, cash=equity,
  exposure=0.0) AND appends a warning naming the three fabricated fields
  to ``result.extra["warnings"]`` so callers can see the lossy translation.
* ``PerformanceMetrics`` computed via ``openbb_backtest.analytics.compute_metrics()``
  from the translated equity series + trades. No hand-rolled metrics.

Deferred (out of #589 scope):
- Slippage / commission modeling (Pine doesn't distinguish; adapter passes
  through ``commission=0``, ``slippage=0``).
- ``PositionSnapshot`` per-bar snapshots (Pine doesn't record positions
  per bar; adapter returns empty ``positions=[]``).
- Fixing the fabricated ``EquityPoint`` fields (needs a Pine-runtime
  change to executor_shell to also stamp ``time`` + ``cash`` + ``exposure``
  on each equity snapshot). Tracked as follow-up issue.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from openbb_core.app.model.obbject import OBBject


def _make_trade_summary(
    *,
    trade_id: str = "t1",
    direction: str = "long",
    entry_time: str = "2026-01-02T14:30:00Z",
    entry_price: float = 100.0,
    exit_time: str = "2026-01-03T14:30:00Z",
    exit_price: float = 110.0,
    qty: float = 10.0,
    pnl: float = 100.0,
    pnl_pct: float = 0.10,
    bars_held: int = 1,
    commission: float = 0.0,
    runup: float = 12.0,
    drawdown: float = 2.0,
    comment: str | None = None,
) -> Any:
    """Produce a real ``TradeSummary`` dataclass instance.

    Uses the actual class from ``pyne_compiler.runtime.strategy_types`` so
    the tests exercise the exact wire shape the executor produces.
    """
    from pyne_compiler.runtime.strategy_types import TradeSummary

    return TradeSummary(
        id=trade_id,
        direction=direction,  # type: ignore[arg-type]
        entry_time=pd.Timestamp(entry_time),
        entry_price=entry_price,
        exit_time=pd.Timestamp(exit_time),
        exit_price=exit_price,
        qty=qty,
        pnl=pnl,
        pnl_pct=pnl_pct,
        bars_held=bars_held,
        commission=commission,
        runup=runup,
        drawdown=drawdown,
        comment=comment,
    )


def _make_result(
    *,
    orders: list[Any] | None = None,
    equity_curve: list[dict[str, Any]] | None = None,
    symbol: str = "AAPL",
    initial_capital: float = 100_000.0,
) -> OBBject:
    """Build a minimal strategy OBBject with the shape the executor produces."""
    obj = OBBject(results=None)
    obj.extra = {
        "script_type": "strategy",
        "orders": orders if orders is not None else [],
        "equity_curve": (
            equity_curve
            if equity_curve is not None
            else [
                {"bar_index": 0, "equity": initial_capital, "drawdown": 0.0},
                {"bar_index": 1, "equity": initial_capital + 500.0, "drawdown": 0.0},
            ]
        ),
        "stats": {
            "initial_capital": initial_capital,
            "final_equity": initial_capital,
        },
        "symbol": symbol,
    }
    return obj


# ---------------------------------------------------------------------------
# Trade fan-out — one TradeSummary → two Trade rows
# ---------------------------------------------------------------------------


def test_long_round_trip_produces_buy_then_sell():
    """A ``direction="long"`` round-trip fans out to buy@entry_time,
    sell@exit_time — same symbol, quantity absolute (matches openbb-backtest
    ``Trade.quantity``), no fabricated commission/slippage.
    """
    from openbb_pine.analytics import ingest_pine_strategy

    result = _make_result(
        orders=[
            _make_trade_summary(
                direction="long", qty=10.0, entry_price=100.0, exit_price=110.0
            )
        ]
    )

    bt = ingest_pine_strategy(result)

    assert len(bt.trades) == 2, "long round-trip → 2 Trade rows (buy + sell)"
    buy, sell = bt.trades
    assert buy.side == "buy"
    assert sell.side == "sell"
    assert buy.timestamp < sell.timestamp
    assert buy.quantity == Decimal("10")
    assert sell.quantity == Decimal("10")
    assert buy.price == Decimal("100")
    assert sell.price == Decimal("110")
    assert buy.symbol == "AAPL"
    assert sell.symbol == "AAPL"
    assert buy.commission == Decimal("0")
    assert buy.slippage == Decimal("0")


def test_short_round_trip_produces_sell_then_buy():
    """A ``direction="short"`` round-trip fans out to sell@entry_time,
    buy@exit_time — the sell is the entry (open short) and the buy closes.
    """
    from openbb_pine.analytics import ingest_pine_strategy

    result = _make_result(
        orders=[
            _make_trade_summary(
                direction="short", qty=5.0, entry_price=50.0, exit_price=48.0
            )
        ]
    )

    bt = ingest_pine_strategy(result)

    assert len(bt.trades) == 2
    first, second = bt.trades
    assert first.side == "sell", "short entry is a sell"
    assert second.side == "buy", "short exit is a buy"
    assert first.timestamp < second.timestamp
    assert first.price == Decimal("50")
    assert second.price == Decimal("48")


def test_multiple_round_trips_preserve_chronological_order():
    """Two round-trips → four Trade rows in strict timestamp order.

    Load-bearing: the openbb-backtest metrics pipeline downstream FIFO-pairs
    trades by time to compute win_rate / profit_factor. Out-of-order rows
    would produce wrong metrics.
    """
    from openbb_pine.analytics import ingest_pine_strategy

    orders = [
        _make_trade_summary(
            trade_id="t1",
            direction="long",
            entry_time="2026-01-02T14:30:00Z",
            exit_time="2026-01-03T14:30:00Z",
        ),
        _make_trade_summary(
            trade_id="t2",
            direction="short",
            entry_time="2026-01-05T14:30:00Z",
            exit_time="2026-01-06T14:30:00Z",
        ),
    ]
    result = _make_result(orders=orders)

    bt = ingest_pine_strategy(result)

    assert len(bt.trades) == 4
    timestamps = [t.timestamp for t in bt.trades]
    assert timestamps == sorted(
        timestamps
    ), f"trades out of chronological order: {timestamps}"


def test_empty_orders_produces_empty_trades():
    """A run with no closed round-trips → empty ``trades`` list, no crash."""
    from openbb_pine.analytics import ingest_pine_strategy

    bt = ingest_pine_strategy(_make_result(orders=[]))
    assert bt.trades == []


# ---------------------------------------------------------------------------
# EquityPoint translation — fabricated fields + warning
# ---------------------------------------------------------------------------


def test_equity_curve_translates_length_and_values():
    """Every Pine equity_curve entry → one ``EquityPoint``. ``equity`` value
    passes through as ``Decimal``.
    """
    from openbb_pine.analytics import ingest_pine_strategy

    result = _make_result(
        equity_curve=[
            {"bar_index": 0, "equity": 100_000.0, "drawdown": 0.0},
            {"bar_index": 1, "equity": 100_500.0, "drawdown": 0.0},
            {"bar_index": 2, "equity": 100_250.0, "drawdown": 250.0},
        ]
    )

    bt = ingest_pine_strategy(result)

    assert len(bt.equity_curve) == 3
    assert bt.equity_curve[0].equity == Decimal("100000")
    assert bt.equity_curve[1].equity == Decimal("100500")
    assert bt.equity_curve[2].equity == Decimal("100250.0")


def test_equity_point_dates_are_monotonic_from_bar_index():
    """Fabricated dates step forward per bar_index — strictly increasing so
    downstream returns computations don't divide by a zero timedelta.
    """
    from openbb_pine.analytics import ingest_pine_strategy

    result = _make_result(
        equity_curve=[
            {"bar_index": 0, "equity": 100.0, "drawdown": 0.0},
            {"bar_index": 5, "equity": 105.0, "drawdown": 0.0},
            {"bar_index": 10, "equity": 110.0, "drawdown": 0.0},
        ]
    )

    bt = ingest_pine_strategy(result)

    dates = [pt.date for pt in bt.equity_curve]
    assert all(isinstance(d, datetime) for d in dates), "dates must be datetime"
    assert dates == sorted(dates), f"dates not monotonic: {dates}"
    # Adjacent dates should reflect the bar-index delta.
    assert dates[1] > dates[0]
    assert dates[2] > dates[1]


def test_equity_point_fabricated_fields_get_warning(caplog):
    """The adapter appends a warning naming the fabricated fields
    (``date``, ``cash``, ``exposure``) to ``result.extra["warnings"]``.
    Callers can see the lossy translation without inspecting individual
    EquityPoint values.
    """
    from openbb_pine.analytics import ingest_pine_strategy

    result = _make_result()
    ingest_pine_strategy(result)

    warnings = result.extra.get("warnings", [])
    assert warnings, "no warning appended"
    # The warning must name every fabricated field so the user knows what's
    # lossy.
    combined = " ".join(warnings)
    assert "date" in combined.lower()
    assert "cash" in combined.lower()
    assert "exposure" in combined.lower()


def test_no_equity_warning_when_equity_curve_empty():
    """When the strategy produced no equity_curve entries, don't append the
    fabricated-fields warning — there's nothing fabricated.
    """
    from openbb_pine.analytics import ingest_pine_strategy

    result = _make_result(equity_curve=[])
    ingest_pine_strategy(result)
    warnings = result.extra.get("warnings", [])
    # There may be OTHER warnings from the pipeline; specifically assert the
    # equity-fabrication warning is absent.
    assert not any(
        "fabricated" in w.lower() and "equity" in w.lower() for w in warnings
    )


# ---------------------------------------------------------------------------
# PerformanceMetrics — delegated to openbb_backtest.compute_metrics
# ---------------------------------------------------------------------------


def test_metrics_are_real_performance_metrics_instance():
    """``bt.metrics`` is an ``openbb_backtest.models.PerformanceMetrics``
    instance with all required fields present (delegated to
    ``compute_metrics``).
    """
    from openbb_backtest.models import PerformanceMetrics

    from openbb_pine.analytics import ingest_pine_strategy

    result = _make_result(
        orders=[
            _make_trade_summary(
                trade_id="t1",
                direction="long",
                entry_time="2026-01-02T14:30:00Z",
                exit_time="2026-01-03T14:30:00Z",
                entry_price=100.0,
                exit_price=110.0,
                qty=10.0,
                pnl=100.0,
            ),
        ],
        equity_curve=[
            {"bar_index": i, "equity": 100_000.0 + i * 100, "drawdown": 0.0}
            for i in range(10)
        ],
    )

    bt = ingest_pine_strategy(result)

    assert isinstance(bt.metrics, PerformanceMetrics)
    # Every required field must be present as a float (Pydantic enforces
    # this at construction, but verify explicitly so a regression that
    # zero-fills instead of delegating gets caught).
    for field in (
        "cagr",
        "sharpe",
        "sortino",
        "calmar",
        "max_drawdown",
        "volatility",
        "var_95",
        "cvar_95",
        "win_rate",
        "profit_factor",
        "turnover",
    ):
        assert isinstance(
            getattr(bt.metrics, field), float
        ), f"{field} must be a float from compute_metrics, not synthesized"


# ---------------------------------------------------------------------------
# BacktestConfig echo — reproducibility
# ---------------------------------------------------------------------------


def test_backtest_result_has_config_and_engine_used():
    """``BacktestResult.config`` echoes the strategy's parameters (universe
    = [symbol], initial_cash from stats). ``engine_used`` names this
    adapter so downstream code can distinguish Pine-produced results from
    real openbb-backtest engine runs.
    """
    from openbb_pine.analytics import ingest_pine_strategy

    result = _make_result(symbol="MSFT", initial_capital=250_000.0)
    bt = ingest_pine_strategy(result)

    assert bt.config.universe == ["MSFT"]
    assert bt.config.initial_cash == Decimal("250000")
    assert "pine" in bt.engine_used.lower()


# ---------------------------------------------------------------------------
# Positions — empty (deferred to a future Pine-runtime issue)
# ---------------------------------------------------------------------------


def test_positions_is_empty_list():
    """Pine doesn't record per-bar position snapshots; ``positions=[]``
    is intentional. Documented in the module docstring so a reader sees
    the deferred item explicitly.
    """
    from openbb_pine.analytics import ingest_pine_strategy

    bt = ingest_pine_strategy(_make_result())
    assert bt.positions == []


# ---------------------------------------------------------------------------
# Guard — non-strategy result / missing fields
# ---------------------------------------------------------------------------


def test_raises_typeerror_on_non_strategy_result():
    """A non-strategy result (indicator, etc.) hitting this adapter is a
    caller bug — raise TypeError so the caller sees the problem
    immediately. #590's ``maybe_export_to_backtest`` already guards this
    for the strategies-router seam; this test locks down the direct-caller
    contract.
    """
    from openbb_pine.analytics import ingest_pine_strategy

    result = _make_result()
    result.extra["script_type"] = "indicator"

    with pytest.raises(TypeError, match="strategy"):
        ingest_pine_strategy(result)


# ---------------------------------------------------------------------------
# #590 bridge integration — bridge now calls the Pine-side ingest
# ---------------------------------------------------------------------------


def test_bridge_calls_pine_side_ingest_on_strategy_result(monkeypatch):
    """After #589 lands, ``maybe_export_to_backtest`` calls
    ``openbb_pine.analytics.ingest_pine_strategy`` (Pine-side) instead of
    the previous ``openbb_backtest.analytics.ingest_pine_strategy`` (which
    never existed). The result is stashed on ``result.extra['backtest_result']``
    for downstream consumers (widget renderers, notebook workflows).
    """
    from openbb_pine.runtime.backtest_bridge import maybe_export_to_backtest

    result = _make_result()
    maybe_export_to_backtest(result)

    # The Pine-side ingest ran (no ImportError; no missing-dep warning).
    assert "backtest_result" in result.extra
    from openbb_backtest.models import BacktestResult

    assert isinstance(result.extra["backtest_result"], BacktestResult)
    # No "openbb-backtest not installed" warning — the dep IS installed
    # in .venv_pine_support now.
    for w in result.extra.get("warnings", []):
        assert "openbb-backtest not installed" not in w
