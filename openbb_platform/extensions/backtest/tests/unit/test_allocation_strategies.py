"""Unit tests for the allocation strategies (component 10.4).

Two portfolio-construction strategies built on the C10.1 base templates:

- ``vol_targeting`` — a :class:`WeightStrategy` that equal-weights the universe
  then scales gross exposure so the book's *realized* annualized volatility
  (estimated from a trailing window) hits a target; it scales **down** when
  trailing vol is high.
- ``risk_parity`` — a :class:`WeightStrategy` offering two long-only,
  sum-to-one schemes: plain inverse-volatility and López de Prado's
  Hierarchical Risk Parity (HRP = correlation-distance linkage →
  quasi-diagonalization → recursive bisection). HRP uses scipy's clustering
  (BSD, already a declared dependency).

Both run end-to-end through the :class:`VectorizedEngine` and are deterministic
given the same inputs.

See ``docs/designs/backtest-design/10-strategy-library.md``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

_SESSIONS = pd.bdate_range("2021-01-04", periods=60)


# ---- in-memory market doubles -------------------------------------------


def _long_frame(closes: dict[str, np.ndarray]) -> pd.DataFrame:
    rows = []
    for sym, series in closes.items():
        for sess, px in zip(_SESSIONS[: len(series)], series):
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


class _PanelMarket:
    """A :class:`MarketData` over an in-memory long-format OHLCV frame."""

    def __init__(self, closes: dict[str, np.ndarray], now: pd.Timestamp | None = None) -> None:
        self._frame = _long_frame(closes)
        self._now = pd.Timestamp(now) if now is not None else self._frame["session"].max()

    def window(self, symbols: list[str], lookback: int) -> pd.DataFrame:
        frame = self._frame
        mask = frame["symbol"].isin(symbols) & (frame["session"] <= self._now)
        return (
            frame.loc[mask]
            .sort_values("session")
            .groupby("symbol", group_keys=False)
            .tail(lookback)
            .reset_index(drop=True)
        )

    @property
    def now(self) -> pd.Timestamp:
        return self._now


class _MemFeed:
    def __init__(self, closes: dict[str, np.ndarray]) -> None:
        self._frame = _long_frame(closes)

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


def _gbm(mu: float, sigma: float, n: int, seed: int, s0: float = 100.0) -> np.ndarray:
    """Deterministic geometric-random-walk close series at a given daily vol."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(mu, sigma, size=n)
    return s0 * np.exp(np.cumsum(rets))


# ---- vol_targeting -------------------------------------------------------


def test_vol_targeting_registered_and_resolvable():
    import openbb_backtest.strategies  # noqa: F401
    from openbb_backtest.registry import list_strategies

    assert "vol_targeting" in list_strategies()


def test_vol_targeting_scales_gross_to_hit_target_vol():
    from openbb_backtest.strategies.vol_targeting import VolTargeting

    # A single asset at ~16% annualized vol (1%/day * sqrt(252) ~= 0.1587).
    closes = {"AAA": _gbm(0.0, 0.01, 60, seed=1)}
    out = VolTargeting(symbols=["AAA"], target_vol=0.08, lookback=40).generate(
        _PanelMarket(closes)
    )
    # Target 8% on a ~16% asset -> scale gross to ~0.5.
    assert out["weight"].abs().sum() == pytest.approx(0.5, abs=0.15)


def test_vol_targeting_scales_down_when_trailing_vol_high():
    from openbb_backtest.strategies.vol_targeting import VolTargeting

    calm = {"AAA": _gbm(0.0, 0.005, 60, seed=2)}
    wild = {"AAA": _gbm(0.0, 0.02, 60, seed=2)}
    vt = VolTargeting(symbols=["AAA"], target_vol=0.10, lookback=40)
    gross_calm = vt.generate(_PanelMarket(calm))["weight"].abs().sum()
    gross_wild = vt.generate(_PanelMarket(wild))["weight"].abs().sum()
    # Higher trailing vol -> smaller gross exposure.
    assert gross_wild < gross_calm


def test_vol_targeting_runs_e2e_on_vectorized_engine():
    from openbb_backtest.engine.execution import RealisticBroker
    from openbb_backtest.engine.vectorized import VectorizedEngine
    from openbb_backtest.models import BacktestConfig, CommissionModel, SlippageModel
    from openbb_backtest.strategies.vol_targeting import VolTargeting

    closes = {"AAA": _gbm(0.0005, 0.01, 60, 3), "BBB": _gbm(0.0, 0.008, 60, 4)}
    cfg = BacktestConfig(
        strategy="vol_targeting",
        universe=["AAA", "BBB"],
        start=date(2021, 1, 4),
        end=_SESSIONS[-1].date(),
        engine="vectorized",
        initial_cash=Decimal("100000"),
        commission=CommissionModel(),
        slippage=SlippageModel(),
    )
    res = VectorizedEngine().run(
        VolTargeting(symbols=["AAA", "BBB"], target_vol=0.10, lookback=30),
        cfg,
        _MemFeed(closes),
        RealisticBroker(cfg.commission, cfg.slippage),
    )
    assert len(res.equity_curve) == len(_SESSIONS)


# ---- risk_parity: inverse-vol -------------------------------------------


def test_risk_parity_registered_and_resolvable():
    import openbb_backtest.strategies  # noqa: F401
    from openbb_backtest.registry import list_strategies

    assert "risk_parity" in list_strategies()


def test_inverse_vol_weights_positive_and_sum_to_one():
    from openbb_backtest.strategies.risk_parity import RiskParity

    # AAA twice as volatile as BBB -> BBB gets twice the weight.
    closes = {"AAA": _gbm(0.0, 0.02, 60, 5), "BBB": _gbm(0.0, 0.01, 60, 6)}
    out = RiskParity(symbols=["AAA", "BBB"], method="inverse_vol", lookback=40).generate(
        _PanelMarket(closes)
    )
    assert (out["weight"] > 0).all()
    assert out["weight"].sum() == pytest.approx(1.0)
    assert out.loc["BBB", "weight"] > out.loc["AAA", "weight"]


# ---- risk_parity: HRP (Lopez de Prado) ----------------------------------


def test_hrp_quasi_diag_reproduces_known_ordering():
    from openbb_backtest.strategies.risk_parity import quasi_diagonal_order

    # Assets 0 & 2 form one correlated pair, 1 & 3 the other (non-adjacent
    # indices): quasi-diagonalization must reorder them adjacent -> [0, 2, 1, 3].
    corr = np.array(
        [
            [1.0, 0.1, 0.9, 0.1],
            [0.1, 1.0, 0.1, 0.8],
            [0.9, 0.1, 1.0, 0.1],
            [0.1, 0.8, 0.1, 1.0],
        ]
    )
    assert quasi_diagonal_order(corr) == [0, 2, 1, 3]


def test_hrp_weights_positive_sum_to_one():
    from openbb_backtest.strategies.risk_parity import RiskParity

    closes = {
        "AAA": _gbm(0.0, 0.02, 80, 7),
        "BBB": _gbm(0.0, 0.015, 80, 8),
        "CCC": _gbm(0.0, 0.01, 80, 9),
        "DDD": _gbm(0.0, 0.008, 80, 10),
    }
    out = RiskParity(
        symbols=["AAA", "BBB", "CCC", "DDD"], method="hrp", lookback=60
    ).generate(_PanelMarket(closes))
    assert (out["weight"] > 0).all()
    assert out["weight"].sum() == pytest.approx(1.0)


def test_hrp_is_deterministic_given_same_data():
    from openbb_backtest.strategies.risk_parity import RiskParity

    closes = {
        "AAA": _gbm(0.0, 0.02, 80, 11),
        "BBB": _gbm(0.0, 0.01, 80, 12),
        "CCC": _gbm(0.0, 0.015, 80, 13),
    }
    rp = RiskParity(symbols=["AAA", "BBB", "CCC"], method="hrp", lookback=60)
    a = rp.generate(_PanelMarket(closes))
    b = rp.generate(_PanelMarket(closes))
    pd.testing.assert_frame_equal(a, b)


def test_risk_parity_rejects_unknown_method():
    from openbb_backtest.strategies.risk_parity import RiskParity

    with pytest.raises(ValueError, match="method"):
        RiskParity(symbols=["AAA"], method="bogus")


def test_risk_parity_runs_e2e_on_vectorized_engine():
    from openbb_backtest.engine.execution import RealisticBroker
    from openbb_backtest.engine.vectorized import VectorizedEngine
    from openbb_backtest.models import BacktestConfig, CommissionModel, SlippageModel
    from openbb_backtest.strategies.risk_parity import RiskParity

    closes = {"AAA": _gbm(0.0003, 0.012, 60, 14), "BBB": _gbm(0.0, 0.009, 60, 15)}
    cfg = BacktestConfig(
        strategy="risk_parity",
        universe=["AAA", "BBB"],
        start=date(2021, 1, 4),
        end=_SESSIONS[-1].date(),
        engine="vectorized",
        initial_cash=Decimal("100000"),
        commission=CommissionModel(),
        slippage=SlippageModel(),
    )
    res = VectorizedEngine().run(
        RiskParity(symbols=["AAA", "BBB"], method="hrp", lookback=40),
        cfg,
        _MemFeed(closes),
        RealisticBroker(cfg.commission, cfg.slippage),
    )
    assert len(res.equity_curve) == len(_SESSIONS)
