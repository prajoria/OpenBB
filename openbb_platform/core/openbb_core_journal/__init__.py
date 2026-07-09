"""openbb-core-journal — shared journaling + replay primitive.

Extracted from fmp-trading's SessionJournal (PRD §1) so multiple consumers
(fmp-trading, techtrade, backtest, ...) share one journal writer + reader +
replay contract instead of duplicating the pattern.

Public API (PRD §5) — everything a consumer should ever import:
    JournalEvent           — base event; consumers subclass with typed payloads
    JournalWriter          — append-only NDJSON writer, one-per-session
    JournalReader          — streaming reader with event-type filter push-down
    replay                 — reader → reconstructor pipeline
    JournalError           — base exception
    SchemaVersionError     — forward-compat guard (raised on unknown version)
    MalformedEventError    — payload validation failure
    CURRENT_SCHEMA_VERSION — int constant, currently 1
"""

from openbb_core_journal.errors import (
    JournalError,
    MalformedEventError,
    SchemaVersionError,
)
from openbb_core_journal.event import CURRENT_SCHEMA_VERSION, JournalEvent
from openbb_core_journal.reader import JournalReader
from openbb_core_journal.replay import replay
from openbb_core_journal.writer import JournalWriter

__version__ = "0.1.0"

__all__ = (
    "CURRENT_SCHEMA_VERSION",
    "JournalError",
    "JournalEvent",
    "JournalReader",
    "JournalWriter",
    "MalformedEventError",
    "SchemaVersionError",
    "replay",
    "__version__",
)
