"""Golden-fixture regression locks for the price-only reference strategies (C10.3).

Each reference strategy is run end-to-end through the :class:`VectorizedEngine`
on a fixed, deterministic in-memory OHLCV panel, and its equity curve + summary
metrics are compared against a committed golden JSON fixture within ``1e-6``.

These tests carry the ``golden`` marker (run with ``-m golden``). Regenerate the
committed fixtures intentionally with ``BACKTEST_REGEN_GOLDEN=1`` after a
*reviewed* behavioral change — never blindly.

See ``docs/designs/backtest-design/10-strategy-library.md``.
"""

from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

pytestmark = pytest.mark.golden

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_TOL = 1e-6

# A deterministic 8-session, 3-symbol panel: AAA trends up, BBB trends down,
# CCC oscillates — enough signal for momentum and mean-reversion to act.
_SESSIONS = pd.to_datetime(
    [
        "2021-01-04",
        "2021-01-05",
        "2021-01-06",
        "2021-01-07",
        "2021-01-08",
        "2021-01-11",
        "2021-01-12",
        "2021-01-13",
    ]
)
_CLOSES = {
    "AAA": [100.0, 101.0, 103.0, 104.0, 106.0, 108.0, 110.0, 112.0],
    "BBB": [100.0, 99.0, 98.0, 96.0, 95.0, 93.0, 92.0, 90.0],
    "CCC": [100.0, 102.0, 99.0, 101.0, 98.0, 103.0, 97.0, 104.0],
}


def _long_frame() -> pd.DataFrame:
    rows = []
    for sym, series in _CLOSES.items():
        for sess, px in zip(_SESSIONS, series):
            rows.append(
                {
                    "symbol": sym,
                    "session": sess,
                    "open": px,
                    "high": px,
                    "low": px,
                    "close": px,
                    "volume": 1_000_000.0,
                }
            )
    return pd.DataFrame(rows)


class _MemFeed:
    """Minimal look-ahead-safe ``DataFeed`` over the fixed panel."""

    def __init__(self) -> None:
        self._frame = _long_frame()

    def history(self, symbols, end, lookback):  # noqa: ANN001
        end = pd.Timestamp(end)
        mask = self._frame["symbol"].isin(symbols) & (self._frame["session"] <= end)
        return (
            self._frame.loc[mask]
            .sort_values("session")
            .groupby("symbol", group_keys=False)
            .tail(lookback)
            .reset_index(drop=True)
        )

    def sessions(self, start, end):  # noqa: ANN001
        s = self._frame["session"]
        return pd.DatetimeIndex(
            sorted(s[(s >= pd.Timestamp(start)) & (s <= pd.Timestamp(end))].unique())
        )


def _run(strategy):  # noqa: ANN001
    from openbb_backtest.engine.execution import RealisticBroker
    from openbb_backtest.engine.vectorized import VectorizedEngine
    from openbb_backtest.models import BacktestConfig, CommissionModel, SlippageModel

    cfg = BacktestConfig(
        strategy=strategy.id,
        universe=["AAA", "BBB", "CCC"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 13),
        engine="vectorized",
        initial_cash=Decimal("100000"),
        commission=CommissionModel(),
        slippage=SlippageModel(),
    )
    res = VectorizedEngine().run(strategy, cfg, _MemFeed(), RealisticBroker(cfg.commission, cfg.slippage))
    return res


def _snapshot(result) -> dict:  # noqa: ANN001
    """Reduce a result to the JSON-able equity curve + metrics we lock."""
    return {
        "equity": [float(p.equity) for p in result.equity_curve],
        "metrics": {
            "cagr": result.metrics.cagr,
            "sharpe": result.metrics.sharpe,
            "max_drawdown": result.metrics.max_drawdown,
            "volatility": result.metrics.volatility,
            "turnover": result.metrics.turnover,
        },
    }


def _strategies():
    from openbb_backtest.strategies.buy_and_hold import BuyAndHold
    from openbb_backtest.strategies.mean_reversion import MeanReversion
    from openbb_backtest.strategies.momentum import Momentum

    universe = ["AAA", "BBB", "CCC"]
    return {
        "buy_and_hold": BuyAndHold(symbols=universe),
        "momentum_12_1": Momentum(symbols=universe, lookback=3, skip=1),
        "mean_reversion": MeanReversion(symbols=universe, lookback=4, entry_z=1.0),
    }


def _assert_matches_golden(name: str, snap: dict) -> None:
    path = _FIXTURE_DIR / f"{name}.json"
    if os.environ.get("BACKTEST_REGEN_GOLDEN") == "1":
        _FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    golden = json.loads(path.read_text(encoding="utf-8"))

    assert len(snap["equity"]) == len(golden["equity"])
    for got, want in zip(snap["equity"], golden["equity"]):
        assert got == pytest.approx(want, abs=_TOL)
    for key, want in golden["metrics"].items():
        assert snap["metrics"][key] == pytest.approx(want, abs=_TOL)


@pytest.mark.parametrize("name", ["buy_and_hold", "momentum_12_1", "mean_reversion"])
def test_reference_strategy_matches_golden(name: str):
    snap = _snapshot(_run(_strategies()[name]))
    _assert_matches_golden(name, snap)


def test_golden_run_is_deterministic():
    a = _snapshot(_run(_strategies()["momentum_12_1"]))
    b = _snapshot(_run(_strategies()["momentum_12_1"]))
    assert a == b
