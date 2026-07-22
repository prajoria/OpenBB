"""Tests for the snapshot-backed yfinance bond-ladder fetcher (#1000)."""

from __future__ import annotations

import asyncio

import pytest
from openbb_yfinance.models.bond_ladder import (
    YFinanceBondHoldingData,
    YFinanceBondLadderData,
    YFinanceBondLadderFetcher,
    _load_extracted,
)


def _run(coro):
    """Run a coroutine synchronously (test helper)."""
    return asyncio.get_event_loop().run_until_complete(coro)


def test_bond_ladder_registered_in_provider():
    """Provider registration is what the coverage gate sees."""
    from openbb_yfinance import yfinance_provider

    assert "BondLadder" in yfinance_provider.fetcher_dict


def test_load_extracted_reads_committed_bnd_snapshot():
    """BND snapshot from PR must resolve via scrape_record."""
    extracted = _load_extracted("BND")
    assert extracted["etf_symbol"] == "BND"
    assert extracted["portfolio_avg_ytm"] == 4.85
    assert len(extracted["holdings"]) == 5


def test_load_extracted_raises_on_missing_etf():
    """Missing ETF raises EmptyDataError with recording command."""
    from openbb_core.provider.utils.errors import EmptyDataError

    with pytest.raises(
        EmptyDataError, match="scrape-record record yahoo_bond_etf_holdings"
    ):
        _load_extracted("XYZ_NOT_A_REAL_ETF")


def test_bond_ladder_returns_typed_row():
    """Fetcher returns a single YFinanceBondLadderData (not a list)."""
    query = YFinanceBondLadderFetcher.transform_query({"symbol": "BND"})
    raw = _run(YFinanceBondLadderFetcher.aextract_data(query, None))
    result = YFinanceBondLadderFetcher.transform_data(query, raw)
    assert isinstance(result, YFinanceBondLadderData)
    assert result.etf_symbol == "BND"
    assert result.portfolio_avg_ytm == 4.85
    assert result.portfolio_duration_years == 6.2
    assert len(result.holdings) == 5
    for h in result.holdings:
        assert isinstance(h, YFinanceBondHoldingData)


def test_bond_ladder_first_holding_is_treasury():
    """BND top holding in fixture is the Feb 2036 Treasury."""
    query = YFinanceBondLadderFetcher.transform_query({"symbol": "BND"})
    raw = _run(YFinanceBondLadderFetcher.aextract_data(query, None))
    result = YFinanceBondLadderFetcher.transform_data(query, raw)
    first = result.holdings[0]
    assert first.issuer == "United States Treasury Note/Bond"
    assert first.coupon == 4.5
    assert first.ytm == 4.32
    assert first.rating == "AAA"


def test_bond_ladder_carries_sector_and_credit_breakdowns():
    """Sector + credit-quality dicts survive round-trip."""
    query = YFinanceBondLadderFetcher.transform_query({"symbol": "BND"})
    raw = _run(YFinanceBondLadderFetcher.aextract_data(query, None))
    result = YFinanceBondLadderFetcher.transform_data(query, raw)
    assert result.sector_weights["Treasury"] == pytest.approx(0.42)
    assert result.credit_quality_breakdown["AAA"] == pytest.approx(0.68)


def test_symbol_pattern_rejects_path_traversal():
    """ETF symbol pattern rejects slashes at pydantic layer."""
    from pydantic import ValidationError

    for bad in ("../etc/passwd", "BND/../etc", "BND\\..\\etc", "BND\x00"):
        with pytest.raises(ValidationError):
            YFinanceBondLadderFetcher.transform_query({"symbol": bad})


def test_dot_and_dotdot_rejected_at_snapshot_layer():
    """`.` and `..` pass pydantic (dot allowed for BRK.B) but caught by config."""
    from scrape_record.config import ConfigError

    for bad in ("..", "."):
        q = YFinanceBondLadderFetcher.transform_query({"symbol": bad})
        with pytest.raises(ConfigError):
            _load_extracted(q.symbol)


def test_symbol_upper_cased_before_lookup():
    """Lowercase input still resolves the BND snapshot."""
    query = YFinanceBondLadderFetcher.transform_query({"symbol": "bnd"})
    raw = _run(YFinanceBondLadderFetcher.aextract_data(query, None))
    result = YFinanceBondLadderFetcher.transform_data(query, raw)
    assert result.etf_symbol == "BND"
