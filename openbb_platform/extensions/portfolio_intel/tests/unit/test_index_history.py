"""Unit tests for index-constituent history refresh + point-in-time (#543)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from openbb_portfolio_intel.data.index_history import (
    SUPPORTED_INDICES,
    UNSUPPORTED_INDICES,
    ConstituentRow,
    IndexHistorySnapshot,
    clear_cache,
    get_snapshot,
    point_in_time,
    refresh,
    refresh_all,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """Every test starts from a clean cache."""
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# refresh — supported / unsupported / error paths
# ---------------------------------------------------------------------------


def _fake_current(rows: list[dict]):
    def _fetcher(idx: str, historical: bool) -> list[dict]:
        return [] if historical else rows

    return _fetcher


def _fake_both(current: list[dict], hist: list[dict]):
    def _fetcher(idx: str, historical: bool) -> list[dict]:
        return hist if historical else current

    return _fetcher


def test_refresh_supported_index_populates_snapshot() -> None:
    with patch(
        "openbb_portfolio_intel.data.index_history._fetch_constituents",
        side_effect=_fake_current(
            [{"symbol": "AAPL", "sector": "Tech"}, {"symbol": "MSFT", "sector": "Tech"}]
        ),
    ):
        snap = refresh("sp500", today=date(2026, 7, 20))
    assert snap.index_symbol == "sp500"
    assert snap.fetched_at == date(2026, 7, 20)
    assert len(snap.current) == 2
    assert {r.symbol for r in snap.current} == {"AAPL", "MSFT"}
    assert snap.warnings == []


def test_refresh_rejects_unsupported_index_with_gap_pointer() -> None:
    for idx in UNSUPPORTED_INDICES:
        with pytest.raises(ValueError, match=r"fmp-cached-gap"):
            refresh(idx, today=date(2026, 7, 20))


def test_refresh_rejects_unknown_index() -> None:
    with pytest.raises(ValueError, match=r"not a supported index"):
        refresh("bogus_index", today=date(2026, 7, 20))


def test_refresh_case_insensitive_index_symbol() -> None:
    with patch(
        "openbb_portfolio_intel.data.index_history._fetch_constituents",
        side_effect=_fake_current([{"symbol": "AAPL"}]),
    ):
        snap = refresh("SP500", today=date(2026, 7, 20))
    assert snap.index_symbol == "sp500"


def test_refresh_current_fetch_failure_degrades_partial() -> None:
    """Current fetch fails → warning, historical still populates."""

    def _fetcher(idx: str, historical: bool) -> list[dict]:
        if not historical:
            raise RuntimeError("simulated API 503")
        return [{"symbol": "OLD", "removed_symbol": "OLD", "date": date(2020, 1, 1)}]

    with patch(
        "openbb_portfolio_intel.data.index_history._fetch_constituents",
        side_effect=_fetcher,
    ):
        snap = refresh("sp500", today=date(2026, 7, 20))
    assert snap.current == []
    assert len(snap.historical) == 1
    assert any("current fetch failed" in w for w in snap.warnings)


def test_refresh_historical_fetch_failure_degrades_partial() -> None:
    def _fetcher(idx: str, historical: bool) -> list[dict]:
        if historical:
            raise RuntimeError("simulated API 503")
        return [{"symbol": "AAPL"}]

    with patch(
        "openbb_portfolio_intel.data.index_history._fetch_constituents",
        side_effect=_fetcher,
    ):
        snap = refresh("sp500", today=date(2026, 7, 20))
    assert len(snap.current) == 1
    assert snap.historical == []
    assert any("historical fetch failed" in w for w in snap.warnings)


def test_refresh_populates_module_cache() -> None:
    with patch(
        "openbb_portfolio_intel.data.index_history._fetch_constituents",
        side_effect=_fake_current([{"symbol": "AAPL"}]),
    ):
        refresh("sp500", today=date(2026, 7, 20))
    fetched = get_snapshot("sp500")
    assert fetched is not None
    assert fetched.index_symbol == "sp500"


# ---------------------------------------------------------------------------
# refresh_all
# ---------------------------------------------------------------------------


def test_refresh_all_walks_every_supported_index() -> None:
    with patch(
        "openbb_portfolio_intel.data.index_history._fetch_constituents",
        side_effect=_fake_current([{"symbol": "AAA"}]),
    ):
        result = refresh_all(today=date(2026, 7, 20))
    assert set(result.keys()) == set(SUPPORTED_INDICES)
    for snap in result.values():
        assert isinstance(snap, IndexHistorySnapshot)


def test_refresh_all_per_index_failure_isolated() -> None:
    """One index failing doesn't abort the walk — matches events-route posture."""

    def _fetcher(idx: str, historical: bool) -> list[dict]:
        if idx == "dowjones" and historical:
            raise RuntimeError("dow historical outage")
        return [] if historical else [{"symbol": f"SYM_{idx}"}]

    with patch(
        "openbb_portfolio_intel.data.index_history._fetch_constituents",
        side_effect=_fetcher,
    ):
        result = refresh_all(today=date(2026, 7, 20))
    assert set(result.keys()) == set(SUPPORTED_INDICES)
    assert result["sp500"].warnings == []
    assert any("historical fetch failed" in w for w in result["dowjones"].warnings)


# ---------------------------------------------------------------------------
# point_in_time reconstitution
# ---------------------------------------------------------------------------


def test_point_in_time_current_membership_when_no_events_after() -> None:
    snap = IndexHistorySnapshot(
        index_symbol="sp500",
        fetched_at=date(2026, 7, 20),
        current=[
            ConstituentRow("AAPL", "Tech", None, None, None, None),
            ConstituentRow("MSFT", "Tech", None, None, None, None),
        ],
        historical=[],
    )
    members = point_in_time(snap, as_of=date(2025, 1, 1))
    assert members == {"AAPL", "MSFT"}


def test_point_in_time_undoes_add_after_as_of() -> None:
    """A symbol added AFTER as_of should NOT be in the reconstituted set."""
    snap = IndexHistorySnapshot(
        index_symbol="sp500",
        fetched_at=date(2026, 7, 20),
        current=[
            ConstituentRow("AAPL", "Tech", None, None, None, None),
            ConstituentRow("NEWCO", "Tech", None, None, None, None),
        ],
        historical=[
            # NEWCO was added on 2026-06-01; as of 2026-01-01, wasn't in yet.
            ConstituentRow(
                symbol="NEWCO",
                sector=None,
                date_added=date(2026, 6, 1),
                removed_symbol=None,
                date=date(2026, 6, 1),
                reason="added",
            ),
        ],
    )
    members = point_in_time(snap, as_of=date(2026, 1, 1))
    assert "AAPL" in members
    assert "NEWCO" not in members


def test_point_in_time_readds_removed_after_as_of() -> None:
    """A symbol removed AFTER as_of should still be a member as of as_of."""
    snap = IndexHistorySnapshot(
        index_symbol="sp500",
        fetched_at=date(2026, 7, 20),
        current=[
            ConstituentRow("AAPL", "Tech", None, None, None, None),
        ],
        historical=[
            # OLDCO was removed 2026-06-01. As of 2026-01-01, still a member.
            ConstituentRow(
                symbol="AAPL",  # the replacement
                sector=None,
                date_added=date(2026, 6, 1),
                removed_symbol="OLDCO",
                date=date(2026, 6, 1),
                reason="removed",
            ),
        ],
    )
    members = point_in_time(snap, as_of=date(2026, 1, 1))
    # AAPL was added on the same event, undo → not present pre-event
    assert "AAPL" not in members
    assert "OLDCO" in members


def test_point_in_time_rejects_future_as_of() -> None:
    snap = IndexHistorySnapshot(
        index_symbol="sp500",
        fetched_at=date(2026, 7, 20),
        current=[],
        historical=[],
    )
    with pytest.raises(ValueError, match=r"cannot reconstitute future"):
        point_in_time(snap, as_of=date(2026, 8, 1))


def test_point_in_time_events_at_as_of_are_applied() -> None:
    """Events dated EXACTLY at as_of are considered applied (<=, not <)."""
    snap = IndexHistorySnapshot(
        index_symbol="sp500",
        fetched_at=date(2026, 7, 20),
        current=[ConstituentRow("NEWCO", "Tech", None, None, None, None)],
        historical=[
            ConstituentRow(
                symbol="NEWCO",
                sector=None,
                date_added=date(2026, 6, 1),
                removed_symbol=None,
                date=date(2026, 6, 1),
                reason="added",
            ),
        ],
    )
    members = point_in_time(snap, as_of=date(2026, 6, 1))
    assert "NEWCO" in members


# ---------------------------------------------------------------------------
# R7.11 reverse-verify — the point-in-time reconstitution is the load-bearing bit
# ---------------------------------------------------------------------------


def test_r711_add_undo_is_load_bearing() -> None:
    """If the undo-add branch were absent, NEWCO would incorrectly appear."""
    snap = IndexHistorySnapshot(
        index_symbol="sp500",
        fetched_at=date(2026, 7, 20),
        current=[ConstituentRow("NEWCO", "Tech", None, None, None, None)],
        historical=[
            ConstituentRow(
                symbol="NEWCO",
                sector=None,
                date_added=date(2026, 6, 1),
                removed_symbol=None,
                date=date(2026, 6, 1),
                reason="added",
            ),
        ],
    )
    # If we skip the historical walk entirely, this test would ERRONEOUSLY
    # return {"NEWCO"}. The production code correctly excludes it.
    members = point_in_time(snap, as_of=date(2026, 1, 1))
    assert members == set(), (
        "reverse-verify: without the undo-add branch, NEWCO would leak into "
        "the reconstituted set"
    )
