"""End-to-end integration test for the Pine → openbb-backtest bridge (#585).

Exercises the full chain that #590 (bridge) + #589 (adapter) built:

    strategy OBBject
      → maybe_export_to_backtest (openbb_pine.runtime.backtest_bridge)
      → ingest_pine_strategy   (openbb_pine.analytics)
      → openbb_backtest.models.BacktestResult stashed on
        result.extra["backtest_result"]

Skip-if-not-installed guard: uses ``pytest.importorskip("openbb_backtest")``
at module top so this test cleanly skips when openbb-backtest is absent
(L1 install case). The bridge's own missing-dep path is covered by the
unit test in ``test_backtest_bridge.py`` (:func:`test_maybe_export_no_op_when_openbb_backtest_missing`
et al) — this file only asserts what happens on the L2 "openbb-backtest
installed" happy path, so a skipif is the right guard rather than a
monkeypatched sys.modules dance.

Why this test exists (D5 §6.1 traceability):

* :func:`test_end_to_end_strategy_result_produces_real_backtest_result`
  is the ONLY test in the repo that actually calls both #590 and #589 in
  sequence with a realistic-shape strategy OBBject and asserts every
  layer of the returned :class:`BacktestResult` structure. The unit
  tests in ``test_analytics.py`` monkeypatch or hand-roll their own
  drives; the unit tests in ``test_backtest_bridge.py`` monkeypatch
  ``openbb_pine.analytics.ingest_pine_strategy``. Neither exercises
  the two-layer wiring in a single call.
* Discovered while implementing #589 — mutating the bridge's
  ``extra["backtest_result"] = ingest_pine_strategy(...)`` line to
  ``ingest_pine_strategy(...)`` (dropping the assignment) breaks NO unit
  tests today because the bridge unit test only checks that the adapter
  was CALLED, not that its return value was stashed. This integration
  test locks down the full wiring.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest
from openbb_core.app.model.obbject import OBBject

# Skip the whole module if openbb-backtest isn't installed. The bridge's
# import-guard behavior is covered by tests in test_backtest_bridge.py that
# monkeypatch sys.modules — no need to duplicate that here.
openbb_backtest = pytest.importorskip(
    "openbb_backtest",
    reason=(
        "openbb-backtest not installed — end-to-end BacktestResult "
        "integration test requires the optional dep. Install with "
        "`pip install -e openbb_platform/extensions/backtest` into "
        "your Pine dev venv."
    ),
)


def _make_trade_summary(**overrides: Any) -> Any:
    """Real ``TradeSummary`` dataclass with sensible defaults."""
    from pyne_compiler.runtime.strategy_types import TradeSummary

    defaults: dict[str, Any] = {
        "id": "t1",
        "direction": "long",
        "entry_time": pd.Timestamp("2026-01-02T14:30:00Z"),
        "entry_price": 100.0,
        "exit_time": pd.Timestamp("2026-01-03T14:30:00Z"),
        "exit_price": 110.0,
        "qty": 10.0,
        "pnl": 100.0,
        "pnl_pct": 0.001,
        "bars_held": 1,
        "commission": 1.0,
        "runup": 12.0,
        "drawdown": 2.0,
        "comment": None,
    }
    defaults.update(overrides)
    return TradeSummary(**defaults)


def _make_strategy_obbject(
    *,
    orders: list[Any] | None = None,
    n_equity_points: int = 5,
    initial_capital: float = 100_000.0,
    symbol: str = "AAPL",
) -> OBBject:
    """Build a realistic-shape strategy OBBject the executor would emit."""
    obj = OBBject(results=None)
    obj.extra = {
        "script_type": "strategy",
        "orders": orders if orders is not None else [],
        "equity_curve": [
            {"bar_index": i, "equity": initial_capital + i * 100.0, "drawdown": 0.0}
            for i in range(n_equity_points)
        ],
        "stats": {
            "initial_capital": initial_capital,
            "final_equity": initial_capital + (n_equity_points - 1) * 100.0,
        },
        "symbol": symbol,
    }
    return obj


# ---------------------------------------------------------------------------
# End-to-end happy path — the ONE test that locks down the full chain
# ---------------------------------------------------------------------------


def test_end_to_end_strategy_result_produces_real_backtest_result():
    """Full chain: strategy OBBject → maybe_export_to_backtest → adapter
    → openbb_backtest.models.BacktestResult on extra['backtest_result'].

    Asserts every visible layer of the wiring so a regression in EITHER
    the bridge (dropped assignment) OR the adapter (wrong shape) surfaces
    here even if the layer's own unit tests pass in isolation.
    """
    from openbb_backtest.models import (
        BacktestConfig,
        BacktestResult,
        EquityPoint,
        PerformanceMetrics,
        Trade,
    )

    from openbb_pine.runtime.backtest_bridge import maybe_export_to_backtest

    # Realistic input: 2 round-trips (1 long + 1 short) + 5 equity points.
    result = _make_strategy_obbject(
        orders=[
            _make_trade_summary(
                id="t1",
                direction="long",
                entry_time=pd.Timestamp("2026-01-02T14:30:00Z"),
                exit_time=pd.Timestamp("2026-01-03T14:30:00Z"),
                entry_price=100.0,
                exit_price=110.0,
                qty=10.0,
                pnl=100.0,
            ),
            _make_trade_summary(
                id="t2",
                direction="short",
                entry_time=pd.Timestamp("2026-01-04T14:30:00Z"),
                exit_time=pd.Timestamp("2026-01-05T14:30:00Z"),
                entry_price=105.0,
                exit_price=100.0,
                qty=5.0,
                pnl=25.0,
            ),
        ],
        n_equity_points=5,
    )

    # Drive the full chain in a single call — no monkeypatching, no
    # synthetic sys.modules. This is the ONE call site the bridge exposes.
    ret = maybe_export_to_backtest(result)
    assert ret is None, "bridge is side-effect-only; should return None"

    # 1. The bridge stashed the BacktestResult on extra['backtest_result'].
    #    A regression that drops the assignment (extra["backtest_result"] =
    #    ingest_pine_strategy(...) → ingest_pine_strategy(...)) fails here.
    assert "backtest_result" in result.extra, (
        "bridge must stash BacktestResult on extra['backtest_result'] — "
        "regression: assignment was dropped from maybe_export_to_backtest"
    )
    bt = result.extra["backtest_result"]
    assert isinstance(
        bt, BacktestResult
    ), f"expected BacktestResult, got {type(bt).__name__}"

    # 2. Trades fan out — 2 round-trips → 4 Trade rows.
    assert len(bt.trades) == 4, "2 round-trips → 4 Trade rows (buy+sell x 2)"
    assert all(isinstance(t, Trade) for t in bt.trades)
    # Long round-trip: buy@entry then sell@exit.
    assert bt.trades[0].side == "buy"
    assert bt.trades[1].side == "sell"
    # Short round-trip: sell@entry then buy@exit.
    assert bt.trades[2].side == "sell"
    assert bt.trades[3].side == "buy"
    # Chronological order preserved.
    timestamps = [t.timestamp for t in bt.trades]
    assert timestamps == sorted(timestamps)

    # 3. Equity curve translated 1:1.
    assert len(bt.equity_curve) == 5
    assert all(isinstance(pt, EquityPoint) for pt in bt.equity_curve)

    # 4. PerformanceMetrics is a real instance with all required fields
    #    populated (delegated to openbb_backtest.compute_metrics).
    assert isinstance(bt.metrics, PerformanceMetrics)

    # 5. Config echo shows universe = [symbol], initial_cash from stats.
    assert isinstance(bt.config, BacktestConfig)
    assert bt.config.universe == ["AAPL"]
    assert bt.engine_used == "pine-adapter"

    # 6. Fabricated-fields warning appended (equity_curve was non-empty).
    warnings = result.extra.get("warnings", [])
    assert any(
        "fabricated" in w.lower() and "equity" in w.lower() for w in warnings
    ), "expected lossy-fields warning on non-empty equity_curve"

    # 7. NO "openbb-backtest not installed" warning on this path — the dep
    #    IS installed (we importorskip'd otherwise).
    assert not any(
        "openbb-backtest not installed" in w for w in warnings
    ), "unexpected missing-dep warning on happy path"


def test_end_to_end_indicator_result_bypasses_export():
    """A non-strategy OBBject (e.g. an indicator result routed here by
    mistake) short-circuits without touching openbb-backtest — no
    ``backtest_result`` stashed, no warning appended.

    Locks down the "silent no-op for non-strategy" branch in
    :func:`maybe_export_to_backtest`. A regression that removed that
    guard would either warn misleadingly ("backtest not installed" on
    an indicator that had nothing to hand off) or invoke the adapter
    and raise ``TypeError`` (adapter's own contract check).
    """
    from openbb_pine.runtime.backtest_bridge import maybe_export_to_backtest

    result = _make_strategy_obbject()
    result.extra["script_type"] = "indicator"

    maybe_export_to_backtest(result)

    assert "backtest_result" not in result.extra
    warnings = result.extra.get("warnings", [])
    assert not any("openbb-backtest" in w for w in warnings), (
        f"non-strategy path should not emit any openbb-backtest warning; "
        f"got: {warnings}"
    )
    assert not any(
        "fabricated" in w.lower() for w in warnings
    ), "non-strategy path should not run the equity-fabrication step"


def test_end_to_end_empty_orders_still_produces_backtest_result():
    """A strategy that closed no round-trips (e.g. always-flat) still
    produces a BacktestResult — just with empty trades and metrics
    computed off the equity curve alone.

    Locks the "flat run" boundary: the adapter must not crash on
    empty orders (a common edge case in strategy development where a
    filter never fires).
    """
    from openbb_backtest.models import BacktestResult

    from openbb_pine.runtime.backtest_bridge import maybe_export_to_backtest

    result = _make_strategy_obbject(orders=[], n_equity_points=10)

    maybe_export_to_backtest(result)

    bt = result.extra["backtest_result"]
    assert isinstance(bt, BacktestResult)
    assert bt.trades == []
    assert len(bt.equity_curve) == 10
    # Metrics still populated (equity-only), just with win_rate/profit_factor
    # reflecting the no-trades case.
    assert bt.metrics is not None
