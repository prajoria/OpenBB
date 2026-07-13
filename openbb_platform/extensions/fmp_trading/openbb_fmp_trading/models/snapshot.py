"""MarketSnapshot + MoverRow — pre-open discovery models (PRD §6.2.2)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from openbb_core.provider.abstract.data import Data
from pydantic import Field


class MoverRow(Data):
    """One row in a unified gainers/losers/actives snapshot."""

    symbol: str
    type: Literal["gainer", "loser", "active"]
    name: str
    price: Decimal
    change: Decimal
    change_pct: float
    volume: int
    sector: str | None = Field(
        default=None,
        description="Populated when sector_rollup=True in market_snapshot().",
    )


class MarketSnapshot(Data):
    """Unified gainers/losers/actives with sentiment + top movers + optional rollup."""

    as_of: datetime
    movers: list[MoverRow] = Field(
        default_factory=list,
        description="Unified list across all included categories.",
    )
    sentiment_ratio: float = Field(
        description="gainer_count / max(loser_count, 1); >1 = bullish tape."
    )
    top_gainer: MoverRow | None = None
    top_loser: MoverRow | None = None
    sector_breakdown: dict[str, int] | None = Field(
        default=None,
        description="Symbol counts per sector when sector_rollup=True.",
    )
    volatile_movers: list[MoverRow] | None = Field(
        default=None,
        description="|change_pct| > volatility_threshold_pct subset.",
    )
