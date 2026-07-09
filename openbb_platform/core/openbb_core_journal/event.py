"""JournalEvent — the base event model consumers subclass with typed payloads.

PRD §3 D2: closed base + open payload. This module owns the closed base;
consumers own the payload shapes and validation via their own subclasses.

Every event carries `schema_version: int = 1` (D5) — bumps require a
JournalReader update to accept the new version, otherwise SchemaVersionError.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from openbb_core.provider.abstract.data import Data
from pydantic import Field

# The current wire-format schema version. Bump this only when the base event
# shape changes (adding fields to `payload` doesn't count — payload is dict).
CURRENT_SCHEMA_VERSION: int = 1


class JournalEvent(Data):
    """Base event. Every journaled event inherits from this.

    Field convention (PRD §4.1):
        schema_version : int = 1        — forward-compat guard
        ts             : datetime       — tz-aware, UTC internally
        session_id     : str            — UUID or date-based scope
        event_type     : str            — dispatch key ("tick","signal","fill",...)
        payload        : dict[str, Any] — consumer-typed via subclass
    """

    schema_version: int = Field(
        default=CURRENT_SCHEMA_VERSION,
        description="Wire-format version; readers reject unknown values.",
    )
    ts: datetime = Field(description="Event timestamp (tz-aware, UTC).")
    session_id: str = Field(description="Session scope identifier.")
    event_type: str = Field(description="Dispatch key for reader filters.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Consumer-typed payload; validate via subclass overrides.",
    )
