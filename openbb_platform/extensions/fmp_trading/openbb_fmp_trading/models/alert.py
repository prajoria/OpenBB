"""Alert models (PRD §6.2.4) — discriminated-union AlertSpec + runtime Alert/AlertEvent.

The AlertSpec discriminated union is Pydantic v2's canonical pattern for
tagged-variant validation. Each concrete spec sets its `kind` Literal as its
tag; the AlertSpec type alias uses Field(discriminator="kind") so pydantic
dispatches to the correct concrete class at deserialization.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from openbb_core.provider.abstract.data import Data
from pydantic import Field


class PriceThresholdSpec(Data):
    """Fires when the symbol's price crosses `price` in the specified direction."""

    kind: Literal["price_threshold"] = "price_threshold"
    symbol: str
    crosses: Literal["up", "down"]
    price: Decimal


class PercentChangeSpec(Data):
    """Fires when |change_pct| >= threshold_pct within the given window."""

    kind: Literal["percent_change"] = "percent_change"
    symbol: str
    threshold_pct: float
    window: Literal["session", "1h", "5m"]


class VolumeSpikeSpec(Data):
    """Fires when the current bar's volume >= ratio_vs_avg × trailing average."""

    kind: Literal["volume_spike"] = "volume_spike"
    symbol: str
    ratio_vs_avg: float
    avg_window: int = Field(default=20, description="Bars used for the trailing average.")


AlertSpec = Annotated[
    PriceThresholdSpec | PercentChangeSpec | VolumeSpikeSpec,
    Field(discriminator="kind"),
]


class Alert(Data):
    """Runtime alert instance — an AlertSpec + registration metadata."""

    id: str = Field(description="UUID assigned at create().")
    spec: AlertSpec
    created_at: datetime
    is_active: bool = True
    fired_count: int = 0
    session_id: str | None = Field(
        default=None,
        description="None until bound to a session by AlertManager.bind_session().",
    )


class AlertEvent(Data):
    """One firing of an Alert. Emitted to journal + optional agent-context sink."""

    alert_id: str
    ts: datetime
    symbol: str
    condition: str = Field(description="Human-readable rule text (e.g. 'price > 180').")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Tick snapshot at fire time (price, volume, etc.).",
    )
