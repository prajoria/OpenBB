"""JournalReader — streaming NDJSON reader with event-type filter push-down.

**Scaffold stub for J1.** Full implementation lands in J2 (streaming iteration,
malformed-line tolerance, SchemaVersionError enforcement). This stub satisfies
the J1 acceptance import contract; calling stream() before J2 raises
NotImplementedError with a clear pointer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from openbb_core_journal.event import JournalEvent


class JournalReader:
    """Streaming NDJSON reader (J2 will implement the reader body).

    Contract from PRD §4.3:
        - streams events lazily (no full-file load)
        - malformed-line tolerance: skip + log, never raise mid-stream
        - SchemaVersionError on any event with schema_version > CURRENT
        - filter push-down: event_types= skips lines without full validation
    """

    def __init__(self, journal_path: Path) -> None:
        self.journal_path = Path(journal_path)

    def stream(
        self, event_types: list[str] | None = None
    ) -> Iterator[JournalEvent]:
        """Yield JournalEvents from the journal file."""
        raise NotImplementedError(
            "JournalReader.stream() is a J1 scaffold stub. "
            "The streaming body lands in J2 "
            "(OpenBBTechnical-2vu.2, GH #410)."
        )

    def read_all(self) -> list[JournalEvent]:
        """Convenience: eagerly materialize the whole journal."""
        return list(self.stream())
