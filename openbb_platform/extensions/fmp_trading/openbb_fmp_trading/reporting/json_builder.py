"""Canonical JSON manifest builder for report() (P5.1).

Serializes a session's events + metrics + optional DailyPlan +
EndOfDayReport as sorted-key canonical JSON. Decimal renders as string
for precision preservation (review finding #3 — SessionMetrics has
``model_config = ConfigDict(json_encoders={Decimal: str})``).

Stability note (review S1): the output IS stable for identical inputs —
NOT because "there are no timestamps" (event ``ts`` values ARE in the
output — they come from the recorded journal) but because we (a) sort
keys deterministically and (b) NEVER call ``datetime.now()`` at render
time. If a future change adds a "generated_at" field it will break byte
stability; add a hash-based test then.
"""

from __future__ import annotations

import json
from typing import Any


def build_json_manifest(
    events: list[Any],
    metrics,
    plan,
    report,
    session_id: str,
) -> str:
    """Serialize a session's events + metrics as sorted-key canonical JSON.

    Args:
        events: Journal events (each rendered via .model_dump if pydantic).
        metrics: SessionMetrics — must have model_dump(mode='json').
        plan: DailyPlan or None.
        report: EndOfDayReport or None.
        session_id: Session identifier.

    Returns:
        A UTF-8 JSON string with sorted keys. Decimal fields render as
        strings via SessionMetrics.model_config's json_encoders.
    """
    payload = {
        "session_id": session_id,
        "metrics": metrics.model_dump(mode="json"),
        "daily_plan": plan.model_dump(mode="json") if plan is not None else None,
        "end_of_day_report": (
            report.model_dump(mode="json") if report is not None else None
        ),
        "events": [
            e.model_dump(mode="json") if hasattr(e, "model_dump") else dict(e)
            for e in events
        ],
    }
    return json.dumps(payload, sort_keys=True, default=str)


__all__ = ["build_json_manifest"]
