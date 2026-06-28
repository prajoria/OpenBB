"""Golden-fixture regression lock for the factor-tilt strategy (C10.5).

``factor_tilt`` is run end-to-end through the :class:`VectorizedEngine` on a
fixed, deterministic in-memory OHLCV panel with a **static stub score provider**
(so the lock is offline and independent of the live ``Analysis`` pipeline, whose
behavior is covered separately by the integration-gated bridge test). Its equity
curve + summary metrics are compared against a committed golden JSON fixture
within ``1e-6``.

Carries the ``golden`` marker (run with ``-m golden``). Regenerate the committed
fixture intentionally with ``BACKTEST_REGEN_GOLDEN=1`` after a *reviewed*
behavioral change — never blindly.

See ``docs/designs/backtest-design/10-strategy-library.md`` §3.
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

# A deterministic 30-session, 3-symbol panel: AAA trends up, BBB sideways, CCC
# down. The stub factor scores favor AAA over BBB over CCC, so the tilt should
# end up long the up-trender and short the down-trender.
_SESSIONS = pd.bdate_range("2021-01-04", periods=30)
_CLOSES = {
    "AAA": np.linspace(100.0, 140.0, len(_SESSIONS)),
    "BBB": np.full(len(_SESSIONS), 100.0) + np.sin(np.arange(len(_SESSIONS))) * 2.0,
    "CCC": np.linspace(100.0, 70.0, len(_SESSIONS)),
}
_SCORES = {"AAA": 4.5, "BBB": 3.0, "CCC": 1.0}


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


def _run():
    from openbb_backtest.engine.execution import RealisticBroker
    from openbb_backtest.engine.vectorized import VectorizedEngine
    from openbb_backtest.models import BacktestConfig, CommissionModel, SlippageModel
    from openbb_backtest.strategies.factor_tilt import FactorTilt

    universe = ["AAA", "BBB", "CCC"]
    cfg = BacktestConfig(
        strategy="factor_tilt",
        universe=universe,
        start=_SESSIONS[0].date(),
        end=_SESSIONS[-1].date(),
        engine="vectorized",
        initial_cash=Decimal("100000"),
        commission=CommissionModel(),
        slippage=SlippageModel(),
    )
    strategy = FactorTilt(symbols=universe, score_provider=_SCORES)
    return VectorizedEngine().run(
        strategy, cfg, _MemFeed(), RealisticBroker(cfg.commission, cfg.slippage)
    )


def _snapshot(result) -> dict:  # noqa: ANN001
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


def test_factor_tilt_matches_golden():
    _assert_matches_golden("factor_tilt", _snapshot(_run()))


def test_factor_tilt_golden_run_is_deterministic():
    assert _snapshot(_run()) == _snapshot(_run())
