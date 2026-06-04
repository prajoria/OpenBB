"""Core Pydantic data models for the backtest extension.

Leaf module: no intra-package imports so every other module can depend on it
without cycles. Money fields use ``Decimal``; ratios use ``float``.

See ``docs/designs/backtest-design/02-data-models.md`` (and ``13`` for
``ComputeConfig``).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from openbb_core.provider.abstract.data import Data
from pydantic import Field, field_validator, model_validator

EngineName = Literal["vectorized", "event", "auto"]
Frequency = Literal["daily", "hourly", "minute"]
Side = Literal["buy", "sell"]
Verdict = Literal["robust", "fragile", "overfit"]
Device = Literal["auto", "cpu", "gpu"]
GpuPrecision = Literal["float64", "float32"]


class ComputeConfig(Data):
    """Device / precision selection for the compute backend (component 13)."""

    device: Device = Field(
        default="auto",
        description="Execution device: auto uses GPU when available, else CPU.",
    )
    n_jobs: int = Field(
        default=-1,
        description="CPU sweep parallelism; -1 uses all available cores.",
    )
    gpu_precision: GpuPrecision = Field(
        default="float64",
        description="GPU float precision; float64 preserves CPU parity.",
    )
    gpu_vram_headroom: float = Field(
        default=0.2,
        description="Fraction of GPU VRAM kept free when sizing on-device batches.",
    )
    host_ram_cap_gb: float | None = Field(
        default=None,
        description="Optional host-RAM cap (GB) for sweep result frames.",
    )

    @field_validator("gpu_vram_headroom")
    @classmethod
    def _headroom_range(cls, v: float) -> float:
        if not 0.0 <= v < 1.0:
            raise ValueError("gpu_vram_headroom must be in [0, 1)")
        return v


class CommissionModel(Data):
    """Commission specification (see ``engine/execution.py``)."""

    kind: Literal["per_share", "flat", "percent", "tiered"] = Field(
        default="flat", description="Commission calculation kind."
    )
    value: Decimal = Field(
        default=Decimal("0"),
        description="Per-share amount, flat amount, or percent fraction by kind.",
    )
    min_per_trade: Decimal = Field(
        default=Decimal("0"), description="Minimum commission charged per trade."
    )


class SlippageModel(Data):
    """Slippage specification (see ``engine/execution.py``)."""

    kind: Literal["fixed_bps", "volume_share", "spread"] = Field(
        default="fixed_bps", description="Slippage calculation kind."
    )
    value: Decimal = Field(
        default=Decimal("0"),
        description="Basis points or share-of-volume impact coefficient by kind.",
    )


class Bar(Data):
    """A single OHLCV bar used by execution realism (slippage/fills)."""

    symbol: str = Field(description="Instrument symbol.")
    timestamp: datetime = Field(description="Bar timestamp (tz-aware UTC).")
    open: Decimal = Field(description="Open price.")
    high: Decimal = Field(description="High price.")
    low: Decimal = Field(description="Low price.")
    close: Decimal = Field(description="Close price.")
    volume: Decimal = Field(default=Decimal("0"), description="Traded volume.")
    spread_bps: float = Field(
        default=0.0, description="Bid/ask spread in basis points (for spread slippage)."
    )


class BacktestConfig(Data):
    """Top-level backtest configuration."""

    strategy: str = Field(description="Registered strategy id or name.")
    universe: list[str] = Field(description="Symbols traded by the backtest.")
    start: date = Field(description="Backtest start date (inclusive).")
    end: date = Field(description="Backtest end date (inclusive).")
    engine: EngineName = Field(default="auto", description="Engine selection.")
    initial_cash: Decimal = Field(
        default=Decimal("100000"), description="Starting cash."
    )
    frequency: Frequency = Field(default="daily", description="Bar frequency.")
    calendar: str = Field(default="XNYS", description="Trading calendar name.")
    commission: CommissionModel = Field(default_factory=CommissionModel)
    slippage: SlippageModel = Field(default_factory=SlippageModel)
    benchmark: str | None = Field(
        default="SPY", description="Benchmark symbol for relative metrics."
    )
    seed: int = Field(default=0, description="Seed for deterministic runs.")
    compute: ComputeConfig = Field(default_factory=ComputeConfig)

    @model_validator(mode="after")
    def _check(self) -> BacktestConfig:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if not self.universe:
            raise ValueError("universe must be non-empty")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        return self


class Trade(Data):
    """A single executed trade."""

    timestamp: datetime = Field(description="Fill timestamp.")
    symbol: str = Field(description="Instrument symbol.")
    side: Side = Field(description="Trade side.")
    quantity: Decimal = Field(description="Filled quantity (absolute value).")
    price: Decimal = Field(description="Fill price including slippage.")
    commission: Decimal = Field(default=Decimal("0"), description="Commission paid.")
    slippage: Decimal = Field(
        default=Decimal("0"), description="Slippage cost component of the fill."
    )


class EquityPoint(Data):
    """One point on the equity curve."""

    date: datetime = Field(description="Timestamp of the equity observation.")
    equity: Decimal = Field(description="Total portfolio value.")
    cash: Decimal = Field(description="Uninvested cash.")
    exposure: float = Field(description="Net exposure fraction (-1..1+).")


class PositionSnapshot(Data):
    """A held position at a point in time."""

    date: datetime = Field(description="Snapshot timestamp.")
    symbol: str = Field(description="Instrument symbol.")
    quantity: Decimal = Field(description="Held quantity (signed).")
    market_value: Decimal = Field(description="Position market value.")
    weight: float = Field(description="Portfolio weight fraction.")


class PerformanceMetrics(Data):
    """Summary performance statistics."""

    cagr: float = Field(description="Compound annual growth rate.")
    sharpe: float = Field(description="Annualized Sharpe ratio.")
    sortino: float = Field(description="Annualized Sortino ratio.")
    calmar: float = Field(description="Calmar ratio (CAGR / |max drawdown|).")
    max_drawdown: float = Field(description="Maximum drawdown (negative fraction).")
    volatility: float = Field(description="Annualized volatility.")
    var_95: float = Field(description="Historical 95% Value at Risk.")
    cvar_95: float = Field(description="95% Conditional VaR (expected shortfall).")
    win_rate: float = Field(description="Fraction of winning round-trips.")
    profit_factor: float = Field(description="Gross profit / gross loss.")
    turnover: float = Field(description="Annualized portfolio turnover.")
    beta: float | None = Field(default=None, description="Beta vs benchmark.")
    alpha: float | None = Field(default=None, description="Annualized alpha.")


class BacktestResult(Data):
    """Canonical backtest output produced by every engine."""

    equity_curve: list[EquityPoint] = Field(description="Equity curve points.")
    trades: list[Trade] = Field(description="Executed trades.")
    positions: list[PositionSnapshot] = Field(description="Position snapshots.")
    metrics: PerformanceMetrics = Field(description="Performance metrics.")
    engine_used: str = Field(description="Engine that produced this result.")
    config: BacktestConfig = Field(description="Config echoed for reproducibility.")


class ValidationReport(Data):
    """Out-of-sample robustness / overfitting report (component 08)."""

    method: Literal["wfo", "cpcv"] = Field(description="Resampling method.")
    in_sample: PerformanceMetrics = Field(description="In-sample metrics.")
    out_of_sample: PerformanceMetrics = Field(description="Out-of-sample metrics.")
    pbo: float = Field(description="Probability of backtest overfitting [0,1].")
    deflated_sharpe: float = Field(description="Deflated Sharpe ratio.")
    n_trials: int = Field(description="Number of trials considered.")
    verdict: Verdict = Field(description="Robustness verdict.")

    @field_validator("pbo")
    @classmethod
    def _pbo_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("pbo must be in [0,1]")
        return v
