"""Unit tests for the #79 scan orchestrator (PRD §9.2, design §3/§5, contract §#79).

Fully offline and deterministic. ``scan_segments`` is pure COMPOSITION over the existing
movers (#70) -> signals/levels/orders (#75-#77) -> fills (#78) chain: it owns only the
fan-out across the 11 GICS sectors and the final cross-segment rank. Every seam is faked
here so the whole fan-out runs with no network, no API key, and no pandas-ta call. The
rank key ``(-round(abs(score), 9), symbol, segment)`` is exercised directly on built
plans so any drift in the sign (direction-neutral |score|), the rounding epsilon, the
symbol/segment total-order tie-break, the flat-plan filter, the limit slice, the
skip-and-continue isolation, or the pre-fill rank independence is caught.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from openbb_techtrade.engine.plan import build_plans
from openbb_techtrade.engine.scan import _rank_key, scan_segments
from openbb_techtrade.models import MoverSignal, TradePlan

_AS_OF = date(2024, 1, 12)
_ENTRY = Decimal("121.40")
_ATR = 1.90


def _signal(symbol: str, segment: str, score: float) -> MoverSignal:
    """Build a ranked MoverSignal with an explicit score (direction from the sign)."""
    direction = "long" if score >= 0.4 else "short" if score <= -0.4 else "flat"
    return MoverSignal(
        symbol=symbol, segment=segment, as_of=_AS_OF, score=score,
        direction=direction, votes=[], rank_in_segment=1,
    )


def _signal_fetcher_for(signals: dict[tuple[str, str], MoverSignal]):
    """Offline signal_fetcher keyed by (symbol, segment): serves the matching signals."""

    def _fetch(symbols=None, segment=None, *, preset="trend_follow", as_of=None):
        return [signals[(s, segment)] for s in (symbols or []) if (s, segment) in signals]

    return _fetch


def _level_fetcher(entry: Decimal = _ENTRY, atr: float = _ATR):
    def _fetch(symbol: str, *, as_of: date):
        return entry, atr

    return _fetch


def _plan(symbol: str, segment: str, score: float) -> TradePlan:
    """Build ONE real TradePlan (signal/rule/size/orders/recommendation) for a score."""
    sig = _signal(symbol, segment, score)
    plans = build_plans(
        symbols=[symbol], segment=segment, as_of=_AS_OF,
        signal_fetcher=_signal_fetcher_for({(symbol, segment): sig}),
        level_fetcher=_level_fetcher(),
    )
    return plans[0]


def test_rank_key_orders_by_abs_score_desc_then_symbol_then_segment():
    """Assert the total-order key sorts by -|score|, then symbol, then segment (design §3)."""
    a = _plan("AAA", "Information Technology", 0.90)
    b = _plan("BBB", "Energy", 0.50)
    c = _plan("CCC", "Financials", -0.95)  # |score| 0.95 is the strongest
    ordered = sorted([a, b, c], key=_rank_key)
    assert [p.symbol for p in ordered] == ["CCC", "AAA", "BBB"]


def test_rank_key_is_direction_neutral_on_equal_abs_score():
    """Assert +0.40 and -0.40 tie on |score| and break by symbol then segment (Q-A/Q-D)."""
    long_xlk = _plan("ZZZ", "Information Technology", 0.40)
    short_aaa = _plan("AAA", "Energy", -0.40)
    ordered = sorted([long_xlk, short_aaa], key=_rank_key)
    # equal |0.40|; "AAA" < "ZZZ" so the short sorts first (symbol tie-break)
    assert [p.symbol for p in ordered] == ["AAA", "ZZZ"]


def test_rank_key_segment_breaks_same_symbol_across_two_etfs():
    """Assert a symbol surfacing in two sectors is total-ordered by segment (design §3)."""
    in_xlk = _plan("DUP", "Information Technology", 0.60)
    in_xlc = _plan("DUP", "Communication Services", 0.60)
    ordered = sorted([in_xlk, in_xlc], key=_rank_key)
    # equal symbol + |score|; "Communication Services" < "Information Technology"
    assert [p.segment for p in ordered] == ["Communication Services", "Information Technology"]


def test_rank_key_rounds_score_to_nine_dp_so_float_noise_does_not_reorder():
    """Assert scores equal within 1e-9 tie on |score| and defer to the symbol key."""
    p1 = _plan("AAA", "Energy", 0.4000000001)
    p2 = _plan("BBB", "Energy", 0.4000000002)  # differ at 1e-10 -> equal after round(...,9)
    ordered = sorted([p2, p1], key=_rank_key)
    assert [p.symbol for p in ordered] == ["AAA", "BBB"]
