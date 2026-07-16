"""Core Pydantic Data models for techtrade (PRD §9.3).

Leaf module: no intra-package imports and no openbb_backtest import, so every
other techtrade module can depend on it without cycles and techtrade stays
installable without the backtest extension. Money/quantity fields use Decimal;
scores, ratios, and percentages use float.

The full pipeline contract: SegmentConfig -> MoverList -> IndicatorPanel ->
IndicatorVote/MoverSignal -> EntryExitRule/Order/Fill -> TradePlan ->
Recommendation, plus ExportConfig.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from pydantic import Field


class Mover(Data):
    """A single ranked top-mover within a segment (a row of a MoverList)."""

    symbol: str = Field(description="Instrument symbol.")
    pct_change: float = Field(
        description=(
            "Percent change over the ranking window, as a HUMAN PERCENT "
            "(1.38 means +1.38%, NOT 0.0138). This differs from "
            "openbb_core.provider.standard_models.equity_performance."
            "EquityPerformanceData.percent_change which is a fraction. "
            "The conversion happens at the compute_ohlcv_metrics boundary "
            "(bd-lw3 fix, Option B2) so downstream display code is "
            "trivially correct: f'{m.pct_change:+.2f}%'."
        ),
    )
    volume: Decimal = Field(description="Share volume over the ranking window.")
    rank: int = Field(description="One-based rank of the mover within its segment.")


class SegmentConfig(Data):
    """Configuration for resolving and ranking a single market segment."""

    segment: str = Field(description="Segment name (e.g. a GICS sector).")
    universe_source: Literal["etf_holdings", "constituent_list", "screener"] = Field(
        default="etf_holdings",
        description="How the segment universe is resolved.",
    )
    benchmark_etf: str | None = Field(
        default=None,
        description="Benchmark ETF for the segment (e.g. for etf_holdings).",
    )
    rank_metric: Literal["pct_change", "volume", "gap", "rel_volume"] = Field(
        default="pct_change",
        description="Metric used to rank movers within the segment.",
    )
    top_n: int = Field(
        default=10,
        description="Number of top movers to keep per segment.",
    )


class MoverList(Data):
    """The ranked top movers resolved for one segment on a given date."""

    segment: str = Field(description="Segment name the movers belong to.")
    as_of: date = Field(description="Session date the ranking was computed for.")
    movers: list[Mover] = Field(description="Ranked movers, best first.")


class IndicatorPanel(Data):
    """Per-symbol technical-indicator outputs grouped by family (PRD §9.3)."""

    symbol: str = Field(description="Instrument symbol.")
    as_of: date = Field(description="Session date the indicators were computed for.")
    trend: dict[str, float] = Field(
        default_factory=dict, description="Trend indicator name -> value."
    )
    momentum: dict[str, float] = Field(
        default_factory=dict, description="Momentum indicator name -> value."
    )
    volatility: dict[str, float] = Field(
        default_factory=dict, description="Volatility indicator name -> value."
    )
    volume: dict[str, float] = Field(
        default_factory=dict, description="Volume indicator name -> value."
    )
    candles: dict[str, int] = Field(
        default_factory=dict, description="Candlestick pattern name -> signal (-1/0/1)."
    )


class IndicatorVote(Data):
    """One indicator's weighted directional vote in the confluence model."""

    family: Literal["trend", "momentum", "volatility", "volume"] = Field(
        description="Indicator family the vote comes from."
    )
    name: str = Field(description="Indicator name (e.g. ema_cross, rsi).")
    vote: float = Field(description="Directional vote in [-1, +1].")
    weight: float = Field(description="Weight applied to the vote in the composite.")


class MoverSignal(Data):
    """A symbol's composite confluence signal within a segment (PRD §9.3)."""

    symbol: str = Field(description="Instrument symbol.")
    segment: str = Field(description="Segment the symbol was ranked in.")
    as_of: date = Field(description="Session date the signal was computed for.")
    score: float = Field(description="Composite confluence score in [-1, +1].")
    direction: Literal["long", "short", "flat"] = Field(
        description="Resolved trade direction from the composite score."
    )
    votes: list[IndicatorVote] = Field(
        default_factory=list, description="Per-indicator votes feeding the composite."
    )
    rank_in_segment: int = Field(
        description="One-based rank of the signal within its segment."
    )


class EntryExitRule(Data):
    """Threshold / stop / target rules that turn a signal into a trade plan."""

    entry_threshold: float = Field(
        default=0.4, description="Minimum |score| required to open a position."
    )
    exit_on_opposite: bool = Field(
        default=True, description="Exit when the composite flips to the opposite side."
    )
    atr_stop_mult: float = Field(
        default=2.0, description="Stop distance as a multiple of ATR."
    )
    target_r_multiple: float = Field(
        default=2.0, description="Profit target as an R multiple of initial risk."
    )
    max_holding_bars: int | None = Field(
        default=20, description="Time stop in bars (None disables the time stop)."
    )


class Order(Data):
    """A single order generated for a trade plan (entry or exit leg)."""

    symbol: str = Field(description="Instrument symbol.")
    side: Literal["buy", "sell", "sell_short", "buy_to_cover"] = Field(
        description="Order side."
    )
    quantity: Decimal = Field(description="Order quantity in shares.")
    order_type: Literal["market", "limit", "stop"] = Field(
        default="market", description="Order type."
    )
    limit_price: Decimal | None = Field(
        default=None, description="Limit price for limit orders."
    )
    stop_price: Decimal | None = Field(
        default=None, description="Stop price for stop orders."
    )
    tif: Literal["day", "gtc"] = Field(default="day", description="Time in force.")
    intent: Literal["entry", "exit_stop", "exit_target", "exit_time", "exit_signal"] = (
        Field(description="Why the order exists in the plan.")
    )


class Fill(Data):
    """A simulated paper fill for an order (produced by the paper broker)."""

    order_ref: str = Field(description="Reference to the order that was filled.")
    timestamp: datetime = Field(description="Fill timestamp (tz-aware).")
    symbol: str = Field(description="Instrument symbol.")
    side: str = Field(description="Order side that was filled.")
    quantity: Decimal = Field(description="Filled quantity in shares.")
    price: Decimal = Field(description="Fill price including slippage.")
    commission: Decimal = Field(description="Commission charged on the fill.")
    slippage: Decimal = Field(description="Slippage cost component of the fill.")


class Recommendation(Data):
    """The full, human-facing trade call derived from a paper-filled TradePlan.

    This is the row-level record that becomes one line of the Excel export (§14.3).
    """

    symbol: str = Field(description="Instrument symbol.")
    segment: str = Field(description="Segment the symbol was ranked in.")
    as_of: date = Field(description="Session date the call was produced for.")
    action: Literal["BUY", "SELL_SHORT", "HOLD/FLAT"] = Field(
        description="Recommended action."
    )
    conviction: Literal["High", "Medium", "Low"] = Field(
        description="Conviction bucket derived from the composite score."
    )
    score: float = Field(description="Composite confluence score in [-1, +1].")
    entry_price: Decimal = Field(description="Planned entry price.")
    stop_price: Decimal = Field(description="Planned stop price.")
    target_price: Decimal = Field(description="Planned profit target price.")
    stop_distance_pct: float = Field(
        description="Stop distance from entry as a percent."
    )
    target_distance_pct: float = Field(
        description="Target distance from entry as a percent."
    )
    risk_reward: float = Field(description="Reward-to-risk ratio (target R multiple).")
    atr: float = Field(description="ATR used for stop / target sizing.")
    position_size: Decimal = Field(description="Position size in shares.")
    risk_per_share: Decimal = Field(description="Risk per share (entry to stop).")
    risk_pct_of_notional: float = Field(
        description="Position risk as a percent of notional."
    )
    time_stop_bars: int | None = Field(
        description="Time stop in bars (None disables the time stop)."
    )
    reasoning: str = Field(description="Deterministic narrative for the call.")
    top_factors: list[str] = Field(
        default_factory=list, description="Top contributing factors, ranked."
    )
    caveats: str = Field(description="Caveats / risk notes for the call.")


class TradePlan(Data):
    """A symbol's end-to-end plan: signal, rules, sizing, orders, fills, and call."""

    symbol: str = Field(description="Instrument symbol.")
    segment: str = Field(description="Segment the symbol was ranked in.")
    as_of: date = Field(description="Session date the plan was produced for.")
    signal: MoverSignal = Field(description="The composite signal driving the plan.")
    rule: EntryExitRule = Field(description="Entry / exit rules applied to the signal.")
    position_size: Decimal = Field(description="Position size in shares.")
    orders: list[Order] = Field(
        default_factory=list, description="Orders generated for the plan."
    )
    simulated_fills: list[Fill] = Field(
        default_factory=list, description="Paper fills simulated for the orders."
    )
    recommendation: Recommendation = Field(
        description="Human-facing call derived from the plan."
    )
    validation: Data | None = Field(
        default=None,
        description=(
            "Robustness report attached by obb.techtrade.validate (#82); carries an "
            "openbb_backtest.models.ValidationReport (a Data subclass) when populated. "
            "Typed as Data to keep techtrade installable without openbb-backtest."
        ),
    )


class TuningReport(Data):
    """Outcome of one ``obb.techtrade.tune(segment)`` call (PRD §12.4, issue #83).

    Carries the candidate ``IndicatorConfig`` tuneta proposed (always -- even when
    not persisted), the ``ValidationReport`` from #82's gate (typed as ``Data |
    None`` so this model stays leaf -- same L2 trick TradePlan.validation uses),
    and the ``persisted`` flag that records whether the candidate cleared the
    L2-strict ``verdict == "robust"`` gate and was written to
    ``~/.openbb_platform/techtrade_tuned.json``.

    Fragile / overfit candidates come back with ``persisted=False`` and a
    diagnostic ``reason`` so the caller can see *what* was proposed and *why* it
    was rejected (Q-F transparency-without-persistence posture).
    """

    segment: str = Field(description="GICS sector name the tune ran for.")
    as_of: date = Field(description="Session date the tune was anchored to.")
    candidate: Any = Field(
        description=(
            "The IndicatorConfig tuneta proposed (8 tuned period knobs + 7 "
            "PRD-default knobs). Always populated, even when not persisted. "
            "Carries an ``IndicatorConfig`` when populated; typed as ``Any`` so "
            "models.py stays a leaf module (no engine import). Same spirit as the "
            "``TradePlan.validation: Data | None`` trick that keeps techtrade "
            "installable without openbb-backtest -- the engine-layer dataclass "
            "is not a Pydantic ``Data`` subclass, so ``Any`` is the loosest "
            "annotation that lets Pydantic accept the dataclass instance."
        )
    )
    validation: Data | None = Field(
        default=None,
        description=(
            "ValidationReport from #82's validate_plan gate. Typed as Data to "
            "keep techtrade installable without openbb-backtest (same Data|None "
            "discipline as TradePlan.validation)."
        ),
    )
    persisted: bool = Field(
        description="True iff verdict == 'robust' AND a genuinely-different "
        "config was written to ~/.openbb_platform/techtrade_tuned.json."
    )
    reason: str = Field(
        description="Human-readable outcome: 'verdict=robust', "
        "'verdict=fragile (pbo=0.31, dsr=0.62)', 'no change from defaults', etc. "
        "Field order/precision is stable across runs for byte-stability."
    )
    tuneta_version: str = Field(description="tuneta.__version__ at fit time.")
    fit_seconds: float = Field(description="Wall-clock the tuneta.fit() took.")
    trials: int = Field(description="Optuna trials budget actually used.")
    early_stop: int = Field(
        description="Optuna early-stop budget (non-improving trials before halt)."
    )


class ExportConfig(Data):
    """Configuration for the Excel export of recommendations (PRD §14.3)."""

    path: str | None = Field(default=None, description="Output workbook path.")
    engine: Literal["openpyxl", "xlsxwriter"] = Field(
        default="openpyxl", description="Excel writer engine."
    )
    include_sheets: list[str] = Field(
        default_factory=lambda: [
            "Recommendations",
            "Levels",
            "Reasoning",
            "Orders",
            "Fills",
            "Summary",
        ],
        description="Sheets to include in the exported workbook.",
    )
    conditional_formatting: bool = Field(
        default=True, description="Apply conditional formatting to the workbook."
    )
