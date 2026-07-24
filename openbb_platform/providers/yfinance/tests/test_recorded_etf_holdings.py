"""Tests for the snapshot-backed yfinance ETF-holdings fetcher (#1375)."""

from __future__ import annotations

import asyncio

import pytest
from openbb_yfinance.models.recorded_etf_holdings import (
    YFinanceEtfHoldingRecordedData,
    YFinanceEtfHoldingsRecordedFetcher,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_etf_holdings_recorded_registered_in_provider():
    from openbb_yfinance import yfinance_provider

    assert "EtfHoldingsRecorded" in yfinance_provider.fetcher_dict


def test_etf_holdings_recorded_returns_list_of_rows():
    query = YFinanceEtfHoldingsRecordedFetcher.transform_query({"symbol": "QQQ"})
    raw = _run(YFinanceEtfHoldingsRecordedFetcher.aextract_data(query, None))
    rows = YFinanceEtfHoldingsRecordedFetcher.transform_data(query, raw)
    assert isinstance(rows, list)
    assert len(rows) == 5
    for r in rows:
        assert isinstance(r, YFinanceEtfHoldingRecordedData)
        assert r.weight is not None


def test_first_holding_is_apple():
    query = YFinanceEtfHoldingsRecordedFetcher.transform_query({"symbol": "QQQ"})
    raw = _run(YFinanceEtfHoldingsRecordedFetcher.aextract_data(query, None))
    rows = YFinanceEtfHoldingsRecordedFetcher.transform_data(query, raw)
    assert rows[0].symbol == "AAPL"
    assert rows[0].weight == pytest.approx(0.089)


def test_raises_on_missing_etf():
    from openbb_core.provider.utils.errors import EmptyDataError

    query = YFinanceEtfHoldingsRecordedFetcher.transform_query({"symbol": "NOETF"})
    with pytest.raises(EmptyDataError, match="scrape-record record yahoo_etf_holdings"):
        _run(YFinanceEtfHoldingsRecordedFetcher.aextract_data(query, None))


def test_symbol_pattern_rejects_path_traversal():
    from pydantic import ValidationError

    for bad in ("../etc/passwd", "QQQ/../etc", "QQQ\x00"):
        with pytest.raises(ValidationError):
            YFinanceEtfHoldingsRecordedFetcher.transform_query({"symbol": bad})


def test_symbol_upper_cased_before_lookup():
    query = YFinanceEtfHoldingsRecordedFetcher.transform_query({"symbol": "qqq"})
    raw = _run(YFinanceEtfHoldingsRecordedFetcher.aextract_data(query, None))
    rows = YFinanceEtfHoldingsRecordedFetcher.transform_data(query, raw)
    assert len(rows) == 5  # snapshot loaded via upper-cased key
