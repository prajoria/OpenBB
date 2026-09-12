"""US-equity EOD session, staleness, and display contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum

import exchange_calendars as xcals
import pandas as pd

EOD_DISCLAIMER = "EOD planning snapshot — not a live/intraday quote"
EARNINGS_ANNOTATION = "Reports before next open"
DEFAULT_CALENDAR = "XNYS"


class StalenessColor(str, Enum):
    """Session-level freshness category."""

    GREEN = "green"
    AMBER = "amber"
    RED = "red"


@dataclass(frozen=True)
class SnapshotStaleness:
    """Freshness measured only in completed trading sessions."""

    as_of_session: date | None
    last_completed_session: date
    missed_sessions: int | None
    color: StalenessColor


@dataclass(frozen=True)
class EodDisplay:
    """PII-free metadata every snapshot-backed planning view can render."""

    as_of_session: date | None
    last_completed_session: date
    missed_sessions: int | None
    color: StalenessColor
    label: str
    disclaimer: str = EOD_DISCLAIMER
    earnings_annotation: str | None = None


def _utc_timestamp(now: datetime) -> pd.Timestamp:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return pd.Timestamp(now.astimezone(timezone.utc))


def last_completed_session(
    now: datetime, calendar_name: str = DEFAULT_CALENDAR
) -> date:
    """Return the newest exchange session whose actual close has passed."""
    instant = _utc_timestamp(now)
    calendar = xcals.get_calendar(calendar_name)
    end = instant.tz_localize(None).normalize()
    start = end - pd.Timedelta(days=31)
    sessions = calendar.sessions_in_range(start, end)
    completed = [
        session for session in sessions if calendar.session_close(session) <= instant
    ]
    if not completed:
        raise ValueError("no completed session found in the preceding 31 days")
    return completed[-1].date()


def snapshot_staleness(
    as_of_session: date | None,
    now: datetime,
    calendar_name: str = DEFAULT_CALENDAR,
) -> SnapshotStaleness:
    """Classify a snapshot by completed sessions missed, not elapsed days."""
    latest = last_completed_session(now, calendar_name)
    if as_of_session is None:
        return SnapshotStaleness(None, latest, None, StalenessColor.RED)
    if as_of_session > latest:
        raise ValueError("as_of_session cannot be after the last completed session")
    calendar = xcals.get_calendar(calendar_name)
    as_of = pd.Timestamp(as_of_session)
    if not calendar.is_session(as_of):
        raise ValueError("as_of_session must be an exchange trading session")
    sessions = calendar.sessions_in_range(as_of, pd.Timestamp(latest))
    missed = max(0, len(sessions) - 1)
    color = (
        StalenessColor.GREEN
        if missed == 0
        else StalenessColor.AMBER if missed == 1 else StalenessColor.RED
    )
    return SnapshotStaleness(as_of_session, latest, missed, color)


def build_eod_display(
    as_of_session: date | None,
    now: datetime,
    *,
    reports_before_next_open: bool = False,
    calendar_name: str = DEFAULT_CALENDAR,
) -> EodDisplay:
    """Build the shared badge/disclaimer/earnings annotation payload."""
    stale = snapshot_staleness(as_of_session, now, calendar_name)
    label = (
        "No EOD snapshot available"
        if as_of_session is None
        else f"As of {as_of_session.isoformat()} close"
    )
    return EodDisplay(
        as_of_session=stale.as_of_session,
        last_completed_session=stale.last_completed_session,
        missed_sessions=stale.missed_sessions,
        color=stale.color,
        label=label,
        earnings_annotation=(EARNINGS_ANNOTATION if reports_before_next_open else None),
    )
