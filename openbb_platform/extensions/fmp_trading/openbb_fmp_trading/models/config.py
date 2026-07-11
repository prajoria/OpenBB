"""DailyConfig + RiskConfig — top-level session configuration (PRD §6.2.1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from openbb_core.provider.abstract.data import Data
from pydantic import Field


class RiskConfig(Data):
    """RiskManager gate thresholds (PRD §8.2). Immutable after commit to session."""

    max_open_positions: int = Field(
        default=5, description="G2 threshold — max concurrent open positions."
    )
    day_dd_pct: float = Field(
        default=-2.0,
        description="G3 threshold — negative pct-of-equity drawdown at which G3 fires.",
    )
    cooldown_after_stopout_min: int = Field(
        default=30, description="G4 minutes-per-symbol cooldown after a stopout."
    )
    max_positions_per_sector: int = Field(
        default=2, description="G5 per-sector open-position cap."
    )
    max_position_size_pct_equity: float = Field(
        default=10.0, description="G6 max single-position notional as % of equity."
    )
    max_notional_pct_equity: float = Field(
        default=30.0, description="G7 max total notional as % of equity."
    )
    flat_by_close_time_et: str = Field(
        default="15:50",
        description="G1 cutoff — no new opens after this ET wall-clock time.",
    )


class DailyConfig(Data):
    """Top-level session config loaded from ~/.openbb_platform/fmp_trading/today.yaml.

    Passed to obb.fmp_trading.run(); serves as the input to PreOpenAgentTurn (P3).
    """

    date: date | None = Field(default=None, description="Session date (None = today).")
    exchange: Literal["NASDAQ", "NYSE", "AMEX"] = Field(default="NASDAQ")
    starting_equity: Decimal = Field(
        default=Decimal("100000"),
        description="Session starting equity for sizing. Default $100k for paper.",
    )
    default_preset: str = Field(default="intraday_momentum")
    bandwidth_tier: Literal["premium", "ultimate"] = Field(default="premium")
    bandwidth_monthly_bytes: int = Field(
        default=50 * 1024**3,
        description="Monthly bandwidth budget (P6). Default: 50 GiB (FMP Premium).",
    )
    default_risk: RiskConfig = Field(
        default_factory=RiskConfig,
        description="Fallback risk gates when the DailyPlan doesn't override.",
    )
    agent_backend: Literal["claude", "openai", "none"] = Field(default="claude")
    agent_max_watchlist_size: int = Field(default=20)
    agent_universe_hint: list[str] | None = Field(
        default=None, description="Symbols the agent should consider (advisory only)."
    )
    default_watchlist: list[str] = Field(
        default_factory=lambda: ["SPY", "QQQ"],
        description=(
            "Last-resort fallback watchlist when neither the agent nor "
            "state_store.load_last_watchlist can provide one (P3.1 fallback "
            "path). Kept small and index-heavy by design."
        ),
    )
