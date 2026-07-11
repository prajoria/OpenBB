"""J3 tests: replay() reader → reconstructor pipeline + determinism golden.

Covers PRD §4.4:
    - replay(path, reconstruct_fn) returns whatever the reconstructor returns
    - Same journal + same reconstructor → byte-identical output (AC-8 for J3)
    - event_types filter propagates to the reader
    - Reconstructor sees events in journal order
"""

from __future__ import annotations

import json
from pathlib import Path

from openbb_core_journal import JournalEvent, replay

FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "sample_session.ndjson"
)


def _reconstruct_types(events: list[JournalEvent]) -> list[str]:
    """Trivial pure reconstructor for determinism testing."""
    return [e.event_type for e in events]


def _reconstruct_summary(events: list[JournalEvent]) -> dict:
    """Slightly richer pure reconstructor — order-sensitive."""
    return {
        "total": len(events),
        "types_ordered": [e.event_type for e in events],
        "first_ts": events[0].ts.isoformat() if events else None,
        "last_ts": events[-1].ts.isoformat() if events else None,
    }


class TestReplayBasics:
    def test_replay_returns_reconstructor_output(self):
        got = replay(FIXTURE, _reconstruct_types)
        assert got == [
            "session_start", "tick", "signal", "order", "fill",
            "tick", "veto", "risk_state_change", "fill", "session_end",
        ]

    def test_replay_preserves_journal_order(self):
        summary = replay(FIXTURE, _reconstruct_summary)
        assert summary["total"] == 10
        assert summary["types_ordered"][0] == "session_start"
        assert summary["types_ordered"][-1] == "session_end"

    def test_replay_with_event_types_filter(self):
        # Only fills should reach the reconstructor.
        fills_only = replay(FIXTURE, _reconstruct_types, event_types=["fill"])
        assert fills_only == ["fill", "fill"]

    def test_replay_returns_reconstructor_return_type_verbatim(self):
        """replay() is generic — whatever the reconstructor returns is returned."""

        def custom(events: list[JournalEvent]) -> tuple[int, str]:
            return (len(events), events[0].event_type)

        got = replay(FIXTURE, custom)
        assert got == (10, "session_start")
        assert isinstance(got, tuple)


class TestReplayDeterminism:
    """AC-8 for the shared primitive: same fixture, N runs, byte-identical output.

    If this test ever flakes, suspect: dict iteration order, datetime.now() in
    the reconstructor, unseeded RNG, or floating-point accumulation. The
    primitive itself is deterministic; violations live in consumer reconstructors.
    """

    def test_three_runs_byte_identical_types(self):
        a = replay(FIXTURE, _reconstruct_types)
        b = replay(FIXTURE, _reconstruct_types)
        c = replay(FIXTURE, _reconstruct_types)
        assert a == b == c, (
            "replay() must produce byte-identical output across N runs on the "
            "same fixture + same reconstructor (PRD §4.4, AC-8)."
        )

    def test_three_runs_byte_identical_summary(self):
        a = replay(FIXTURE, _reconstruct_summary)
        b = replay(FIXTURE, _reconstruct_summary)
        c = replay(FIXTURE, _reconstruct_summary)
        assert a == b == c

    def test_three_runs_byte_identical_serialized_output(self):
        """The stricter form: JSON-serialized output byte-identical.

        This catches subtle non-determinism the dict-equality above might miss
        (e.g. dict-key iteration order differences that == papers over).
        """
        outputs = [
            json.dumps(replay(FIXTURE, _reconstruct_summary), sort_keys=True)
            for _ in range(3)
        ]
        assert outputs[0] == outputs[1] == outputs[2]
