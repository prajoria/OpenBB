"""Tests for job schedule calculations."""

from datetime import datetime, timezone

from openbb_core.app.jobs.schedules import DailySchedule, IntervalSchedule


def test_daily_schedule_honors_weekdays():
    """DailySchedule skips to the next configured weekday."""
    schedule = DailySchedule(
        hour=9,
        minute=30,
        timezone="America/New_York",
        weekdays=(0, 2),
    )

    next_run = schedule.next_after(datetime(2024, 1, 1, 15, 0, tzinfo=timezone.utc))

    assert next_run == datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc)


def test_daily_schedule_converts_local_time_to_utc():
    """DailySchedule returns UTC datetimes based on the configured timezone."""
    schedule = DailySchedule(
        hour=9,
        minute=30,
        timezone="America/New_York",
        weekdays=(0, 1, 2, 3, 4),
    )

    next_run = schedule.next_after(datetime(2024, 7, 1, 11, 0, tzinfo=timezone.utc))

    assert next_run == datetime(2024, 7, 1, 13, 30, tzinfo=timezone.utc)


def test_daily_schedule_moves_through_dst_gap():
    """A nonexistent local wall time advances to the first valid minute."""
    schedule = DailySchedule(
        hour=2,
        minute=30,
        timezone="America/New_York",
    )

    next_run = schedule.next_after(datetime(2024, 3, 10, 6, 55, tzinfo=timezone.utc))

    assert next_run == datetime(2024, 3, 10, 7, 0, tzinfo=timezone.utc)


def test_interval_schedule_returns_next_aligned_run():
    """IntervalSchedule aligns the next run to its anchor time."""
    schedule = IntervalSchedule(
        every_seconds=300,
        start_at=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
    )

    next_run = schedule.next_after(datetime(2024, 1, 1, 0, 7, 30, tzinfo=timezone.utc))

    assert next_run == datetime(2024, 1, 1, 0, 10, tzinfo=timezone.utc)


def test_schedules_are_strictly_after_the_reference_time():
    """next_after never returns the reference time itself."""
    daily_schedule = DailySchedule(hour=9, minute=30, timezone="UTC")
    interval_schedule = IntervalSchedule(
        every_seconds=300,
        start_at=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert daily_schedule.next_after(
        datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    ) == datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc)
    assert interval_schedule.next_after(
        datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    ) == datetime(2024, 1, 1, 0, 5, tzinfo=timezone.utc)
