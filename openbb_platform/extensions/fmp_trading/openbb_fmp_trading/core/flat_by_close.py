"""Flat-by-close window state machine (PRD §8.5, P4).

Three states based on wall-clock ET, driven by ``exchange_calendars`` so
half-day closes (Black Friday, day before Christmas, July 3, etc.) get
auto-scaled without operator intervention:

  NORMAL       (before 15:50 on a full session)  — RiskManager permits opens
  NO_NEW_OPENS (15:50–15:54)                     — G1 rejects new opens
  FORCE_CLOSE  (15:55 onward)                    — queue MARKET SELL / BUY_TO_COVER

Why a separate state helper vs. inlining into RiskManager?
  * Testability: pure function of ``now_et`` → state, no fixtures, no mocks
  * Reuse: P2.5 wires this into ``tick_loop.run_tick`` BEFORE the signal
    cascade. The RiskManager's G1 gate also asks this helper — that way
    the timeline definition lives in one place.
  * Half-day discipline: ``exchange_calendars`` is already a project dep
    (``risk_manager.py`` imports it); this reuses the same session_close
    computation instead of duplicating the calendar lookup.

The state is a pure function of ``now_et`` and (optionally) an injected
close time. Session-scoped mutable state (which positions to close) lives
on IntradaySession, not here — this module only computes "is it time?".
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import Enum

import exchange_calendars as xcals

# Shared calendar handle — the same "XNYS" (NYSE) calendar the RiskManager
# uses. Reused across calls; xcals caches session lookups internally.
_CALENDAR = xcals.get_calendar("XNYS")

# Default full-session cutoffs (16:00 ET close): stop opens at 15:50,
# force-close at 15:55. On half-days these shift by _CLOSE_MINUS_OPEN_STOP
# and _CLOSE_MINUS_FORCE minutes below.
_DEFAULT_NO_NEW_OPENS = time(15, 50)
_DEFAULT_FORCE_CLOSE = time(15, 55)

# On half-day sessions, scale the two cutoffs relative to the actual close
# (PRD Open Q4: "close - 5min" for force, "close - 10min" for no-opens).
# A 13:00 close on July 3 becomes: no-opens 12:50, force 12:55.
_CLOSE_MINUS_NO_OPENS_MIN = 10
_CLOSE_MINUS_FORCE_MIN = 5


class WindowState(str, Enum):
    """Three-way state indicating how the RiskManager should treat this tick."""

    NORMAL = "normal"
    NO_NEW_OPENS = "no_new_opens"
    FORCE_CLOSE = "force_close"


def enter_flat_window(
    now_et: datetime,
    no_new_opens_time: time | None = None,
    force_close_time: time | None = None,
) -> WindowState:
    """Compute the current flat-by-close state for a wall-clock ET datetime.

    On a full session (16:00 close), the defaults are 15:50 / 15:55.
    On a half-day session, the times get auto-shifted so the same
    (10-min-warn, 5-min-force) spacing applies relative to the actual close.

    Args:
        now_et:               Current wall-clock time interpreted as ET.
                              Callers that hold UTC must convert first;
                              this helper does no timezone math to keep
                              the reasoning local.
        no_new_opens_time:    Override the no-new-opens cutoff (test injection).
        force_close_time:     Override the force-close cutoff (test injection).

    Returns:
        WindowState indicating how the RiskManager and tick loop should
        treat this tick.
    """
    session_date: date = now_et.date()

    # Only auto-scale to half-days when the caller hasn't pinned custom times.
    # If they did pass explicit times, respect them verbatim — this is the
    # test-injection escape hatch.
    if no_new_opens_time is None or force_close_time is None:
        auto_no_opens, auto_force = _cutoffs_for_session(session_date)
        no_new_opens_time = no_new_opens_time or auto_no_opens
        force_close_time = force_close_time or auto_force

    t = now_et.time()
    if t >= force_close_time:
        return WindowState.FORCE_CLOSE
    if t >= no_new_opens_time:
        return WindowState.NO_NEW_OPENS
    return WindowState.NORMAL


def _cutoffs_for_session(session_date: date) -> tuple[time, time]:
    """Look up (no_new_opens, force_close) for this session date.

    Returns the defaults (15:50, 15:55) on non-session days or when
    ``exchange_calendars`` doesn't know about the date — the tick loop
    never runs on non-session days, so this is defensive not load-bearing.
    """
    if not _CALENDAR.is_session(session_date):
        return _DEFAULT_NO_NEW_OPENS, _DEFAULT_FORCE_CLOSE

    close_dt = _CALENDAR.session_close(session_date)
    close_t = close_dt.time() if hasattr(close_dt, "time") else close_dt

    # Full session: use the defaults. Half-day: derive from actual close.
    if close_t >= time(16, 0):
        return _DEFAULT_NO_NEW_OPENS, _DEFAULT_FORCE_CLOSE
    return (
        _minutes_before(close_t, _CLOSE_MINUS_NO_OPENS_MIN),
        _minutes_before(close_t, _CLOSE_MINUS_FORCE_MIN),
    )


def _minutes_before(t: time, minutes: int) -> time:
    """Subtract N minutes from a ``time`` via a throwaway datetime — the only
    way ``timedelta`` composes with ``time`` in the stdlib."""
    anchor = datetime(2000, 1, 1, t.hour, t.minute, t.second)
    return (anchor - timedelta(minutes=minutes)).time()
