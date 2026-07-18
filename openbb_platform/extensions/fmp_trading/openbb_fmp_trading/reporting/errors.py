"""Reporting-layer exceptions (P5.3)."""

from __future__ import annotations

# Re-export ``OutputPathEscapesJail`` from ``.report`` so callers can
# import it from a single canonical location (``.errors``) rather than
# having to know it lives in ``.report``. Test suites already expect
# the ``.errors`` path (see test_report_toctou_hardening.py line 441).
# #868.
from .report import OutputPathEscapesJail  # noqa: F401  (re-exported)


class ReplayDivergenceError(Exception):
    """Raised when :func:`replay` produced an event that differs from
    the recorded event at the same tick position.

    Attributes carry actionable debug context so the operator can
    reproduce the failing tick in isolation:

      * ``tick_index``: 0-based index of the diverging tick in the range
        being replayed (post ``from_tick`` / ``to_tick`` slicing).
      * ``event_type``: which event type diverged (e.g. 'fill', 'veto').
      * ``field``: which payload field or structural attribute disagrees
        (``event_type_sequence`` for a type-mismatch at the top level,
        ``payload.<key>`` for a per-field mismatch).
      * ``expected``: value from the recorded journal.
      * ``actual``: value from the replayed run.
    """

    def __init__(
        self,
        tick_index: int,
        event_type: str,
        field: str,
        expected,
        actual,
    ):
        self.tick_index = tick_index
        self.event_type = event_type
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"replay divergence at tick {tick_index} "
            f"({event_type}.{field}): expected={expected!r}, actual={actual!r}"
        )


__all__ = ["OutputPathEscapesJail", "ReplayDivergenceError"]
