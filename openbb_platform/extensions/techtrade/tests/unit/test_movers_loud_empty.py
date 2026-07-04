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
    assert "sources_ok=0/3" in msg
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
