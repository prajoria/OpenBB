"""Unit tests for the vectorized in-house engine (component 04).

Covers the (T, S) accounting math, the Numba hot-path kernels (which run as
correct pure-Python when numba is absent — "CPU is always correct"), the
``VectorizedEngine`` end-to-end run with the MANDATORY ``shift(1)`` look-ahead
guard, and the ``sweep`` parameter-grid API.

See ``docs/designs/backtest-design/04-vectorized-engine.md``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from openbb_backtest.models import CommissionModel, SlippageModel

# ---- Accounting math (pure NumPy) ---------------------------------------


def test_lag_weights_applies_mandatory_one_bar_shift():
    from openbb_backtest.engine.vectorized import lag_weights

    w = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    lagged = lag_weights(w)
    # Row t holds the weights generated at t-1.
    np.testing.assert_allclose(lagged, [[0.0, 0.0], [1.0, 2.0], [3.0, 4.0]])


def test_lag_weights_first_row_is_zero_no_same_bar_fill():
    from openbb_backtest.engine.vectorized import lag_weights

    w = np.array([[0.9, 0.1]])
    lagged = lag_weights(w)
    # A single-session run can hold nothing on its own bar.
    np.testing.assert_allclose(lagged, [[0.0, 0.0]])


def test_simple_returns_first_row_zero_then_pct_change():
    from openbb_backtest.engine.vectorized import simple_returns

    close = np.array([[100.0], [110.0], [99.0]])
    rets = simple_returns(close)
    np.testing.assert_allclose(rets, [[0.0], [0.10], [-0.10]])


def test_turnover_is_sum_abs_weight_delta_per_session():
    from openbb_backtest.engine.vectorized import turnover

    w_lag = np.array([[0.0, 0.0], [0.5, 0.5], [0.5, -0.5]])
    # |Δ| per session: row0 from flat = 0; row1 = 0.5+0.5 = 1.0; row2 = 0 + 1.0
    np.testing.assert_allclose(turnover(w_lag), [0.0, 1.0, 1.0])


def test_cost_rate_combines_slippage_bps_and_percent_commission():
    from openbb_backtest.engine.vectorized import cost_rate

    rate = cost_rate(
        CommissionModel(kind="percent", value=Decimal("0.0005")),
        SlippageModel(kind="fixed_bps", value=Decimal("10")),
    )
    # 10 bps = 0.0010 plus 0.0005 percent commission = 0.0015
    assert rate == pytest.approx(0.0015)


def test_portfolio_returns_weighted_minus_costs():
    from openbb_backtest.engine.vectorized import portfolio_returns

    w_lag = np.array([[0.0, 0.0], [1.0, 0.0]])
    rets = np.array([[0.0, 0.0], [0.10, -0.20]])
    costs = np.array([0.0, 0.01])
    port = portfolio_returns(w_lag, rets, costs)
    np.testing.assert_allclose(port, [0.0, 0.09])  # 1.0*0.10 - 0.01


def test_equity_curve_compounds_from_initial_cash():
    from openbb_backtest.engine.vectorized import equity_curve_values

    eq = equity_curve_values(1000.0, np.array([0.0, 0.10, -0.50]))
    np.testing.assert_allclose(eq, [1000.0, 1100.0, 550.0])


# ---- Numba kernels (correct in pure-Python fallback) --------------------


def test_running_drawdown_tracks_peak_to_trough():
    from openbb_backtest.engine.vectorized import _running_drawdown

    dd = _running_drawdown(np.array([100.0, 120.0, 90.0, 150.0]))
    np.testing.assert_allclose(dd, [0.0, 0.0, -0.25, 0.0])
    assert dd.min() == pytest.approx(-0.25)


def test_apply_constraints_clamps_and_zeros_restricted():
    from openbb_backtest.engine.vectorized import _apply_constraints

    weights = np.array([0.8, 0.5, -0.9])
    restricted = np.array([False, True, False])
    out = _apply_constraints(weights, 0.5, restricted)
    # clamp to ±0.5, zero the restricted middle column.
    np.testing.assert_allclose(out, [0.5, 0.0, -0.5])


def test_apply_constraints_renormalizes_gross_over_one():
    from openbb_backtest.engine.vectorized import _apply_constraints

    weights = np.array([0.6, 0.6, 0.6])
    out = _apply_constraints(weights, 1.0, np.array([False, False, False]))
    # gross 1.8 > 1 -> scaled so sum|w| == 1.
    assert np.abs(out).sum() == pytest.approx(1.0)
    np.testing.assert_allclose(out, [1 / 3, 1 / 3, 1 / 3])


def test_volume_cap_fills_partial_fill_respects_cap_and_sign():
    from openbb_backtest.engine.vectorized import _volume_cap_fills

    orders = np.array([100.0, -200.0, 50.0])
    volume = np.array([1000.0, 1000.0, 10.0])
    filled = _volume_cap_fills(orders, volume, 0.1)
    # cap*vol = [100, 100, 1]; signed partial fills.
    np.testing.assert_allclose(filled, [100.0, -100.0, 1.0])


def test_tax_lot_pnl_fifo_matches_oldest_lot():
    from openbb_backtest.engine.vectorized import _tax_lot_pnl

    qty = np.array([10.0, 10.0, -10.0])
    px = np.array([100.0, 110.0, 120.0])
    # FIFO: sell matches the 100 lot -> (120-100)*10 = 200.
    assert _tax_lot_pnl(qty, px, 0) == pytest.approx(200.0)


def test_tax_lot_pnl_lifo_matches_newest_lot():
    from openbb_backtest.engine.vectorized import _tax_lot_pnl

    qty = np.array([10.0, 10.0, -10.0])
    px = np.array([100.0, 110.0, 120.0])
    # LIFO: sell matches the 110 lot -> (120-110)*10 = 100.
    assert _tax_lot_pnl(qty, px, 1) == pytest.approx(100.0)


# ---- Test fixtures: in-memory feed + deterministic strategies -----------

_SESSIONS = pd.to_datetime(
    ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07", "2021-01-08"]
)


def _ohlcv_frame() -> pd.DataFrame:
    """Two symbols, five sessions; AAA rises 1%/day, BBB falls 1%/day."""
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
    """Minimal ``DataFeed`` over an in-memory OHLCV frame (no look-ahead)."""

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


class _EqualWeightStrategy:
    """Stateless long-only equal-weight allocator across the universe."""

    id = "equal_weight"

    def generate(self, data) -> pd.DataFrame:
        win = data.window(["AAA", "BBB"], lookback=1)
        symbols = sorted(win["symbol"].unique())
        w = 1.0 / len(symbols)
        return pd.DataFrame({"weight": [w] * len(symbols)}, index=symbols)


class _SpikeAtSessionStrategy:
    """Goes all-in on AAA at exactly one session, flat otherwise.

    Used to prove the engine's shift(1): the weight requested *at* the spike
    session must earn nothing on that session and only take effect the next one.
    """

    id = "spike"

    def __init__(self, spike: pd.Timestamp) -> None:
        self._spike = pd.Timestamp(spike)

    def generate(self, data) -> pd.DataFrame:
        on = pd.Timestamp(data.now) == self._spike
        return pd.DataFrame(
            {"weight": [1.0 if on else 0.0, 0.0]}, index=["AAA", "BBB"]
        )


def _config(**kw):
    from openbb_backtest.models import BacktestConfig

    params = dict(
        strategy="equal_weight",
        universe=["AAA", "BBB"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 8),
        engine="vectorized",
        initial_cash=Decimal("100000"),
    )
    params.update(kw)
    return BacktestConfig(**params)


def _broker(config):
    from openbb_backtest.engine.execution import RealisticBroker

    return RealisticBroker(config.commission, config.slippage)


# ---- VectorizedEngine.run -----------------------------------------------


def test_vectorized_engine_is_an_engine():
    from openbb_backtest.engine.vectorized import VectorizedEngine
    from openbb_backtest.interfaces import Engine

    assert isinstance(VectorizedEngine(), Engine)
    assert VectorizedEngine().name == "vectorized"


def test_vectorized_engine_is_registered_for_discovery():
    # Importing the module registers the engine under "vectorized".
    import openbb_backtest.engine.vectorized  # noqa: F401
    from openbb_backtest.engine.vectorized import VectorizedEngine
    from openbb_backtest.registry import get_engine

    assert get_engine("vectorized") is VectorizedEngine


def test_run_produces_result_with_equity_curve_for_every_session():
    from openbb_backtest.engine.vectorized import VectorizedEngine

    cfg = _config()
    res = VectorizedEngine().run(
        _EqualWeightStrategy(), cfg, _MatrixFeed(_ohlcv_frame()), _broker(cfg)
    )
    assert res.engine_used == "vectorized"
    assert len(res.equity_curve) == len(_SESSIONS)
    # First point is the untouched starting cash (nothing held on bar 0).
    assert res.equity_curve[0].equity == pytest.approx(Decimal("100000"))


def test_run_enforces_mandatory_shift_no_same_bar_fill():
    from openbb_backtest.engine.vectorized import VectorizedEngine

    cfg = _config(
        strategy="equal_weight",
        commission=CommissionModel(),
        slippage=SlippageModel(),
    )
    res = VectorizedEngine().run(
        _EqualWeightStrategy(), cfg, _MatrixFeed(_ohlcv_frame()), _broker(cfg)
    )
    eq = [float(p.equity) for p in res.equity_curve]
    # With AAA +1%/day and BBB -1%/day at equal weight, the lagged portfolio
    # return on session 1 is 0 (held nothing on session 0). So equity[1]==equity[0].
    assert eq[1] == pytest.approx(eq[0])
    # And the average of +1%/-1% on a held 50/50 book is ~0 each day after.
    assert eq[-1] == pytest.approx(eq[0], rel=1e-3)


def test_run_signal_at_session_t_earns_nothing_until_t_plus_one():
    from openbb_backtest.engine.vectorized import VectorizedEngine

    cfg = _config(strategy="spike", commission=CommissionModel(), slippage=SlippageModel())
    spike = _SESSIONS[1]  # request all-in AAA at session index 1
    res = VectorizedEngine().run(
        _SpikeAtSessionStrategy(spike), cfg, _MatrixFeed(_ohlcv_frame()), _broker(cfg)
    )
    eq = [float(p.equity) for p in res.equity_curve]
    # The weight is requested AT session 1, so it must NOT capture the 1->1
    # move: equity is unchanged through session 1.
    assert eq[1] == pytest.approx(eq[0])
    # It only takes effect on session 2 (AAA's 1->2 return, +1%).
    assert eq[2] == pytest.approx(eq[1] * 1.01, rel=1e-9)
    # After the single spike day the book is flat again: no further change.
    assert eq[3] == pytest.approx(eq[2])


def test_run_costs_reduce_equity_versus_frictionless():
    from openbb_backtest.engine.vectorized import VectorizedEngine

    feed = _MatrixFeed(_ohlcv_frame())
    free_cfg = _config(commission=CommissionModel(), slippage=SlippageModel())
    free = VectorizedEngine().run(_EqualWeightStrategy(), free_cfg, feed, _broker(free_cfg))

    costly_cfg = _config(slippage=SlippageModel(kind="fixed_bps", value=Decimal("50")))
    costly = VectorizedEngine().run(
        _EqualWeightStrategy(), costly_cfg, feed, _broker(costly_cfg)
    )
    assert float(costly.equity_curve[-1].equity) < float(free.equity_curve[-1].equity)


# ---- sweep API ----------------------------------------------------------


class _TiltStrategy:
    """Allocate ``tilt`` to AAA and the remainder to BBB (a sweepable param)."""

    def __init__(self, tilt: float) -> None:
        self.id = f"tilt_{tilt}"
        self._tilt = float(tilt)

    def generate(self, data) -> pd.DataFrame:
        return pd.DataFrame(
            {"weight": [self._tilt, 1.0 - self._tilt]}, index=["AAA", "BBB"]
        )


def test_sweep_runs_every_grid_combo():
    from openbb_backtest.engine.vectorized import sweep

    cfg = _config(commission=CommissionModel(), slippage=SlippageModel())
    result = sweep(
        lambda tilt: _TiltStrategy(tilt),
        {"tilt": [0.0, 0.5, 1.0]},
        cfg,
        _MatrixFeed(_ohlcv_frame()),
    )
    assert len(result.results) == 3
    assert {tuple(sorted(p.items())) for p, _ in result.results} == {
        (("tilt", 0.0),),
        (("tilt", 0.5),),
        (("tilt", 1.0),),
    }


def test_sweep_cartesian_product_of_multiple_params():
    from openbb_backtest.engine.vectorized import sweep

    cfg = _config(commission=CommissionModel(), slippage=SlippageModel())
    result = sweep(
        lambda tilt, unused: _TiltStrategy(tilt),
        {"tilt": [0.0, 1.0], "unused": ["a", "b", "c"]},
        cfg,
        _MatrixFeed(_ohlcv_frame()),
    )
    assert len(result.results) == 6  # 2 x 3 cartesian product


def test_sweep_selects_best_by_sharpe():
    from openbb_backtest.engine.vectorized import sweep

    cfg = _config(commission=CommissionModel(), slippage=SlippageModel())
    result = sweep(
        lambda tilt: _TiltStrategy(tilt),
        {"tilt": [0.0, 1.0]},
        cfg,
        _MatrixFeed(_ohlcv_frame()),
        rank_by="sharpe",
    )
    # AAA (+1%/day) all-in (tilt=1.0) dominates BBB (-1%/day) all-in on Sharpe.
    assert result.best["tilt"] == 1.0
    assert result.best_metrics.sharpe == max(m.sharpe for _, m in result.results)


def test_sweep_reuses_returns_matrix_computing_it_once():
    from openbb_backtest.engine import vectorized as vec

    cfg = _config(commission=CommissionModel(), slippage=SlippageModel())
    calls = {"n": 0}
    original = vec.simple_returns

    def _counting(close):
        calls["n"] += 1
        return original(close)

    vec.simple_returns = _counting
    try:
        vec.sweep(
            lambda tilt: _TiltStrategy(tilt),
            {"tilt": [0.0, 0.5, 1.0]},
            cfg,
            _MatrixFeed(_ohlcv_frame()),
        )
    finally:
        vec.simple_returns = original
    # Returns matrix is computed exactly once and reused across all combos.
    assert calls["n"] == 1


# ---- benchmark harness --------------------------------------------------


def test_benchmark_sweep_reports_positive_throughput():
    from openbb_backtest.engine.vectorized import benchmark_sweep

    cfg = _config(commission=CommissionModel(), slippage=SlippageModel())
    bench = benchmark_sweep(
        lambda tilt: _TiltStrategy(tilt),
        {"tilt": [0.0, 0.25, 0.5, 0.75, 1.0]},
        cfg,
        _MatrixFeed(_ohlcv_frame()),
    )
    assert bench.n_combos == 5
    assert bench.elapsed_s > 0.0
    assert bench.combos_per_min > 0.0
    # The documented NFR target travels with the benchmark for comparison.
    assert bench.target_combos_per_min == 10_000


def test_benchmark_sweep_result_matches_plain_sweep():
    from openbb_backtest.engine.vectorized import benchmark_sweep

    cfg = _config(commission=CommissionModel(), slippage=SlippageModel())
    bench = benchmark_sweep(
        lambda tilt: _TiltStrategy(tilt),
        {"tilt": [0.0, 1.0]},
        cfg,
        _MatrixFeed(_ohlcv_frame()),
        rank_by="sharpe",
    )
    # The benchmark wraps a real sweep, so the winning combo is still selected.
    assert bench.result.best["tilt"] == 1.0


# ---- robustness & correctness (from review) -----------------------------


def _mk_metrics(**over):
    from openbb_backtest.models import PerformanceMetrics

    base = dict(
        cagr=0.0,
        sharpe=0.0,
        sortino=0.0,
        calmar=0.0,
        max_drawdown=0.0,
        volatility=0.0,
        var_95=0.0,
        cvar_95=0.0,
        win_rate=0.0,
        profit_factor=0.0,
        turnover=0.0,
    )
    base.update(over)
    return PerformanceMetrics(**base)


def test_select_best_higher_is_better_for_sharpe():
    from openbb_backtest.engine.vectorized import select_best

    results = [
        ({"k": 1}, _mk_metrics(sharpe=0.5)),
        ({"k": 2}, _mk_metrics(sharpe=1.5)),
    ]
    best, _ = select_best(results, "sharpe")
    assert best == {"k": 2}


def test_select_best_lower_is_better_for_volatility():
    from openbb_backtest.engine.vectorized import select_best

    results = [
        ({"k": 1}, _mk_metrics(volatility=0.30)),
        ({"k": 2}, _mk_metrics(volatility=0.10)),
    ]
    best, _ = select_best(results, "volatility")
    # Lower volatility wins — a naive max() would pick the wrong combo here.
    assert best == {"k": 2}


def test_select_best_lower_is_better_for_turnover():
    from openbb_backtest.engine.vectorized import select_best

    results = [
        ({"k": 1}, _mk_metrics(turnover=5.0)),
        ({"k": 2}, _mk_metrics(turnover=1.0)),
    ]
    best, _ = select_best(results, "turnover")
    assert best == {"k": 2}


def test_select_best_rejects_unknown_metric():
    from openbb_backtest.engine.vectorized import select_best

    with pytest.raises(ValueError, match="rank_by"):
        select_best([({"k": 1}, _mk_metrics())], "not_a_metric")


def test_sweep_rejects_unknown_rank_by():
    from openbb_backtest.engine.vectorized import sweep

    cfg = _config(commission=CommissionModel(), slippage=SlippageModel())
    with pytest.raises(ValueError, match="rank_by"):
        sweep(
            lambda tilt: _TiltStrategy(tilt),
            {"tilt": [0.0, 1.0]},
            cfg,
            _MatrixFeed(_ohlcv_frame()),
            rank_by="bogus",
        )


def test_cost_rate_warns_when_dropping_unsupported_commission():
    from openbb_backtest.engine.vectorized import cost_rate

    with pytest.warns(UserWarning, match="per_share"):
        cost_rate(
            CommissionModel(kind="per_share", value=Decimal("0.01")),
            SlippageModel(),
        )


def test_cost_rate_warns_when_dropping_unsupported_slippage():
    from openbb_backtest.engine.vectorized import cost_rate

    with pytest.warns(UserWarning, match="volume_share"):
        cost_rate(
            CommissionModel(),
            SlippageModel(kind="volume_share", value=Decimal("0.1")),
        )


def test_cost_rate_silent_for_zero_cost_defaults():
    import warnings

    from openbb_backtest.engine.vectorized import cost_rate

    # The frictionless defaults (flat 0 commission, fixed_bps 0 slippage) must
    # not emit spurious warnings — they model to exactly 0.0.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert cost_rate(CommissionModel(), SlippageModel()) == 0.0


class _EmptySessionsFeed:
    """A feed whose calendar yields no sessions in the requested range."""

    def history(self, symbols, end, lookback):
        import pandas as pd

        return pd.DataFrame(
            columns=["symbol", "session", "open", "high", "low", "close", "volume"]
        )

    def sessions(self, start, end):
        import pandas as pd

        return pd.DatetimeIndex([])


def test_run_raises_clear_error_on_empty_session_window():
    from openbb_backtest.engine.vectorized import VectorizedEngine

    cfg = _config(commission=CommissionModel(), slippage=SlippageModel())
    with pytest.raises(ValueError, match="no trading sessions"):
        VectorizedEngine().run(
            _EqualWeightStrategy(), cfg, _EmptySessionsFeed(), _broker(cfg)
        )


class _CountingFeed:
    """Wraps a feed and counts ``history`` calls reaching the underlying feed."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.history_calls = 0

    def history(self, symbols, end, lookback):
        self.history_calls += 1
        return self._inner.history(symbols, end, lookback)

    def sessions(self, start, end):
        return self._inner.sessions(start, end)


class _FeedReadingTiltStrategy:
    """A sweepable tilt strategy that actually reads the feed every session.

    The weights depend only on ``tilt``, but ``generate`` touches the PIT window
    on every call — so without sweep-level memoization the underlying feed-read
    count scales with (combos x sessions), and with memoization it does not.
    """

    def __init__(self, tilt: float) -> None:
        self.id = f"fr_tilt_{tilt}"
        self._tilt = float(tilt)

    def generate(self, data) -> pd.DataFrame:
        data.window(["AAA", "BBB"], lookback=1)  # touch the feed each session
        return pd.DataFrame(
            {"weight": [self._tilt, 1.0 - self._tilt]}, index=["AAA", "BBB"]
        )


def test_sweep_feed_reads_do_not_scale_with_combo_count():
    from openbb_backtest.engine.vectorized import sweep

    cfg = _config(commission=CommissionModel(), slippage=SlippageModel())

    feed2 = _CountingFeed(_MatrixFeed(_ohlcv_frame()))
    sweep(lambda tilt: _FeedReadingTiltStrategy(tilt), {"tilt": [0.0, 1.0]}, cfg, feed2)

    feed4 = _CountingFeed(_MatrixFeed(_ohlcv_frame()))
    sweep(
        lambda tilt: _FeedReadingTiltStrategy(tilt),
        {"tilt": [0.0, 0.33, 0.66, 1.0]},
        cfg,
        feed4,
    )
    # The per-session data windows are identical across combos, so memoization
    # makes the underlying feed-read count independent of the grid size.
    assert feed2.history_calls == feed4.history_calls


def test_sweep_memoization_preserves_results():
    from openbb_backtest.engine.vectorized import sweep

    cfg = _config(commission=CommissionModel(), slippage=SlippageModel())
    plain = sweep(
        lambda tilt: _TiltStrategy(tilt),
        {"tilt": [0.0, 0.5, 1.0]},
        cfg,
        _MatrixFeed(_ohlcv_frame()),
        rank_by="sharpe",
    )
    # AAA-heavy tilt still wins; memoization must not change the numbers.
    assert plain.best["tilt"] == 1.0
    assert len(plain.results) == 3


class _NaNWeightStrategy:
    """Emits a NaN weight for one in-universe symbol alongside a real one.

    A NaN weight must be skipped without desyncing the per-symbol column/value
    assignment — the named symbol gets its weight, the NaN one stays flat.
    """

    id = "nan_weight"

    def generate(self, data) -> pd.DataFrame:
        return pd.DataFrame(
            {"weight": [1.0, float("nan")]}, index=["AAA", "BBB"]
        )


def test_run_skips_nan_weights_without_desync():
    import math

    from openbb_backtest.engine.vectorized import VectorizedEngine

    cfg = _config(commission=CommissionModel(), slippage=SlippageModel())
    res = VectorizedEngine().run(
        _NaNWeightStrategy(), cfg, _MatrixFeed(_ohlcv_frame()), _broker(cfg)
    )
    eq = [float(p.equity) for p in res.equity_curve]
    # BBB's NaN weight is dropped (never leaks into the math), so equity stays
    # finite and tracks AAA held at 1.0: +1%/day, lagged one bar.
    assert all(math.isfinite(e) for e in eq)
    assert eq[1] == pytest.approx(eq[0] * 1.01, rel=1e-9)
    assert eq[2] == pytest.approx(eq[1] * 1.01, rel=1e-9)
