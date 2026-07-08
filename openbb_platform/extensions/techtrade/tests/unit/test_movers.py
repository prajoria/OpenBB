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
    # bd-lw3 Option B2: pct_change + gap stored as HUMAN PERCENT (5.0 for
    # a +5% move). Reverting the *100 conversion in compute_ohlcv_metrics
    # would flip these assertions.
    assert metrics["pct_change"] == pytest.approx(5.0)
    assert metrics["gap"] == pytest.approx(2.0)
    assert metrics["rel_volume"] == pytest.approx(3.0)
    assert metrics["volume"] == 300


def test_compute_ohlcv_metrics_attribute_rows():
    rows = [SimpleNamespace(**bar) for bar in _ascending_bars_as_dicts()]
    metrics = compute_ohlcv_metrics("XYZ", rows)
    # bd-lw3 Option B2: pct_change + gap stored as human percent.
    assert metrics["pct_change"] == pytest.approx(5.0)
    assert metrics["gap"] == pytest.approx(2.0)
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


# =========================================================================== #
# bd-lw3 regression tests: 3-defect fix for techtrade.movers pct_change/volume
#
# Defects:
#   1. DATA SHAPE — discovery feed carries volume=None (never populated by
#      EquityPerformanceData)
#   2. UNITS — pct_change is a fraction (0.0138), notebook prints it as
#      percent producing '0.01%' for a real +1.38% move
#   3. DESIGN — fan-out-then-filter collapses the candidate pool: 140
#      market-wide discovery symbols ∩ 75 XLK constituents = 5 movers only
#
# Fix (Option B2): compute_ohlcv_metrics stores pct_change as human
# percent (1.38, not 0.0138). _default_candidate_fetcher takes an OHLCV
# path for ALL metrics when a universe is provided, not just gap/rel_volume.
# =========================================================================== #


class TestBdLw3PctChangeUnit:
    """Defect 2 fix: pct_change is a human percent, not a fraction.

    Load-bearing (R7.11): reverting the *100 conversion in
    compute_ohlcv_metrics flips these tests from PASS → FAIL. Verified
    via mutation before ship.
    """

    def test_compute_ohlcv_metrics_pct_change_is_percent_not_fraction(self):
        """Two bars: close 100 → 101.38. Expected pct_change: 1.38
        (percent), NOT 0.0138 (fraction). This is the reviewer's
        recommended Option B2 unit contract.
        """
        bars = [
            {"open": 100, "high": 101, "low": 99, "close": 100.0, "volume": 100},
            {"open": 101, "high": 102, "low": 100, "close": 101.38, "volume": 200},
        ]
        m = compute_ohlcv_metrics("XYZ", bars)
        assert m["pct_change"] == pytest.approx(1.38), (
            f"pct_change must be a human percent (1.38 for a +1.38% move), "
            f"got {m['pct_change']}. If this test fails, either Option B2 "
            f"conversion was reverted OR the unit contract changed silently."
        )

    def test_compute_ohlcv_metrics_negative_move_is_negative_percent(self):
        """Sign is preserved through the conversion."""
        bars = [
            {"open": 100, "high": 101, "low": 99, "close": 100.0, "volume": 100},
            {"open": 100, "high": 101, "low": 90, "close": 90.34, "volume": 200},
        ]
        m = compute_ohlcv_metrics("XYZ", bars)
        assert m["pct_change"] == pytest.approx(-9.66, abs=0.01)

    def test_gap_is_also_percent(self):
        """gap is a sibling of pct_change — same unit contract applies
        (both are (X - prev_close) / prev_close style ratios).
        """
        bars = [
            {"open": 100, "high": 101, "low": 99, "close": 100.0, "volume": 100},
            {"open": 102, "high": 106, "low": 101, "close": 105.0, "volume": 300},
        ]
        m = compute_ohlcv_metrics("XYZ", bars)
        # Gap = (102 - 100) / 100 = 2.0% (not 0.02)
        assert m["gap"] == pytest.approx(2.0)
        # pct_change = (105 - 100) / 100 = 5.0%
        assert m["pct_change"] == pytest.approx(5.0)

    def test_rel_volume_unchanged_by_pct_conversion(self):
        """rel_volume is a ratio-of-volumes (not a change fraction). The
        Option B2 conversion applies to pct_change + gap only, NOT
        rel_volume. Load-bearing: mutating the code to multiply
        rel_volume by 100 too would flip this.
        """
        bars = [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 300},
        ]
        m = compute_ohlcv_metrics("XYZ", bars)
        assert m["rel_volume"] == pytest.approx(3.0)   # 300 / mean(100,100)


class TestBdLw3UniversePath:
    """Defect 3 fix: R7.5 narrow-then-fan-out for pct_change / volume
    metrics. When a universe is provided, use per-symbol OHLCV for ALL
    metrics — do NOT intersect with the discovery firehose.
    """

    def _make_bars(self, symbol: str, last_close: float, last_volume: int) -> list[dict]:
        """Two-bar OHLCV series: baseline (close=100, vol=100) → last."""
        return [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
            {"open": last_close, "high": last_close, "low": last_close,
             "close": last_close, "volume": last_volume},
        ]

    def test_universe_path_returns_one_candidate_per_universe_symbol(self):
        """R7.5: 20-symbol universe → 20 candidates going into rank_movers,
        NOT `len(universe ∩ discovery_feed)`.

        Load-bearing: reverting the fix (letting the fetcher run its
        discovery-firehose branch instead of the universe-driven branch)
        would drop the candidate count to whatever the fake discovery
        returns intersected with the universe.
        """
        from openbb_techtrade.engine.movers import _fetch_universe_candidates

        universe = [f"SYM{i:03d}" for i in range(20)]
        fetched: list[str] = []

        def fake_history_fetcher(symbol, **kwargs):
            fetched.append(symbol)
            # Each symbol gets a distinct pct_change so ranking is deterministic
            idx = int(symbol[3:])
            return self._make_bars(symbol, 100 + idx * 0.5, 1_000_000 + idx)

        candidates = _fetch_universe_candidates(
            universe, date(2026, 7, 7),
            history_fetcher=fake_history_fetcher,
        )
        assert len(candidates) == 20, (
            f"universe path must produce one candidate per symbol "
            f"(narrow-then-fan-out). Got {len(candidates)}."
        )
        assert set(fetched) == set(universe)

    def test_universe_path_carries_real_volume(self):
        """R7.1: fixture models the real defect — discovery feed carried
        volume=None; per-symbol OHLCV DOES carry real volume. Assert every
        Mover has volume > 0 when driven from the universe path.
        """
        from openbb_techtrade.engine.movers import _fetch_universe_candidates

        def fake_history_fetcher(symbol, **kwargs):
            return self._make_bars(symbol, 105.0, 42_097_217)

        candidates = _fetch_universe_candidates(
            ["AAPL", "MSFT", "GOOGL"], date(2026, 7, 7),
            history_fetcher=fake_history_fetcher,
        )
        for c in candidates:
            assert c["volume"] > 0, (
                f"universe path must carry real volume, got 0 for {c['symbol']}. "
                f"Bug: the fetcher fell back to the discovery-union path where "
                f"EquityPerformanceData.volume is None."
            )

    def test_universe_path_skips_symbols_with_no_history(self, caplog):
        """R7.3 loud-empty: if a symbol's history fetch fails or returns
        empty, it must be skipped with a WARNING (not silently ranked
        with pct_change=0).
        """
        import logging
        from openbb_techtrade.engine.movers import _fetch_universe_candidates

        def fake_history_fetcher(symbol, **kwargs):
            if symbol == "BAD":
                raise ValueError("no data")
            return self._make_bars(symbol, 105.0, 1_000_000)

        with caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"):
            candidates = _fetch_universe_candidates(
                ["AAPL", "BAD", "MSFT"], date(2026, 7, 7),
                history_fetcher=fake_history_fetcher,
            )
        assert len(candidates) == 2
        assert {c["symbol"] for c in candidates} == {"AAPL", "MSFT"}
        # Warning must document WHY BAD was dropped
        bad_warnings = [r for r in caplog.records if "BAD" in r.getMessage()]
        assert len(bad_warnings) >= 1, (
            "R7.3: dropped symbol must emit a WARNING with the reason. "
            f"Got: {[r.getMessage() for r in caplog.records]}"
        )


class TestBdLw3BuildMoverListUniverseIntegration:
    """End-to-end: build_mover_list with a universe MUST use the
    per-symbol OHLCV path for pct_change/volume metrics (not just
    gap/rel_volume), so the resulting MoverList has real volumes and
    the candidate pool equals the universe size (subject to OHLCV
    availability).
    """

    def _make_bars(self, close: float, volume: int) -> list[dict]:
        return [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
            {"open": close, "high": close, "low": close, "close": close, "volume": volume},
        ]

    def test_pct_change_metric_with_universe_uses_ohlcv_path(self):
        """R7.11 load-bearing: reverting the fix means build_mover_list
        with metric='pct_change' + universe would use the discovery
        union → 0/None volumes. Assert every Mover has volume > 0.
        """
        universe = ["AAPL", "MSFT", "GOOGL", "NVDA", "META"]

        def fake_fetcher(as_of, universe=None, needs_ohlcv=False, **kwargs):
            # This is the injected candidate_fetcher — must accept universe kwarg
            # and return per-symbol OHLCV-derived candidates.
            assert universe is not None, (
                "build_mover_list must pass the universe into the fetcher for "
                "pct_change/volume metrics (bd-lw3 fix)."
            )
            candidates = []
            for i, sym in enumerate(universe):
                bars = self._make_bars(100 + i, 10_000_000 + i * 1000)
                m = compute_ohlcv_metrics(sym, bars)
                candidates.append(m)
            return candidates

        cfg = SegmentConfig(segment="Information Technology", benchmark_etf="XLK")
        ml = build_mover_list(
            cfg, as_of="2026-07-07",
            universe=universe,
            candidate_fetcher=fake_fetcher,
            metric="pct_change",
        )
        assert len(ml.movers) == 5   # all universe members ranked
        for m in ml.movers:
            assert m.volume > 0, (
                f"bd-lw3: with universe supplied, pct_change metric must use "
                f"OHLCV path → non-zero volumes. Got volume={m.volume} for "
                f"{m.symbol}."
            )


class TestBdLw3DiscoveryPathUnit:
    """iter-1 reviewer NIT: the discovery-path pct_change *100 conversion
    (in ``_default_candidate_fetcher`` when NO universe is supplied) had
    zero unit coverage. Verify it here so a future mutation from
    ``raw_pct * 100.0`` to ``raw_pct`` gets caught.
    """

    def test_discovery_path_converts_percent_change_fraction_to_percent(self, monkeypatch):
        """Live discovery feed returns pct_change as a fraction (0.0138).
        The fetcher must convert to human percent (1.38) at the seam so
        Mover.pct_change contract is uniform across discovery + OHLCV paths.

        R7.11 load-bearing: mutating ``raw_pct * 100.0`` to ``raw_pct``
        would silently reintroduce Defect 2 on the discovery-only path
        (no universe passed).
        """
        from openbb_techtrade.engine import movers as movers_mod

        # Fake obb with a discovery.gainers that returns a fraction-typed
        # percent_change (mirrors real EquityPerformanceData shape).
        gainer = SimpleNamespace(symbol="PLTR", percent_change=0.0138, volume=52_334_140)

        class _FakeCommand:
            def __call__(self, provider=None):
                return SimpleNamespace(results=[gainer])

        fake_discovery = SimpleNamespace(
            gainers=_FakeCommand(),
            losers=_FakeCommand(),
            active=_FakeCommand(),
        )
        fake_equity = SimpleNamespace(discovery=fake_discovery, price=None)
        fake_obb = SimpleNamespace(equity=fake_equity)

        import sys
        monkeypatch.setitem(sys.modules, "openbb", SimpleNamespace(obb=fake_obb))

        # No universe → discovery path is exercised.
        candidates = movers_mod._default_candidate_fetcher(
            date(2026, 7, 7), needs_ohlcv=False,
        )

        # First matching row for PLTR — the union may collect it once per source
        # so we filter to first-hit-only per the fetcher's own contract.
        pltr = next(c for c in candidates if c["symbol"] == "PLTR")
        assert pltr["pct_change"] == pytest.approx(1.38), (
            f"bd-lw3 Defect 2 (discovery-path unit): stored fraction 0.0138 "
            f"must be converted to human percent 1.38 at the fetcher seam. "
            f"Got {pltr['pct_change']!r}. If this fails, the *100.0 "
            f"conversion in the discovery branch was removed."
        )

    def test_discovery_path_none_percent_change_stays_none(self, monkeypatch):
        """The *100 conversion must be None-safe — a discovery row with
        no percent_change field stays None (not TypeError on None*100).
        """
        from openbb_techtrade.engine import movers as movers_mod

        gainer = SimpleNamespace(symbol="XYZ", percent_change=None, volume=1_000)

        class _FakeCommand:
            def __call__(self, provider=None):
                return SimpleNamespace(results=[gainer])

        fake_discovery = SimpleNamespace(
            gainers=_FakeCommand(),
            losers=_FakeCommand(),
            active=_FakeCommand(),
        )
        fake_obb = SimpleNamespace(equity=SimpleNamespace(discovery=fake_discovery, price=None))
        import sys
        monkeypatch.setitem(sys.modules, "openbb", SimpleNamespace(obb=fake_obb))

        candidates = movers_mod._default_candidate_fetcher(
            date(2026, 7, 7), needs_ohlcv=False,
        )
        xyz = next(c for c in candidates if c["symbol"] == "XYZ")
        assert xyz["pct_change"] is None, (
            f"None percent_change must pass through as None, not raise "
            f"TypeError on None*100. Got {xyz['pct_change']!r}."
        )


class TestBdLw3FetchUniverseAggregateWarning:
    """iter-1 reviewer soft: if ALL universe symbols fail their fetch,
    emit an aggregate 0/N summary WARNING so ops can distinguish a
    per-symbol data issue from a provider-wide outage.
    """

    def test_zero_of_n_candidates_emits_aggregate_warning(self, caplog):
        """R7.3 loud-empty at the aggregate level: 0/N survival must be
        loud beyond per-symbol warnings.
        """
        import logging
        from openbb_techtrade.engine.movers import _fetch_universe_candidates

        def always_fail_fetcher(symbol, **kwargs):
            raise ValueError("provider down")

        with caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"):
            candidates = _fetch_universe_candidates(
                ["AAA", "BBB", "CCC"], date(2026, 7, 7),
                history_fetcher=always_fail_fetcher,
            )
        assert candidates == []
        # There should be per-symbol warnings AND an aggregate summary
        aggregate = [
            r for r in caplog.records
            if "0/" in r.getMessage() and "candidates" in r.getMessage()
        ]
        assert len(aggregate) == 1, (
            f"R7.3: 0/N survival must emit an aggregate summary warning. "
            f"Got messages: {[r.getMessage() for r in caplog.records]}"
        )

