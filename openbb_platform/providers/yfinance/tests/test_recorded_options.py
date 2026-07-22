"""Tests for the snapshot-backed yfinance options fetchers (#999)."""

from __future__ import annotations

import asyncio

import pytest
from openbb_yfinance.models.recorded_options import (
    YFinanceAtmIvTermRowData,
    YFinanceAtmIvTermStructureFetcher,
    YFinanceRecordedOptionData,
    YFinanceRecordedOptionsChainsFetcher,
    _load_extracted,
)


def _run(coro):
    """Run a coroutine synchronously (test helper)."""
    return asyncio.get_event_loop().run_until_complete(coro)


def test_both_fetchers_registered_in_provider():
    """Provider registration is what the coverage gate sees."""
    from openbb_yfinance import yfinance_provider

    assert "OptionsChainsRecorded" in yfinance_provider.fetcher_dict
    assert "AtmIvTermStructure" in yfinance_provider.fetcher_dict


def test_load_extracted_reads_committed_aapl_snapshot():
    """The AAPL snapshot from PR #1349 must resolve via scrape_record."""
    extracted = _load_extracted("AAPL")
    assert extracted["symbol"] == "AAPL"
    assert extracted["spot"] == pytest.approx(327.74)
    assert len(extracted["chains"]) == 2
    assert len(extracted["atm_iv_term"]) == 2


def test_load_extracted_raises_on_missing_symbol():
    """A symbol without a snapshot raises the platform-idiomatic EmptyDataError."""
    from openbb_core.provider.utils.errors import EmptyDataError

    with pytest.raises(EmptyDataError, match="scrape-record record"):
        _load_extracted("XYZ_NOT_A_REAL_SYMBOL")


def test_recorded_options_chains_returns_flat_contract_rows():
    """Full-chain fetcher produces a flat list with side + expiry per contract."""
    query = YFinanceRecordedOptionsChainsFetcher.transform_query({"symbol": "AAPL"})
    raw = _run(YFinanceRecordedOptionsChainsFetcher.aextract_data(query, None))
    rows = YFinanceRecordedOptionsChainsFetcher.transform_data(query, raw)
    # AAPL fixture: 2 expiries × (2 calls + 2 puts) = 8 rows
    assert len(rows) == 8
    for row in rows:
        assert isinstance(row, YFinanceRecordedOptionData)
        assert row.side in ("call", "put")
        assert row.expiration_unix > 0
        assert row.strike is not None
        assert row.implied_volatility is not None


def test_atm_iv_term_structure_returns_one_row_per_expiry():
    """ATM IV term fetcher: 2 expiries in AAPL fixture → 2 rows."""
    query = YFinanceAtmIvTermStructureFetcher.transform_query({"symbol": "AAPL"})
    raw = _run(YFinanceAtmIvTermStructureFetcher.aextract_data(query, None))
    rows = YFinanceAtmIvTermStructureFetcher.transform_data(query, raw)
    assert len(rows) == 2
    for row in rows:
        assert isinstance(row, YFinanceAtmIvTermRowData)
        assert row.atm_strike == 330.0  # closest-to-spot (327.74) in fixture
        assert row.call_iv is not None
        assert row.put_iv is not None
        assert 0.20 <= row.call_iv <= 0.40
        assert row.call_contract_symbol is not None
        assert row.put_contract_symbol is not None


def test_atm_iv_term_rows_sorted_chronologically():
    """Rows come back in expiration_unix ascending order (matches extractor)."""
    query = YFinanceAtmIvTermStructureFetcher.transform_query({"symbol": "AAPL"})
    raw = _run(YFinanceAtmIvTermStructureFetcher.aextract_data(query, None))
    rows = YFinanceAtmIvTermStructureFetcher.transform_data(query, raw)
    exps = [r.expiration_unix for r in rows]
    assert exps == sorted(exps)


def test_symbol_is_upper_cased_before_snapshot_lookup():
    """Lowercase symbol input still finds the AAPL snapshot on disk."""
    query = YFinanceAtmIvTermStructureFetcher.transform_query({"symbol": "aapl"})
    raw = _run(YFinanceAtmIvTermStructureFetcher.aextract_data(query, None))
    rows = YFinanceAtmIvTermStructureFetcher.transform_data(query, raw)
    assert len(rows) == 2


def test_query_params_require_symbol():
    """Missing symbol raises pydantic ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        YFinanceRecordedOptionsChainsFetcher.transform_query({})


def test_symbol_pattern_rejects_path_traversal():
    """Symbol pydantic pattern rejects slashes (first-line defense)."""
    from pydantic import ValidationError

    for bad in ("../etc/passwd", "AAPL/../etc", "AAPL\\..\\etc"):
        with pytest.raises(ValidationError):
            YFinanceRecordedOptionsChainsFetcher.transform_query({"symbol": bad})


def test_dot_and_dotdot_rejected_at_snapshot_path_layer():
    """Bare '.' and '..' pass pydantic (dot allowed for BRK.B) but caught by config."""
    from scrape_record.config import ConfigError

    for bad in ("..", "."):
        q = YFinanceRecordedOptionsChainsFetcher.transform_query({"symbol": bad})
        with pytest.raises(ConfigError):
            _load_extracted(q.symbol)


def test_symbol_pattern_rejects_null_byte():
    """NUL byte in symbol rejected at pydantic layer."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        YFinanceRecordedOptionsChainsFetcher.transform_query({"symbol": "AAPL\x00"})


def test_symbol_pattern_rejects_overlong():
    """Symbol > 32 chars rejected."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        YFinanceRecordedOptionsChainsFetcher.transform_query({"symbol": "A" * 33})


def test_symbol_pattern_accepts_finance_legit_forms():
    """Pattern allows BRK.B, BRK-B, ^GSPC, CL=F, OCC option symbols."""
    for good in ("AAPL", "BRK.B", "BRK-B", "^GSPC", "CL=F", "AAPL251230C00325000"):
        q = YFinanceRecordedOptionsChainsFetcher.transform_query({"symbol": good})
        assert q.symbol == good
