"""Loud-empty WARNING tests for the techtrade movers engine (bd 90e, R7.3).

Motivation
----------
bd ``OpenBBTechnical-z7f`` took a full user-driven debug session to diagnose
because ``techtrade.movers`` returned ``MoverList(movers=[])`` silently — no
log, no error, no diagnostic. Rule R7.3 in ``rules/DEVELOPMENT_RULES.md``
Section 7 now requires that empty results a caller could reasonably expect
to be non-empty emit a ``logging.WARNING`` explaining WHY.

This module verifies the four warnings added by bd ``OpenBBTechnical-90e``:

1. ``build_mover_list`` — universe filter removed every candidate
2. ``_fetch_universe_candidates`` — no OHLCV history for any universe symbol
3. ``_default_candidate_fetcher`` — discovery feed produced 0 candidates
4. ``_default_holdings_fetcher`` — ETF holdings endpoint yielded 0 symbols

Each test drives the code path with a synthetic zero case and asserts the
expected substring appears in ``caplog`` at ``WARNING`` level.
"""

from __future__ import annotations

import logging
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from openbb_techtrade.engine.movers import (
    _default_candidate_fetcher,
    _fetch_universe_candidates,
    build_mover_list,
)
from openbb_techtrade.engine.universe import _default_holdings_fetcher
from openbb_techtrade.models import SegmentConfig


# --------------------------------------------------------------------------- #
# Warning 1: build_mover_list — universe filter eliminated every candidate
# --------------------------------------------------------------------------- #
def test_build_mover_list_warns_when_universe_filter_removes_all_candidates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The z7f fingerprint: non-empty pre-filter, empty post-filter."""

    def fetcher_returning_non_intersecting_candidates(**_kwargs):
        # 3 candidates, none of which are in the universe below.
        return [
            {"symbol": "AAAA", "pct_change": 0.05, "volume": 100},
            {"symbol": "BBBB", "pct_change": 0.04, "volume": 200},
            {"symbol": "CCCC", "pct_change": 0.03, "volume": 300},
        ]

    config = SegmentConfig(
        segment="Information Technology",
        benchmark_etf="XLK",
        universe_source="etf_holdings",
        rank_metric="pct_change",
        top_n=10,
    )
    with caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"):
        result = build_mover_list(
            config,
            as_of="2024-01-10",
            universe=["NVDA", "MSFT", "AAPL"],  # zero overlap with candidates
            candidate_fetcher=fetcher_returning_non_intersecting_candidates,
        )

    assert result.movers == []
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "universe filter removed all candidates" in r.getMessage()
    ]
    assert len(warnings) == 1, (
        f"expected exactly 1 z7f-style warning, got {len(warnings)}; "
        f"records: {[r.getMessage() for r in caplog.records]}"
    )
    msg = warnings[0].getMessage()
    assert "Information Technology" in msg
    assert "pre_filter=3" in msg
    assert "allowed=3" in msg
    assert "intersection=0" in msg
    assert "bd z7f" in msg  # traceable back to the origin bug


def test_build_mover_list_does_not_warn_when_intersection_non_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No warning noise on the happy path — R7.3's "avoid noise" non-goal."""

    def fetcher(**_kwargs):
        return [
            {"symbol": "NVDA", "pct_change": 0.05, "volume": 100},
            {"symbol": "MSFT", "pct_change": 0.04, "volume": 200},
        ]

    config = SegmentConfig(
        segment="Information Technology",
        benchmark_etf="XLK",
        universe_source="etf_holdings",
        rank_metric="pct_change",
        top_n=10,
    )
    with caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"):
        result = build_mover_list(
            config,
            as_of="2024-01-10",
            universe=["NVDA", "MSFT"],
            candidate_fetcher=fetcher,
        )

    assert len(result.movers) == 2
    assert not [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "universe filter" in r.getMessage()
    ], "no warning should fire on the happy path"


# --------------------------------------------------------------------------- #
# Warning 2: _fetch_universe_candidates — every per-symbol OHLCV fetch failed
# --------------------------------------------------------------------------- #
def test_fetch_universe_candidates_warns_when_no_history_returned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Universe non-empty, but every historical() call returned empty bars."""
    fake_obb = SimpleNamespace(
        equity=SimpleNamespace(
            price=SimpleNamespace(
                historical=lambda **_kwargs: SimpleNamespace(results=[])
            )
        )
    )

    with caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"):
        out = _fetch_universe_candidates(
            fake_obb,
            ["NVDA", "MSFT", "AAPL"],
            as_of=date(2024, 1, 10),
            ohlcv_lookback=21,
        )

    assert out == []
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "no OHLCV history returned" in r.getMessage()
    ]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "3 universe symbols" in msg
    assert "as_of=2024-01-10" in msg
    assert "fmp_cached" in msg


# --------------------------------------------------------------------------- #
# Warning 3: _default_candidate_fetcher — every discovery source raised
# --------------------------------------------------------------------------- #
def test_default_candidate_fetcher_warns_when_discovery_feed_yields_zero(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """All three discovery sources raise → zero candidates → WARNING."""

    def _raising_fetch(*_a, **_kw):
        raise RuntimeError("simulated fmp_cached outage")

    fake_discovery = SimpleNamespace(
        gainers=_raising_fetch,
        losers=_raising_fetch,
        active=_raising_fetch,
    )
    # NOTE: sys.modules patching does not work here because
    # ``from openbb import obb`` binds the name from the module, not the
    # module itself — the patched sys.modules['openbb'] would need a
    # matching ``obb`` attribute AND the fetcher's inner import needs to
    # find it. Simplest working approach: monkey-patch openbb.obb directly.
    import openbb  # actual module (already installed via dev_install)
    fake_obb = SimpleNamespace(equity=SimpleNamespace(discovery=fake_discovery))
    with (
        patch.object(openbb, "obb", fake_obb),
        caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"),
    ):
        out = _default_candidate_fetcher(as_of=date(2024, 1, 10))

    assert out == []
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "discovery feed produced 0 candidates" in r.getMessage()
    ]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    # Post-PR-#325-review message format distinguishes raised (exception)
    # from empty (returned []) sources so ops can localize outages.
    assert "raised=" in msg
    assert "empty=" in msg
    assert "'gainers'" in msg  # all three sources should appear as raised
    assert "'losers'" in msg
    assert "'active'" in msg
    assert "as_of=2024-01-10" in msg
    assert "fmp_cached" in msg


# --------------------------------------------------------------------------- #
# Warning 4: _default_holdings_fetcher — ETF endpoint returned 0 symbols
# --------------------------------------------------------------------------- #
def test_default_holdings_fetcher_warns_on_empty_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ETF endpoint returned no rows at all."""
    import openbb
    fake_obb = SimpleNamespace(
        etf=SimpleNamespace(
            holdings=lambda **_kwargs: SimpleNamespace(results=[])
        )
    )
    with (
        patch.object(openbb, "obb", fake_obb),
        caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.universe"),
    ):
        out = _default_holdings_fetcher("XLK")

    assert out == []
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "yielded no" in r.getMessage()
    ]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "'XLK'" in msg  # repr'd symbol
    assert "rows_returned=0" in msg


def test_default_holdings_fetcher_warns_when_all_rows_have_null_symbols(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ETF endpoint returned rows but every one had a null symbol.

    Distinct failure mode from "no rows at all" — the warning message must
    reflect the actual ``rows_returned`` count so ops can localize the hop.
    """
    import openbb
    fake_rows = [SimpleNamespace(symbol=None), SimpleNamespace(symbol="")]
    fake_obb = SimpleNamespace(
        etf=SimpleNamespace(
            holdings=lambda **_kwargs: SimpleNamespace(results=fake_rows)
        )
    )
    with (
        patch.object(openbb, "obb", fake_obb),
        caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.universe"),
    ):
        out = _default_holdings_fetcher("XLK")

    assert out == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "rows_returned=2" in msg  # rows arrived, but were unusable


# --------------------------------------------------------------------------- #
# PR #325 iter-1 review fixes — negative "does not fire on happy path" tests
# for the warnings that lacked them (F8: only 1 of 4 had a negative test).
# --------------------------------------------------------------------------- #
def test_fetch_universe_candidates_does_not_warn_when_history_returned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R7.3 "avoid noise" — no warning on happy path for universe scan."""
    fake_bars = [
        SimpleNamespace(open=100.0, high=101.0, low=99.0, close=100.5, volume=1_000_000),
        SimpleNamespace(open=100.5, high=102.0, low=100.0, close=101.5, volume=1_200_000),
    ]
    fake_obb = SimpleNamespace(
        equity=SimpleNamespace(
            price=SimpleNamespace(
                historical=lambda **_kwargs: SimpleNamespace(results=fake_bars)
            )
        )
    )

    with caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"):
        out = _fetch_universe_candidates(
            fake_obb,
            ["NVDA", "MSFT", "AAPL"],
            as_of=date(2024, 1, 10),
            ohlcv_lookback=21,
        )

    assert len(out) == 3
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_default_candidate_fetcher_does_not_warn_when_discovery_returns_rows(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R7.3 "avoid noise" — no warning when all 3 discovery sources return rows."""
    fake_row = SimpleNamespace(symbol="AAPL", percent_change=0.05, volume=1_000_000)

    def _fake_source(*_a, **_kw):
        return SimpleNamespace(results=[fake_row])

    fake_obb = SimpleNamespace(
        equity=SimpleNamespace(
            discovery=SimpleNamespace(
                gainers=_fake_source,
                losers=_fake_source,
                active=_fake_source,
            )
        )
    )
    import openbb

    with (
        patch.object(openbb, "obb", fake_obb),
        caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"),
    ):
        out = _default_candidate_fetcher(as_of=date(2024, 1, 10))

    assert len(out) == 1  # 3 sources returned same row, deduped by symbol
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_default_holdings_fetcher_does_not_warn_when_rows_have_symbols(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R7.3 "avoid noise" — no warning when ETF endpoint returns usable symbols."""
    import openbb
    fake_rows = [SimpleNamespace(symbol="NVDA"), SimpleNamespace(symbol="MSFT")]
    fake_obb = SimpleNamespace(
        etf=SimpleNamespace(
            holdings=lambda **_kwargs: SimpleNamespace(results=fake_rows)
        )
    )
    with (
        patch.object(openbb, "obb", fake_obb),
        caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.universe"),
    ):
        out = _default_holdings_fetcher("XLK")

    assert out == ["NVDA", "MSFT"]
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


# --------------------------------------------------------------------------- #
# Warning 5 (NEW, PR #325 iter-1): _resolve_filter_universe silent-swallow
# — silent-failure-hunter finding #2, the exact z7f-class silent failure
# sitting three lines below the original 90e warnings.
# --------------------------------------------------------------------------- #
def test_resolve_filter_universe_warns_when_holdings_fetcher_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R7.3: silent degrade to no-filter after resolution failure must warn."""
    from openbb_techtrade.engine.movers import _resolve_filter_universe

    def _raising_holdings(_etf_symbol):
        raise RuntimeError("simulated FMP 429 rate-limit")

    config = SegmentConfig(
        segment="Information Technology",
        benchmark_etf="XLK",
        universe_source="etf_holdings",
        rank_metric="pct_change",
        top_n=10,
    )
    with caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"):
        result = _resolve_filter_universe(
            config,
            candidate_fetcher=None,           # live path
            resolve_universe_filter=True,
            holdings_fetcher=_raising_holdings,
            screener_fetcher=None,
            constituents_map=None,
        )

    assert result is None  # degrades to no filter
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "universe resolution failed" in r.getMessage()
    ]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "Information Technology" in msg
    assert "RuntimeError" in msg
    assert "429" in msg or "rate-limit" in msg
    assert "results are NOT scoped to the segment" in msg
    assert "benchmark_etf=XLK" in msg


# --------------------------------------------------------------------------- #
# Warning 6 (NEW, PR #325 iter-1): rank_movers metric-drop warning
# — silent-failure-hunter finding #3, catches volume=null silent-empty on
# discovery-path fixtures ranked by "volume" and future metric-drift.
# --------------------------------------------------------------------------- #
def test_rank_movers_warns_when_all_candidates_lack_ranking_metric(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fixture-style scenario: every candidate has volume=None; metric='volume'
    would previously return MoverList(movers=[]) silently.
    """
    from openbb_techtrade.engine.movers import rank_movers

    candidates = [
        {"symbol": "AAA", "pct_change": 0.01, "volume": None},
        {"symbol": "BBB", "pct_change": 0.02, "volume": None},
        {"symbol": "CCC", "pct_change": 0.03, "volume": None},
    ]
    with caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"):
        result = rank_movers("test", date(2024, 1, 10), candidates, metric="volume")

    assert result.movers == []
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "rank_movers" in r.getMessage()
    ]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "dropped 3/3" in msg
    assert "'volume'" in msg


def test_rank_movers_warns_when_half_of_candidates_lack_metric(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Partial degradation (>= 50%) also warns — biased ranking hazard."""
    from openbb_techtrade.engine.movers import rank_movers

    candidates = [
        {"symbol": "AAA", "pct_change": 0.01, "volume": None},
        {"symbol": "BBB", "pct_change": 0.02, "volume": None},
        {"symbol": "CCC", "pct_change": 0.03, "volume": 100},
        {"symbol": "DDD", "pct_change": 0.04, "volume": 200},
    ]
    with caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"):
        result = rank_movers("test", date(2024, 1, 10), candidates, metric="volume")

    assert len(result.movers) == 2
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "dropped 2/4" in warnings[0].getMessage()


def test_rank_movers_does_not_warn_when_all_candidates_have_metric(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R7.3 "avoid noise" — happy path is silent."""
    from openbb_techtrade.engine.movers import rank_movers

    candidates = [
        {"symbol": "AAA", "pct_change": 0.01, "volume": 100},
        {"symbol": "BBB", "pct_change": 0.02, "volume": 200},
    ]
    with caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"):
        result = rank_movers("test", date(2024, 1, 10), candidates, metric="volume")

    assert len(result.movers) == 2
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


# --------------------------------------------------------------------------- #
# Warning 7 (NEW, PR #325 iter-1): partial-degradation warnings for both
# discovery (F5) and universe-scan (F6) paths — no more silent under-sampling.
# --------------------------------------------------------------------------- #
def test_default_candidate_fetcher_warns_on_partial_discovery_degradation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """2 of 3 sources return empty; caller gets biased pool -> PARTIAL warning."""
    fake_row = SimpleNamespace(symbol="AAPL", percent_change=0.05, volume=1_000_000)

    def _one_row(*_a, **_kw):
        return SimpleNamespace(results=[fake_row])

    def _empty(*_a, **_kw):
        return SimpleNamespace(results=[])

    fake_obb = SimpleNamespace(
        equity=SimpleNamespace(
            discovery=SimpleNamespace(
                gainers=_one_row,
                losers=_empty,
                active=_empty,
            )
        )
    )
    import openbb

    with (
        patch.object(openbb, "obb", fake_obb),
        caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"),
    ):
        out = _default_candidate_fetcher(as_of=date(2024, 1, 10))

    assert len(out) == 1
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "partially degraded" in r.getMessage()
    ]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "1/3 sources produced rows" in msg
    assert "'losers'" in msg
    assert "'active'" in msg


def test_fetch_universe_candidates_warns_on_partial_scan_degradation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """>= 20% of universe symbols dropped -> PARTIAL warning (biased ranking)."""
    # 5 symbols; 2 will fail (40% > 20% threshold).
    fake_bars = [
        SimpleNamespace(open=100.0, high=101.0, low=99.0, close=100.5, volume=1_000_000),
        SimpleNamespace(open=100.5, high=102.0, low=100.0, close=101.5, volume=1_200_000),
    ]

    def _sometimes_fail(**kwargs):
        symbol = kwargs.get("symbol")
        if symbol in {"BAD1", "BAD2"}:
            raise RuntimeError("simulated per-symbol fetch failure")
        return SimpleNamespace(results=fake_bars)

    fake_obb = SimpleNamespace(
        equity=SimpleNamespace(price=SimpleNamespace(historical=_sometimes_fail))
    )

    with caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.movers"):
        out = _fetch_universe_candidates(
            fake_obb,
            ["NVDA", "MSFT", "AAPL", "BAD1", "BAD2"],
            as_of=date(2024, 1, 10),
            ohlcv_lookback=21,
        )

    assert len(out) == 3
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "partially degraded" in r.getMessage()
    ]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "2/5 symbols dropped" in msg
    assert "failed_fetch=2" in msg
