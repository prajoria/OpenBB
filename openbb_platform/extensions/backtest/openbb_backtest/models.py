"""Core Pydantic data models for the backtest extension.

Leaf module: no intra-package imports so every other module can depend on it
without cycles. Money fields use ``Decimal``; ratios use ``float``.

See ``docs/designs/backtest-design/02-data-models.md`` (and ``13`` for
``ComputeConfig``).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

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


class SweepPoint(Data):
    """One parameter combination's out-of-sample metrics in a sweep (component 09.2).

    The serializable, router-facing counterpart of the engine's internal
    ``(params, metrics)`` tuple: ``params`` is the combo's keyword arguments and
    ``metrics`` its :class:`PerformanceMetrics`.
    """

    params: dict[str, Any] = Field(description="Strategy keyword arguments for the combo.")
    metrics: PerformanceMetrics = Field(description="Metrics for this combo.")


class SweepResult(Data):
    """Outcome of a parameter sweep (component 09.2, ``obb.backtest.sweep``).

    The router-facing Data model: every grid combination's metrics plus the
    winning combo selected by ``rank_by`` (see the vectorized engine's
    ``select_best`` for the higher/lower-is-better direction per metric).
    """

    results: list[SweepPoint] = Field(description="Per-combo metrics across the grid.")
    best: dict[str, Any] = Field(description="Parameters of the best combo.")
    best_metrics: PerformanceMetrics = Field(description="Metrics of the best combo.")
    rank_by: str = Field(description="PerformanceMetrics field used to rank combos.")


class ReconciliationReport(Data):
    """Engine parity result (component 09.2, ``obb.backtest.reconcile``).

    The router-facing Data model mirroring the engine gate's dataclass: whether
    the candidate engine's equity curve matched the reference within
    ``tolerance``, and the largest point-for-point equity divergence observed.
    """

    passed: bool = Field(description="Whether divergence stayed within tolerance.")
    max_divergence: float = Field(description="Largest absolute equity divergence.")
    tolerance: float = Field(description="Tolerance applied to the comparison.")
    reference_engine: str = Field(description="Source-of-truth engine name.")
    candidate_engine: str = Field(description="Engine under test name.")


class FactorExposure(Data):
    """One ``(date, asset)`` row of cross-sectional factor values (component 09.3).

    The serializable, router-facing counterpart of a single ``FactorPanel`` grid
    cell: ``values`` maps each factor name to its value for this asset on this
    session (``NaN`` when history was insufficient — never a look-ahead fill).
    """

    date: datetime = Field(description="Session timestamp of the exposure.")
    asset: str = Field(description="Instrument symbol.")
    values: dict[str, float] = Field(description="Factor name -> value for this row.")


class FactorPanel(Data):
    """Cross-sectional factor panel (component 09.3, ``obb.backtest.pipeline``).

    The router-facing Data model: a flattened, serializable view of the pipeline's
    internal ``(date, asset)`` MultiIndex panel. ``factors`` lists the factor
    columns in panel order; ``records`` is the full per-session grid of
    :class:`FactorExposure` rows.
    """

    factors: list[str] = Field(description="Factor column names, in panel order.")
    records: list[FactorExposure] = Field(
        description="Per-(date, asset) factor exposures across the grid."
    )


class FactorReport(Data):
    """Alphalens-style factor diagnostics (component 09.3, ``obb.backtest.factor_eval``).

    The router-facing Data model summarizing a factor's predictive power: the
    information coefficient (IC) mean / std / information-ratio per forward
    period, plus mean returns by factor quantile. All values are normalized
    floats keyed by string labels so the model serializes cleanly to JSON.
    """

    factor: str = Field(description="Evaluated factor name.")
    periods: list[int] = Field(description="Forward return periods analysed (sessions).")
    quantiles: int = Field(description="Number of factor quantiles formed.")
    ic_mean: dict[str, float] = Field(description="Mean IC per forward period.")
    ic_std: dict[str, float] = Field(description="IC standard deviation per period.")
    ic_ir: dict[str, float] = Field(
        description="IC information ratio (mean / std) per period."
    )
    quantile_returns: dict[str, float] = Field(
        description="Mean forward return per factor quantile label."
    )


class FoldResult(Data):
    """One resampling fold's out-of-sample result (component 08, §3).

    Carries the fold's index and its out-of-sample
    :class:`PerformanceMetrics`; ``path_id`` labels the recombined CPCV backtest
    path (``None`` for plain walk-forward folds).
    """

    fold: int = Field(description="Zero-based fold index.")
    metrics: PerformanceMetrics = Field(description="Out-of-sample fold metrics.")
    path_id: int | None = Field(
        default=None, description="CPCV backtest-path label, if applicable."
    )


class ValidationReport(Data):
    """Out-of-sample robustness / overfitting report (component 08, §3).

    Aligns to ``docs/designs/backtest-design/08-validation.md`` §3: each fold runs
    through the normal engine + analytics path, so ``oos_metrics`` reuses
    component 07. ``thresholds`` records the effective verdict cut-offs verbatim so
    the ``verdict`` is auditable.
    """

    method: Literal["wfo", "cpcv"] = Field(description="Resampling method.")
    folds: list[FoldResult] = Field(description="Per-fold out-of-sample results.")
    oos_metrics: PerformanceMetrics = Field(
        description="Aggregated out-of-sample metrics."
    )
    pbo: float = Field(description="Probability of backtest overfitting [0,1].")
    deflated_sharpe: float = Field(description="Deflated Sharpe ratio.")
    min_backtest_length_years: float = Field(
        description="Minimum backtest length (years) to trust the target Sharpe."
    )
    verdict: Verdict = Field(description="Robustness verdict.")
    thresholds: dict[str, float] = Field(
        description="Effective verdict thresholds, recorded for auditability."
    )

    @field_validator("pbo")
    @classmethod
    def _pbo_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("pbo must be in [0,1]")
        return v


class DrawdownPeriod(Data):
    """A single peak-to-recovery drawdown episode (component 07 tear sheet).

    Normalized: ``depth`` is a fraction (negative), not a dollar amount.
    """

    start: date = Field(description="Date of the prior equity peak.")
    valley: date = Field(description="Date of the drawdown trough.")
    end: date = Field(description="Recovery date (peak regained).")
    depth: float = Field(description="Maximum drawdown depth (negative fraction).")
    length: int = Field(description="Duration in sessions from peak to recovery.")


class MonthlyReturn(Data):
    """One month's total return (normalized fraction), for the returns heatmap."""

    year: int = Field(description="Calendar year.")
    month: int = Field(description="Calendar month (1-12).")
    ret: float = Field(description="Month total return (fraction).")


class BenchmarkStats(Data):
    """Benchmark-relative statistics (component 07, §2).

    All normalized floats — alpha is annualized, beta is unitless, information
    ratio is annualized active-return / tracking-error.
    """

    alpha: float = Field(description="Annualized alpha vs benchmark.")
    beta: float = Field(description="Beta vs benchmark.")
    information_ratio: float = Field(
        description="Annualized active return / tracking error."
    )


class TearSheet(Data):
    """Structured institutional tear sheet (component 07, §2).

    Carries only normalized analytics — never dollar amounts, account numbers or
    lot detail (fork privacy rule). ``html_path`` holds the saved artifact path
    only (the large HTML/PNG blob lives on disk, not in the model).
    """

    metrics: PerformanceMetrics = Field(description="Summary performance metrics.")
    rolling_sharpe: list[float] = Field(
        description="Rolling Sharpe ratio series (normalized)."
    )
    drawdown_periods: list[DrawdownPeriod] = Field(
        description="Ranked drawdown episodes."
    )
    monthly_returns: list[MonthlyReturn] = Field(
        description="Per-month total returns."
    )
    html_path: str | None = Field(
        default=None, description="Path to the saved HTML artifact, if exported."
    )
    benchmark_relative: BenchmarkStats | None = Field(
        default=None, description="Benchmark-relative stats, if a benchmark was given."
    )


class BundleInfo(Data):
    """Public descriptor for a persisted data bundle (component 03 / 09.5).

    The serializable face of :class:`~openbb_backtest.data.bundle.BundleMetadata`:
    it mirrors only the descriptive fields written to ``metadata.json`` (never the
    parquet payload or any internal ``extra`` bag), so ``obb.backtest.bundle.*``
    can report what was ingested without exposing the on-disk store layout.
    """

    name: str = Field(description="Bundle name (the store sub-directory).")
    symbols: list[str] = Field(description="Symbols ingested into the bundle.")
    calendar: str = Field(description="Trading calendar code (e.g. XNYS).")
    start: str | None = Field(
        default=None, description="First session date (ISO), if known."
    )
    end: str | None = Field(
        default=None, description="Last session date (ISO), if known."
    )
    ingested_at: str | None = Field(
        default=None, description="UTC ingest timestamp (ISO), if known."
    )
    has_fundamentals: bool = Field(
        default=False, description="Whether point-in-time fundamentals were ingested."
    )
