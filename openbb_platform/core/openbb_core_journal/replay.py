"""replay() — reader → reconstructor pipeline.

**Scaffold stub for J1.** Full implementation + determinism golden test land
in J3 (OpenBBTechnical-2vu.3, GH #411). This stub satisfies the J1 acceptance
import contract; calling replay() before J3 raises NotImplementedError.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

from openbb_core_journal.event import JournalEvent

T = TypeVar("T")


def replay(
    journal_path: Path,
    reconstruct: Callable[[list[JournalEvent]], T],
    event_types: list[str] | None = None,
) -> T:
    """Read a journal fully and hand to the consumer's reconstructor.

    Contract from PRD §4.4:
        - deterministic event delivery (byte-identical across N calls)
        - consumer's reconstruct(events) must be pure for determinism
    """
    raise NotImplementedError(
        "replay() is a J1 scaffold stub. "
        "The reader-driven replay body + AC-8 determinism golden test land "
        "in J3 (OpenBBTechnical-2vu.3, GH #411)."
    )
