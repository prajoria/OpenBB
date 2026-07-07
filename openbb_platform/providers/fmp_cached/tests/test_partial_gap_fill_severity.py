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
    remaining_gaps = [(date(2026, 3, 15), date(2026, 3, 15))]

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
    """Gap fraction between WARN and ERROR thresholds → WARNING with dates + count (bd-lyzk)."""
    warn_fraction, error_fraction = _import_severity_thresholds()
    trading_days_requested = 100
    target_fraction = (warn_fraction + error_fraction) / 2
    missing_days = int(target_fraction * trading_days_requested)
    start = date(2026, 3, 1)
    remaining_gaps = [
        (start, start + timedelta(days=missing_days - 1)),
    ]

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
    assert "2026-03-01" in msg, f"warning missing gap start date: {msg!r}"
    assert (
        "%" in msg or "fraction" in msg.lower() or str(missing_days) in msg
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
    """
    _, error_fraction = _import_severity_thresholds()
    trading_days_requested = 100
    missing_days = int((error_fraction + 0.25) * trading_days_requested)
    start = date(2026, 3, 1)
    remaining_gaps = [
        (start, start + timedelta(days=missing_days - 1)),
    ]

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
    assert "2026-03-01" in msg, f"error missing gap start date: {msg!r}"


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
