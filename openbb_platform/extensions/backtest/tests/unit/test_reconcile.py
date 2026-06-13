"""Unit tests for the engine reconciliation gate (component 04, §3).

The gate is engine-agnostic: it runs a baseline config through two engines and
asserts their equity curves agree within ``reconcile_tolerance``. Here we
exercise the mechanism with the vectorized engine against itself (must pass) and
against a deliberately perturbed stub engine (must fail) — the live
vectorized-vs-event reconciliation test is added when the event engine (C05)
lands.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from openbb_backtest.engine.execution import RealisticBroker
from openbb_backtest.engine.vectorized import VectorizedEngine
from openbb_backtest.models import BacktestConfig, CommissionModel, SlippageModel

_SESSIONS = pd.to_datetime(
    ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07", "2021-01-08"]
)


def _ohlcv_frame() -> pd.DataFrame:
    rows = []
    for sym, base, step in (("AAA", 100.0, 1.01), ("BBB", 100.0, 0.99)):
        price = base
        for sess in _SESSIONS:
            rows.append(
                {
                    "symbol": sym,
                    "session": sess,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1_000_000.0,
                    "adj_factor": 1.0,
                }
            )
            price *= step
    return pd.DataFrame(rows)


class _MatrixFeed:
    def __init__(self, ohlcv: pd.DataFrame) -> None:
        self._ohlcv = ohlcv

    def history(self, symbols, end, lookback):
        end = pd.Timestamp(end)
        frame = self._ohlcv
        mask = frame["symbol"].isin(symbols) & (frame["session"] <= end)
        return (
            frame.loc[mask]
            .sort_values("session")
            .groupby("symbol", group_keys=False)
            .tail(lookback)
            .reset_index(drop=True)
        )

    def sessions(self, start, end):
        s = self._ohlcv["session"]
        return pd.DatetimeIndex(
            sorted(s[(s >= pd.Timestamp(start)) & (s <= pd.Timestamp(end))].unique())
        )


class _EqualWeight:
    id = "equal_weight"

    def generate(self, data) -> pd.DataFrame:
        return pd.DataFrame({"weight": [0.5, 0.5]}, index=["AAA", "BBB"])


class _PerturbedEngine(VectorizedEngine):
    """A vectorized engine whose equity is nudged to force a divergence."""

    name = "perturbed"

    def run(self, strategy, config, feed, broker):
        res = super().run(strategy, config, feed, broker)
        bumped = list(res.equity_curve)
        bumped[-1] = bumped[-1].model_copy(
            update={"equity": bumped[-1].equity + Decimal("1")}
        )
        return res.model_copy(update={"equity_curve": bumped})


def _config():
    return BacktestConfig(
        strategy="equal_weight",
        universe=["AAA", "BBB"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 8),
        engine="vectorized",
        commission=CommissionModel(),
        slippage=SlippageModel(),
    )


def _broker(cfg):
    return RealisticBroker(cfg.commission, cfg.slippage)


def test_equity_array_extracts_curve_as_floats():
    from openbb_backtest.engine.reconcile import equity_array

    cfg = _config()
    res = VectorizedEngine().run(_EqualWeight(), cfg, _MatrixFeed(_ohlcv_frame()), _broker(cfg))
    arr = equity_array(res)
    assert isinstance(arr, np.ndarray)
    assert arr.shape == (len(_SESSIONS),)
    assert arr[0] == pytest.approx(100000.0)


def test_max_equity_divergence_zero_for_identical_results():
    from openbb_backtest.engine.reconcile import max_equity_divergence

    cfg = _config()
    res = VectorizedEngine().run(_EqualWeight(), cfg, _MatrixFeed(_ohlcv_frame()), _broker(cfg))
    assert max_equity_divergence(res, res) == pytest.approx(0.0)


def test_reconcile_passes_engine_against_itself():
    from openbb_backtest.engine.reconcile import reconcile

    cfg = _config()
    report = reconcile(
        VectorizedEngine(),
        VectorizedEngine(),
        _EqualWeight(),
        cfg,
        _MatrixFeed(_ohlcv_frame()),
        _broker(cfg),
    )
    assert report.passed is True
    assert report.max_divergence == pytest.approx(0.0)
    assert report.tolerance == pytest.approx(1e-6)


def test_reconcile_fails_when_engines_diverge_beyond_tolerance():
    from openbb_backtest.engine.reconcile import reconcile

    cfg = _config()
    report = reconcile(
        VectorizedEngine(),
        _PerturbedEngine(),
        _EqualWeight(),
        cfg,
        _MatrixFeed(_ohlcv_frame()),
        _broker(cfg),
        tolerance=1e-6,
    )
    assert report.passed is False
    assert report.max_divergence >= 1.0


def test_reconcile_raises_in_strict_mode_on_divergence():
    from openbb_backtest.engine.reconcile import ReconciliationError, reconcile

    cfg = _config()
    with pytest.raises(ReconciliationError):
        reconcile(
            VectorizedEngine(),
            _PerturbedEngine(),
            _EqualWeight(),
            cfg,
            _MatrixFeed(_ohlcv_frame()),
            _broker(cfg),
            strict=True,
        )
