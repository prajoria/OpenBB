"""Unit tests for the core techtrade Data models (PRD §9.3, issue #66)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from openbb_core.provider.abstract.data import Data
from openbb_techtrade.models import (
    EntryExitRule,
    ExportConfig,
    Fill,
    IndicatorPanel,
    IndicatorVote,
    Mover,
    MoverList,
    MoverSignal,
    Order,
    Recommendation,
    SegmentConfig,
    TradePlan,
)
from pydantic import ValidationError


def _signal() -> MoverSignal:
    return MoverSignal(
        symbol="MSFT",
        segment="Information Technology",
        as_of=date(2026, 6, 13),
        score=0.62,
        direction="long",
        votes=[
            IndicatorVote(family="trend", name="ema_cross", vote=1.0, weight=0.35),
            IndicatorVote(family="momentum", name="rsi", vote=0.4, weight=0.25),
        ],
        rank_in_segment=1,
    )


def _recommendation() -> Recommendation:
    return Recommendation(
        symbol="MSFT",
        segment="Information Technology",
        as_of=date(2026, 6, 13),
        action="BUY",
        conviction="High",
        score=0.62,
        entry_price=Decimal("150.25"),
        stop_price=Decimal("144.00"),
        target_price=Decimal("162.75"),
        stop_distance_pct=4.16,
        target_distance_pct=8.32,
        risk_reward=2.0,
        atr=3.12,
        position_size=Decimal("100"),
        risk_per_share=Decimal("6.25"),
        risk_pct_of_notional=0.42,
        time_stop_bars=20,
        reasoning="EMA cross up with RSI confirmation; top-ranked mover in segment.",
        top_factors=["ema_cross", "rsi", "rel_volume"],
        caveats="Elevated ATR; size kept to 1% notional risk.",
    )


def _trade_plan() -> TradePlan:
    return TradePlan(
        symbol="MSFT",
        segment="Information Technology",
        as_of=date(2026, 6, 13),
        signal=_signal(),
        rule=EntryExitRule(),
        position_size=Decimal("100"),
        orders=[
            Order(
                symbol="MSFT",
                side="buy",
                quantity=Decimal("100"),
                order_type="limit",
                limit_price=Decimal("150.25"),
                intent="entry",
            ),
            Order(
                symbol="MSFT",
                side="sell",
                quantity=Decimal("100"),
                order_type="stop",
                stop_price=Decimal("144.00"),
                intent="exit_stop",
            ),
        ],
        simulated_fills=[
            Fill(
                order_ref="entry-1",
                timestamp=datetime(2026, 6, 13, 14, 30, tzinfo=timezone.utc),
                symbol="MSFT",
                side="buy",
                quantity=Decimal("100"),
                price=Decimal("150.30"),
                commission=Decimal("1.00"),
                slippage=Decimal("0.05"),
            )
        ],
        recommendation=_recommendation(),
    )


def test_all_models_construct_with_realistic_values():
    mover = Mover(symbol="MSFT", pct_change=3.21, volume=Decimal("31250000"), rank=1)
    assert mover.rank == 1
    assert isinstance(mover.volume, Decimal)

    seg = SegmentConfig(segment="Information Technology")
    assert seg.universe_source == "etf_holdings"
    assert seg.rank_metric == "pct_change"
    assert seg.top_n == 10
    assert seg.benchmark_etf is None

    mlist = MoverList(segment="Information Technology", as_of=date(2026, 6, 13), movers=[mover])
    assert mlist.movers[0].symbol == "MSFT"

    panel = IndicatorPanel(symbol="MSFT", as_of=date(2026, 6, 13))
    assert panel.trend == {} and panel.candles == {}
    panel_full = IndicatorPanel(
        symbol="MSFT",
        as_of=date(2026, 6, 13),
        trend={"ema_20": 149.5},
        momentum={"rsi_14": 58.2},
        volatility={"atr_14": 3.12},
        volume={"obv": 1.0e7},
        candles={"engulfing": 1},
    )
    assert panel_full.candles["engulfing"] == 1

    vote = IndicatorVote(family="trend", name="ema_cross", vote=1.0, weight=0.35)
    assert -1.0 <= vote.vote <= 1.0

    sig = _signal()
    assert sig.direction == "long"
    assert len(sig.votes) == 2

    rule = EntryExitRule()
    assert rule.entry_threshold == 0.4
    assert rule.exit_on_opposite is True
    assert rule.max_holding_bars == 20

    order = Order(symbol="MSFT", side="buy", quantity=Decimal("100"), intent="entry")
    assert order.order_type == "market"
    assert order.tif == "day"

    fill = Fill(
        order_ref="entry-1",
        timestamp=datetime(2026, 6, 13, 14, 30, tzinfo=timezone.utc),
        symbol="MSFT",
        side="buy",
        quantity=Decimal("100"),
        price=Decimal("150.30"),
        commission=Decimal("1.00"),
        slippage=Decimal("0.05"),
    )
    assert fill.order_ref == "entry-1"

    rec = _recommendation()
    assert rec.action == "BUY"
    assert rec.conviction == "High"

    plan = _trade_plan()
    assert plan.symbol == "MSFT"

    export = ExportConfig()
    assert export.conditional_formatting is True


def test_tradeplan_nesting_and_validation_defaults_none():
    plan = _trade_plan()
    # Deep nesting is preserved.
    assert plan.signal.votes[0].name == "ema_cross"
    assert plan.rule.atr_stop_mult == 2.0
    assert plan.orders[0].intent == "entry"
    assert plan.orders[1].intent == "exit_stop"
    assert plan.simulated_fills[0].price == Decimal("150.30")
    assert plan.recommendation.action == "BUY"
    # The decoupled validation slot is empty until #82 attaches a ValidationReport.
    assert plan.validation is None
    # When populated, it accepts any Data subclass (no openbb_backtest import here).
    populated = _trade_plan()
    populated.validation = Data(verdict="robust", pbo=0.1)
    assert isinstance(populated.validation, Data)


def test_decimal_preservation_and_roundtrips():
    plan = _trade_plan()

    # Money / quantity fields are Decimal, and strings coerce to Decimal.
    assert isinstance(plan.orders[0].quantity, Decimal)
    assert isinstance(Order(symbol="MSFT", side="buy", quantity="100", intent="entry").quantity, Decimal)
    assert isinstance(plan.position_size, Decimal)
    assert isinstance(plan.recommendation.entry_price, Decimal)

    # Python round-trip equivalence.
    assert TradePlan.model_validate(plan.model_dump()) == plan

    # JSON round-trip equivalence, with Decimal money fields preserved.
    restored = TradePlan.model_validate_json(plan.model_dump_json())
    assert restored == plan
    assert isinstance(restored.position_size, Decimal)
    assert isinstance(restored.orders[0].quantity, Decimal)
    assert isinstance(restored.simulated_fills[0].price, Decimal)
    assert isinstance(restored.recommendation.entry_price, Decimal)


def test_literal_enforcement_and_exportconfig_defaults():
    # An out-of-set Literal value is rejected.
    with pytest.raises(ValidationError):
        Order(symbol="MSFT", side="invalid", quantity=Decimal("100"), intent="entry")
    with pytest.raises(ValidationError):
        SegmentConfig(segment="IT", rank_metric="not_a_metric")

    # ExportConfig ships the §14.3 sheet list and the openpyxl engine by default.
    cfg = ExportConfig()
    assert cfg.include_sheets == ["Recommendations", "Levels", "Reasoning", "Orders", "Fills", "Summary"]
    assert cfg.engine == "openpyxl"
    assert cfg.path is None


def test_tuning_report_construction_with_realistic_values():
    """TuningReport carries everything obb.techtrade.tune returns (#83 L3, §4.2)."""
    from openbb_techtrade.models import TuningReport
    from openbb_techtrade.engine.indicators import DEFAULT_CONFIG, IndicatorConfig

    report = TuningReport(
        segment="Information Technology",
        as_of=date(2026, 6, 21),
        candidate=DEFAULT_CONFIG,
        validation=None,
        persisted=False,
        reason="verdict=fragile (pbo=0.31, dsr=0.62)",
        tuneta_version="0.2.3",
        fit_seconds=42.7,
        trials=100,
        early_stop=20,
    )
    assert report.segment == "Information Technology"
    assert report.persisted is False
    assert report.validation is None  # the Data|None field (mirrors TradePlan.validation L2-of-82)
    # candidate must be exactly an IndicatorConfig; field is typed loosely in the model
    # layer to keep models.py a leaf module (see TuningReport docstring), so we assert
    # via isinstance rather than via static attribute access.
    assert isinstance(report.candidate, IndicatorConfig)
    # Structural-attribute check: confirm the dataclass instance round-trips intact
    # through the Any-typed field (per the brief's original assertion shape).
    assert report.candidate.macd_fast == DEFAULT_CONFIG.macd_fast == 12
    # Round-trip through dict (the OBBject pathway uses model_dump under the hood):
    assert report.model_dump()["reason"].startswith("verdict=")
