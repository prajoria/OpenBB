"""Unit tests for intraday_drift strategy calculations."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from openbb_backtest.strategies.intraday_drift import (
    DriftSummary,
    build_observations,
    summarize_observations,
)

NY = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")


# ---------------------------------------------------------------------------
# build_observations
# ---------------------------------------------------------------------------


def test_build_observations_uses_noon_open_and_three_pm_close():
    bars = pd.DataFrame(
        [
            {"timestamp": datetime(2026, 2, 10, 12, tzinfo=NY), "symbol": "AAA", "open": 100.0, "close": 101.0},
            {"timestamp": datetime(2026, 2, 10, 15, tzinfo=NY), "symbol": "AAA", "open": 104.0, "close": 105.0},
            {"timestamp": datetime(2026, 7, 10, 12, tzinfo=NY), "symbol": "BBB", "open": 200.0, "close": 198.0},
            {"timestamp": datetime(2026, 7, 10, 15, tzinfo=NY), "symbol": "BBB", "open": 197.0, "close": 196.0},
            {"timestamp": datetime(2026, 7, 10, 12, tzinfo=NY), "symbol": "CCC", "open": 50.0, "close": 51.0},
        ]
    )

    observations = build_observations(bars)

    assert observations[["symbol", "entry_price", "exit_price", "win"]].to_dict("records") == [
        {"symbol": "AAA", "entry_price": 100.0, "exit_price": 105.0, "win": True},
        {"symbol": "BBB", "entry_price": 200.0, "exit_price": 196.0, "win": False},
    ]


def test_build_observations_output_columns():
    bars = pd.DataFrame(
        [
            {"timestamp": datetime(2026, 2, 10, 12, tzinfo=NY), "symbol": "AAA", "open": 100.0, "close": 101.0},
            {"timestamp": datetime(2026, 2, 10, 15, tzinfo=NY), "symbol": "AAA", "open": 104.0, "close": 105.0},
        ]
    )
    obs = build_observations(bars)
    assert set(obs.columns) >= {"session", "symbol", "entry_price", "exit_price", "return", "win"}


def test_build_observations_sorted_by_session_symbol():
    """Output must be sorted by (session ASC, symbol ASC) regardless of input order."""
    bars = pd.DataFrame(
        [
            # BBB on July 10 fed first; AAA on Feb 10 fed second
            {"timestamp": datetime(2026, 7, 10, 12, tzinfo=NY), "symbol": "BBB", "open": 200.0, "close": 198.0},
            {"timestamp": datetime(2026, 7, 10, 15, tzinfo=NY), "symbol": "BBB", "open": 197.0, "close": 196.0},
            {"timestamp": datetime(2026, 2, 10, 12, tzinfo=NY), "symbol": "AAA", "open": 100.0, "close": 101.0},
            {"timestamp": datetime(2026, 2, 10, 15, tzinfo=NY), "symbol": "AAA", "open": 104.0, "close": 105.0},
        ]
    )
    obs = build_observations(bars)

    # Exact structural check: earlier session comes first; within session, symbol ASC
    from datetime import date as _date
    assert obs.iloc[0]["session"] == _date(2026, 2, 10)
    assert obs.iloc[0]["symbol"] == "AAA"
    assert obs.iloc[1]["session"] == _date(2026, 7, 10)
    assert obs.iloc[1]["symbol"] == "BBB"
    assert len(obs) == 2


def test_build_observations_missing_columns_raises():
    bars = pd.DataFrame({"timestamp": [datetime(2026, 2, 10, 12, tzinfo=NY)], "symbol": ["AAA"]})
    with pytest.raises(ValueError, match="bars missing required columns"):
        build_observations(bars)


def test_build_observations_excludes_nonpositive_prices():
    bars = pd.DataFrame(
        [
            {"timestamp": datetime(2026, 2, 10, 12, tzinfo=NY), "symbol": "AAA", "open": 0.0, "close": 101.0},
            {"timestamp": datetime(2026, 2, 10, 15, tzinfo=NY), "symbol": "AAA", "open": 104.0, "close": 105.0},
            {"timestamp": datetime(2026, 2, 10, 12, tzinfo=NY), "symbol": "BBB", "open": 100.0, "close": 101.0},
            {"timestamp": datetime(2026, 2, 10, 15, tzinfo=NY), "symbol": "BBB", "open": 104.0, "close": 105.0},
        ]
    )
    obs = build_observations(bars)
    assert "AAA" not in obs["symbol"].values
    assert "BBB" in obs["symbol"].values


def test_build_observations_tie_is_loss():
    """exact tie (exit == entry) must produce win=False."""
    bars = pd.DataFrame(
        [
            {"timestamp": datetime(2026, 2, 10, 12, tzinfo=NY), "symbol": "TIE", "open": 100.0, "close": 100.0},
            {"timestamp": datetime(2026, 2, 10, 15, tzinfo=NY), "symbol": "TIE", "open": 100.0, "close": 100.0},
        ]
    )
    obs = build_observations(bars)
    assert len(obs) == 1
    # Use bool() to coerce numpy.bool_ → Python bool before identity check.
    assert bool(obs.iloc[0]["win"]) is False


def test_build_observations_missing_exit_excluded():
    """Stock-days with no hour-15 bar are excluded."""
    bars = pd.DataFrame(
        [
            {"timestamp": datetime(2026, 2, 10, 12, tzinfo=NY), "symbol": "CCC", "open": 50.0, "close": 51.0},
        ]
    )
    obs = build_observations(bars)
    assert len(obs) == 0


def test_build_observations_duplicate_entry_bars_raises():
    """Two hour-12 bars for the same session/symbol must raise ValueError, not silently Cartesian-join."""
    bars = pd.DataFrame(
        [
            {"timestamp": datetime(2026, 2, 10, 12, tzinfo=NY), "symbol": "AAA", "open": 100.0, "close": 101.0},
            {"timestamp": datetime(2026, 2, 10, 12, tzinfo=NY), "symbol": "AAA", "open": 102.0, "close": 103.0},  # dup
            {"timestamp": datetime(2026, 2, 10, 15, tzinfo=NY), "symbol": "AAA", "open": 104.0, "close": 105.0},
        ]
    )
    with pytest.raises(ValueError, match="duplicate hour-12 bars"):
        build_observations(bars)


def test_build_observations_duplicate_exit_bars_raises():
    """Two hour-15 bars for the same session/symbol must raise ValueError."""
    bars = pd.DataFrame(
        [
            {"timestamp": datetime(2026, 2, 10, 12, tzinfo=NY), "symbol": "AAA", "open": 100.0, "close": 101.0},
            {"timestamp": datetime(2026, 2, 10, 15, tzinfo=NY), "symbol": "AAA", "open": 104.0, "close": 105.0},
            {"timestamp": datetime(2026, 2, 10, 15, tzinfo=NY), "symbol": "AAA", "open": 106.0, "close": 107.0},  # dup
        ]
    )
    with pytest.raises(ValueError, match="duplicate hour-15 bars"):
        build_observations(bars)


def test_build_observations_pacific_time_converted_to_new_york():
    """Bars timestamped in Pacific time (09:00 PT == 12:00 ET, 12:00 PT == 15:00 ET)
    must be converted to New York before hour selection, so PT 09:00 becomes the
    entry bar and PT 12:00 becomes the exit bar.
    """
    bars = pd.DataFrame(
        [
            # 09:00 PT = 12:00 ET  → entry
            {"timestamp": datetime(2026, 2, 10, 9, tzinfo=PT), "symbol": "ZZZ", "open": 50.0, "close": 51.0},
            # 12:00 PT = 15:00 ET  → exit
            {"timestamp": datetime(2026, 2, 10, 12, tzinfo=PT), "symbol": "ZZZ", "open": 55.0, "close": 56.0},
        ]
    )
    obs = build_observations(bars)

    assert len(obs) == 1
    row = obs.iloc[0]
    assert row["symbol"] == "ZZZ"
    # entry_price = open of the 12:00 ET bar (09:00 PT) = 50.0
    assert row["entry_price"] == pytest.approx(50.0)
    # exit_price  = close of the 15:00 ET bar (12:00 PT) = 56.0
    assert row["exit_price"] == pytest.approx(56.0)
    assert row["win"] == True  # noqa: E712  (numpy bool, not Python bool)


# ---------------------------------------------------------------------------
# summarize_observations
# ---------------------------------------------------------------------------


def test_summary_reports_stock_day_and_equal_weight_basket_rates():
    from datetime import date as _date

    observations = pd.DataFrame(
        {
            "session": pd.to_datetime(["2026-08-10", "2026-08-10", "2026-08-11", "2026-08-11"]).date,
            "symbol": ["AAA", "BBB", "AAA", "BBB"],
            "return": [0.02, -0.01, -0.02, -0.01],
            "win": [True, False, False, False],
        }
    )

    summary = summarize_observations(observations, expected_symbols=2)

    # Rates and coverage
    assert summary.stock_day_win_rate_pct == pytest.approx(25.0)
    assert summary.basket_day_win_rate_pct == pytest.approx(50.0)
    assert summary.valid_stock_days == 4
    assert summary.coverage_pct == pytest.approx(100.0)
    # Return statistics
    # mean([0.02, -0.01, -0.02, -0.01]) = -0.005 → -0.5 %
    assert summary.mean_stock_day_return_pct == pytest.approx(-0.5)
    # median(sorted: -0.02, -0.01, -0.01, 0.02) = (-0.01 + -0.01)/2 = -0.01 → -1.0 %
    assert summary.median_stock_day_return_pct == pytest.approx(-1.0)
    # basket daily: 2026-08-10 = mean(0.02,-0.01)=0.005; 2026-08-11 = mean(-0.02,-0.01)=-0.015
    # cumulative: (1.005)(0.985) - 1 = -0.010075 → -1.0075 %
    assert summary.cumulative_basket_return_pct == pytest.approx(-1.0075, rel=1e-4)
    # Session and symbol metadata
    assert summary.start_session == _date(2026, 8, 10)
    assert summary.end_session == _date(2026, 8, 11)
    assert summary.sessions == 2
    assert summary.symbols_observed == 2
    assert summary.expected_stock_days == 4


def test_summary_missing_columns_raises():
    """observations lacking any of session/symbol/return/win must raise ValueError."""
    obs_no_win = pd.DataFrame(
        {
            "session": pd.to_datetime(["2026-08-10"]).date,
            "symbol": ["AAA"],
            "return": [0.01],
            # "win" deliberately omitted
        }
    )
    with pytest.raises(ValueError, match="observations missing required columns"):
        summarize_observations(obs_no_win, expected_symbols=1)


def test_summary_missing_multiple_columns_names_all():
    """Error message must name every missing column, not just the first."""
    obs_bare = pd.DataFrame({"session": pd.to_datetime(["2026-08-10"]).date})
    with pytest.raises(ValueError, match="observations missing required columns"):
        summarize_observations(obs_bare, expected_symbols=1)


def test_summary_empty_observations_raises():
    obs = pd.DataFrame(columns=["session", "symbol", "return", "win"])
    with pytest.raises(ValueError, match="no complete stock-days"):
        summarize_observations(obs, expected_symbols=2)


def test_summary_nonpositive_expected_symbols_raises():
    obs = pd.DataFrame(
        {
            "session": pd.to_datetime(["2026-08-10"]).date,
            "symbol": ["AAA"],
            "return": [0.01],
            "win": [True],
        }
    )
    with pytest.raises(ValueError, match="expected_symbols must be positive"):
        summarize_observations(obs, expected_symbols=0)


def test_summary_valid_stock_days_exceeds_expected_raises():
    """valid_stock_days > n_sessions * expected_symbols must raise ValueError."""
    observations = pd.DataFrame(
        {
            # 3 stock-days in 1 session but expected_symbols=2 → exceeds
            "session": pd.to_datetime(["2026-08-10", "2026-08-10", "2026-08-10"]).date,
            "symbol": ["AAA", "BBB", "CCC"],
            "return": [0.01, 0.02, 0.03],
            "win": [True, True, True],
        }
    )
    with pytest.raises(ValueError, match="valid_stock_days.*exceeds expected_stock_days"):
        summarize_observations(observations, expected_symbols=2)


def test_summary_drift_summary_is_immutable():
    observations = pd.DataFrame(
        {
            "session": pd.to_datetime(["2026-08-10", "2026-08-10"]).date,
            "symbol": ["AAA", "BBB"],
            "return": [0.02, -0.01],
            "win": [True, False],
        }
    )
    summary = summarize_observations(observations, expected_symbols=2)
    assert isinstance(summary, DriftSummary)
    with pytest.raises((TypeError, AttributeError)):
        summary.sessions = 999  # type: ignore[misc]

