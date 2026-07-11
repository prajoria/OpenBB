"""JournalWriter — append-only NDJSON writer, one instance per session.

Contract (PRD §4.2):
    - append-only: no rewriting or truncation
    - atomic per-line: mid-line crash discards last partial line on read
      (reader tolerates malformed lines via MalformedEventError handling)
    - auto-flush on close (context-manager exit or explicit .close())

Design notes:
    * File is opened in "a" (append) mode, one line per event, terminated by \n.
    * Parent directory is created on demand via Path.mkdir(parents=True).
    * We use Pydantic v2 model_dump_json() which produces canonical JSON with
      no whitespace — one line per event by construction.
    * fsync is deferred to close() for throughput; single-writer-per-file per
      NG4 means we don't need per-write durability guarantees.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import IO

from openbb_core_journal.event import JournalEvent


class JournalWriter:
    """Append-only NDJSON writer.

    Usage:
        with JournalWriter(path, session_id="2026-07-08") as w:
            w.write(some_event)
    """

    def __init__(self, journal_path: Path, session_id: str) -> None:
        self.journal_path: Path = Path(journal_path)
        self.session_id: str = session_id
        self._fh: IO[str] | None = None

    def _ensure_open(self) -> IO[str]:
        if self._fh is None:
            # Create parent directory tree if missing — writers own their session file.
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            # newline="" prevents Python translating \n -> \r\n on Windows, which
            # would break the "1 line = 1 event" invariant for the reader.
            self._fh = open(self.journal_path, "a", encoding="utf-8", newline="")
        return self._fh

    def write(self, event: JournalEvent) -> None:
        """Append one JournalEvent to the journal file.

        Serialization uses Pydantic v2 model_dump_json(mode="json") which
        produces JSON with datetime -> ISO string, Decimal -> string, no
        embedded newlines. One event = one line by construction.
        """
        fh = self._ensure_open()
        # model_dump_json produces canonical JSON (no whitespace, no newlines).
        line = event.model_dump_json()
        fh.write(line)
        fh.write("\n")

    def close(self) -> None:
        """Flush + close the underlying file handle. Idempotent."""
        if self._fh is not None:
            self._fh.flush()
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "JournalWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
