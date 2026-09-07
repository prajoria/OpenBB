"""Job scheduling models."""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

UTC = timezone.utc
ALL_WEEKDAYS = (0, 1, 2, 3, 4, 5, 6)
MAX_DST_GAP_SEARCH_MINUTES = 180


def ensure_utc(value: datetime, field_name: str = "datetime") -> datetime:
    """Normalize an aware datetime to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")

    return value.astimezone(UTC)


def _roundtrip_matches(aware_value: datetime, local_value: datetime, tz: ZoneInfo) -> bool:
    """Check whether a local wall time exists in the configured zone."""
    roundtrip_value = aware_value.astimezone(UTC).astimezone(tz)
    return roundtrip_value.replace(tzinfo=None) == local_value


def _is_ambiguous(local_value: datetime, tz: ZoneInfo) -> bool:
    """Determine whether a wall time occurs twice because of DST fall-back."""
    first = local_value.replace(tzinfo=tz, fold=0)
    second = local_value.replace(tzinfo=tz, fold=1)

    if first.utcoffset() == second.utcoffset():
        return False

    return _roundtrip_matches(first, local_value, tz) and _roundtrip_matches(
        second, local_value, tz
    )


def _localize_at_or_after(local_value: datetime, tz: ZoneInfo) -> datetime:
    """Resolve a local wall time, moving through DST gaps when required."""
    for minute_offset in range(MAX_DST_GAP_SEARCH_MINUTES + 1):
        candidate = local_value + timedelta(minutes=minute_offset)

        if _is_ambiguous(candidate, tz):
            first = candidate.replace(tzinfo=tz, fold=0)
            second = candidate.replace(tzinfo=tz, fold=1)
            return min(first, second, key=lambda item: item.astimezone(UTC))

        aware_candidate = candidate.replace(tzinfo=tz)
        if _roundtrip_matches(aware_candidate, candidate, tz):
            return aware_candidate

    raise ValueError(
        "Unable to resolve scheduled wall time within "
        f"{MAX_DST_GAP_SEARCH_MINUTES} minutes"
    )


class DailySchedule(BaseModel):
    """Run once per selected day at a local wall-clock time."""

    model_config = ConfigDict(frozen=True)

    hour: int = Field(ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    timezone: str = "UTC"
    weekdays: tuple[int, ...] = ALL_WEEKDAYS

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """Require a valid IANA timezone."""
        ZoneInfo(value)
        return value

    @field_validator("weekdays", mode="before")
    @classmethod
    def validate_weekdays(cls, value: object) -> tuple[int, ...]:
        """Normalize and validate weekday numbers."""
        weekdays = ALL_WEEKDAYS if value is None else tuple(value)  # type: ignore[arg-type]
        if not weekdays:
            raise ValueError("weekdays must not be empty")

        normalized = tuple(sorted(set(weekdays)))
        if any(day not in ALL_WEEKDAYS for day in normalized):
            raise ValueError("weekdays must contain values from 0 to 6")

        return normalized

    @property
    def zone(self) -> ZoneInfo:
        """Return the schedule timezone object."""
        return ZoneInfo(self.timezone)

    def next_after(self, after: datetime) -> datetime:
        """Return the next scheduled run strictly after the given instant."""
        after_utc = ensure_utc(after, "after")
        after_local = after_utc.astimezone(self.zone)

        for day_offset in range(8):
            candidate_date = after_local.date() + timedelta(days=day_offset)
            if candidate_date.weekday() not in self.weekdays:
                continue

            candidate_local = datetime.combine(
                candidate_date,
                time(self.hour, self.minute),
            )
            scheduled_local = _localize_at_or_after(candidate_local, self.zone)
            scheduled_utc = scheduled_local.astimezone(UTC)

            if scheduled_utc > after_utc:
                return scheduled_utc

        raise RuntimeError("Unable to calculate the next run within one week")


class IntervalSchedule(BaseModel):
    """Run repeatedly at a fixed number of seconds from a UTC anchor."""

    model_config = ConfigDict(frozen=True)

    every_seconds: int = Field(ge=1)
    start_at: datetime = Field(default_factory=lambda: datetime(1970, 1, 1, tzinfo=UTC))

    @field_validator("start_at")
    @classmethod
    def validate_start_at(cls, value: datetime) -> datetime:
        """Store the anchor in UTC."""
        return ensure_utc(value, "start_at")

    def next_after(self, after: datetime) -> datetime:
        """Return the next interval strictly after the given instant."""
        after_utc = ensure_utc(after, "after")
        anchor = self.start_at

        if after_utc < anchor:
            return anchor

        elapsed_seconds = (after_utc - anchor).total_seconds()
        intervals = math.floor(elapsed_seconds / self.every_seconds) + 1

        return anchor + timedelta(seconds=intervals * self.every_seconds)
