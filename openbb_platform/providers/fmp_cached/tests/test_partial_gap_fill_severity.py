"""Unit tests for partial-gap-fill severity logging — bd-lyzk.

After ``aextract_data`` fetches ``missing_data``, stores it, and re-runs
``_analyze_cache_gaps`` to get the complete-from-cache view, the code
checks ``remaining_gaps`` for anything the fetch didn't fill. Pre-fix
this was a single ``logger.warning`` with just the count — no gap
detail, no severity distinction between "FMP legitimately doesn't have
this date" (halt / IPO pre-history / weekend that slipped past the
holiday filter / end_date in the future) and "the fetch actually
failed silently" (200 OK but empty body, partial response).

The fix (bd-lyzk) does NOT raise on ``remaining_gaps`` because FMP
legitimately has data holes for the reasons above. Instead:

1. Log at ``INFO`` when the gap fraction is below a "probably holidays"
   threshold (small gaps are expected background noise).
2. Log at ``WARNING`` when the gap fraction is above that threshold but
   below a "probably fetch failure" threshold — includes the specific
   date ranges + missing-count + fraction so operators can act.
3. Log at ``ERROR`` when the gap fraction is above the fetch-failure
   threshold — same details as WARNING but at a level that triggers
   real ops alerting.

The log message MUST include the missing ranges as tuples so operators
can immediately re-request those exact windows.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta


def _import_severity_thresholds():
    """Import the two severity-threshold constants from the source module."""
    from openbb_fmp_cached.models.equity_historical import (
        _PARTIAL_GAP_ERROR_FRACTION,
        _PARTIAL_GAP_WARN_FRACTION,
    )

    return _PARTIAL_GAP_WARN_FRACTION, _PARTIAL_GAP_ERROR_FRACTION


def _call_helper(symbol, remaining_gaps, trading_days_requested):
    """Invoke ``_log_partial_gap_severity`` via public module symbol."""
    from openbb_fmp_cached.models import equity_historical

    return equity_historical._log_partial_gap_severity(
        symbol, remaining_gaps, trading_days_requested
    )


# ---------------------------------------------------------------------------
# Contract 1 — no gaps: silent (no log at all).
# ---------------------------------------------------------------------------


def test_log_partial_gap_severity_no_gaps_is_silent(caplog):
    """Zero remaining gaps → no log record at all (regression lock)."""
    with caplog.at_level(
        logging.DEBUG, logger="openbb_fmp_cached.models.equity_historical"
    ):
        _call_helper("AAPL", [], trading_days_requested=100)
    assert caplog.records == [], (
        f"expected zero log records on empty gaps, got: "
        f"{[r.getMessage() for r in caplog.records]!r}"
    )


# ---------------------------------------------------------------------------
# Contract 2 — small gap: INFO (probably holidays / pre-IPO).
# ---------------------------------------------------------------------------


def test_log_partial_gap_severity_small_gap_is_info(caplog):
    """Gap fraction below WARN threshold → INFO level (bd-lyzk)."""
    warn_fraction, _ = _import_severity_thresholds()
    # 1 trading day missing out of 100 → 1% gap, well below default 5% warn.
    # Use a WEEKDAY — PR #352 review P1 fix made the numerator count
    # trading days, so a weekend gap contributes 0. 2026-03-16 is Monday.
    remaining_gaps = [(date(2026, 3, 16), date(2026, 3, 16))]

    with caplog.at_level(
        logging.DEBUG, logger="openbb_fmp_cached.models.equity_historical"
    ):
        _call_helper("AAPL", remaining_gaps, trading_days_requested=100)

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert info_records, (
        f"small gap should log at INFO, got no INFO records. All: "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]!r}"
    )
    high_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not high_records, (
        f"small gap emitted WARNING+/ERROR record — should be INFO only. "
        f"Got: {[(r.levelname, r.getMessage()) for r in high_records]!r}"
    )


# ---------------------------------------------------------------------------
# Contract 3 — moderate gap: WARNING with specifics.
# ---------------------------------------------------------------------------


def test_log_partial_gap_severity_moderate_gap_is_warning_with_specifics(caplog):
    """Gap fraction between WARN and ERROR thresholds → WARNING with dates + count (bd-lyzk).

    PR #352 review P1 fix: numerator now counts TRADING days, so the
    test must construct a gap that yields the right trading-day count
    (not just calendar days). Mar 2 → Mar 20 2026 is a Mon-Fri span
    of 15 trading days (19 calendar days including 2 weekends).
    """
    warn_fraction, error_fraction = _import_severity_thresholds()
    trading_days_requested = 100
    # Target ~15% (midway between 5% WARN and 25% ERROR) = 15 trading days
    remaining_gaps = [(date(2026, 3, 2), date(2026, 3, 20))]  # 15 tdays

    with caplog.at_level(
        logging.DEBUG, logger="openbb_fmp_cached.models.equity_historical"
    ):
        _call_helper(
            "AAPL", remaining_gaps, trading_days_requested=trading_days_requested
        )

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning_records, (
        f"moderate gap should log at WARNING, got no WARNING records. All: "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]!r}"
    )
    msg = warning_records[0].getMessage()
    assert "AAPL" in msg, f"warning missing symbol: {msg!r}"
    assert "2026-03-02" in msg, f"warning missing gap start date: {msg!r}"
    assert (
        "%" in msg or "fraction" in msg.lower() or "trading day" in msg.lower()
    ), f"warning lacks gap-size context (percent / fraction / count): {msg!r}"


# ---------------------------------------------------------------------------
# Contract 4 — large gap: ERROR (likely fetch failure).
# ---------------------------------------------------------------------------


def test_log_partial_gap_severity_large_gap_is_error(caplog):
    """Gap fraction above ERROR threshold → ERROR level (bd-lyzk).

    Large fraction of missing days is very unlikely to be legitimate
    (holidays are a small % even in a short window). Escalate to ERROR
    so ops alerting fires — this is the primary silent-fetch-failure
    signal the bead flags.

    PR #352 review P1: numerator counts trading days. Mar 2 → May 8
    2026 is ~50 trading days (Mon-Fri span with 9 embedded weekends).
    """
    _, error_fraction = _import_severity_thresholds()
    trading_days_requested = 100
    # Target ~50% = 50 trading days
    remaining_gaps = [(date(2026, 3, 2), date(2026, 5, 8))]

    with caplog.at_level(
        logging.DEBUG, logger="openbb_fmp_cached.models.equity_historical"
    ):
        _call_helper(
            "AAPL", remaining_gaps, trading_days_requested=trading_days_requested
        )

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, (
        f"large gap should log at ERROR, got no ERROR records. All: "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]!r}"
    )
    msg = error_records[0].getMessage()
    assert "AAPL" in msg, f"error missing symbol: {msg!r}"
    assert "2026-03-02" in msg, f"error missing gap start date: {msg!r}"


# ---------------------------------------------------------------------------
# Contract 5 — trading_days_requested == 0: safe divide-by-zero handling.
# ---------------------------------------------------------------------------


def test_log_partial_gap_severity_zero_trading_days_no_crash(caplog):
    """trading_days_requested == 0 (edge case) must not crash on division."""
    remaining_gaps = [(date(2026, 3, 7), date(2026, 3, 8))]  # weekend

    with caplog.at_level(
        logging.DEBUG, logger="openbb_fmp_cached.models.equity_historical"
    ):
        # Must not raise.
        _call_helper("AAPL", remaining_gaps, trading_days_requested=0)

    assert caplog.records, (
        "no log emitted for 0-trading-day + non-empty gaps — the severity "
        "helper should still surface the unusual state"
    )


# ---------------------------------------------------------------------------
# Contract 6 — PR #352 review P1: unit-consistency between numerator + denominator.
# ---------------------------------------------------------------------------


def test_log_partial_gap_severity_weekend_spanning_gap_uses_trading_days(caplog):
    """PR #352 code-reviewer P1: numerator must count trading days, not calendar days.

    Pre-review-fix used ``(end - start).days + 1`` which counted CALENDAR
    days. A Fri→Wed gap = 5 calendar days but only 3 trading days;
    over a 20-trading-day window that computed as 25% ERROR when the
    correct fraction is 15% WARN. This test constructs a
    weekend-spanning gap and asserts the severity is WARN (not ERROR),
    which proves the numerator correctly excludes the weekend.

    Empirically verified by silent-failure-hunter: pre-review-fix, a
    whole-year empty cache reported gap fraction 145.6% and a Fri→Mon
    closure reported 200.0% — mathematically impossible under the
    correct trading-day units.
    """
    # Fri 2026-03-06 → Wed 2026-03-11 = 6 calendar days but 4 trading
    # days (Fri, Mon, Tue, Wed). Over 20 trading days denominator:
    # - Pre-review-fix (calendar num): 6/20 = 30% → ERROR
    # - Post-review-fix (trading num): 4/20 = 20% → WARNING
    remaining_gaps = [(date(2026, 3, 6), date(2026, 3, 11))]

    with caplog.at_level(
        logging.DEBUG, logger="openbb_fmp_cached.models.equity_historical"
    ):
        _call_helper("AAPL", remaining_gaps, trading_days_requested=20)

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]

    # Post-fix: 4 trading days / 20 = 20% → WARN band.
    assert warning_records, (
        f"weekend-spanning Fri→Wed gap (4 trading days) over 20-day window "
        f"should log at WARNING (20%), not ERROR (which would fire if the "
        f"numerator still counted calendar days at 6/20=30%). All records: "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]!r}"
    )
    assert not error_records, (
        f"weekend-spanning gap logged at ERROR — indicates numerator is "
        f"still counting CALENDAR days (bug: 6/20=30%) instead of TRADING "
        f"days (correct: 4/20=20%). Got ERROR: "
        f"{[r.getMessage() for r in error_records]!r}"
    )


def test_log_partial_gap_severity_future_end_date_clipped_at_today(caplog):
    """PR #352 code-reviewer P1: gap end-dates past today must be clipped.

    Pre-review-fix a caller with ``end_date = today + 3y`` had
    ``_count_trading_days_in_range`` count ~750 future weekdays in the
    denominator, then the numerator counted the same future weekdays as
    "missing" (they will never be filled — FMP can't have the future).
    Result: gap_fraction ≈ 87% ERROR on a request that was actually
    fully-fulfilled through today.

    Post-review-fix the numerator clips gap-end-dates at ``today``. A
    gap fully in the future contributes 0 to missing_days; a gap
    straddling today contributes only its past-today portion.

    This test constructs an entirely-future gap and asserts NO log fires
    (it's the "silently return, no report" fast-path — legitimate
    happy-path for a future-range request).
    """
    from datetime import date as _date

    # Gap starts 1 year in the future — entirely unreachable by any
    # fetch, but not a real miss.
    future_start = _date.today().replace(year=_date.today().year + 1)
    future_end = _date(future_start.year, future_start.month, 28)
    if future_end <= future_start:
        future_end = _date(future_start.year + 1, 1, 15)
    remaining_gaps = [(future_start, future_end)]

    with caplog.at_level(
        logging.DEBUG, logger="openbb_fmp_cached.models.equity_historical"
    ):
        _call_helper("AAPL", remaining_gaps, trading_days_requested=250)

    # Post-fix: entirely-future gap → clipped to 0 missing_days →
    # early-return with NO log. Pre-fix would have logged at ERROR
    # (250 missing / 250 requested = 100% ERROR).
    high_records = [r for r in caplog.records if r.levelno >= logging.INFO]
    assert not high_records, (
        f"entirely-future gap should be silent (clipped at today), but got "
        f"records: {[(r.levelname, r.getMessage()) for r in high_records]!r} "
        f"— pre-fix ERROR was ~100% because numerator counted the future "
        f"weekdays FMP will never have."
    )


def test_log_partial_gap_severity_capped_range_list_when_many_gaps(caplog):
    """PR #352 code-reviewer P2: cap formatted range list at 10 (bd-lyzk).

    200 single-day gaps would produce a ~5KB log line and risk Datadog/
    syslog truncation on the ERROR-level lines ops alerting depends on.
    Cap at 10 entries + '... and N more' suffix.
    """
    # 15 single-day trading-day gaps → will trip the cap (> 10).
    # Use consecutive weekdays so each is a real trading day.
    gaps = []
    d = date(2026, 3, 2)  # Monday
    added = 0
    while added < 15:
        if d.weekday() < 5:
            gaps.append((d, d))
            added += 1
        d += timedelta(days=1)

    with caplog.at_level(
        logging.DEBUG, logger="openbb_fmp_cached.models.equity_historical"
    ):
        _call_helper("AAPL", gaps, trading_days_requested=100)

    # Find the partial-fill log record (there are DEBUG lines from the
    # holiday-DB helper that we skip past).
    partial_fill_records = [
        r for r in caplog.records if "Partial-fill for AAPL" in r.getMessage()
    ]
    assert partial_fill_records, (
        f"no partial-fill record captured. All: "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]!r}"
    )
    msg = partial_fill_records[0].getMessage()
    # The cap suffix "... and 5 more" (15 gaps - 10 shown) must appear.
    assert "... and 5 more" in msg, (
        f"log message did not include the range-cap suffix — should read "
        f"'... and N more' when > 10 ranges. Got: {msg!r}"
    )
