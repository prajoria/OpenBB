"""Trading calendars wrapper (component 03).

Thin wrapper over ``exchange_calendars`` (Apache-2.0) providing the trading
sessions, holidays and half-days the engines use. This **supersedes the
hand-maintained ``market_holidays`` table** for backtest correctness.

See ``docs/designs/backtest-design/03-data-bundle.md`` §3.
"""

from __future__ import annotations

import exchange_calendars as xcals
import pandas as pd

DEFAULT_CALENDAR = "XNYS"


def get_calendar(code: str = DEFAULT_CALENDAR) -> xcals.ExchangeCalendar:
    """Return the exchange calendar for ``code`` (default ``XNYS``).

    The version is pinned by the installed ``exchange_calendars`` release for
    determinism. Raises if ``code`` is not a known calendar.
    """
    return xcals.get_calendar(code)


def sessions_in_range(
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    code: str = DEFAULT_CALENDAR,
) -> pd.DatetimeIndex:
    """Return trading sessions in ``[start, end]`` (inclusive) for ``code``."""
    cal = get_calendar(code)
    return cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))


def is_session(
    day: str | pd.Timestamp,
    code: str = DEFAULT_CALENDAR,
) -> bool:
    """Return whether ``day`` is a trading session on calendar ``code``."""
    cal = get_calendar(code)
    return bool(cal.is_session(pd.Timestamp(day)))
