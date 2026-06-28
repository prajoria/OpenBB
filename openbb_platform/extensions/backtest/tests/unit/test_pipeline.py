"""Unit tests for the cross-sectional factor pipeline (component 05, §2).

Covers the :class:`Factor` abstraction (declared ``inputs`` + ``window_length``,
trailing-window compute), two concrete factors ported from ``Analysis/`` Phase
2-5 (a momentum/technical factor and a valuation factor) with hand-computed
expectations, the insufficient-history NaN rule (no look-ahead), the
cross-sectional ``rank``/``zscore`` helpers, and the :class:`FactorPanel`
``from_frame``/``to_frame`` lossless round-trip.

See ``docs/designs/backtest-design/05-event-driven-engine.md`` §2.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

_SESSIONS = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"])


def _window(closes: dict[str, list[float]], eps: dict[str, float] | None = None):
    """Build a long trailing-window frame: columns symbol/session/close[/eps]."""
    rows = []
    for sym, series in closes.items():
        sessions = _SESSIONS[-len(series):]
        for sess, px in zip(sessions, series):
            row = {"symbol": sym, "session": sess, "close": px}
            if eps is not None:
                row["eps"] = eps[sym]
            rows.append(row)
    return pd.DataFrame(rows)


# ---- Factor base ---------------------------------------------------------


def test_momentum_factor_declares_inputs_and_window_length():
    from openbb_backtest.pipeline.factor import Momentum

    f = Momentum(window_length=3)
    assert f.inputs == ["close"]
    assert f.window_length == 3
    assert f.name == "momentum_3"


def test_earnings_yield_factor_declares_inputs_and_window_length():
    from openbb_backtest.pipeline.factor import EarningsYield

    f = EarningsYield()
    assert set(f.inputs) == {"close", "eps"}
    assert f.window_length == 1
    assert f.name == "earnings_yield"


# ---- Concrete factors: hand-computed -------------------------------------


def test_momentum_computes_window_return_per_asset():
    from openbb_backtest.pipeline.factor import Momentum

    window = _window(
        {
            "AAA": [100.0, 110.0, 121.0],  # 121/100 - 1 = 0.21
            "BBB": [100.0, 100.0, 100.0],  # flat -> 0.0
            "CCC": [100.0, 90.0, 81.0],  # 81/100 - 1 = -0.19
        }
    )
    out = Momentum(window_length=3).compute(window)
    assert out["AAA"] == pytest.approx(0.21)
    assert out["BBB"] == pytest.approx(0.0)
    assert out["CCC"] == pytest.approx(-0.19)


def test_momentum_insufficient_history_is_nan_no_look_ahead():
    from openbb_backtest.pipeline.factor import Momentum

    window = _window(
        {
            "AAA": [100.0, 110.0, 121.0],  # 3 bars: enough
            "BBB": [100.0, 105.0],  # only 2 bars: insufficient for window 3
        }
    )
    out = Momentum(window_length=3).compute(window)
    assert out["AAA"] == pytest.approx(0.21)
    assert np.isnan(out["BBB"])


def test_earnings_yield_uses_latest_bar_per_asset():
    from openbb_backtest.pipeline.factor import EarningsYield

    window = _window(
        {"AAA": [100.0], "BBB": [50.0], "CCC": [200.0]},
        eps={"AAA": 5.0, "BBB": 5.0, "CCC": 5.0},
    )
    out = EarningsYield().compute(window)
    # earnings yield = eps / close (higher = cheaper).
    assert out["AAA"] == pytest.approx(0.05)
    assert out["BBB"] == pytest.approx(0.10)
    assert out["CCC"] == pytest.approx(0.025)


# ---- Cross-sectional helpers ---------------------------------------------


def test_cross_sectional_zscore_standardizes_across_assets():
    from openbb_backtest.pipeline.factor import zscore

    s = pd.Series({"AAA": 1.0, "BBB": 2.0, "CCC": 3.0})
    z = zscore(s)
    # mean 2, sample std 1 -> [-1, 0, 1].
    assert z["AAA"] == pytest.approx(-1.0)
    assert z["BBB"] == pytest.approx(0.0)
    assert z["CCC"] == pytest.approx(1.0)


def test_cross_sectional_zscore_constant_series_is_zero_not_nan():
    from openbb_backtest.pipeline.factor import zscore

    z = zscore(pd.Series({"AAA": 5.0, "BBB": 5.0}))
    # Zero dispersion must not divide-by-zero into NaN/inf.
    assert (z == 0.0).all()


def test_cross_sectional_rank_is_percentile_in_unit_interval():
    from openbb_backtest.pipeline.factor import rank

    r = rank(pd.Series({"AAA": 10.0, "BBB": 30.0, "CCC": 20.0}))
    # Ascending percentile rank: smallest -> 1/3, largest -> 1.0.
    assert r["AAA"] == pytest.approx(1 / 3)
    assert r["CCC"] == pytest.approx(2 / 3)
    assert r["BBB"] == pytest.approx(1.0)


# ---- FactorPanel ---------------------------------------------------------


def _panel_frame():
    idx = pd.MultiIndex.from_tuples(
        [
            (_SESSIONS[0], "AAA"),
            (_SESSIONS[0], "BBB"),
            (_SESSIONS[1], "AAA"),
            (_SESSIONS[1], "BBB"),
        ],
        names=["date", "asset"],
    )
    return pd.DataFrame(
        {"momentum_3": [0.21, -0.19, 0.10, -0.05], "earnings_yield": [0.05, 0.10, 0.04, 0.11]},
        index=idx,
    )


def test_factor_panel_from_frame_to_frame_round_trips_losslessly():
    from openbb_backtest.pipeline.panel import FactorPanel

    frame = _panel_frame()
    panel = FactorPanel.from_frame(frame)
    pd.testing.assert_frame_equal(panel.to_frame(), frame)


def test_factor_panel_exposes_dates_and_assets():
    from openbb_backtest.pipeline.panel import FactorPanel

    panel = FactorPanel.from_frame(_panel_frame())
    assert list(panel.factors) == ["momentum_3", "earnings_yield"]
    assert list(panel.assets) == ["AAA", "BBB"]
    assert len(panel.dates) == 2


def test_factor_panel_cross_section_returns_one_session():
    from openbb_backtest.pipeline.panel import FactorPanel

    panel = FactorPanel.from_frame(_panel_frame())
    xs = panel.cross_section(_SESSIONS[0])
    # One row per asset for the requested date, factors as columns.
    assert list(xs.index) == ["AAA", "BBB"]
    assert xs.loc["AAA", "momentum_3"] == pytest.approx(0.21)


def test_factor_panel_rejects_non_multiindex_frame():
    from openbb_backtest.pipeline.panel import FactorPanel

    with pytest.raises(ValueError, match="MultiIndex"):
        FactorPanel.from_frame(pd.DataFrame({"momentum_3": [0.1, 0.2]}))


# ---- C05.5: per-session cross-sectional pipeline runner -----------------

from datetime import date  # noqa: E402

_RUN_SESSIONS = pd.to_datetime(
    ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"]
)


def _ohlcv_bundle_frame(closes: dict[str, list[float]]) -> pd.DataFrame:
    """Long OHLCV frame (open==close) for the given per-symbol close series."""
    rows = []
    for sym, series in closes.items():
        for sess, px in zip(_RUN_SESSIONS, series):
            rows.append(
                {
                    "symbol": sym,
                    "session": sess,
                    "open": px,
                    "high": px,
                    "low": px,
                    "close": px,
                    "volume": 1_000_000.0,
                    "adj_factor": 1.0,
                }
            )
    return pd.DataFrame(rows)


def _bundle(closes: dict[str, list[float]], eps: dict[str, float] | None = None):
    from openbb_backtest.data.bundle import Bundle

    fundamentals = None
    if eps is not None:
        fundamentals = pd.DataFrame(
            [
                {
                    "symbol": s,
                    "available_date": pd.Timestamp("2021-01-01"),
                    "field": "eps",
                    "value": v,
                }
                for s, v in eps.items()
            ]
        )
    return Bundle.from_frames(
        _ohlcv_bundle_frame(closes), fundamentals=fundamentals, calendar="XNYS"
    )


class _SpyFeed:
    """Wraps a bundle and records every ``end`` passed to ``history``."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.history_ends: list[pd.Timestamp] = []

    def history(self, symbols, end, lookback):
        self.history_ends.append(pd.Timestamp(end))
        frame = self._inner.history(symbols, end=end, lookback=lookback)
        # Hard look-ahead guard: nothing past the requested session may surface.
        assert (frame["session"] <= pd.Timestamp(end)).all()
        return frame

    def sessions(self, start, end):
        return self._inner.sessions(start, end)

    def as_of(self, symbol, field, when):
        return self._inner.as_of(symbol, field, when)


def test_pipeline_returns_full_session_asset_grid():
    from openbb_backtest.pipeline import pipeline
    from openbb_backtest.pipeline.factor import Momentum

    feed = _bundle(
        {
            "AAA": [100.0, 110.0, 121.0, 121.0],
            "BBB": [100.0, 90.0, 81.0, 81.0],
        }
    )
    panel = pipeline(
        [Momentum(window_length=2)],
        ["AAA", "BBB"],
        date(2021, 1, 4),
        date(2021, 1, 7),
        feed,
    )
    frame = panel.to_frame()
    # 4 sessions x 2 assets = 8-row (session, asset) grid.
    assert len(frame) == 8
    assert list(panel.assets) == ["AAA", "BBB"]
    assert len(panel.dates) == 4


def test_pipeline_values_match_per_session_hand_compute():
    from openbb_backtest.pipeline import pipeline
    from openbb_backtest.pipeline.factor import Momentum

    feed = _bundle(
        {
            "AAA": [100.0, 110.0, 121.0, 121.0],  # mom(2): NaN, .10, .10, .0
            "BBB": [100.0, 90.0, 81.0, 81.0],  # mom(2): NaN, -.10, -.10, .0
        }
    )
    panel = pipeline(
        [Momentum(window_length=2)],
        ["AAA", "BBB"],
        date(2021, 1, 4),
        date(2021, 1, 7),
        feed,
    )
    xs1 = panel.cross_section(_RUN_SESSIONS[1])
    assert xs1.loc["AAA", "momentum_2"] == pytest.approx(0.10)
    assert xs1.loc["BBB", "momentum_2"] == pytest.approx(-0.10)
    xs3 = panel.cross_section(_RUN_SESSIONS[3])
    assert xs3.loc["AAA", "momentum_2"] == pytest.approx(0.0)


def test_pipeline_insufficient_lookback_is_nan_not_exception():
    from openbb_backtest.pipeline import pipeline
    from openbb_backtest.pipeline.factor import Momentum

    feed = _bundle({"AAA": [100.0, 110.0, 121.0, 121.0]})
    panel = pipeline(
        [Momentum(window_length=2)],
        ["AAA"],
        date(2021, 1, 4),
        date(2021, 1, 7),
        feed,
    )
    # The first session has only one bar -> momentum is NaN, never an error.
    xs0 = panel.cross_section(_RUN_SESSIONS[0])
    assert np.isnan(xs0.loc["AAA", "momentum_2"])


def test_pipeline_two_factors_with_fundamentals():
    from openbb_backtest.pipeline import pipeline
    from openbb_backtest.pipeline.factor import EarningsYield, Momentum

    feed = _bundle(
        {
            "AAA": [100.0, 110.0, 121.0, 121.0],
            "BBB": [100.0, 90.0, 81.0, 81.0],
        },
        eps={"AAA": 5.0, "BBB": 9.0},
    )
    panel = pipeline(
        [Momentum(window_length=2), EarningsYield()],
        ["AAA", "BBB"],
        date(2021, 1, 4),
        date(2021, 1, 7),
        feed,
    )
    assert set(panel.factors) == {"momentum_2", "earnings_yield"}
    xs3 = panel.cross_section(_RUN_SESSIONS[3])
    # earnings yield = eps / close at that session (AAA: 5/121, BBB: 9/81).
    assert xs3.loc["AAA", "earnings_yield"] == pytest.approx(5.0 / 121.0)
    assert xs3.loc["BBB", "earnings_yield"] == pytest.approx(9.0 / 81.0)


def test_pipeline_point_in_time_universe_excludes_non_members():
    from openbb_backtest.data.bundle import universe_at
    from openbb_backtest.pipeline import pipeline
    from openbb_backtest.pipeline.factor import Momentum

    feed = _bundle(
        {
            "AAA": [100.0, 110.0, 121.0, 121.0],
            "BBB": [100.0, 90.0, 81.0, 81.0],
            "CCC": [100.0, 100.0, 100.0, 100.0],
        }
    )
    constituents = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "from_date": ["2021-01-01", "2021-01-01", "2021-01-06"],
            "thru_date": [pd.NaT, pd.Timestamp("2021-01-05"), pd.NaT],
        }
    )

    def universe(when):
        return universe_at(constituents, when)

    panel = pipeline(
        [Momentum(window_length=2)],
        universe,
        date(2021, 1, 4),
        date(2021, 1, 7),
        feed,
    )
    frame = panel.to_frame()
    # CCC joins 01-06: excluded on 01-04; BBB leaves after 01-05: gone on 01-06.
    assert (_RUN_SESSIONS[0], "CCC") not in frame.index
    assert (_RUN_SESSIONS[0], "AAA") in frame.index
    assert (_RUN_SESSIONS[2], "BBB") not in frame.index
    assert (_RUN_SESSIONS[2], "CCC") in frame.index


def test_pipeline_is_look_ahead_free_per_session():
    from openbb_backtest.pipeline import pipeline
    from openbb_backtest.pipeline.factor import Momentum

    # A poisoned future spike: if the runner queried the global end instead of
    # the per-session end, session 1's momentum would reflect the 9999 bar.
    feed = _SpyFeed(_bundle({"AAA": [100.0, 110.0, 9999.0, 9999.0]}))
    panel = pipeline(
        [Momentum(window_length=2)],
        ["AAA"],
        date(2021, 1, 4),
        date(2021, 1, 7),
        feed,
    )
    xs1 = panel.cross_section(_RUN_SESSIONS[1])
    # Only bars up to session 1 are visible: 110/100 - 1 = 0.10 (not the spike).
    assert xs1.loc["AAA", "momentum_2"] == pytest.approx(0.10)
    # Every history request is bounded at a real session, never the global end.
    assert set(feed.history_ends) <= set(_RUN_SESSIONS)


def test_pipeline_empty_range_raises_value_error():
    from openbb_backtest.pipeline import pipeline
    from openbb_backtest.pipeline.factor import Momentum

    feed = _bundle({"AAA": [100.0, 110.0, 121.0, 121.0]})
    with pytest.raises(ValueError, match="no trading sessions"):
        pipeline(
            [Momentum(window_length=2)],
            ["AAA"],
            date(2021, 1, 9),  # Saturday -> Sunday: no XNYS sessions
            date(2021, 1, 10),
            feed,
        )

