"""Unit tests for the #80 Recommendation builder (PRD §14.2 / §9.3 / §13).

Fully offline + deterministic: hand-built ``TradePlan`` fixtures, no network, no
``openbb.build()``. Every numeric expectation is pinned to the #76 / #77 "worked golden"
(entry 121.40, ATR 1.90, stop 117.60, target 129.00, qty 263 -- account 100000, risk 0.01)
so any drift in :func:`build_recommendation`'s level resolution (Q-D), the derived gaps
formula (§2.1), the action/conviction map (L2/L3), the deterministic narrative (§4), the
top-factors rank (§4.2/Q-B), the caveats precedence (§4.3/Q-C), or the Q-E E3 risk
fraction is caught here.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from openbb_core.provider.abstract.data import Data
from openbb_techtrade.engine.execution import (
    DEFAULT_REC,
    RecommendationConfig,
    build_recommendation,
)
from openbb_techtrade.models import (
    EntryExitRule,
    Fill,
    IndicatorVote,
    MoverSignal,
    Order,
    Recommendation,
    TradePlan,
)

# --- Worked-golden constants (carried verbatim from #76 / #77 tests) -----------------
_AS_OF = date(2024, 1, 12)
_ENTRY = Decimal("121.40")
_STOP_LONG = Decimal("117.60")
_TARGET_LONG = Decimal("129.00")
_STOP_SHORT = Decimal("125.20")
_TARGET_SHORT = Decimal("113.80")
_QTY = Decimal("263")
_ATR = 1.90
_ACCOUNT = Decimal("100000")


# --- Plan-builder helpers ------------------------------------------------------------


def _votes_buy() -> list[IndicatorVote]:
    """Build a vote set that fully reconciles the long-BUY plan (positive every family)."""
    return [
        IndicatorVote(family="trend", name="macd_hist", vote=1.0, weight=0.40),
        IndicatorVote(family="trend", name="ema_cross", vote=1.0, weight=0.40),
        IndicatorVote(family="momentum", name="rsi", vote=0.8, weight=0.25),
        IndicatorVote(family="momentum", name="stoch", vote=1.0, weight=0.25),
        IndicatorVote(family="volatility", name="bb_pctb", vote=0.6, weight=0.20),
        IndicatorVote(family="volume", name="obv_slope", vote=1.0, weight=0.15),
        IndicatorVote(family="volume", name="cmf", vote=1.0, weight=0.15),
    ]


def _votes_short() -> list[IndicatorVote]:
    """Mirror of :func:`_votes_buy` for the short side (sign-flipped)."""
    return [
        IndicatorVote(family="trend", name="macd_hist", vote=-1.0, weight=0.40),
        IndicatorVote(family="trend", name="ema_cross", vote=-1.0, weight=0.40),
        IndicatorVote(family="momentum", name="rsi", vote=-0.8, weight=0.25),
        IndicatorVote(family="momentum", name="stoch", vote=-1.0, weight=0.25),
        IndicatorVote(family="volatility", name="bb_pctb", vote=-0.6, weight=0.20),
        IndicatorVote(family="volume", name="obv_slope", vote=-1.0, weight=0.15),
        IndicatorVote(family="volume", name="cmf", vote=-1.0, weight=0.15),
    ]


def _signal(direction: str, *, score: float | None = None, votes: list[IndicatorVote] | None = None) -> MoverSignal:
    """Build a ``MoverSignal`` aligned to ``direction`` with optional explicit score / votes."""
    default_score = {"long": 0.72, "short": -0.72, "flat": 0.05}[direction]
    default_votes = {"long": _votes_buy(), "short": _votes_short(), "flat": []}[direction]
    return MoverSignal(
        symbol="TEST",
        segment="Information Technology",
        as_of=_AS_OF,
        score=score if score is not None else default_score,
        direction=direction,
        votes=votes if votes is not None else default_votes,
        rank_in_segment=1,
    )


def _orders(direction: str, stop: Decimal, target: Decimal, qty: Decimal = _QTY) -> list[Order]:
    """Build the #77 canonical order legs for a non-flat plan."""
    entry_side, exit_side = (
        ("buy", "sell") if direction == "long" else ("sell_short", "buy_to_cover")
    )
    return [
        Order(symbol="TEST", side=entry_side, quantity=qty, order_type="market", tif="day", intent="entry"),
        Order(symbol="TEST", side=exit_side, quantity=qty, order_type="stop", stop_price=stop, tif="gtc", intent="exit_stop"),
        Order(symbol="TEST", side=exit_side, quantity=qty, order_type="limit", limit_price=target, tif="gtc", intent="exit_target"),
        Order(symbol="TEST", side=exit_side, quantity=qty, order_type="market", tif="gtc", intent="exit_time"),
        Order(symbol="TEST", side=exit_side, quantity=qty, order_type="market", tif="gtc", intent="exit_signal"),
    ]


def _inline_recommendation(
    direction: str,
    *,
    entry: Decimal = _ENTRY,
    stop: Decimal = _STOP_LONG,
    target: Decimal = _TARGET_LONG,
    qty: Decimal = _QTY,
    score: float = 0.72,
    atr: float = _ATR,
) -> Recommendation:
    """A placeholder Recommendation carrying the planned entry + ATR -- matches #77's inline build."""
    action = {"long": "BUY", "short": "SELL_SHORT", "flat": "HOLD/FLAT"}[direction]
    conviction = "High" if abs(score) >= 0.7 else "Medium" if abs(score) >= 0.4 else "Low"
    if direction == "flat":
        return Recommendation(
            symbol="TEST", segment="Information Technology", as_of=_AS_OF,
            action=action, conviction=conviction, score=score,
            entry_price=entry, stop_price=entry, target_price=entry,
            stop_distance_pct=0.0, target_distance_pct=0.0, risk_reward=0.0, atr=atr,
            position_size=Decimal(0), risk_per_share=Decimal(0),
            risk_pct_of_notional=0.0, time_stop_bars=None,
            reasoning="HOLD/FLAT TEST: score below threshold.", caveats="",
        )
    return Recommendation(
        symbol="TEST", segment="Information Technology", as_of=_AS_OF,
        action=action, conviction=conviction, score=score,
        entry_price=entry, stop_price=stop, target_price=target,
        stop_distance_pct=0.0, target_distance_pct=0.0, risk_reward=0.0, atr=atr,
        position_size=qty, risk_per_share=abs(entry - stop),
        risk_pct_of_notional=0.0, time_stop_bars=20,
        reasoning="placeholder", caveats="",
    )


def _entry_fill(price: Decimal, *, side: str = "buy", qty: Decimal = _QTY) -> Fill:
    """Synthesize a #78-shaped entry fill at the requested price."""
    return Fill(
        order_ref="TEST:entry",
        timestamp=datetime(2024, 1, 16, 14, 30, tzinfo=timezone.utc),
        symbol="TEST",
        side=side,
        quantity=qty,
        price=price,
        commission=Decimal("0"),
        slippage=Decimal("0.05"),
    )


def _plan(
    direction: str,
    *,
    entry: Decimal = _ENTRY,
    stop: Decimal = _STOP_LONG,
    target: Decimal = _TARGET_LONG,
    fill_price: Decimal | None = _ENTRY,
    score: float | None = None,
    votes: list[IndicatorVote] | None = None,
    rule: EntryExitRule | None = None,
    validation: object | None = None,
) -> TradePlan:
    """Assemble a paper-filled-ish TradePlan for the builder to consume."""
    sig = _signal(direction, score=score, votes=votes)
    used_rule = rule or EntryExitRule()
    if direction == "flat":
        orders: list[Order] = []
        fills: list[Fill] = []
        qty = Decimal(0)
    else:
        orders = _orders(direction, stop=stop, target=target)
        fill_side = "buy" if direction == "long" else "sell_short"
        fills = [_entry_fill(fill_price, side=fill_side)] if fill_price is not None else []
        qty = _QTY
    rec = _inline_recommendation(
        direction, entry=entry, stop=stop, target=target,
        qty=qty if direction != "flat" else Decimal(0),
        score=sig.score, atr=_ATR,
    )
    return TradePlan(
        symbol="TEST",
        segment="Information Technology",
        as_of=_AS_OF,
        signal=sig,
        rule=used_rule,
        position_size=qty,
        orders=orders,
        simulated_fills=fills,
        recommendation=rec,
        validation=validation,
    )


# --- Tests (per design §5.1) ---------------------------------------------------------


def test_all_fields_populated():
    """Assert every Recommendation field is non-None and the right type (L1, L5)."""
    rec = build_recommendation(_plan("long"))
    # Identity / scalars
    assert rec.symbol == "TEST"
    assert rec.segment == "Information Technology"
    assert rec.as_of == _AS_OF
    assert rec.action == "BUY"
    assert rec.conviction == "High"
    assert isinstance(rec.score, float)
    # Money / sizing Decimals
    assert type(rec.entry_price) is Decimal
    assert type(rec.stop_price) is Decimal
    assert type(rec.target_price) is Decimal
    assert type(rec.position_size) is Decimal
    assert type(rec.risk_per_share) is Decimal
    # Ratios / pcts as float
    assert isinstance(rec.stop_distance_pct, float)
    assert isinstance(rec.target_distance_pct, float)
    assert isinstance(rec.risk_reward, float)
    assert isinstance(rec.atr, float)
    assert isinstance(rec.risk_pct_of_notional, float)
    # Time stop + narrative
    assert rec.time_stop_bars == 20
    assert isinstance(rec.reasoning, str) and rec.reasoning
    assert isinstance(rec.top_factors, list) and all(isinstance(f, str) for f in rec.top_factors)
    assert isinstance(rec.caveats, str) and rec.caveats


def test_distance_and_rr_decimal():
    """Assert §2.1 Decimal gaps + R:R reproduce the #76 worked-golden exactly (long, filled at plan)."""
    rec = build_recommendation(_plan("long", fill_price=_ENTRY))
    # stop_distance = |121.40 - 117.60| / 121.40 = 3.80 / 121.40
    assert rec.stop_distance_pct == pytest.approx(float(Decimal("3.80") / _ENTRY))
    # target_distance = |129.00 - 121.40| / 121.40 = 7.60 / 121.40
    assert rec.target_distance_pct == pytest.approx(float(Decimal("7.60") / _ENTRY))
    # risk_reward = 7.60 / 3.80 = 2.0
    assert rec.risk_reward == pytest.approx(2.0)


def test_realized_fill_drives_entry_and_drifts_rr():
    """Q-D filled-trade branch: freeze planned stop/target, report drifted R:R off realized entry."""
    realized = Decimal("121.55")  # 15c worse than planned
    rec = build_recommendation(_plan("long", fill_price=realized))
    assert rec.entry_price == realized
    assert rec.stop_price == _STOP_LONG  # frozen (not re-anchored)
    assert rec.target_price == _TARGET_LONG  # frozen
    # Drift: stop dist = 121.55 - 117.60 = 3.95; target dist = 129.00 - 121.55 = 7.45
    assert rec.risk_reward == pytest.approx(float(Decimal("7.45") / Decimal("3.95")))


def test_no_fill_fallback():
    """Q-D no-fill branch: action != FLAT but empty fills => planned entry + no-fill caveat."""
    plan = _plan("long", fill_price=None)
    rec = build_recommendation(plan)
    assert rec.action == "BUY"
    assert rec.entry_price == _ENTRY  # planned entry_ref
    assert rec.stop_price == _STOP_LONG
    assert rec.target_price == _TARGET_LONG
    assert "no paper fill" in rec.caveats.lower()


def test_action_map():
    """L2: long -> BUY, short -> SELL_SHORT, flat -> HOLD/FLAT."""
    assert build_recommendation(_plan("long")).action == "BUY"
    short_plan = _plan("short", stop=_STOP_SHORT, target=_TARGET_SHORT)
    assert build_recommendation(short_plan).action == "SELL_SHORT"
    assert build_recommendation(_plan("flat")).action == "HOLD/FLAT"


def test_conviction_buckets():
    """L3: lower-inclusive edges: 0.7 -> High; 0.4 -> Medium; 0.39 -> Low."""
    high = build_recommendation(_plan("long", score=0.70))
    assert high.conviction == "High"
    medium = build_recommendation(_plan("long", score=0.40))
    assert medium.conviction == "Medium"
    low = build_recommendation(
        _plan("long", score=0.39, votes=_votes_buy())
    )
    assert low.conviction == "Low"
    # Symmetric for shorts
    short_high = build_recommendation(_plan("short", score=-0.85, stop=_STOP_SHORT, target=_TARGET_SHORT))
    assert short_high.conviction == "High"


def test_reasoning_references_top_votes():
    """§4.3 auditability: each top_factor name appears in signal.votes AND in reasoning."""
    plan = _plan("long")
    rec = build_recommendation(plan)
    vote_names = {v.name for v in plan.signal.votes}
    # Every top_factor traces to a real vote name.
    for factor in rec.top_factors:
        name = factor.split("+")[0].split("-")[0]
        assert name in vote_names, f"top_factor {factor!r} not in votes {vote_names}"
    # And every top factor name appears in the reasoning string.
    for factor in rec.top_factors:
        name = factor.split("+")[0].split("-")[0]
        assert name in rec.reasoning, f"top_factor {name!r} missing from reasoning"


def test_top_factors_rank_and_tiebreak():
    """Q-B: rank by |weight*vote| desc, top-K=3, drop near-zero contributors."""
    rec = build_recommendation(_plan("long"))
    assert len(rec.top_factors) == 3
    # macd_hist & ema_cross both 1.0 * 0.40 = 0.40 (largest); tie-break by name (alpha) =>
    # "ema_cross" before "macd_hist".
    assert rec.top_factors[0] == "ema_cross+ (trend)"
    assert rec.top_factors[1] == "macd_hist+ (trend)"
    # Next largest: stoch (1.0 * 0.25 = 0.25)
    assert rec.top_factors[2] == "stoch+ (momentum)"


def test_top_factors_drops_near_zero_contributors():
    """Near-zero |weight*vote| (<= epsilon) is dropped (Q-B)."""
    votes = [
        IndicatorVote(family="trend", name="macd_hist", vote=1.0, weight=0.40),
        IndicatorVote(family="momentum", name="rsi", vote=0.0, weight=0.25),  # zero -> drop
        IndicatorVote(family="volume", name="obv_slope", vote=1.0, weight=0.15),
    ]
    rec = build_recommendation(_plan("long", votes=votes))
    factor_names = [f.split("+")[0].split("-")[0] for f in rec.top_factors]
    assert "rsi" not in factor_names
    assert "macd_hist" in factor_names
    assert "obv_slope" in factor_names


def test_top_k_configurable():
    """Q-B: top_k is configurable via RecommendationConfig (default 3)."""
    plan = _plan("long")
    rec = build_recommendation(plan, config=RecommendationConfig(top_k=1))
    assert len(rec.top_factors) == 1


def test_caveats_no_fill_precedence_over_borderline():
    """Q-C fixed precedence: validation -> no-fill -> volume -> split -> borderline -> missing."""
    # Filled plan with no triggers other than borderline (|score|=0.42 in [0.4, 0.5))
    borderline = _plan("long", score=0.42, votes=_votes_buy(), fill_price=_ENTRY)
    rec = build_recommendation(borderline)
    assert "borderline conviction" in rec.caveats.lower()
    # No-fill version should mention both, with no-fill BEFORE borderline
    no_fill = _plan("long", score=0.42, votes=_votes_buy(), fill_price=None)
    rec_nf = build_recommendation(no_fill)
    no_fill_idx = rec_nf.caveats.lower().index("no paper fill")
    borderline_idx = rec_nf.caveats.lower().index("borderline conviction")
    assert no_fill_idx < borderline_idx


def test_caveats_volume_divergence_trigger():
    """Q-C trigger #3: a volume vote opposing sign(score) fires."""
    votes = _votes_buy()
    # Flip one volume vote to oppose the (positive) score.
    votes = [
        v if v.name != "obv_slope" else IndicatorVote(family="volume", name="obv_slope", vote=-1.0, weight=0.15)
        for v in votes
    ]
    rec = build_recommendation(_plan("long", votes=votes))
    assert "volume diverging from price" in rec.caveats.lower()


def test_caveats_intra_family_split_trigger():
    """Q-C trigger #4: opposing signs within one family fire the family-split caveat."""
    votes = [
        IndicatorVote(family="trend", name="macd_hist", vote=1.0, weight=0.40),
        IndicatorVote(family="trend", name="ema_cross", vote=-1.0, weight=0.40),
        IndicatorVote(family="momentum", name="rsi", vote=0.8, weight=0.25),
        IndicatorVote(family="momentum", name="stoch", vote=1.0, weight=0.25),
        IndicatorVote(family="volatility", name="bb_pctb", vote=0.6, weight=0.20),
        IndicatorVote(family="volume", name="obv_slope", vote=1.0, weight=0.15),
        IndicatorVote(family="volume", name="cmf", vote=1.0, weight=0.15),
    ]
    rec = build_recommendation(_plan("long", votes=votes))
    assert "trend votes split" in rec.caveats.lower()


def test_caveats_missing_family_trigger():
    """Q-C trigger #6: a family absent from the panel fires the missing-family caveat."""
    votes = [
        v for v in _votes_buy() if v.family != "volatility"
    ]
    rec = build_recommendation(_plan("long", votes=votes))
    assert "volatility unavailable" in rec.caveats.lower()


def test_caveats_empty_is_benign_string():
    """Q-C empty case: no triggers => 'None.' (golden-stable, non-blank)."""
    rec = build_recommendation(_plan("long", score=0.85))  # decisive, no triggers, fully populated
    assert rec.caveats == "None."


def test_flat_no_fill_edge():
    """Q-D FLAT branch: HOLD/FLAT, zero-distance, qty/risk zero, no ZeroDivisionError."""
    rec = build_recommendation(_plan("flat"))
    assert rec.action == "HOLD/FLAT"
    assert rec.entry_price == rec.stop_price == rec.target_price  # zero-distance
    assert rec.stop_distance_pct == 0.0
    assert rec.target_distance_pct == 0.0
    assert rec.risk_reward == 0.0
    assert rec.position_size == Decimal(0)
    assert rec.risk_per_share == Decimal(0)
    assert rec.risk_pct_of_notional == 0.0
    assert rec.time_stop_bars is None


def test_risk_pct_of_notional_e3_formula():
    """Q-E E3: risk_pct = (position_size * risk_per_share) / account_size (fraction, not %)."""
    rec = build_recommendation(_plan("long", fill_price=_ENTRY))
    # qty 263 * risk/share 3.80 = 999.40 / 100000 = 0.009994
    expected = float(_QTY * Decimal("3.80") / _ACCOUNT)
    assert rec.risk_pct_of_notional == pytest.approx(expected)


def test_risk_pct_of_notional_uses_realized_drift():
    """Q-E E3 honestly reflects drifted risk when the realized entry shifts."""
    realized = Decimal("121.55")  # +0.15 vs planned => risk/share = 3.95
    rec = build_recommendation(_plan("long", fill_price=realized))
    expected = float(_QTY * Decimal("3.95") / _ACCOUNT)
    assert rec.risk_pct_of_notional == pytest.approx(expected)


def test_deterministic_same_plan_same_recommendation():
    """L7: identical TradePlan in => identical Recommendation out (incl. reasoning string)."""
    plan = _plan("long")
    rec_a = build_recommendation(plan)
    rec_b = build_recommendation(plan)
    assert rec_a.model_dump() == rec_b.model_dump()


def test_reasoning_carries_lead_and_levels_sentence():
    """§4.1: lead + family clauses + levels sentence for non-flat; FLAT skips the levels sentence."""
    long_rec = build_recommendation(_plan("long"))
    assert long_rec.reasoning.startswith("Long TEST: ")
    assert "Stop 2xATR below entry" in long_rec.reasoning
    assert "target at 2.0R" in long_rec.reasoning

    flat_rec = build_recommendation(_plan("flat"))
    assert flat_rec.reasoning.startswith("Hold TEST: ")
    assert "Stop" not in flat_rec.reasoning


def test_reasoning_short_uses_above_entry_wording():
    """§4.1: a short's levels sentence reads 'Stop 2xATR above entry' (sign-folded levels)."""
    rec = build_recommendation(_plan("short", stop=_STOP_SHORT, target=_TARGET_SHORT))
    assert "Stop 2xATR above entry" in rec.reasoning


def test_account_size_zero_yields_zero_risk_fraction():
    """Defensive division guard: account_size==0 => risk_pct_of_notional=0.0 (no ZeroDivisionError)."""
    rec = build_recommendation(
        _plan("long"), config=RecommendationConfig(account_size=Decimal(0))
    )
    assert rec.risk_pct_of_notional == 0.0


def test_default_config_is_top3_delta010_account100k():
    """The shipped defaults match design Q-B/Q-C/Q-E (top_k=3, delta=0.10, account=$100k)."""
    assert DEFAULT_REC.top_k == 3
    assert DEFAULT_REC.borderline_delta == 0.10
    assert DEFAULT_REC.account_size == Decimal("100000")


def test_purity_no_mutation_of_input_plan():
    """Q-F return-only: building a recommendation must not mutate the input plan."""
    plan = _plan("long")
    snapshot = plan.model_dump()
    build_recommendation(plan)
    assert plan.model_dump() == snapshot


def test_borderline_band_only_within_delta():
    """Q-C trigger #5: |score| at threshold+delta+epsilon is OUTSIDE the band (no caveat)."""
    # 0.5 == entry_threshold (0.4) + delta (0.10) => upper exclusive bound, NOT borderline.
    rec = build_recommendation(_plan("long", score=0.55, votes=_votes_buy()))
    assert "borderline" not in rec.caveats.lower()


def test_validation_failure_fires_caveat():
    """Q-C trigger #1: a duck-typed validation report with passed=False fires."""

    class _FakeValidation(Data):
        passed: bool = False
        overfit_probability: float = 0.2

    rec = build_recommendation(_plan("long", validation=_FakeValidation()))
    assert "validation flags overfitting" in rec.caveats.lower()
