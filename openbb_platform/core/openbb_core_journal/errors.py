"""Exception hierarchy for openbb_core_journal.

Base + two specific subclasses are the entire error surface; consumers catch
JournalError to handle "anything wrong with a journal" and the specific
subclasses when they need to distinguish (e.g. offer migration guidance on
SchemaVersionError).
"""

from __future__ import annotations


class JournalError(Exception):
    """Base for every journal-layer error."""


class SchemaVersionError(JournalError):
    """Raised when a journal event carries a schema_version the reader can't handle.

    The reader supports up to CURRENT_SCHEMA_VERSION (see event.py). Any event
    with a higher version raises this immediately — no silent data loss.
    """


class MalformedEventError(JournalError):
    """Raised when a journal line fails JSON parse or Pydantic validation.

    Note: JournalReader.stream() SKIPS malformed lines and logs them rather
    than raising this — but explicit consumer code that wants strict mode can
    re-parse a line and catch this error.
    """
