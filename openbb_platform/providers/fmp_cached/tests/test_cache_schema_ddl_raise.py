"""Unit tests for ``create_all_flattened_tables`` DDL error handling — bd-jt4r.

The pre-fix ``create_all_flattened_tables`` at
``openbb_fmp_cached/utils/cache_schema.py:5469`` had three defects:

1. **Bare ``except Exception`` swallowed DDL failures** — the loop kept
   going and returned a dict with stringified errors. Downstream code
   didn't check ``isinstance(v, str)`` so cache reads later hit "table
   doesn't exist" errors far from the root cause.
2. **``print()`` for status lines** — no log-level, no stderr/stdout
   distinction, no way to silence in tests, no timestamps.
3. **Emoji-decorated status lines** (``✅``, ``❌``) — UnicodeEncodeError
   under Windows ``cp1252`` consoles (this repo runs on Windows per
   CLAUDE.md — ``.venv_win``).

Fix: raise on first DDL failure (safer than half-provisioned DB), swap
``print()`` for ``logger.info`` / ``logger.exception``, strip emojis.
This file locks in each corner of that contract.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from openbb_fmp_cached.utils import cache_schema


# ---------------------------------------------------------------------------
# Contract 1 — DDL failure MUST propagate (bd-jt4r).
# ---------------------------------------------------------------------------


def test_create_all_flattened_tables_raises_on_ddl_failure(caplog):
    """First DDL failure aborts the loop and re-raises (bd-jt4r).

    Pre-fix the loop swallowed the exception and returned a dict where
    the failed table's value was ``"Error: <stringified exc>"``, leaving
    the DB half-provisioned. Post-fix the exception propagates so the
    operator sees the failure at init time, not at first cache read.
    """
    boom = RuntimeError("simulated DDL failure — table X missing column Y")
    call_count = {"n": 0}

    def _fake_schema():
        call_count["n"] += 1
        # Fail on the SECOND table so we can assert the loop actually
        # aborted (does NOT proceed to a third).
        if call_count["n"] == 2:
            raise boom
        return "ok"

    fake_tables = {
        "table_one": {"schema": _fake_schema},
        "table_two_will_fail": {"schema": _fake_schema},
        "table_three_never_reached": {"schema": _fake_schema},
    }

    with patch.object(cache_schema, "FLATTENED_TABLES", fake_tables), caplog.at_level(
        logging.INFO, logger=cache_schema.__name__
    ):
        with pytest.raises(RuntimeError, match="simulated DDL failure"):
            cache_schema.create_all_flattened_tables()

    # Loop aborted at table_two — table_three_never_reached must NOT have
    # been called. This proves the fix actually stops on first failure
    # rather than continuing and just re-raising at the end.
    assert call_count["n"] == 2, (
        f"loop did not abort on first failure (called {call_count['n']} "
        f"times, expected 2) — bd-jt4r regression"
    )


# ---------------------------------------------------------------------------
# Contract 2 — happy path returns a success mapping (regression lock).
# ---------------------------------------------------------------------------


def test_create_all_flattened_tables_returns_success_dict_on_happy_path(caplog):
    """All tables created → returns ``{table_name: schema_result, ...}`` (regression)."""
    fake_tables = {
        "alpha": {"schema": lambda: "created:alpha"},
        "beta": {"schema": lambda: "created:beta"},
    }

    with patch.object(cache_schema, "FLATTENED_TABLES", fake_tables), caplog.at_level(
        logging.INFO, logger=cache_schema.__name__
    ):
        results = cache_schema.create_all_flattened_tables()

    assert results == {"alpha": "created:alpha", "beta": "created:beta"}


# ---------------------------------------------------------------------------
# Contract 3 — status messages go through logger, NOT print() (bd-jt4r).
# ---------------------------------------------------------------------------


def test_create_all_flattened_tables_uses_logger_not_print(caplog, capsys):
    """Status lines land in the logger, not on stdout via print() (bd-jt4r).

    Pre-fix the function used bare ``print(f"...{emoji}...")`` for every
    table. That is (a) unsilence-able in tests, (b) can't be filtered by
    log level, and (c) crashes on Windows ``cp1252`` consoles when
    Unicode characters land in the format string. Post-fix, all status
    goes through the module's ``logger`` so tests can capture it via
    ``caplog`` and production can filter by level.
    """
    fake_tables = {"only_table": {"schema": lambda: "ok"}}

    with patch.object(cache_schema, "FLATTENED_TABLES", fake_tables), caplog.at_level(
        logging.INFO, logger=cache_schema.__name__
    ):
        cache_schema.create_all_flattened_tables()

    # Logger MUST have received a record. This is the load-bearing
    # assertion — pre-fix, caplog.records would be empty because
    # ``print()`` bypasses the logging system entirely.
    assert caplog.records, (
        "no log records captured — create_all_flattened_tables is still "
        "using print() instead of logger.info() (bd-jt4r)"
    )
    # And nothing should have leaked to stdout (post-fix the function
    # should be silent on stdout — a caller who wants console output
    # configures a logging handler for that).
    captured = capsys.readouterr()
    assert captured.out == "", (
        f"create_all_flattened_tables leaked to stdout: {captured.out!r} — "
        f"must go through logger only (bd-jt4r)"
    )


# ---------------------------------------------------------------------------
# Contract 4 — status messages are ASCII-safe (bd-jt4r, Windows cp1252).
# ---------------------------------------------------------------------------


def test_create_all_flattened_tables_status_messages_are_ascii_safe():
    """Log messages must encode cleanly under cp1252 (bd-jt4r, Windows safety).

    CLAUDE.md's fork runs on Windows via ``.venv_win``; the default
    console encoding is ``cp1252``. Pre-fix the ``✅`` / ``❌`` emojis
    in the print statements would UnicodeEncodeError before the operator
    saw which table failed. Post-fix the log messages must round-trip
    cleanly through ``cp1252``.
    """

    captured_messages: list[str] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
            captured_messages.append(record.getMessage())

    handler = _CaptureHandler()
    logger = logging.getLogger(cache_schema.__name__)
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.DEBUG)

    fake_tables = {
        "alpha": {"schema": lambda: "ok"},
        "beta": {"schema": lambda: "ok"},
    }
    try:
        with patch.object(cache_schema, "FLATTENED_TABLES", fake_tables):
            cache_schema.create_all_flattened_tables()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)

    assert captured_messages, "no log messages captured — see logger-not-print test"
    for msg in captured_messages:
        # cp1252 is the default Windows console codepage. If this raises,
        # the log line would crash the CLI before the operator saw it.
        try:
            msg.encode("cp1252")
        except UnicodeEncodeError as exc:
            pytest.fail(
                f"log message contains characters that cannot be encoded "
                f"under Windows cp1252 (bd-jt4r): {msg!r} — {exc}"
            )


def test_create_all_flattened_tables_error_path_is_cp1252_safe():
    """Failure log path must also be cp1252-safe (PR #344 review, P2).

    The happy-path test above only exercises the ``logger.info`` success
    messages. The failure log uses ``logger.exception(... %r, table_name)``
    which formats the table name and includes the traceback. This test
    triggers an actual failure with a Unicode-tainted exception message
    to prove the error-path log also round-trips through cp1252 without
    crashing the Windows console.
    """

    captured_messages: list[str] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
            captured_messages.append(record.getMessage())

    handler = _CaptureHandler()
    logger = logging.getLogger(cache_schema.__name__)
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.DEBUG)

    # ASCII-only table name (production names are e.g. "balance_sheet");
    # ASCII-only exception message. The point is to exercise the error
    # log-emission path, not to prove Unicode in exception messages is
    # somehow handled — that would be a separate concern (Windows CLI
    # would need to handle Unicode in traceback text anyway).
    def _failing_schema():
        raise RuntimeError("simulated DDL failure for cp1252 test")

    fake_tables = {"failing_table": {"schema": _failing_schema}}

    try:
        with patch.object(cache_schema, "FLATTENED_TABLES", fake_tables):
            with pytest.raises(RuntimeError, match="simulated DDL failure"):
                cache_schema.create_all_flattened_tables()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)

    # We should have captured the initial "Creating N tables..." info
    # AND the error-path "DDL failed while creating..." exception log.
    assert len(captured_messages) >= 2, (
        f"expected at least 2 log messages (init + error), got "
        f"{len(captured_messages)}: {captured_messages!r}"
    )
    for msg in captured_messages:
        try:
            msg.encode("cp1252")
        except UnicodeEncodeError as exc:
            pytest.fail(
                f"error-path log message contains characters that cannot "
                f"be encoded under Windows cp1252 (bd-jt4r, PR #344 review): "
                f"{msg!r} — {exc}"
            )


def test_create_all_tables_is_the_same_object_as_flattened(caplog):
    """The public ``create_all_tables`` alias must be the SAME callable
    as ``create_all_flattened_tables`` — not a stale wrapper.

    Pre-fix the alias was a one-line wrapper with its own docstring that
    said "alias for create_all_flattened_tables" but didn't inherit the
    full failure-semantics docstring. Post-fix (PR #344 review P1) the
    alias is a direct name binding so callers get the identical behavior
    AND the identical docstring — no drift possible.
    """
    assert cache_schema.create_all_tables is cache_schema.create_all_flattened_tables, (
        "create_all_tables must be the SAME function object as "
        "create_all_flattened_tables (name binding, not wrapper) so the "
        "docstring cannot drift"
    )
    # And the shared docstring must include the load-bearing 'bd-jt4r'
    # failure-semantics section — proves the alias inherits the full doc.
    assert cache_schema.create_all_tables.__doc__ is not None
    assert "bd-jt4r" in cache_schema.create_all_tables.__doc__, (
        "alias's inherited docstring lost the bd-jt4r failure-semantics "
        "reference — someone re-wrapped the alias in a plain function"
    )
