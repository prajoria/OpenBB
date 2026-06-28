"""Unit tests for ``strategies/base.py`` (component 10.1, strategy templates).

Covers the three engine-agnostic base classes that satisfy the
:class:`~openbb_backtest.interfaces.Strategy` protocol by normalizing a single
abstract hook into the symbol-indexed weight DataFrame the engines'
``_build_weights`` consumes:

- :class:`WeightStrategy` — hook ``target_weights`` is validated and passed
  through (NaN-safe) into a ``['weight']`` column.
- :class:`SignalStrategy` — hook ``signal`` (values in ``{-1, 0, 1}``) is mapped
  to weights whose gross exposure sums to ``target_gross``.
- :class:`CrossSectionalStrategy` — hook ``rank`` is demeaned and normalized to
  dollar-neutral weights whose gross exposure sums to ``target_gross``.

All three only ever touch ``data.window`` / ``data.now`` (point-in-time, no
future peeking) — the templates delegate the lone hook the exact ``MarketData``
they were handed and add no data access of their own.

See ``docs/designs/backtest-design/10-strategies.md`` and
``openbb_backtest/interfaces.py`` (Strategy / MarketData protocols).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from openbb_backtest.interfaces import Strategy

# ---- test doubles: real (non-mock) point-in-time market views ------------


class _FakeMarket:
    """Minimal real :class:`MarketData`: exposes only ``window`` and ``now``."""

    def __init__(self, frame: pd.DataFrame, now: pd.Timestamp) -> None:
        self._frame = frame
        self._now = now

    def window(self, symbols: list[str], lookback: int) -> pd.DataFrame:
        return self._frame.loc[:, symbols].tail(lookback)

    @property
    def now(self) -> pd.Timestamp:
        return self._now


class _RecordingMarket(_FakeMarket):
    """A :class:`_FakeMarket` that records which attributes were accessed."""

    def __init__(self, frame: pd.DataFrame, now: pd.Timestamp) -> None:
        super().__init__(frame, now)
        self.accessed: set[str] = set()

    def window(self, symbols: list[str], lookback: int) -> pd.DataFrame:
        self.accessed.add("window")
        return super().window(symbols, lookback)

    @property
    def now(self) -> pd.Timestamp:
        self.accessed.add("now")
        return super().now


def _market(symbols: list[str]) -> _FakeMarket:
    idx = pd.date_range("2021-01-01", periods=5, freq="D")
    frame = pd.DataFrame(1.0, index=idx, columns=symbols)
    return _FakeMarket(frame, idx[-1])


# ---- protocol conformance + settable id ----------------------------------


def test_each_base_satisfies_strategy_protocol():
    from openbb_backtest.strategies.base import (
        CrossSectionalStrategy,
        SignalStrategy,
        WeightStrategy,
    )

    assert isinstance(WeightStrategy(), Strategy)
    assert isinstance(SignalStrategy(), Strategy)
    assert isinstance(CrossSectionalStrategy(), Strategy)


def test_id_is_settable_via_ctor_and_attribute():
    from openbb_backtest.strategies.base import WeightStrategy

    s = WeightStrategy(id="momentum")
    assert s.id == "momentum"
    s.id = "renamed"
    assert s.id == "renamed"
    assert isinstance(s, Strategy)


# ---- abstract hooks ------------------------------------------------------


def test_abstract_hooks_raise_not_implemented():
    from openbb_backtest.strategies.base import (
        CrossSectionalStrategy,
        SignalStrategy,
        WeightStrategy,
    )

    data = _market(["AAA"])
    with pytest.raises(NotImplementedError):
        WeightStrategy().target_weights(data)
    with pytest.raises(NotImplementedError):
        SignalStrategy().signal(data)
    with pytest.raises(NotImplementedError):
        CrossSectionalStrategy().rank(data)


# ---- WeightStrategy: validated passthrough -------------------------------


def test_weight_strategy_generate_returns_symbol_indexed_weight_column():
    from openbb_backtest.strategies.base import WeightStrategy

    class _Fixed(WeightStrategy):
        def target_weights(self, data):  # noqa: ANN001
            return pd.Series({"AAA": 0.6, "BBB": 0.4})

    out = _Fixed().generate(_market(["AAA", "BBB"]))
    assert isinstance(out, pd.DataFrame)
    assert list(out.columns) == ["weight"]
    assert list(out.index) == ["AAA", "BBB"]


def test_weight_strategy_passthrough_values_unchanged():
    from openbb_backtest.strategies.base import WeightStrategy

    weights = pd.Series({"AAA": 0.6, "BBB": -0.4})

    class _Fixed(WeightStrategy):
        def target_weights(self, data):  # noqa: ANN001
            return weights

    out = _Fixed().generate(_market(["AAA", "BBB"]))
    assert out.loc["AAA", "weight"] == pytest.approx(0.6)
    assert out.loc["BBB", "weight"] == pytest.approx(-0.4)


def test_weight_strategy_is_nan_safe():
    from openbb_backtest.strategies.base import WeightStrategy

    class _Fixed(WeightStrategy):
        def target_weights(self, data):  # noqa: ANN001
            return pd.Series({"AAA": 0.5, "BBB": np.nan})

    out = _Fixed().generate(_market(["AAA", "BBB"]))
    assert out.loc["BBB", "weight"] == pytest.approx(0.0)
    assert not out["weight"].isna().any()


# ---- SignalStrategy: signals -> weights ----------------------------------


def test_signal_strategy_maps_signals_to_weights_summing_to_gross():
    from openbb_backtest.strategies.base import SignalStrategy

    class _Sig(SignalStrategy):
        def signal(self, data):  # noqa: ANN001
            return pd.Series({"AAA": 1, "BBB": -1, "CCC": 0})

    out = _Sig().generate(_market(["AAA", "BBB", "CCC"]))
    assert out.loc["AAA", "weight"] == pytest.approx(0.5)
    assert out.loc["BBB", "weight"] == pytest.approx(-0.5)
    assert out.loc["CCC", "weight"] == pytest.approx(0.0)
    # Gross exposure equals the (default) target gross of 1.0.
    assert out["weight"].abs().sum() == pytest.approx(1.0)


def test_signal_strategy_respects_custom_target_gross():
    from openbb_backtest.strategies.base import SignalStrategy

    class _Sig(SignalStrategy):
        def signal(self, data):  # noqa: ANN001
            return pd.Series({"AAA": 1, "BBB": 1})

    out = _Sig(target_gross=2.0).generate(_market(["AAA", "BBB"]))
    assert out["weight"].abs().sum() == pytest.approx(2.0)
    assert out.loc["AAA", "weight"] == pytest.approx(1.0)


def test_signal_strategy_rejects_non_unit_signals():
    from openbb_backtest.strategies.base import SignalStrategy

    class _Bad(SignalStrategy):
        def signal(self, data):  # noqa: ANN001
            return pd.Series({"AAA": 2, "BBB": 0})

    with pytest.raises(ValueError, match="signal"):
        _Bad().generate(_market(["AAA", "BBB"]))


def test_signal_strategy_all_flat_gives_zero_weights():
    from openbb_backtest.strategies.base import SignalStrategy

    class _Flat(SignalStrategy):
        def signal(self, data):  # noqa: ANN001
            return pd.Series({"AAA": 0, "BBB": 0})

    out = _Flat().generate(_market(["AAA", "BBB"]))
    assert out["weight"].abs().sum() == pytest.approx(0.0)


# ---- CrossSectionalStrategy: rank -> dollar-neutral weights --------------


def test_cross_sectional_normalizes_rank_to_target_gross():
    from openbb_backtest.strategies.base import CrossSectionalStrategy

    class _Rank(CrossSectionalStrategy):
        def rank(self, data):  # noqa: ANN001
            return pd.Series({"AAA": 3.0, "BBB": 2.0, "CCC": 1.0})

    out = _Rank().generate(_market(["AAA", "BBB", "CCC"]))
    # Demeaned (mean 2): +1, 0, -1; gross 2 -> scale to target gross 1.0.
    assert out.loc["AAA", "weight"] == pytest.approx(0.5)
    assert out.loc["BBB", "weight"] == pytest.approx(0.0)
    assert out.loc["CCC", "weight"] == pytest.approx(-0.5)
    assert out["weight"].abs().sum() == pytest.approx(1.0)
    # Dollar-neutral: net exposure cancels.
    assert out["weight"].sum() == pytest.approx(0.0)


def test_cross_sectional_respects_custom_target_gross():
    from openbb_backtest.strategies.base import CrossSectionalStrategy

    class _Rank(CrossSectionalStrategy):
        def rank(self, data):  # noqa: ANN001
            return pd.Series({"AAA": 3.0, "BBB": 2.0, "CCC": 1.0})

    out = _Rank(target_gross=2.0).generate(_market(["AAA", "BBB", "CCC"]))
    assert out["weight"].abs().sum() == pytest.approx(2.0)


def test_cross_sectional_flat_ranks_give_zero_weights():
    from openbb_backtest.strategies.base import CrossSectionalStrategy

    class _Flat(CrossSectionalStrategy):
        def rank(self, data):  # noqa: ANN001
            return pd.Series({"AAA": 5.0, "BBB": 5.0})

    out = _Flat().generate(_market(["AAA", "BBB"]))
    assert out["weight"].abs().sum() == pytest.approx(0.0)


# ---- point-in-time discipline: only window / now, same data object -------


def test_only_reads_window_and_now_no_peeking():
    from openbb_backtest.strategies.base import WeightStrategy

    seen: dict[str, object] = {}

    class _Reader(WeightStrategy):
        def target_weights(self, data):  # noqa: ANN001
            seen["data"] = data
            window = data.window(["AAA"], 2)
            _ = data.now
            return pd.Series({"AAA": float(len(window))})

    idx = pd.date_range("2021-01-01", periods=5, freq="D")
    market = _RecordingMarket(pd.DataFrame(1.0, index=idx, columns=["AAA"]), idx[-1])
    _Reader().generate(market)

    # The template hands the hook the exact same market object (no peeking wrapper).
    assert seen["data"] is market
    # Only the two point-in-time members were ever touched.
    assert market.accessed
    assert market.accessed <= {"window", "now"}


def test_generate_is_deterministic():
    from openbb_backtest.strategies.base import CrossSectionalStrategy

    class _Rank(CrossSectionalStrategy):
        def rank(self, data):  # noqa: ANN001
            return pd.Series({"AAA": 3.0, "BBB": 1.0, "CCC": 2.0})

    market = _market(["AAA", "BBB", "CCC"])
    a = _Rank().generate(market)
    b = _Rank().generate(market)
    pd.testing.assert_frame_equal(a, b)
