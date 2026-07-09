"""Smoke test for openbb_core_journal J1 scaffold acceptance.

Asserts the public API surface described in PRD §5 imports cleanly:
    JournalEvent, JournalWriter, JournalReader, replay,
    JournalError, SchemaVersionError, MalformedEventError,
    CURRENT_SCHEMA_VERSION
"""

from __future__ import annotations


def test_public_api_imports():
    """Every symbol named in PRD §5 must be importable from the top-level package."""
    import openbb_core_journal as journal

    # PRD §5 exported surface — kept in sync with __all__.
    expected_symbols = (
        "CURRENT_SCHEMA_VERSION",
        "JournalError",
        "JournalEvent",
        "JournalReader",
        "JournalWriter",
        "MalformedEventError",
        "SchemaVersionError",
        "replay",
    )
    for name in expected_symbols:
        # getattr avoids eval() (security hook would flag); still catches missing/None symbols.
        assert hasattr(journal, name), f"openbb_core_journal missing public symbol: {name}"
        assert getattr(journal, name) is not None, f"{name} is None"


def test_current_schema_version_is_int_ge_1():
    from openbb_core_journal import CURRENT_SCHEMA_VERSION

    assert isinstance(CURRENT_SCHEMA_VERSION, int)
    assert CURRENT_SCHEMA_VERSION >= 1


def test_errors_inherit_from_journal_error():
    """PRD §4.1: JournalError is the base; specific errors subclass it."""
    from openbb_core_journal import (
        JournalError,
        MalformedEventError,
        SchemaVersionError,
    )

    assert issubclass(SchemaVersionError, JournalError)
    assert issubclass(MalformedEventError, JournalError)
