"""Unit tests for the techtrade screener: GICS map + segments command (issue #68).

Covers the static 11-sector GICS -> sector-SPDR ETF map (PRD §10), the placeholder
``list_segments`` resolver (PRD §9.2), and the ``segments`` router command wired onto
``obb.techtrade.*`` via the lazy sub-router include in ``techtrade_router``.
"""

from __future__ import annotations

from openbb_core.app.model.obbject import OBBject
from openbb_techtrade.models import SegmentConfig

# The authoritative GICS sector -> benchmark sector-SPDR ETF mapping (PRD §10).
EXPECTED_GICS_SECTOR_ETFS = {
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Energy": "XLE",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}
EXPECTED_ETFS = {"XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLRE", "XLU", "XLC"}


def test_gics_map_has_all_11_sectors_and_etfs():
    from openbb_techtrade.engine.screener import GICS_SECTOR_ETFS

    # Exactly the 11 GICS sectors, mapped to their exact benchmark ETFs.
    assert len(GICS_SECTOR_ETFS) == 11
    assert GICS_SECTOR_ETFS == EXPECTED_GICS_SECTOR_ETFS
    assert set(GICS_SECTOR_ETFS.values()) == EXPECTED_ETFS
    # 11 distinct ETFs (no duplicate symbols across sectors).
    assert len(set(GICS_SECTOR_ETFS.values())) == 11


def test_list_segments_returns_11_segmentconfigs():
    from openbb_techtrade.engine.screener import GICS_SECTOR_ETFS, list_segments

    segments = list_segments()
    assert len(segments) == 11
    assert all(isinstance(seg, SegmentConfig) for seg in segments)

    for seg in segments:
        # Every segment is one of the known GICS sectors, with the mapped ETF.
        assert seg.segment in GICS_SECTOR_ETFS
        assert seg.benchmark_etf == GICS_SECTOR_ETFS[seg.segment]
        # Placeholder defaults per the issue.
        assert seg.universe_source == "etf_holdings"
        assert seg.rank_metric == "pct_change"
        assert seg.top_n == 10

    # All 11 sectors are represented exactly once, in canonical map order.
    assert [seg.segment for seg in segments] == list(GICS_SECTOR_ETFS)


def test_list_segments_respects_overrides():
    from openbb_techtrade.engine.screener import list_segments

    segments = list_segments(universe_source="constituent_list", rank_metric="volume", top_n=5)
    assert len(segments) == 11
    for seg in segments:
        assert seg.universe_source == "constituent_list"
        assert seg.rank_metric == "volume"
        assert seg.top_n == 5
        # The benchmark ETF is still populated regardless of the universe source.
        assert seg.benchmark_etf is not None


def test_segments_command_returns_obbject_with_11():
    from openbb_techtrade.engine.screener_router import segments

    result = segments()
    assert isinstance(result, OBBject)
    assert isinstance(result.results, list)
    assert len(result.results) == 11
    assert all(isinstance(seg, SegmentConfig) for seg in result.results)


def test_segments_command_propagates_overrides():
    from openbb_techtrade.engine.screener_router import segments

    # The router's keyword pass-through must reach every SegmentConfig.
    result = segments(universe_source="screener", rank_metric="gap", top_n=3)
    assert len(result.results) == 11
    for seg in result.results:
        assert seg.universe_source == "screener"
        assert seg.rank_metric == "gap"
        assert seg.top_n == 3


def test_segments_route_registered():
    from openbb_techtrade.techtrade_router import router

    # Commands are FastAPI routes on `router.api_router.routes`, each with a `.path`.
    paths = {getattr(route, "path", None) for route in router.api_router.routes}
    assert "/segments" in paths
