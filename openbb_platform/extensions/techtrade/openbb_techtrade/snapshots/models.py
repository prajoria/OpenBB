"""Snapshot domain models for persisted TechTrade scans (issue #1934).

A *snapshot* is the durable, widget-ready record of one market segment's scan for
one session. It is deliberately decoupled from the rich ``TradePlan`` object graph:
the Morning Scan widgets read snapshots without importing the engine or performing
any computation, so every field here is plain JSON-safe scalar data (``str`` /
``float`` / ``int`` / ``bool`` / ``None``). ``Decimal`` money fields on the
``TradePlan`` are narrowed to ``float`` at the :func:`plan_to_row` boundary so a
reader never has to know about ``Decimal`` or the pydantic engine models.

The unit of persistence is one ``(kind, segment)`` snapshot -- append-only. A later
run that fails for a segment simply never writes, so the previous committed snapshot
remains the "last good" one a reader sees.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from openbb_techtrade.models import TradePlan

UTC = timezone.utc

#: Default snapshot ``kind`` for the daily cross-segment scan.
DEFAULT_SCAN_KIND = "daily_scan"


def _utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


def _ensure_utc(value: datetime) -> datetime:
    """Normalize an aware datetime to UTC, rejecting naive values."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("computed_at must be timezone-aware")

    return value.astimezone(UTC)


def new_snapshot_id() -> str:
    """Return a fresh, opaque snapshot identifier."""
    return uuid.uuid4().hex


def plan_to_row(plan: TradePlan) -> dict[str, Any]:
    """Flatten a ``TradePlan`` into one widget-ready, JSON-safe row.

    Every value is a plain scalar so a widget can render it and ``json.dumps`` can
    serialize it without a custom encoder. ``Decimal`` fields (prices, sizes) are
    narrowed to ``float`` here -- the single boundary where the engine's ``Decimal``
    money representation is converted, mirroring the ``compute_ohlcv_metrics``
    boundary the movers layer already uses.

    Parameters
    ----------
    plan : TradePlan
        A fully-built, actionable trade plan produced by the scan chain.

    Returns
    -------
    dict[str, Any]
        A flat JSON-safe mapping of the plan's headline signal + recommendation.
    """
    signal = plan.signal
    rec = plan.recommendation
    return {
        "symbol": plan.symbol,
        "segment": plan.segment,
        "as_of": plan.as_of.isoformat(),
        "direction": signal.direction,
        "score": float(signal.score),
        "rank_in_segment": int(signal.rank_in_segment),
        "action": rec.action,
        "conviction": rec.conviction,
        "entry_price": float(rec.entry_price),
        "stop_price": float(rec.stop_price),
        "target_price": float(rec.target_price),
        "stop_distance_pct": float(rec.stop_distance_pct),
        "target_distance_pct": float(rec.target_distance_pct),
        "risk_reward": float(rec.risk_reward),
        "atr": float(rec.atr),
        "position_size": float(plan.position_size),
        "risk_per_share": float(rec.risk_per_share),
        "risk_pct_of_notional": float(rec.risk_pct_of_notional),
        "time_stop_bars": rec.time_stop_bars,
        "reasoning": rec.reasoning,
        "top_factors": list(rec.top_factors),
        "order_count": len(plan.orders),
        "filled": bool(plan.simulated_fills),
    }


class ScanSnapshot(BaseModel):
    """An append-only, widget-ready record of one segment's scan for one session."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(default_factory=new_snapshot_id)
    kind: str = DEFAULT_SCAN_KIND
    segment: str
    as_of_session: date
    computed_at: datetime = Field(default_factory=_utc_now)
    preset: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("kind", "segment")
    @classmethod
    def _validate_non_blank(cls, value: str) -> str:
        """Reject blank ``kind`` / ``segment`` values."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")

        return normalized

    @field_validator("computed_at")
    @classmethod
    def _validate_computed_at(cls, value: datetime) -> datetime:
        """Store ``computed_at`` in UTC."""
        return _ensure_utc(value)

    @property
    def row_count(self) -> int:
        """Return the number of rows in the snapshot."""
        return len(self.rows)

    @property
    def is_empty(self) -> bool:
        """Return whether the snapshot has no rows (a fresh-but-empty scan)."""
        return not self.rows
