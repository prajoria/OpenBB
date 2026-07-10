"""Unit tests for the multi-tier FMPCachedEtfHoldingsFetcher (#97 T5).

All offline -- _get_cached/_store target a mocked execute_query/execute_many,
the FMP tier is mocked, the issuer tier is mocked. No live network.

Mirrors test_institutional_ownership_cached.py patterns: per-tier fakes for
the fallback chain, JSON-blob cache via existing etf_holdings table.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from openbb_fmp.models.etf_holdings import FMPEtfHoldingsFetcher  # noqa: F401


@pytest.fixture
def event_loop():
    """Override session-scoped event loop fixture to avoid pytest-asyncio introspection bug."""
    import asyncio

    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Module under test
from openbb_fmp_cached.models.etf_holdings import (  # noqa: E402
    FMPCachedEtfHoldingsFetcher,
    _get_cached_etf_holdings,
    _store_etf_holdings,
    _try_fmp,
    _try_issuer,
    _try_nport,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _etf_row(
    symbol: str = "AAPL", weight: float = 0.235, data_source: str = "issuer_ssga"
) -> dict:
    """Build a minimal ETF holding row in the normalized dict shape."""
    return {
        "symbol": symbol,
        "name": f"{symbol} INC",
        "weight": weight,
        "shares": 1_000_000,
        "value": None,
        "cusip": "037833100" if symbol == "AAPL" else None,
        "isin": None,
        "data_source": data_source,
    }


def _fake_query():
    """Build a FMPEtfHoldingsQueryParams stand-in for XLK."""
    from openbb_fmp.models.etf_holdings import FMPEtfHoldingsQueryParams

    return FMPEtfHoldingsQueryParams(symbol="XLK")


# ---------------------------------------------------------------------------
# _get_cached_etf_holdings: JSON-blob cache reads
# ---------------------------------------------------------------------------


def test_get_cached_etf_holdings_returns_decoded_rows():
    """Cache rows have JSON in data_json; we decode them back to dicts."""
    blob = [_etf_row("AAPL"), _etf_row("MSFT", 0.19)]
    db_rows = [{"data_json": json.dumps(payload)} for payload in blob]
    with patch(
        "openbb_fmp_cached.models.etf_holdings.execute_query", return_value=db_rows
    ):
        result = _get_cached_etf_holdings("XLK")
    assert len(result) == 2
    assert result[0]["symbol"] == "AAPL"
    assert result[1]["symbol"] == "MSFT"


def test_get_cached_etf_holdings_handles_already_decoded_dict():
    """MySQL JSON columns may return dict, not str. Both paths work."""
    blob = [_etf_row("AAPL")]
    db_rows = [{"data_json": blob[0]}]  # already a dict
    with patch(
        "openbb_fmp_cached.models.etf_holdings.execute_query", return_value=db_rows
    ):
        result = _get_cached_etf_holdings("XLK")
    assert result == [blob[0]]


def test_get_cached_etf_holdings_empty_table_returns_empty():
    """No rows in cache -> []."""
    with patch("openbb_fmp_cached.models.etf_holdings.execute_query", return_value=[]):
        assert _get_cached_etf_holdings("XLK") == []


def test_get_cached_etf_holdings_db_error_returns_empty():
    """Cache failure -> [] (graceful)."""
    with patch(
        "openbb_fmp_cached.models.etf_holdings.execute_query",
        side_effect=RuntimeError("DB down"),
    ):
        assert _get_cached_etf_holdings("XLK") == []


def test_get_cached_etf_holdings_uppercases_symbol():
    """Lowercase input is upper-cased before the SQL params."""
    captured = {}

    def execute_query(sql, params=()):
        captured["params"] = params
        return []

    with patch(
        "openbb_fmp_cached.models.etf_holdings.execute_query", side_effect=execute_query
    ):
        _get_cached_etf_holdings("xlk")
    assert captured["params"][0] == "XLK"


# ---------------------------------------------------------------------------
# _store_etf_holdings: delete-then-insert per ETF, JSON-blob persistence
# ---------------------------------------------------------------------------


def test_store_etf_holdings_writes_one_row_per_holding():
    """Each holding dict becomes one (symbol, data_json) row.

    Post-bd-n3sf: DELETE + INSERT are now routed through replace_rows()
    for atomicity. The unit-test surface changes: instead of separately
    asserting DELETE fired and INSERT fired, we assert replace_rows was
    called exactly once with the ETF symbol as the where_val and 2 rows.
    """
    rows = [_etf_row("AAPL"), _etf_row("MSFT", 0.19)]
    captured = {"call": None}
    with patch(
        "openbb_fmp_cached.models.etf_holdings.replace_rows",
        side_effect=lambda *a, **kw: captured.__setitem__("call", (a, kw)) or len(a[3]),
    ):
        _store_etf_holdings("XLK", rows, data_source="issuer_ssga")
    assert captured["call"] is not None
    args, _ = captured["call"]
    assert args[0] == "etf_holdings"  # table
    assert args[1] == "symbol"  # where_col
    assert args[2] == "XLK"  # where_val (etf symbol)
    assert len(args[3]) == 2  # 2 rows


def test_store_etf_holdings_skips_when_empty():
    """Empty rows -> no-op (no replace_rows call)."""
    with patch(
        "openbb_fmp_cached.models.etf_holdings.replace_rows",
        side_effect=AssertionError("must NOT be called"),
    ):
        _store_etf_holdings("XLK", [], data_source="fmp")


def test_store_etf_holdings_attaches_data_source_tag():
    """The data_source param overrides whatever the row dicts had."""
    rows = [_etf_row("AAPL", data_source="fmp")]  # tag will be overridden
    captured = {"rows": None}
    with patch(
        "openbb_fmp_cached.models.etf_holdings.replace_rows",
        side_effect=lambda *a, **kw: captured.__setitem__("rows", a[3]) or len(a[3]),
    ):
        _store_etf_holdings("XLK", rows, data_source="issuer_ssga")
    # replace_rows was passed dict rows; each has a data_json blob.
    inserted_rows = captured["rows"]
    assert inserted_rows is not None and len(inserted_rows) == 1
    payload = json.loads(inserted_rows[0]["data_json"])
    assert payload["data_source"] == "issuer_ssga"


# ---------------------------------------------------------------------------
# _try_fmp / _try_issuer / _try_nport: each tier returns [] on error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_try_fmp_returns_results_on_success():
    """Happy path: FMPEtfHoldingsFetcher.aextract_data returns rows."""
    expected = [_etf_row("AAPL", data_source="fmp")]
    with patch.object(
        FMPEtfHoldingsFetcher, "aextract_data", new=AsyncMock(return_value=expected)
    ):
        result = await _try_fmp(_fake_query(), "XLK", credentials={"fmp_api_key": "x"})
    assert result == expected


@pytest.mark.asyncio
async def test_try_fmp_returns_empty_on_402():
    """402 from FMP -> [] (the original #97 motivation)."""
    with patch.object(
        FMPEtfHoldingsFetcher,
        "aextract_data",
        new=AsyncMock(side_effect=Exception("402 Restricted Endpoint")),
    ):
        result = await _try_fmp(_fake_query(), "XLK", credentials={"fmp_api_key": "x"})
    assert result == []


@pytest.mark.asyncio
async def test_try_issuer_returns_rows_for_spdr_etf():
    """Issuer-tier wraps fetch_issuer_holdings; XLK is in ISSUER_REGISTRY."""
    expected = [
        _etf_row("AAPL", data_source="issuer_ssga"),
        _etf_row("MSFT", 0.19, data_source="issuer_ssga"),
    ]
    with patch(
        "openbb_fmp_cached.models.etf_holdings_issuer.fetch_issuer_holdings",
        return_value=expected,
    ):
        result = await _try_issuer("XLK")
    assert result == expected


@pytest.mark.asyncio
async def test_try_issuer_returns_empty_on_error():
    """Any exception from the issuer-tier helper -> [] (graceful)."""
    with patch(
        "openbb_fmp_cached.models.etf_holdings_issuer.fetch_issuer_holdings",
        side_effect=RuntimeError("issuer broke"),
    ):
        assert await _try_issuer("XLK") == []


@pytest.mark.asyncio
async def test_try_nport_is_a_stub_until_t2_t3_land():
    """N-PORT tier is deferred (T2/T3 follow-up); _try_nport returns [] for v1."""
    assert await _try_nport("XLK") == []


# ---------------------------------------------------------------------------
# Full chain: cache → FMP → issuer → N-PORT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_cache_hit_short_circuits_all_other_tiers():
    """A fresh cache hit means we never call FMP / issuer / N-PORT."""
    cached = [_etf_row("AAPL"), _etf_row("MSFT", 0.19)]
    with patch(
        "openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
        return_value=cached,
    ), patch("openbb_fmp_cached.models.etf_holdings.init_database"), patch(
        "openbb_fmp_cached.models.etf_holdings._try_fmp",
        side_effect=AssertionError("must NOT be called"),
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._try_issuer",
        side_effect=AssertionError("must NOT be called"),
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._try_nport",
        side_effect=AssertionError("must NOT be called"),
    ):
        result = await FMPCachedEtfHoldingsFetcher.aextract_data(
            _fake_query(),
            credentials={"fmp_api_key": "x"},
        )
    assert result == cached


@pytest.mark.asyncio
async def test_chain_fmp_402_falls_through_to_issuer():
    """When FMP returns [] (e.g. 402), issuer tier fires next."""
    issuer_rows = [_etf_row("AAPL", data_source="issuer_ssga")]
    with patch(
        "openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
        return_value=[],
    ), patch("openbb_fmp_cached.models.etf_holdings.init_database"), patch(
        "openbb_fmp_cached.models.etf_holdings._try_fmp", new=AsyncMock(return_value=[])
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._try_issuer",
        new=AsyncMock(return_value=issuer_rows),
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._try_nport",
        side_effect=AssertionError("must NOT be called"),
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._store_etf_holdings"
    ):
        result = await FMPCachedEtfHoldingsFetcher.aextract_data(
            _fake_query(),
            credentials={"fmp_api_key": "x"},
        )
    assert result == issuer_rows


@pytest.mark.asyncio
async def test_chain_issuer_empty_falls_through_to_nport():
    """Issuer-tier empty -> N-PORT tier fires."""
    nport_rows = [_etf_row("AAPL", data_source="sec_nport")]
    with patch(
        "openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
        return_value=[],
    ), patch("openbb_fmp_cached.models.etf_holdings.init_database"), patch(
        "openbb_fmp_cached.models.etf_holdings._try_fmp", new=AsyncMock(return_value=[])
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._try_issuer",
        new=AsyncMock(return_value=[]),
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._try_nport",
        new=AsyncMock(return_value=nport_rows),
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._store_etf_holdings"
    ):
        result = await FMPCachedEtfHoldingsFetcher.aextract_data(
            _fake_query(),
            credentials={"fmp_api_key": "x"},
        )
    assert result == nport_rows


@pytest.mark.asyncio
async def test_chain_all_tiers_empty_returns_empty_never_raises():
    """Everything empty -> [] (never raises)."""
    with patch(
        "openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
        return_value=[],
    ), patch("openbb_fmp_cached.models.etf_holdings.init_database"), patch(
        "openbb_fmp_cached.models.etf_holdings._try_fmp", new=AsyncMock(return_value=[])
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._try_issuer",
        new=AsyncMock(return_value=[]),
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._try_nport",
        new=AsyncMock(return_value=[]),
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._store_etf_holdings"
    ):
        result = await FMPCachedEtfHoldingsFetcher.aextract_data(
            _fake_query(),
            credentials={"fmp_api_key": "x"},
        )
    assert result == []


@pytest.mark.asyncio
async def test_chain_winning_tier_persists_with_its_data_source_tag():
    """When the issuer tier wins, _store_etf_holdings is called with 'issuer_ssga'."""
    issuer_rows = [_etf_row("AAPL", data_source="issuer_ssga")]
    captured = {}

    def fake_store(etf, rows, data_source):
        captured["etf"] = etf
        captured["data_source"] = data_source

    with patch(
        "openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
        return_value=[],
    ), patch("openbb_fmp_cached.models.etf_holdings.init_database"), patch(
        "openbb_fmp_cached.models.etf_holdings._try_fmp", new=AsyncMock(return_value=[])
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._try_issuer",
        new=AsyncMock(return_value=issuer_rows),
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._try_nport",
        new=AsyncMock(return_value=[]),
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._store_etf_holdings",
        side_effect=fake_store,
    ):
        await FMPCachedEtfHoldingsFetcher.aextract_data(
            _fake_query(),
            credentials={"fmp_api_key": "x"},
        )
    assert captured == {"etf": "XLK", "data_source": "issuer_ssga"}


@pytest.mark.asyncio
async def test_chain_fmp_winning_stores_with_fmp_tag():
    """FMP wins -> stored with 'fmp' tag."""
    fmp_rows = [_etf_row("AAPL", data_source="fmp")]
    captured = {}
    with patch(
        "openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
        return_value=[],
    ), patch("openbb_fmp_cached.models.etf_holdings.init_database"), patch(
        "openbb_fmp_cached.models.etf_holdings._try_fmp",
        new=AsyncMock(return_value=fmp_rows),
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._try_issuer",
        side_effect=AssertionError("must NOT be called"),
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._try_nport",
        side_effect=AssertionError("must NOT be called"),
    ), patch(
        "openbb_fmp_cached.models.etf_holdings._store_etf_holdings",
        side_effect=lambda etf, rows, data_source: captured.update({"ds": data_source}),
    ):
        await FMPCachedEtfHoldingsFetcher.aextract_data(
            _fake_query(),
            credentials={"fmp_api_key": "x"},
        )
    assert captured == {"ds": "fmp"}
