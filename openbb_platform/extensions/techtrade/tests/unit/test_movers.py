"""Unit tests for the techtrade top-mover ranking engine (issue #70, PRD §10).

These tests are fully offline: the live candidate fetcher is injected as a fake,
so no API key and no network are needed. Session snapping uses ``exchange_calendars``
(deterministic, offline). Coverage spans ``resolve_session`` calendar snapping,
the pure ``rank_movers`` ranking across all four metrics, ``compute_ohlcv_metrics``
on synthetic bars (dict and attribute rows), ``build_mover_list`` with an injected
fetcher + universe filtering, and ``list_movers`` over one / all GICS segments.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from openbb_techtrade.engine.movers import (
    _call_discovery,
    _resolve_filter_universe,
    build_mover_list,
    compute_ohlcv_metrics,
    list_movers,
    rank_movers,
    resolve_session,
)
from openbb_techtrade.engine.screener import GICS_SECTOR_ETFS
from openbb_techtrade.models import MoverList, SegmentConfig


def _pct_candidates() -> list[dict]:
    return [
        {"symbol": "AAA", "pct_change": 0.01, "volume": 100},
        {"symbol": "BBB", "pct_change": 0.05, "volume": 200},
        {"symbol": "CCC", "pct_change": 0.03, "volume": 300},
    ]


# --------------------------------------------------------------------------- #
# resolve_session
# --------------------------------------------------------------------------- #
def test_resolve_session_snaps_saturday_to_friday():
    # 2024-01-13 is a Saturday -> previous session is Friday 2024-01-12.
    session = resolve_session("2024-01-13")
    assert session == date(2024, 1, 12)
    assert isinstance(session, date)


def test_resolve_session_snaps_holiday_to_prior_session():
    # 2024-01-15 is the MLK holiday -> previous session is Friday 2024-01-12.
    session = resolve_session("2024-01-15")
    assert session == date(2024, 1, 12)


def test_resolve_session_returns_weekday_unchanged():
    # 2024-01-10 is a normal Wednesday trading session.
    session = resolve_session("2024-01-10")
    assert session == date(2024, 1, 10)


def test_resolve_session_accepts_date_object():
    session = resolve_session(date(2024, 1, 13))
    assert session == date(2024, 1, 12)


# --------------------------------------------------------------------------- #
# rank_movers
# --------------------------------------------------------------------------- #
def test_rank_movers_by_pct_change_descending_with_ranks():
    ml = rank_movers("Tech", date(2024, 1, 12), _pct_candidates(), metric="pct_change")

    assert isinstance(ml, MoverList)
    assert ml.segment == "Tech"
    assert isinstance(ml.as_of, date)
    # Descending by pct_change: BBB(0.05), CCC(0.03), AAA(0.01).
    assert [m.symbol for m in ml.movers] == ["BBB", "CCC", "AAA"]
    assert [m.rank for m in ml.movers] == [1, 2, 3]
    # volume is coerced to Decimal; pct_change stays float.
    assert all(isinstance(m.volume, Decimal) for m in ml.movers)
    assert all(isinstance(m.pct_change, float) for m in ml.movers)


def test_rank_movers_truncates_to_top_n():
    ml = rank_movers("Tech", date(2024, 1, 12), _pct_candidates(), metric="pct_change", top_n=2)
    assert len(ml.movers) == 2
    assert [m.symbol for m in ml.movers] == ["BBB", "CCC"]
    assert [m.rank for m in ml.movers] == [1, 2]


def test_rank_movers_deterministic_symbol_tiebreak():
    candidates = [
        {"symbol": "ZZZ", "pct_change": 0.05, "volume": 1},
        {"symbol": "AAA", "pct_change": 0.05, "volume": 1},
    ]
    ml = rank_movers("Tech", date(2024, 1, 12), candidates, metric="pct_change")
    # Equal metric -> ascending symbol tie-break: AAA before ZZZ.
    assert [m.symbol for m in ml.movers] == ["AAA", "ZZZ"]
    assert [m.rank for m in ml.movers] == [1, 2]


def test_rank_movers_excludes_candidates_missing_metric():
    candidates = [
        {"symbol": "AAA", "pct_change": 0.05, "volume": 1},
        {"symbol": "BBB", "volume": 2},  # missing pct_change key -> excluded
        {"symbol": "CCC", "pct_change": None, "volume": 3},  # None -> excluded
    ]
    ml = rank_movers("Tech", date(2024, 1, 12), candidates, metric="pct_change")
    assert [m.symbol for m in ml.movers] == ["AAA"]


def test_rank_movers_rejects_bogus_metric():
    with pytest.raises(ValueError):
        rank_movers("Tech", date(2024, 1, 12), _pct_candidates(), metric="bogus")


def test_rank_movers_by_volume():
    candidates = [
        {"symbol": "AAA", "pct_change": 0.0, "volume": 100},
        {"symbol": "BBB", "pct_change": 0.0, "volume": 300},
        {"symbol": "CCC", "pct_change": 0.0, "volume": 200},
    ]
    ml = rank_movers("Tech", date(2024, 1, 12), candidates, metric="volume")
    assert [m.symbol for m in ml.movers] == ["BBB", "CCC", "AAA"]


def test_rank_movers_by_gap():
    candidates = [
        {"symbol": "AAA", "pct_change": 0.0, "volume": 1, "gap": 0.01},
        {"symbol": "BBB", "pct_change": 0.0, "volume": 1, "gap": 0.03},
        {"symbol": "CCC", "pct_change": 0.0, "volume": 1, "gap": 0.02},
    ]
    ml = rank_movers("Tech", date(2024, 1, 12), candidates, metric="gap")
    assert [m.symbol for m in ml.movers] == ["BBB", "CCC", "AAA"]


def test_rank_movers_by_rel_volume():
    candidates = [
        {"symbol": "AAA", "pct_change": 0.0, "volume": 1, "rel_volume": 1.5},
        {"symbol": "BBB", "pct_change": 0.0, "volume": 1, "rel_volume": 3.0},
        {"symbol": "CCC", "pct_change": 0.0, "volume": 1, "rel_volume": 2.0},
    ]
    ml = rank_movers("Tech", date(2024, 1, 12), candidates, metric="rel_volume")
    assert [m.symbol for m in ml.movers] == ["BBB", "CCC", "AAA"]


# --------------------------------------------------------------------------- #
# compute_ohlcv_metrics
# --------------------------------------------------------------------------- #
def _ascending_bars_as_dicts() -> list[dict]:
    # prev_close = 100 (3rd bar), last open 102, last close 105, vols [100,100,100,300].
    return [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
        {"open": 102, "high": 106, "low": 101, "close": 105, "volume": 300},
    ]


def test_compute_ohlcv_metrics_dict_rows():
    metrics = compute_ohlcv_metrics("XYZ", _ascending_bars_as_dicts())
    assert metrics["symbol"] == "XYZ"
    assert metrics["pct_change"] == pytest.approx(0.05)
    assert metrics["gap"] == pytest.approx(0.02)
    assert metrics["rel_volume"] == pytest.approx(3.0)
    assert metrics["volume"] == 300


def test_compute_ohlcv_metrics_attribute_rows():
    rows = [SimpleNamespace(**bar) for bar in _ascending_bars_as_dicts()]
    metrics = compute_ohlcv_metrics("XYZ", rows)
    assert metrics["pct_change"] == pytest.approx(0.05)
    assert metrics["gap"] == pytest.approx(0.02)
    assert metrics["rel_volume"] == pytest.approx(3.0)
    assert metrics["volume"] == 300


def test_compute_ohlcv_metrics_single_bar_is_degenerate():
    metrics = compute_ohlcv_metrics("XYZ", [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 50}])
    assert metrics["symbol"] == "XYZ"
    assert metrics["pct_change"] == 0.0
    assert metrics["gap"] == 0.0
    assert metrics["rel_volume"] == 0.0
    assert metrics["volume"] == 50


def test_compute_ohlcv_metrics_empty_rows():
    metrics = compute_ohlcv_metrics("XYZ", [])
    assert metrics["symbol"] == "XYZ"
    assert metrics["pct_change"] == 0.0
    assert metrics["gap"] == 0.0
    assert metrics["rel_volume"] == 0.0
    assert metrics["volume"] == 0


# --------------------------------------------------------------------------- #
# build_mover_list
# --------------------------------------------------------------------------- #
def test_build_mover_list_with_injected_fetcher():
    seen: list[date] = []

    def fake(as_of, **kwargs):
        seen.append(as_of)
        return _pct_candidates()

    cfg = SegmentConfig(segment="Information Technology", benchmark_etf="XLK")
    ml = build_mover_list(cfg, as_of="2024-01-12", candidate_fetcher=fake)

    assert isinstance(ml, MoverList)
    assert ml.segment == "Information Technology"
    # The fetcher received the resolved session date (Friday 2024-01-12 unchanged).
    assert seen == [date(2024, 1, 12)]
    assert [m.symbol for m in ml.movers] == ["BBB", "CCC", "AAA"]


def test_build_mover_list_snaps_session_before_fetching():
    seen: list[date] = []

    def fake(as_of, **kwargs):
        seen.append(as_of)
        return _pct_candidates()

    cfg = SegmentConfig(segment="Information Technology", benchmark_etf="XLK")
    # Saturday input snaps back to Friday 2024-01-12 before the fetch.
    build_mover_list(cfg, as_of="2024-01-13", candidate_fetcher=fake)
    assert seen == [date(2024, 1, 12)]


def test_build_mover_list_universe_filter_drops_outsiders():
    def fake(as_of, **kwargs):
        return _pct_candidates()

    cfg = SegmentConfig(segment="Information Technology", benchmark_etf="XLK")
    ml = build_mover_list(
        cfg,
        as_of="2024-01-12",
        candidate_fetcher=fake,
        universe=["AAA", "BBB"],
    )
    # CCC is filtered out because it is not in the universe.
    assert {m.symbol for m in ml.movers} == {"AAA", "BBB"}


def test_build_mover_list_metric_override():
    def fake(as_of, **kwargs):
        return [
            {"symbol": "AAA", "pct_change": 0.0, "volume": 100},
            {"symbol": "BBB", "pct_change": 0.0, "volume": 300},
            {"symbol": "CCC", "pct_change": 0.0, "volume": 200},
        ]

    cfg = SegmentConfig(segment="Information Technology", benchmark_etf="XLK")
    ml = build_mover_list(cfg, as_of="2024-01-12", candidate_fetcher=fake, metric="volume")
    assert [m.symbol for m in ml.movers] == ["BBB", "CCC", "AAA"]


# --------------------------------------------------------------------------- #
# list_movers
# --------------------------------------------------------------------------- #
def test_list_movers_single_segment():
    def fake(as_of, **kwargs):
        return _pct_candidates()

    result = list_movers(segment="Information Technology", candidate_fetcher=fake)
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], MoverList)
    assert result[0].segment == "Information Technology"
    assert [m.symbol for m in result[0].movers] == ["BBB", "CCC", "AAA"]


def test_list_movers_all_segments_in_canonical_order():
    def fake(as_of, **kwargs):
        return _pct_candidates()

    result = list_movers(candidate_fetcher=fake)
    assert len(result) == 11
    assert [ml.segment for ml in result] == list(GICS_SECTOR_ETFS)
    assert all(isinstance(ml, MoverList) for ml in result)


def test_list_movers_rejects_bogus_segment():
    with pytest.raises(ValueError):
        list_movers(segment="Bogus")


def test_list_movers_propagates_top_n():
    def fake(as_of, **kwargs):
        return _pct_candidates()

    result = list_movers(segment="Information Technology", candidate_fetcher=fake, top_n=2)
    assert len(result[0].movers) == 2


# --------------------------------------------------------------------------- #
# _call_discovery (fmp_cached-only, no fallback)
# --------------------------------------------------------------------------- #
def test_call_discovery_uses_fmp_cached_provider():
    seen: list[dict] = []

    def fake(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(
            results=[SimpleNamespace(symbol="AAA", percent_change=0.01, volume=100)]
        )

    rows = _call_discovery(fake)
    assert len(rows) == 1
    assert rows[0].symbol == "AAA"
    # The engine's only provider is fmp_cached, passed with no fallback.
    assert seen == [{"provider": "fmp_cached"}]


def test_call_discovery_none_results_returns_empty_list():
    def fake(**kwargs):
        return SimpleNamespace(results=None)

    assert _call_discovery(fake) == []


def test_call_discovery_propagates_failure_no_fallback():
    def fake(**kwargs):
        raise RuntimeError("fmp_cached down")

    # No silent fallback to a default provider: the failure propagates.
    with pytest.raises(RuntimeError):
        _call_discovery(fake)


# --------------------------------------------------------------------------- #
# _resolve_filter_universe (live-path-only universe gating)
# --------------------------------------------------------------------------- #
def test_resolve_filter_universe_live_path_resolves():
    cfg = SegmentConfig(segment="Information Technology", benchmark_etf="XLK")
    universe = _resolve_filter_universe(
        cfg,
        candidate_fetcher=None,
        resolve_universe_filter=True,
        holdings_fetcher=lambda etf: ["AAA", "BBB", "CCC", "DDD", "EEE"],
        screener_fetcher=None,
        constituents_map=None,
    )
    assert universe == ["AAA", "BBB", "CCC", "DDD", "EEE"]


def test_resolve_filter_universe_gated_off_when_fetcher_injected():
    cfg = SegmentConfig(segment="Information Technology", benchmark_etf="XLK")
    universe = _resolve_filter_universe(
        cfg,
        candidate_fetcher=lambda **k: [],
        resolve_universe_filter=True,
        holdings_fetcher=lambda etf: ["AAA", "BBB", "CCC", "DDD", "EEE"],
        screener_fetcher=None,
        constituents_map=None,
    )
    assert universe is None


def test_resolve_filter_universe_disabled_returns_none():
    cfg = SegmentConfig(segment="Information Technology", benchmark_etf="XLK")
    universe = _resolve_filter_universe(
        cfg,
        candidate_fetcher=None,
        resolve_universe_filter=False,
        holdings_fetcher=lambda etf: ["AAA", "BBB", "CCC", "DDD", "EEE"],
        screener_fetcher=None,
        constituents_map=None,
    )
    assert universe is None


def test_resolve_filter_universe_degrades_to_none_on_failure():
    def _boom(_etf):
        raise RuntimeError("holdings unavailable")

    cfg = SegmentConfig(segment="Information Technology", benchmark_etf="XLK")
    universe = _resolve_filter_universe(
        cfg,
        candidate_fetcher=None,
        resolve_universe_filter=True,
        holdings_fetcher=_boom,
        screener_fetcher=None,
        constituents_map=None,
    )
    assert universe is None
