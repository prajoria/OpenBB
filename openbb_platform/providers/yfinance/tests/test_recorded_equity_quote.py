"""Tests for the snapshot-backed yfinance equity-quote fetcher (#1375, unblocks #1373)."""

from __future__ import annotations

import asyncio

import pytest
from openbb_yfinance.models.recorded_equity_quote import (
    YFinanceEquityQuoteRecordedData,
    YFinanceEquityQuoteRecordedFetcher,
    _load_extracted,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_equity_quote_recorded_registered_in_provider():
    """Provider registration is what the coverage gate sees."""
    from openbb_yfinance import yfinance_provider

    assert "EquityQuoteRecorded" in yfinance_provider.fetcher_dict


def test_load_extracted_reads_committed_msft_fixture():
    extracted = _load_extracted("MSFT")
    assert extracted["symbol"] == "MSFT"
    assert extracted["name"] == "Microsoft Corporation"
    assert extracted["last_price"] == 450.12


def test_load_extracted_raises_on_missing_symbol():
    from openbb_core.provider.utils.errors import EmptyDataError

    with pytest.raises(
        EmptyDataError, match="scrape-record record yahoo_equity_quote"
    ):
        _load_extracted("ZZZ_NOT_A_REAL_SYMBOL")


def test_equity_quote_recorded_returns_typed_row():
    query = YFinanceEquityQuoteRecordedFetcher.transform_query({"symbol": "MSFT"})
    raw = _run(YFinanceEquityQuoteRecordedFetcher.aextract_data(query, None))
    result = YFinanceEquityQuoteRecordedFetcher.transform_data(query, raw)
    assert isinstance(result, YFinanceEquityQuoteRecordedData)
    assert result.symbol == "MSFT"
    assert result.last_price == 450.12
    assert result.market_cap == 3350000000000
    assert result.volume == 12345678


def test_symbol_pattern_rejects_path_traversal():
    from pydantic import ValidationError

    for bad in ("../etc/passwd", "MSFT/../etc", "MSFT\\..\\etc", "MSFT\x00"):
        with pytest.raises(ValidationError):
            YFinanceEquityQuoteRecordedFetcher.transform_query({"symbol": bad})


def test_dot_and_dotdot_rejected_at_snapshot_layer():
    """Dot passes pydantic (BRK.B) but caught by scrape_record config."""
    from scrape_record.config import ConfigError

    for bad in ("..", "."):
        q = YFinanceEquityQuoteRecordedFetcher.transform_query({"symbol": bad})
        with pytest.raises(ConfigError):
            _load_extracted(q.symbol)


def test_symbol_upper_cased_before_lookup():
    query = YFinanceEquityQuoteRecordedFetcher.transform_query({"symbol": "msft"})
    raw = _run(YFinanceEquityQuoteRecordedFetcher.aextract_data(query, None))
    result = YFinanceEquityQuoteRecordedFetcher.transform_data(query, raw)
    assert result.symbol == "MSFT"
