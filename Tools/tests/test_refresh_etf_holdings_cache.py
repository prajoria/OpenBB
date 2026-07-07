"""Unit tests for ``Tools/refresh_etf_holdings_cache.py``.

All tests are offline -- the obb provider call is mocked, the DB connection
is patched, and no live network/cache writes happen. Mirrors the
``Tools/tests/test_enrich_cusip_figi.py`` test patterns (sys.path bootstrap,
MagicMock-based fakes).
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

# Make the Tools/ directory importable when running from the repo root.
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

# Make the techtrade extension importable for the regression test.
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _p in (
    os.path.join(_REPO_ROOT, "openbb_platform", "providers", "fmp_cached"),
    os.path.join(_REPO_ROOT, "openbb_platform", "extensions", "techtrade"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import refresh_etf_holdings_cache as tool  # noqa: E402

# ---------------------------------------------------------------------------
# L9 regression: SPDR_SECTORS is derived from techtrade GICS_SECTOR_ETFS
# ---------------------------------------------------------------------------


def test_spdr_sectors_matches_techtrade_gics_sector_etfs():
    """SPDR_SECTORS must equal the set of techtrade's GICS_SECTOR_ETFS values (L9)."""
    from openbb_techtrade.engine.screener import GICS_SECTOR_ETFS

    assert set(tool.SPDR_SECTORS) == set(GICS_SECTOR_ETFS.values()), (
        "SPDR_SECTORS drift detected. Either (a) techtrade's GICS_SECTOR_ETFS "
        "changed -- update the fallback constant in refresh_etf_holdings_cache.py, "
        "or (b) the module's runtime derivation broke."
    )


def test_spdr_sectors_has_eleven_tickers():
    """The GICS taxonomy has 11 sectors; the SPDR tuple must reflect that."""
    assert len(tool.SPDR_SECTORS) == 11


def test_known_etfs_is_superset_of_spdr_sectors():
    """Every SPDR sector ETF must be in KNOWN_ETFS so the portfolio filter accepts it."""
    assert set(tool.SPDR_SECTORS).issubset(tool.KNOWN_ETFS)


def test_known_etfs_excludes_common_non_etfs():
    """Sanity: heavily-held single stocks must not look like ETFs to the filter."""
    for non_etf in ("AAPL", "MSFT", "GOOGL", "NVDA", "META"):
        assert non_etf not in tool.KNOWN_ETFS


# ---------------------------------------------------------------------------
# list_portfolio_etfs: KNOWN_ETFS filter applied to Portfolio_Positions
# ---------------------------------------------------------------------------


def _fake_connection(rows):
    """Return a MagicMock that simulates a fmp_cached get_connection() context."""
    fake_cursor = MagicMock()
    fake_cursor.fetchall.return_value = rows
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.cursor.return_value.__exit__.return_value = False
    return fake_conn


def test_list_portfolio_etfs_filters_by_known_set():
    """Mixed Portfolio_Positions symbols -- only KNOWN_ETFS pass through."""
    rows = [
        {"symbol": "AAPL"},
        {"symbol": "IVV"},
        {"symbol": "MSFT"},
        {"symbol": "QQQ"},
        {"symbol": "VTI"},
        {"symbol": "NVDA"},
    ]
    with patch.object(tool, "_connect", return_value=_fake_connection(rows)):
        result = tool.list_portfolio_etfs(database=None)
    assert result == ["IVV", "QQQ", "VTI"]  # sorted, uppercased, non-ETFs dropped


def test_list_portfolio_etfs_returns_empty_on_db_error():
    """Graceful degradation: connect/read failure -> [] (no exception)."""
    with patch.object(tool, "_connect", side_effect=RuntimeError("DB down")):
        result = tool.list_portfolio_etfs(database=None)
    assert result == []


def test_list_portfolio_etfs_handles_uppercase_inconsistency():
    """Portfolio rows arriving in mixed case still resolve through KNOWN_ETFS."""
    rows = [{"symbol": "ivv"}, {"symbol": "Voo"}, {"symbol": "qqq"}]
    with patch.object(tool, "_connect", return_value=_fake_connection(rows)):
        result = tool.list_portfolio_etfs(database=None)
    assert result == ["IVV", "QQQ", "VOO"]


# ---------------------------------------------------------------------------
# resolve_universe: union + dedup + uppercase + skip-portfolio
# ---------------------------------------------------------------------------


def test_resolve_universe_unions_spdr_portfolio_extras():
    """All three sources should appear in the union, sorted."""
    with patch.object(tool, "list_portfolio_etfs", return_value=["IVV", "QQQ"]):
        result = tool.resolve_universe(
            database=None,
            skip_portfolio=False,
            extra_etfs=["VOO", "DIA"],
        )
    expected_min = set(tool.SPDR_SECTORS) | {"IVV", "QQQ", "VOO", "DIA"}
    assert set(result) == expected_min
    assert result == sorted(result)


def test_resolve_universe_dedupes():
    """Same ETF arriving from multiple sources appears once."""
    with patch.object(tool, "list_portfolio_etfs", return_value=["XLK", "IVV"]):
        result = tool.resolve_universe(
            database=None,
            skip_portfolio=False,
            extra_etfs=["XLK", "IVV", "VOO"],
        )
    # XLK is in SPDR_SECTORS AND portfolio AND extras -- still one entry
    assert result.count("XLK") == 1
    assert result.count("IVV") == 1


def test_resolve_universe_uppercases_and_strips_extras():
    """`--etfs ' ivv ,voo,'` -> {'IVV','VOO'}; blank tokens dropped."""
    with patch.object(tool, "list_portfolio_etfs", return_value=[]):
        result = tool.resolve_universe(
            database=None,
            skip_portfolio=False,
            extra_etfs=[" ivv ", "voo", "", "  "],
        )
    assert "IVV" in result
    assert "VOO" in result
    assert "" not in result
    assert "  " not in result


def test_resolve_universe_skip_portfolio_drops_portfolio_etfs():
    """`--skip-portfolio` ignores Portfolio_Positions entirely."""
    with patch.object(tool, "list_portfolio_etfs", return_value=["IVV", "QQQ"]):
        result = tool.resolve_universe(
            database=None,
            skip_portfolio=True,
            extra_etfs=None,
        )
    assert "IVV" not in result
    assert "QQQ" not in result
    # SPDRs still present
    for spdr in tool.SPDR_SECTORS:
        assert spdr in result


# ---------------------------------------------------------------------------
# refresh_one_etf: dry-run / error handling / data_source extraction
# ---------------------------------------------------------------------------


def test_refresh_one_etf_dry_run_makes_no_obb_call():
    """Dry-run returns a zero tuple without ever touching obb."""
    with patch.dict(sys.modules, {"openbb": MagicMock()}) as mods:
        mods["openbb"].obb.etf.holdings = MagicMock(
            side_effect=AssertionError("obb must NOT be called in dry-run"),
        )
        result = tool.refresh_one_etf("XLK", dry_run=True, api_key=None)
    etf, row_count, data_source, elapsed_ms, error = result
    assert etf == "XLK"
    assert row_count == 0
    assert data_source is None
    assert elapsed_ms == 0.0
    assert error is None


def test_refresh_one_etf_catches_402_returns_error_tuple():
    """A 402 / any exception from obb is caught + returned in the error slot."""
    fake_obb = MagicMock()
    fake_obb.obb.etf.holdings = MagicMock(
        side_effect=Exception("402 Restricted Endpoint (EtfHoldings)\nmore detail"),
    )
    with patch.dict(sys.modules, {"openbb": fake_obb}):
        result = tool.refresh_one_etf("XLK", dry_run=False, api_key=None)
    etf, row_count, data_source, elapsed_ms, error = result
    assert etf == "XLK"
    assert row_count == 0
    assert data_source is None
    # Error message: first line only (newlines stripped)
    assert "402 Restricted Endpoint" in (error or "")
    assert "\n" not in (error or "")


def test_refresh_one_etf_extracts_data_source_from_first_row_object():
    """When rows are objects with .data_source attr, we read it for tier attribution."""
    fake_row = MagicMock()
    fake_row.data_source = "issuer_ssga"
    fake_result = MagicMock(results=[fake_row, MagicMock(data_source="issuer_ssga")])
    fake_obb = MagicMock()
    fake_obb.obb.etf.holdings = MagicMock(return_value=fake_result)
    with patch.dict(sys.modules, {"openbb": fake_obb}):
        result = tool.refresh_one_etf("XLK", dry_run=False, api_key=None)
    etf, row_count, data_source, _elapsed, error = result
    assert etf == "XLK"
    assert row_count == 2
    assert data_source == "issuer_ssga"
    assert error is None


def test_refresh_one_etf_extracts_data_source_from_first_row_dict():
    """When rows are dicts (some providers normalize to dicts), still works."""
    fake_result = MagicMock(results=[{"data_source": "fmp", "symbol": "AAPL"}])
    fake_obb = MagicMock()
    fake_obb.obb.etf.holdings = MagicMock(return_value=fake_result)
    with patch.dict(sys.modules, {"openbb": fake_obb}):
        _, row_count, data_source, _, _ = tool.refresh_one_etf(
            "XLK",
            dry_run=False,
            api_key=None,
        )
    assert row_count == 1
    assert data_source == "fmp"


def test_refresh_one_etf_empty_results_yields_zero_rows_no_error():
    """Empty results is a distinct outcome from an exception (counted as 'empty')."""
    fake_result = MagicMock(results=[])
    fake_obb = MagicMock()
    fake_obb.obb.etf.holdings = MagicMock(return_value=fake_result)
    with patch.dict(sys.modules, {"openbb": fake_obb}):
        _, row_count, data_source, _, error = tool.refresh_one_etf(
            "XLK",
            dry_run=False,
            api_key=None,
        )
    assert row_count == 0
    assert data_source is None
    assert error is None


# ---------------------------------------------------------------------------
# refresh_universe: aggregates stats correctly
# ---------------------------------------------------------------------------


def test_refresh_universe_aggregates_stats_correctly():
    """Mix of populated/errored/empty per-ETF outcomes rolls up into the right counts."""
    outcomes = {
        "XLK": ("XLK", 75, "issuer_ssga", 120.0, None),  # populated
        "XLF": ("XLF", 72, "issuer_ssga", 110.0, None),  # populated
        "IVV": ("IVV", 0, None, 15.0, "402 Restricted"),  # errored
        "QQQ": ("QQQ", 0, None, 20.0, "402 Restricted"),  # errored
        "VTI": ("VTI", 0, None, 80.0, None),  # empty (no rows, no err)
    }
    with patch.object(
        tool,
        "refresh_one_etf",
        side_effect=lambda etf, **_kw: outcomes[etf],
    ):
        stats = tool.refresh_universe(
            list(outcomes.keys()),
            dry_run=False,
            api_key=None,
        )
    assert stats == {"requested": 5, "populated": 2, "errored": 2, "empty": 1}
