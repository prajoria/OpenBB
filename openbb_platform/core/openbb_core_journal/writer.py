"""JournalWriter — append-only NDJSON writer, one-per-session.

**Scaffold stub for J1.** Full implementation lands in J2 (writer + reader
+ base event with round-trip tests + atomic-append semantics). This stub
satisfies the J1 acceptance import contract; calling write() before J2
raises NotImplementedError with a clear pointer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class JournalWriter:
    """Append-only NDJSON writer (J2 will implement the writer body).

    Contract from PRD §4.2:
        - append-only: no rewriting or truncation
        - atomic per-line: mid-line crash discards last partial line on read
        - auto-flush on close
    """

    def __init__(self, journal_path: Path, session_id: str) -> None:
        self.journal_path = Path(journal_path)
        self.session_id = session_id

    def write(self, event: Any) -> None:  # noqa: D401
        """Append one JournalEvent to the journal file."""
        raise NotImplementedError(
            "JournalWriter.write() is a J1 scaffold stub. "
            "The append-only NDJSON body lands in J2 "
            "(OpenBBTechnical-2vu.2, GH #410)."
        )

    def close(self) -> None:
        """Flush + close the underlying file handle."""
        raise NotImplementedError(
            "JournalWriter.close() is a J1 scaffold stub. "
            "The close-with-flush body lands in J2."
        )

    def __enter__(self) -> "JournalWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        # Real close() lands in J2; the stub context-manager exit is a no-op
        # so J1 tests that only exercise the import path succeed.
        pass
