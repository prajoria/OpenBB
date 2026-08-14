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
    bars = pd.DataFrame(
        [
            {"timestamp": datetime(2026, 7, 10, 12, tzinfo=NY), "symbol": "BBB", "open": 200.0, "close": 198.0},
            {"timestamp": datetime(2026, 7, 10, 15, tzinfo=NY), "symbol": "BBB", "open": 197.0, "close": 196.0},
            {"timestamp": datetime(2026, 2, 10, 12, tzinfo=NY), "symbol": "AAA", "open": 100.0, "close": 101.0},
            {"timestamp": datetime(2026, 2, 10, 15, tzinfo=NY), "symbol": "AAA", "open": 104.0, "close": 105.0},
        ]
    )
    obs = build_observations(bars)
    symbols = obs["symbol"].tolist()
    assert symbols == sorted(symbols) or obs["session"].iloc[0] <= obs["session"].iloc[-1]


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
    assert obs.iloc[0]["win"] is False or obs.iloc[0]["win"] == False  # noqa: E712


def test_build_observations_missing_exit_excluded():
    """Stock-days with no hour-15 bar are excluded."""
    bars = pd.DataFrame(
        [
            {"timestamp": datetime(2026, 2, 10, 12, tzinfo=NY), "symbol": "CCC", "open": 50.0, "close": 51.0},
        ]
    )
    obs = build_observations(bars)
    assert len(obs) == 0


# ---------------------------------------------------------------------------
# summarize_observations
# ---------------------------------------------------------------------------


def test_summary_reports_stock_day_and_equal_weight_basket_rates():
    observations = pd.DataFrame(
        {
            "session": pd.to_datetime(["2026-08-10", "2026-08-10", "2026-08-11", "2026-08-11"]).date,
            "symbol": ["AAA", "BBB", "AAA", "BBB"],
            "return": [0.02, -0.01, -0.02, -0.01],
            "win": [True, False, False, False],
        }
    )

    summary = summarize_observations(observations, expected_symbols=2)

    assert summary.stock_day_win_rate_pct == 25.0
    assert summary.basket_day_win_rate_pct == 50.0
    assert summary.valid_stock_days == 4
    assert summary.coverage_pct == 100.0


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
