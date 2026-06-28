"""Unit tests for the techtrade segment universe resolver (issue #69).

These tests are fully offline: every external data call (ETF holdings, equity
screener) is injected as a fake fetcher, so no API key and no network are needed.
They cover the three universe sources (``etf_holdings`` default,
``constituent_list``, ``screener``), order-preserving dedupe, membership-count
sanity validation, and the convenience ``resolve_all_segments`` over the 11 GICS
sectors (PRD §10, §20 Q3).
"""

from __future__ import annotations

import pytest

from openbb_techtrade.engine.screener import GICS_SECTOR_ETFS
from openbb_techtrade.engine.universe import (
    resolve_all_segments,
    resolve_universe,
)
from openbb_techtrade.models import SegmentConfig


def test_resolve_etf_holdings_uses_benchmark_etf():
    calls: list[str] = []

    def fake(etf_symbol: str) -> list[str]:
        calls.append(etf_symbol)
        return ["AAPL", "MSFT", "NVDA"]

    cfg = SegmentConfig(segment="Information Technology", benchmark_etf="XLK")
    universe = resolve_universe(cfg, holdings_fetcher=fake, min_members=1)

    assert universe == ["AAPL", "MSFT", "NVDA"]
    # The benchmark ETF drives the holdings fetch.
    assert calls == ["XLK"]


def test_resolve_etf_holdings_dedupes_and_drops_empty():
    def fake(_etf_symbol: str) -> list[str]:
        return ["AAPL", "AAPL", "", None, "MSFT"]

    cfg = SegmentConfig(segment="Information Technology", benchmark_etf="XLK")
    universe = resolve_universe(cfg, holdings_fetcher=fake, min_members=1)

    # Order-preserving dedupe, falsy symbols dropped.
    assert universe == ["AAPL", "MSFT"]


def test_resolve_constituent_list():
    cfg = SegmentConfig(segment="Energy", universe_source="constituent_list")
    # A deliberate constituent_list is exempt from the membership floor (default 5):
    # two explicitly named symbols resolve even though they are below it.
    universe = resolve_universe(cfg, constituents=["XOM", "CVX"])
    assert universe == ["XOM", "CVX"]


def test_resolve_constituent_list_requires_constituents():
    cfg = SegmentConfig(segment="Energy", universe_source="constituent_list")
    with pytest.raises(ValueError):
        resolve_universe(cfg, constituents=None)
    with pytest.raises(ValueError):
        resolve_universe(cfg, constituents=[])


def test_membership_sanity_raises_on_too_few():
    def fake(_etf_symbol: str) -> list[str]:
        return ["AAPL"]

    cfg = SegmentConfig(segment="Information Technology", benchmark_etf="XLK")
    with pytest.raises(ValueError) as exc_info:
        resolve_universe(cfg, holdings_fetcher=fake, min_members=5)
    # The error names the offending segment.
    assert "Information Technology" in str(exc_info.value)


def test_resolve_all_segments_with_fake():
    def fake(_etf_symbol: str) -> list[str]:
        # Any ETF resolves to a plausible (>= 5) universe.
        return ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]

    resolved = resolve_all_segments(holdings_fetcher=fake)

    # Every GICS sector resolves, keyed by sector name, each non-empty.
    assert set(resolved) == set(GICS_SECTOR_ETFS)
    assert len(resolved) == 11
    for segment, universe in resolved.items():
        assert universe, f"{segment} resolved to an empty universe"
        assert isinstance(universe, list)


def test_etf_holdings_requires_benchmark():
    cfg = SegmentConfig(segment="X", benchmark_etf=None)
    with pytest.raises(ValueError):
        resolve_universe(cfg, holdings_fetcher=lambda _etf: ["A", "B", "C", "D", "E"])


def test_resolve_screener_uses_injected_fetcher():
    calls: list[str] = []

    def fake_screener(segment: str) -> list[str]:
        calls.append(segment)
        return ["A", "B", "C", "D", "E"]

    cfg = SegmentConfig(segment="Financials", universe_source="screener")
    universe = resolve_universe(cfg, screener_fetcher=fake_screener, min_members=1)

    assert universe == ["A", "B", "C", "D", "E"]
    # The injected screener seam is driven by the segment name.
    assert calls == ["Financials"]


def test_default_screener_fetcher_rejects_unknown_segment():
    from openbb_techtrade.engine.universe import _default_screener_fetcher

    # An unknown segment is rejected before any network / openbb import, so this
    # stays fully offline (the ValueError is raised by the GICS-membership guard).
    with pytest.raises(ValueError) as exc_info:
        _default_screener_fetcher("Bogus Sector")
    assert "Bogus Sector" in str(exc_info.value)
