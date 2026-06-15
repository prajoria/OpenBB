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


def _candidate_fetcher(*rows: dict):
    """Offline candidate_fetcher (segment-blind): returns the same movers for every sector."""

    def _fetch(as_of=None, calendar="XNYS", needs_ohlcv=False, **kwargs):
        return [dict(r) for r in rows]

    return _fetch


def _bar(open_, high, low, close):
    return {
        "open": Decimal(open_), "high": Decimal(high), "low": Decimal(low),
        "close": Decimal(close), "volume": Decimal("1000000"),
        "timestamp": "2024-01-16T21:00:00+00:00",
    }


# Two movers fetched for EVERY sector (the fetcher is segment-blind), with per-(symbol,segment)
# scores so the same symbol gets a deterministic score in each sector it surfaces in.
def _all_signals(score_aaa: float, score_bbb: float) -> dict:
    from openbb_techtrade.engine.movers import list_movers as _lm  # local import: avoid top cycle
    segments = [ml.segment for ml in _lm(
        segment=None, candidate_fetcher=_candidate_fetcher(
            {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
            {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
        ), as_of=_AS_OF,
    )]
    out: dict[tuple[str, str], MoverSignal] = {}
    for seg in segments:
        out[("AAA", seg)] = _signal("AAA", seg, score_aaa)
        out[("BBB", seg)] = _signal("BBB", seg, score_bbb)
    return out


def test_scan_segments_fans_out_across_all_sectors_and_sorts_by_abs_score():
    """Assert scan fans out over 11 sectors and returns plans sorted by |score| (AAA before BBB)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.50)
    plans = scan_segments(
        as_of=_AS_OF, simulate=False,
        candidate_fetcher=_candidate_fetcher(
            {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
            {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
        ),
        signal_fetcher=_signal_fetcher_for(signals),
        level_fetcher=_level_fetcher(),
    )
    # 11 sectors x 2 movers = 22 actionable plans (all |score| >= 0.4 -> all have orders)
    assert len(plans) == 22
    assert len({p.segment for p in plans}) == 11
    keys = [_rank_key(p) for p in plans]
    assert keys == sorted(keys)
    # AAA (|0.90|) entirely precedes BBB (|0.50|)
    assert {p.symbol for p in plans[:11]} == {"AAA"}
    assert {p.symbol for p in plans[11:]} == {"BBB"}


def test_scan_segments_filters_flat_subthreshold_plans():
    """Assert flat / sub-threshold plans (empty orders) are filtered from the ranked list (Q-A)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.05)  # BBB flat (|0.05| < 0.4)
    plans = scan_segments(
        as_of=_AS_OF, simulate=False,
        candidate_fetcher=_candidate_fetcher(
            {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
            {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
        ),
        signal_fetcher=_signal_fetcher_for(signals),
        level_fetcher=_level_fetcher(),
    )
    assert {p.symbol for p in plans} == {"AAA"}  # all 11 BBB flats filtered out
    assert all(p.orders for p in plans)


def test_scan_segments_limit_slices_top_of_list_after_sort():
    """Assert ``limit=k`` returns the first k after the cross-segment sort (Q-A opt-iii)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.50)
    plans = scan_segments(
        as_of=_AS_OF, simulate=False, limit=5,
        candidate_fetcher=_candidate_fetcher(
            {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
            {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
        ),
        signal_fetcher=_signal_fetcher_for(signals),
        level_fetcher=_level_fetcher(),
    )
    assert len(plans) == 5
    assert {p.symbol for p in plans} == {"AAA"}  # top 5 are all the |0.90| AAA plans


def test_scan_segments_skip_and_continue_on_segment_build_failure():
    """Assert a build raising for one sector drops that sector and keeps the rest (Q-E)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.50)

    def _boom_for_energy(symbols=None, segment=None, *, preset="trend_follow", as_of=None):
        if segment == "Energy":
            raise RuntimeError("synthetic mover/panel failure")
        return [signals[(s, segment)] for s in (symbols or []) if (s, segment) in signals]

    import pytest
    with pytest.warns(UserWarning, match="Energy"):
        plans = scan_segments(
            as_of=_AS_OF, simulate=False,
            candidate_fetcher=_candidate_fetcher(
                {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
                {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
            ),
            signal_fetcher=_boom_for_energy,
            level_fetcher=_level_fetcher(),
        )
    assert "Energy" not in {p.segment for p in plans}
    assert len({p.segment for p in plans}) == 10  # the other 10 sectors survive


def test_scan_segments_simulate_attaches_fills_when_bars_supplied():
    """Assert simulate=True with a forward window populates simulated_fills (L6, Q-C)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.50)
    window = [_bar("121.40", "122", "120.0", "121"), _bar("119", "120", "117.00", "118")]
    plans = scan_segments(
        as_of=_AS_OF, simulate=True, limit=1,
        candidate_fetcher=_candidate_fetcher(
            {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
        ),
        signal_fetcher=_signal_fetcher_for(signals),
        level_fetcher=_level_fetcher(),
        bars={"AAA": window},
    )
    assert plans[0].simulated_fills, "expected fills attached for AAA"
    assert plans[0].simulated_fills[0].order_ref == "AAA:entry"


def test_scan_segments_rank_is_identical_with_and_without_simulate():
    """Assert ranking (pre-fill |score|) is independent of the simulate flag (Q-C C3)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.50)
    cand = _candidate_fetcher(
        {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
        {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
    )
    no_fills = scan_segments(
        as_of=_AS_OF, simulate=False, candidate_fetcher=cand,
        signal_fetcher=_signal_fetcher_for(signals), level_fetcher=_level_fetcher(),
    )
    with_fills = scan_segments(
        as_of=_AS_OF, simulate=True, candidate_fetcher=cand,
        signal_fetcher=_signal_fetcher_for(signals), level_fetcher=_level_fetcher(),
        bars={"AAA": [_bar("121.40", "122", "120.0", "121")]},
    )
    assert [(p.symbol, p.segment) for p in no_fills] == [(p.symbol, p.segment) for p in with_fills]


def test_scan_segments_empty_universe_returns_empty_list():
    """Assert no movers (empty candidate pool) yields an empty plan list (no error)."""
    plans = scan_segments(
        as_of=_AS_OF, simulate=False,
        candidate_fetcher=_candidate_fetcher(),  # no rows
        signal_fetcher=_signal_fetcher_for({}),
        level_fetcher=_level_fetcher(),
    )
    assert plans == []


def test_scan_segments_is_deterministic():
    """Assert two identical scans produce equal plan snapshots (pure, no hidden state)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.50)
    cand = _candidate_fetcher(
        {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
        {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
    )
    kw = dict(as_of=_AS_OF, simulate=False, candidate_fetcher=cand,
              signal_fetcher=_signal_fetcher_for(signals), level_fetcher=_level_fetcher())
    a = scan_segments(**kw)
    b = scan_segments(**kw)
    assert [p.model_dump() for p in a] == [p.model_dump() for p in b]
