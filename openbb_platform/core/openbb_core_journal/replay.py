"""replay() — reader → reconstructor pipeline.

Contract (PRD §4.4):
    - Reads a journal fully in event order and hands the list to the
      consumer's reconstruct(events) callable.
    - Whatever the reconstructor returns is returned to the caller verbatim.
    - Determinism: same (journal, reconstructor) → byte-identical output
      across N calls. This function is deterministic by construction; any
      non-determinism must come from the reconstructor (documented in
      the Callable's own contract).
    - event_types= is passed through to the underlying JournalReader.stream()
      which applies the same push-down filter used by ad-hoc reader usage.

Design note:
    The reader-first pattern (list(reader.stream())) means the whole journal
    is materialized before the reconstructor runs. For sessions with 10k-50k
    events this is fine (~200 bytes/event × 50k = ~10MB). For >100k-event
    journals consider a streaming reconstructor API in v2 (PRD §11 Q2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

from openbb_core_journal.event import JournalEvent
from openbb_core_journal.reader import JournalReader

T = TypeVar("T")


def replay(
    journal_path: Path,
    reconstruct: Callable[[list[JournalEvent]], T],
    event_types: list[str] | None = None,
) -> T:
    """Reconstruct a domain object from a journal deterministically.

    Args:
        journal_path: Path to an NDJSON journal file.
        reconstruct: Pure function that takes the ordered list of events and
                     returns a consumer-defined domain object (SessionResult,
                     list[TradePlan], summary dict, etc.). MUST be pure for
                     determinism — no datetime.now(), no unseeded RNG, no
                     external state.
        event_types: Optional list of event_type strings to include. When set,
                     the reader filters at line-level (perf) — non-matching
                     events don't reach the reconstructor at all.

    Returns:
        Whatever `reconstruct` returns, verbatim.

    Raises:
        SchemaVersionError: journal contains an event with schema_version
                            greater than CURRENT_SCHEMA_VERSION.
        FileNotFoundError:  journal_path does not exist.

    Never raises for malformed lines — those are skipped + logged by the
    reader per PRD §4.3.
    """
    reader = JournalReader(Path(journal_path))
    events = list(reader.stream(event_types=event_types))
    return reconstruct(events)
