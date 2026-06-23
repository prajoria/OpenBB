"""Unit tests for the trading-calendar wrapper (component 03, data/calendars.py).

These assert known NYSE (XNYS) facts via our wrapper; no DB or network needed.
"""

from __future__ import annotations

import pandas as pd
import pytest


def test_get_calendar_default_is_xnys():
    from openbb_backtest.data.calendars import get_calendar

    cal = get_calendar()
    assert cal.name == "XNYS"


def test_get_calendar_named():
    from openbb_backtest.data.calendars import get_calendar

    assert get_calendar("XNYS").name == "XNYS"


def test_sessions_in_range_counts_trading_days():
    # 2021-01-04 (Mon) .. 2021-01-08 (Fri): a full holiday-free week = 5 sessions.
    from openbb_backtest.data.calendars import sessions_in_range

    sessions = sessions_in_range("2021-01-04", "2021-01-08")
    assert isinstance(sessions, pd.DatetimeIndex)
    assert len(sessions) == 5


def test_sessions_in_range_excludes_holiday():
    # 2021-01-18 is MLK Day (holiday); 2021-01-19..22 (Tue-Fri) trade = 4 sessions.
    from openbb_backtest.data.calendars import sessions_in_range

    sessions = sessions_in_range("2021-01-18", "2021-01-22")
    assert len(sessions) == 4
    assert pd.Timestamp("2021-01-18") not in sessions


def test_is_session_true_and_false():
    from openbb_backtest.data.calendars import is_session

    assert is_session("2021-01-04") is True  # Monday, trading day
    assert is_session("2021-01-01") is False  # New Year's Day holiday
    assert is_session("2021-01-09") is False  # Saturday


def test_sessions_in_range_inclusive_bounds():
    # Single-session range where start == end on a trading day returns that day.
    from openbb_backtest.data.calendars import sessions_in_range

    sessions = sessions_in_range("2021-01-04", "2021-01-04")
    assert len(sessions) == 1
    assert sessions[0] == pd.Timestamp("2021-01-04")


def test_unknown_calendar_raises():
    from openbb_backtest.data.calendars import get_calendar

    with pytest.raises(Exception):  # exchange_calendars raises on unknown code
        get_calendar("NOT_A_REAL_CALENDAR")
