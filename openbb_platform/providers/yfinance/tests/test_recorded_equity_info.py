"""Tests for the snapshot-backed yfinance equity-info fetcher (#1375)."""

from __future__ import annotations

import asyncio

import pytest
from openbb_yfinance.models.recorded_equity_info import (
    YFinanceEquityInfoRecordedData,
    YFinanceEquityInfoRecordedFetcher,
    _load_extracted,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_equity_info_recorded_registered_in_provider():
    from openbb_yfinance import yfinance_provider

    assert "EquityInfoRecorded" in yfinance_provider.fetcher_dict


def test_load_extracted_reads_committed_msft_fixture():
    extracted = _load_extracted("MSFT")
    assert extracted["symbol"] == "MSFT"
    assert extracted["sector"] == "Technology"
    assert extracted["industry"] == "Software - Infrastructure"
    assert extracted["full_time_employees"] == 221000


def test_load_extracted_raises_on_missing_symbol():
    from openbb_core.provider.utils.errors import EmptyDataError

    with pytest.raises(EmptyDataError, match="scrape-record record yahoo_equity_info"):
        _load_extracted("ZZZ_NOT_A_REAL_SYMBOL")


def test_equity_info_recorded_returns_typed_row():
    query = YFinanceEquityInfoRecordedFetcher.transform_query({"symbol": "MSFT"})
    raw = _run(YFinanceEquityInfoRecordedFetcher.aextract_data(query, None))
    result = YFinanceEquityInfoRecordedFetcher.transform_data(query, raw)
    assert isinstance(result, YFinanceEquityInfoRecordedData)
    assert result.symbol == "MSFT"
    assert result.sector == "Technology"
    assert "Microsoft" in (result.long_business_summary or "")
    assert result.website == "https://www.microsoft.com"


def test_symbol_pattern_rejects_path_traversal():
    from pydantic import ValidationError

    for bad in ("../etc/passwd", "MSFT/../etc", "MSFT\x00"):
        with pytest.raises(ValidationError):
            YFinanceEquityInfoRecordedFetcher.transform_query({"symbol": bad})
