"""Golden-fixture regression locks for the allocation strategies (C10.4).

Each allocation strategy (``vol_targeting`` and ``risk_parity`` in both its
inverse-vol and HRP modes) is run end-to-end through the :class:`VectorizedEngine`
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
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.golden

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_TOL = 1e-6

# A deterministic 40-session, 3-symbol panel. Each symbol follows a seeded
# geometric random walk at a distinct daily volatility so the risk-based
# allocators have a meaningful covariance structure to act on.
_SESSIONS = pd.bdate_range("2021-01-04", periods=40)
_SPECS = {
    "AAA": (0.0004, 0.020, 21),
    "BBB": (0.0000, 0.012, 22),
    "CCC": (0.0002, 0.008, 23),
}


def _gbm(mu: float, sigma: float, n: int, seed: int, s0: float = 100.0) -> np.ndarray:
    """Deterministic geometric-random-walk close series at a given daily vol."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(mu, sigma, size=n)
    return s0 * np.exp(np.cumsum(rets))


_CLOSES = {sym: _gbm(mu, sigma, len(_SESSIONS), seed) for sym, (mu, sigma, seed) in _SPECS.items()}


def _long_frame() -> pd.DataFrame:
    rows = []
    for sym, series in _CLOSES.items():
        for sess, px in zip(_SESSIONS, series):
            rows.append(
                {
                    "symbol": sym,
                    "session": sess,
                    "open": float(px),
                    "high": float(px),
                    "low": float(px),
                    "close": float(px),
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
        start=_SESSIONS[0].date(),
        end=_SESSIONS[-1].date(),
        engine="vectorized",
        initial_cash=Decimal("100000"),
        commission=CommissionModel(),
        slippage=SlippageModel(),
    )
    return VectorizedEngine().run(
        strategy, cfg, _MemFeed(), RealisticBroker(cfg.commission, cfg.slippage)
    )


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
    from openbb_backtest.strategies.risk_parity import RiskParity
    from openbb_backtest.strategies.vol_targeting import VolTargeting

    universe = ["AAA", "BBB", "CCC"]
    return {
        "vol_targeting": VolTargeting(symbols=universe, target_vol=0.10, lookback=20),
        "risk_parity_inverse_vol": RiskParity(
            symbols=universe, method="inverse_vol", lookback=20, id="risk_parity_inverse_vol"
        ),
        "risk_parity_hrp": RiskParity(
            symbols=universe, method="hrp", lookback=20, id="risk_parity_hrp"
        ),
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


@pytest.mark.parametrize(
    "name", ["vol_targeting", "risk_parity_inverse_vol", "risk_parity_hrp"]
)
def test_allocation_strategy_matches_golden(name: str):
    snap = _snapshot(_run(_strategies()[name]))
    _assert_matches_golden(name, snap)


def test_allocation_golden_run_is_deterministic():
    a = _snapshot(_run(_strategies()["risk_parity_hrp"]))
    b = _snapshot(_run(_strategies()["risk_parity_hrp"]))
    assert a == b
