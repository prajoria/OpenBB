"""US-equity EOD session and display semantics (#1966)."""

# ruff: noqa: D103

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from openbb_techtrade.snapshot.semantics import (
    EARNINGS_ANNOTATION,
    EOD_DISCLAIMER,
    StalenessColor,
    build_eod_display,
    last_completed_session,
    snapshot_staleness,
)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 9, 11, 22, tzinfo=timezone.utc), date(2026, 9, 11)),
        (datetime(2026, 9, 12, 16, tzinfo=timezone.utc), date(2026, 9, 11)),
        (datetime(2026, 9, 13, 16, tzinfo=timezone.utc), date(2026, 9, 11)),
        (datetime(2026, 9, 14, 12, tzinfo=timezone.utc), date(2026, 9, 11)),
        (datetime(2026, 7, 4, 16, tzinfo=timezone.utc), date(2026, 7, 2)),
    ],
)
def test_last_completed_session_respects_weekends_holidays_and_preopen(
    now: datetime, expected: date
) -> None:
    assert last_completed_session(now) == expected


def test_last_completed_session_respects_early_close() -> None:
    assert last_completed_session(
        datetime(2026, 11, 27, 17, 59, tzinfo=timezone.utc)
    ) == date(2026, 11, 25)
    assert last_completed_session(
        datetime(2026, 11, 27, 18, 1, tzinfo=timezone.utc)
    ) == date(2026, 11, 27)


def test_naive_wall_clock_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        last_completed_session(datetime(2026, 9, 11, 22))


@pytest.mark.parametrize(
    ("as_of", "expected_sessions", "expected_color"),
    [
        (date(2026, 9, 15), 0, StalenessColor.GREEN),
        (date(2026, 9, 14), 1, StalenessColor.AMBER),
        (date(2026, 9, 11), 2, StalenessColor.RED),
        (None, None, StalenessColor.RED),
    ],
)
def test_staleness_counts_completed_trading_sessions(
    as_of: date | None,
    expected_sessions: int | None,
    expected_color: StalenessColor,
) -> None:
    result = snapshot_staleness(as_of, datetime(2026, 9, 15, 22, tzinfo=timezone.utc))

    assert result.missed_sessions == expected_sessions
    assert result.color is expected_color
    assert result.last_completed_session == date(2026, 9, 15)


def test_eod_display_contract_always_has_disclaimer_and_optional_earnings() -> None:
    plain = build_eod_display(
        date(2026, 9, 15),
        datetime(2026, 9, 15, 22, tzinfo=timezone.utc),
    )
    earnings = build_eod_display(
        date(2026, 9, 15),
        datetime(2026, 9, 15, 22, tzinfo=timezone.utc),
        reports_before_next_open=True,
    )

    assert plain.disclaimer == EOD_DISCLAIMER
    assert plain.earnings_annotation is None
    assert earnings.disclaimer == EOD_DISCLAIMER
    assert earnings.earnings_annotation == EARNINGS_ANNOTATION
