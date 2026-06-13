"""Unit tests for the price-only reference strategies (component 10.3).

Three committed reference strategies built on the C10.1 base templates:

- ``buy_and_hold`` — a static :class:`WeightStrategy`: equal weights across the
  universe summing to a target gross (no data dependence).
- ``momentum_12_1`` — a :class:`CrossSectionalStrategy` ranking on the trailing
  12-month return that *skips the most recent month* (the classic 12-1 momentum),
  yielding a dollar-neutral long-winners / short-losers book.
- ``mean_reversion`` — a :class:`SignalStrategy` that fades z-score extremes:
  longs (+1) symbols trading below their trailing mean, shorts (-1) those above.

Each is registered under its name (importing the package registers it), runs
end-to-end through the :class:`VectorizedEngine` (one equity point per session)
and only ever reads ``data.window`` / ``data.now`` (no future peeking — the
engine's mandatory one-bar lag means a signal at ``t`` earns nothing until
``t+1``).

See ``docs/designs/backtest-design/10-strategy-library.md``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from openbb_backtest.interfaces import Strategy

_SESSIONS = pd.to_datetime(
    [
        "2021-01-04",
        "2021-01-05",
        "2021-01-06",
        "2021-01-07",
        "2021-01-08",
        "2021-01-11",
    ]
)


# ---- in-memory market doubles (long-format OHLCV, look-ahead safe) -------


def _long_frame(closes: dict[str, list[float]]) -> pd.DataFrame:
    """Build a long-format OHLCV frame from per-symbol close lists."""
    rows = []
    for sym, series in closes.items():
        for sess, px in zip(_SESSIONS[: len(series)], series):
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


class _PanelMarket:
    """A :class:`MarketData` over an in-memory long-format OHLCV frame."""

    def __init__(self, closes: dict[str, list[float]], now: pd.Timestamp | None = None) -> None:
        self._frame = _long_frame(closes)
        self._now = pd.Timestamp(now) if now is not None else _SESSIONS[-1]

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
    """Minimal ``DataFeed`` over the same long-format OHLCV frame."""

    def __init__(self, closes: dict[str, list[float]]) -> None:
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


def _config(universe: list[str], **kw):
    from openbb_backtest.models import BacktestConfig, CommissionModel, SlippageModel

    params = dict(
        strategy="buy_and_hold",
        universe=universe,
        start=date(2021, 1, 4),
        end=date(2021, 1, 11),
        engine="vectorized",
        initial_cash=Decimal("100000"),
        commission=CommissionModel(),
        slippage=SlippageModel(),
    )
    params.update(kw)
    return BacktestConfig(**params)


def _broker(config):
    from openbb_backtest.engine.execution import RealisticBroker

    return RealisticBroker(config.commission, config.slippage)


# ---- discovery / registration by name ------------------------------------


def test_reference_strategies_registered_by_name():
    import openbb_backtest.strategies  # noqa: F401 - import registers
    from openbb_backtest.registry import list_strategies

    names = list_strategies()
    assert "buy_and_hold" in names
    assert "momentum_12_1" in names
    assert "mean_reversion" in names


def test_each_reference_resolves_to_strategy_instance():
    import openbb_backtest.strategies  # noqa: F401
    from openbb_backtest.strategies.discovery import resolve

    for name in ("buy_and_hold", "momentum_12_1", "mean_reversion"):
        obj = resolve(name, {"symbols": ["AAA", "BBB"]})
        assert isinstance(obj, Strategy)
        assert obj.id == name


# ---- buy_and_hold: static, equal weight, sums to target gross ------------


def test_buy_and_hold_equal_weight_sums_to_target_gross():
    from openbb_backtest.strategies.buy_and_hold import BuyAndHold

    out = BuyAndHold(symbols=["AAA", "BBB", "CCC"]).generate(
        _PanelMarket({"AAA": [1.0], "BBB": [1.0], "CCC": [1.0]})
    )
    assert list(out.columns) == ["weight"]
    assert out["weight"].sum() == pytest.approx(1.0)
    assert out.loc["AAA", "weight"] == pytest.approx(1 / 3)


def test_buy_and_hold_respects_custom_gross():
    from openbb_backtest.strategies.buy_and_hold import BuyAndHold

    out = BuyAndHold(symbols=["AAA", "BBB"], gross=0.5).generate(
        _PanelMarket({"AAA": [1.0], "BBB": [1.0]})
    )
    assert out["weight"].sum() == pytest.approx(0.5)


def test_buy_and_hold_is_static_across_sessions():
    from openbb_backtest.strategies.buy_and_hold import BuyAndHold

    bah = BuyAndHold(symbols=["AAA", "BBB"])
    early = bah.generate(_PanelMarket({"AAA": [1.0, 2.0], "BBB": [1.0, 9.0]}, now=_SESSIONS[0]))
    late = bah.generate(_PanelMarket({"AAA": [1.0, 2.0], "BBB": [1.0, 9.0]}, now=_SESSIONS[1]))
    pd.testing.assert_frame_equal(early, late)


# ---- momentum_12_1: provably skips the most recent month -----------------


def test_momentum_skips_most_recent_month():
    from openbb_backtest.strategies.momentum import Momentum

    # AAA rises across the window then crashes on the last (skipped) day;
    # BBB is flat across the window then spikes on the last (skipped) day.
    closes = {
        "AAA": [100.0, 101.0, 102.0, 103.0, 104.0, 50.0],
        "BBB": [100.0, 100.0, 100.0, 100.0, 100.0, 500.0],
    }
    mom = Momentum(symbols=["AAA", "BBB"], lookback=3, skip=1)
    scores = mom.rank(_PanelMarket(closes))
    # Skipping the last day, AAA's window return is positive and BBB's is ~0,
    # so AAA outranks BBB. Including the last day would flip this entirely.
    assert scores["AAA"] > scores["BBB"]


def test_momentum_longs_winner_shorts_loser_dollar_neutral():
    from openbb_backtest.strategies.momentum import Momentum

    closes = {
        "AAA": [100.0, 101.0, 102.0, 103.0, 104.0, 50.0],
        "BBB": [100.0, 100.0, 100.0, 100.0, 100.0, 500.0],
    }
    out = Momentum(symbols=["AAA", "BBB"], lookback=3, skip=1).generate(_PanelMarket(closes))
    assert out.loc["AAA", "weight"] > 0.0  # long the winner
    assert out.loc["BBB", "weight"] < 0.0  # short the loser
    assert out["weight"].sum() == pytest.approx(0.0)  # dollar-neutral
    assert out["weight"].abs().sum() == pytest.approx(1.0)  # gross 1.0


def test_momentum_default_lookback_is_twelve_one_months():
    from openbb_backtest.strategies.momentum import Momentum

    mom = Momentum(symbols=["AAA"])
    # 12 months / 1 month expressed in trading days.
    assert mom.lookback == 252
    assert mom.skip == 21


# ---- mean_reversion: fade z-score extremes -------------------------------


def test_mean_reversion_longs_negative_zscore_shorts_positive():
    from openbb_backtest.strategies.mean_reversion import MeanReversion

    closes = {
        "AAA": [100.0, 101.0, 99.0, 100.0, 80.0],   # last price far below mean -> long
        "BBB": [100.0, 101.0, 99.0, 100.0, 120.0],  # last price far above mean -> short/zero
        "CCC": [100.0, 101.0, 99.0, 100.0, 100.0],  # at the mean -> flat
    }
    mr = MeanReversion(symbols=["AAA", "BBB", "CCC"], lookback=4, entry_z=1.0)
    sig = mr.signal(_PanelMarket(closes))
    assert sig["AAA"] == 1   # long the depressed name
    assert sig["BBB"] <= 0   # short (or zero) the elevated name
    assert sig["CCC"] == 0   # flat at the mean


def test_mean_reversion_generate_maps_signals_to_weights():
    from openbb_backtest.strategies.mean_reversion import MeanReversion

    closes = {
        "AAA": [100.0, 101.0, 99.0, 100.0, 80.0],
        "BBB": [100.0, 101.0, 99.0, 100.0, 120.0],
    }
    out = MeanReversion(symbols=["AAA", "BBB"], lookback=4, entry_z=1.0).generate(
        _PanelMarket(closes)
    )
    assert out.loc["AAA", "weight"] > 0.0
    assert out.loc["BBB", "weight"] < 0.0
    assert out["weight"].abs().sum() == pytest.approx(1.0)


def test_mean_reversion_flat_when_within_band():
    from openbb_backtest.strategies.mean_reversion import MeanReversion

    closes = {
        "AAA": [100.0, 101.0, 99.0, 100.0, 100.5],  # tiny deviation, within band
        "BBB": [100.0, 101.0, 99.0, 100.0, 99.5],
    }
    sig = MeanReversion(symbols=["AAA", "BBB"], lookback=4, entry_z=3.0).signal(
        _PanelMarket(closes)
    )
    assert (sig == 0).all()


# ---- end-to-end via VectorizedEngine -------------------------------------


def test_buy_and_hold_runs_e2e_one_equity_point_per_session():
    from openbb_backtest.engine.vectorized import VectorizedEngine
    from openbb_backtest.strategies.buy_and_hold import BuyAndHold

    closes = {"AAA": [100.0] * 6, "BBB": [100.0] * 6}
    cfg = _config(["AAA", "BBB"])
    res = VectorizedEngine().run(
        BuyAndHold(symbols=["AAA", "BBB"]), cfg, _MemFeed(closes), _broker(cfg)
    )
    assert res.engine_used == "vectorized"
    assert len(res.equity_curve) == len(_SESSIONS)


def test_reference_strategy_signal_earns_nothing_until_next_bar():
    from openbb_backtest.engine.vectorized import VectorizedEngine
    from openbb_backtest.strategies.buy_and_hold import BuyAndHold

    # AAA +10%/session held buy-and-hold: nothing is held on bar 0 (mandatory
    # one-bar lag), so equity[0] is exactly the starting cash and the first
    # return only lands on bar 1.
    closes = {"AAA": [100.0, 110.0, 121.0, 133.1, 146.41, 161.051]}
    cfg = _config(["AAA"])
    res = VectorizedEngine().run(
        BuyAndHold(symbols=["AAA"]), cfg, _MemFeed(closes), _broker(cfg)
    )
    eq = [float(p.equity) for p in res.equity_curve]
    assert eq[0] == pytest.approx(100000.0)
    assert eq[1] == pytest.approx(eq[0] * 1.10, rel=1e-9)
