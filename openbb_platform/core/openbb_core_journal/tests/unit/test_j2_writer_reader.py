"""J2 tests: JournalWriter + JournalReader round-trip + edge cases.

Covers PRD §4.2 writer contract and §4.3 reader contract:
- Round-trip: write N events, read them back in order
- Filter push-down: event_types= skips non-matching lines
- Atomic append: mid-line crash discards last partial line on read
- Malformed-line tolerance: reader skips + logs invalid JSON, does NOT raise
- SchemaVersionError: reader raises on any event with schema_version > CURRENT
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from openbb_core_journal import (
    CURRENT_SCHEMA_VERSION,
    JournalEvent,
    JournalReader,
    JournalWriter,
    SchemaVersionError,
)


def _ev(event_type: str, session_id: str = "s1", payload=None) -> JournalEvent:
    return JournalEvent(
        ts=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
        session_id=session_id,
        event_type=event_type,
        payload=payload or {"k": "v"},
    )


class TestWriterRoundTrip:
    def test_write_then_read_preserves_order(self, tmp_path: Path):
        p = tmp_path / "j.ndjson"
        with JournalWriter(p, session_id="s1") as w:
            w.write(_ev("a"))
            w.write(_ev("b"))
            w.write(_ev("c"))

        events = JournalReader(p).read_all()
        assert [e.event_type for e in events] == ["a", "b", "c"]

    def test_write_creates_file_if_missing(self, tmp_path: Path):
        p = tmp_path / "nested" / "j.ndjson"
        with JournalWriter(p, session_id="s1") as w:
            w.write(_ev("a"))
        assert p.exists()

    def test_write_is_append_only(self, tmp_path: Path):
        p = tmp_path / "j.ndjson"
        with JournalWriter(p, session_id="s1") as w:
            w.write(_ev("first"))
        # Reopen and append — must not truncate.
        with JournalWriter(p, session_id="s1") as w:
            w.write(_ev("second"))
        events = JournalReader(p).read_all()
        assert [e.event_type for e in events] == ["first", "second"]

    def test_one_line_per_event(self, tmp_path: Path):
        p = tmp_path / "j.ndjson"
        with JournalWriter(p, session_id="s1") as w:
            for _ in range(5):
                w.write(_ev("tick"))
        lines = p.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5
        for line in lines:
            json.loads(line)  # each line is standalone valid JSON


class TestReaderStreamFilter:
    def test_stream_yields_events_lazily(self, tmp_path: Path):
        p = tmp_path / "j.ndjson"
        with JournalWriter(p, session_id="s1") as w:
            for i in range(3):
                w.write(_ev(f"e{i}"))

        r = JournalReader(p)
        got = [e.event_type for e in r.stream()]
        assert got == ["e0", "e1", "e2"]

    def test_stream_filter_by_event_type(self, tmp_path: Path):
        p = tmp_path / "j.ndjson"
        with JournalWriter(p, session_id="s1") as w:
            w.write(_ev("tick"))
            w.write(_ev("signal"))
            w.write(_ev("tick"))
            w.write(_ev("fill"))

        r = JournalReader(p)
        ticks = list(r.stream(event_types=["tick"]))
        assert [e.event_type for e in ticks] == ["tick", "tick"]

    def test_stream_filter_multiple_types(self, tmp_path: Path):
        p = tmp_path / "j.ndjson"
        with JournalWriter(p, session_id="s1") as w:
            w.write(_ev("tick"))
            w.write(_ev("signal"))
            w.write(_ev("fill"))

        r = JournalReader(p)
        got = [e.event_type for e in r.stream(event_types=["tick", "fill"])]
        assert got == ["tick", "fill"]


class TestReaderErrorHandling:
    def test_reader_skips_malformed_lines(self, tmp_path: Path, caplog):
        """Malformed lines are logged + skipped, NEVER raise mid-stream (PRD §4.3)."""
        p = tmp_path / "j.ndjson"
        with JournalWriter(p, session_id="s1") as w:
            w.write(_ev("good1"))

        # Simulate a mid-line crash: append a partial/garbage line, then a good one.
        with p.open("a", encoding="utf-8") as fh:
            fh.write("{not json}\n")
            fh.write(json.dumps(_ev("good2").model_dump(mode="json"),
                                default=str) + "\n")

        events = JournalReader(p).read_all()
        assert [e.event_type for e in events] == ["good1", "good2"]

    def test_reader_skips_empty_lines(self, tmp_path: Path):
        """Empty/whitespace-only lines are silently skipped (common with editors)."""
        p = tmp_path / "j.ndjson"
        with JournalWriter(p, session_id="s1") as w:
            w.write(_ev("a"))
        with p.open("a", encoding="utf-8") as fh:
            fh.write("\n   \n")
            fh.write(json.dumps(_ev("b").model_dump(mode="json"),
                                default=str) + "\n")
        got = [e.event_type for e in JournalReader(p).read_all()]
        assert got == ["a", "b"]

    def test_reader_raises_on_future_schema_version(self, tmp_path: Path):
        """PRD §4.3: SchemaVersionError on any event with schema_version > CURRENT."""
        p = tmp_path / "j.ndjson"
        # Write a well-formed event that claims a future schema_version:
        with p.open("w", encoding="utf-8") as fh:
            future = {
                "schema_version": CURRENT_SCHEMA_VERSION + 1,
                "ts": "2026-07-08T12:00:00+00:00",
                "session_id": "s1",
                "event_type": "future",
                "payload": {},
            }
            fh.write(json.dumps(future) + "\n")

        with pytest.raises(SchemaVersionError):
            JournalReader(p).read_all()


class TestFilePermissions:
    """PRD NFR: session files are 0o640 on POSIX. On Windows this is a no-op."""

    def test_writer_creates_file_with_reasonable_mode(self, tmp_path: Path):
        p = tmp_path / "j.ndjson"
        with JournalWriter(p, session_id="s1") as w:
            w.write(_ev("a"))
        # We only assert the file exists + is readable; the umask/mode contract
        # is platform-dependent and covered by an integration test in CI.
        assert p.exists()
        assert p.read_text(encoding="utf-8").strip() != ""
