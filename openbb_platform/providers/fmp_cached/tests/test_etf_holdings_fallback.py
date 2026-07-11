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


def _etf_row(symbol: str = "AAPL", weight: float = 0.235,
             data_source: str = "issuer_ssga") -> dict:
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
    with patch("openbb_fmp_cached.models.etf_holdings.execute_query",
               return_value=db_rows):
        result = _get_cached_etf_holdings("XLK")
    assert len(result) == 2
    assert result[0]["symbol"] == "AAPL"
    assert result[1]["symbol"] == "MSFT"


def test_get_cached_etf_holdings_handles_already_decoded_dict():
    """MySQL JSON columns may return dict, not str. Both paths work."""
    blob = [_etf_row("AAPL")]
    db_rows = [{"data_json": blob[0]}]  # already a dict
    with patch("openbb_fmp_cached.models.etf_holdings.execute_query",
               return_value=db_rows):
        result = _get_cached_etf_holdings("XLK")
    assert result == [blob[0]]


def test_get_cached_etf_holdings_empty_table_returns_empty():
    """No rows in cache -> []."""
    with patch("openbb_fmp_cached.models.etf_holdings.execute_query",
               return_value=[]):
        assert _get_cached_etf_holdings("XLK") == []


def test_get_cached_etf_holdings_db_error_returns_empty():
    """Cache failure -> [] (graceful)."""
    with patch("openbb_fmp_cached.models.etf_holdings.execute_query",
               side_effect=RuntimeError("DB down")):
        assert _get_cached_etf_holdings("XLK") == []


def test_get_cached_etf_holdings_uppercases_symbol():
    """Lowercase input is upper-cased before the SQL params."""
    captured = {}
    def execute_query(sql, params=()):
        captured["params"] = params
        return []
    with patch("openbb_fmp_cached.models.etf_holdings.execute_query",
               side_effect=execute_query):
        _get_cached_etf_holdings("xlk")
    assert captured["params"][0] == "XLK"


# ---------------------------------------------------------------------------
# _store_etf_holdings: delete-then-insert per ETF, JSON-blob persistence
# ---------------------------------------------------------------------------


def test_store_etf_holdings_writes_one_row_per_holding():
    """Each holding dict becomes one (symbol, etf, data_json, source) row."""
    rows = [_etf_row("AAPL"), _etf_row("MSFT", 0.19)]
    captured = {"delete": [], "insert": []}
    with patch("openbb_fmp_cached.models.etf_holdings.execute_query",
               side_effect=lambda sql, params=(): captured["delete"].append((sql, params))), \
         patch("openbb_fmp_cached.models.etf_holdings.execute_many",
               side_effect=lambda sql, p_list: captured["insert"].extend(p_list) or len(p_list)):
        _store_etf_holdings("XLK", rows, data_source="issuer_ssga")
    # DELETE first for clean slate
    assert len(captured["delete"]) == 1
    delete_sql, _ = captured["delete"][0]
    assert "DELETE FROM etf_holdings" in delete_sql
    # 2 INSERT rows
    assert len(captured["insert"]) == 2


def test_store_etf_holdings_skips_when_empty():
    """Empty rows -> no-op (no DELETE, no INSERT)."""
    with patch("openbb_fmp_cached.models.etf_holdings.execute_query",
               side_effect=AssertionError("must NOT be called")), \
         patch("openbb_fmp_cached.models.etf_holdings.execute_many",
               side_effect=AssertionError("must NOT be called")):
        _store_etf_holdings("XLK", [], data_source="fmp")


def test_store_etf_holdings_attaches_data_source_tag():
    """The data_source param overrides whatever the row dicts had."""
    rows = [_etf_row("AAPL", data_source="fmp")]  # tag will be overridden
    captured = {"insert": []}
    with patch("openbb_fmp_cached.models.etf_holdings.execute_query"), \
         patch("openbb_fmp_cached.models.etf_holdings.execute_many",
               side_effect=lambda sql, p_list: captured["insert"].extend(p_list) or len(p_list)):
        _store_etf_holdings("XLK", rows, data_source="issuer_ssga")
    # Decode the data_json blob and confirm the tag was set
    inserted = captured["insert"][0]
    # Tuple shape from institutional_ownership pattern: (symbol, date, data_json)
    # We adapt for ETF holdings: include etf_symbol in the JSON blob and use
    # holding symbol as primary key column
    payload = json.loads(inserted[-1]) if isinstance(inserted[-1], str) else inserted[-1]
    assert payload["data_source"] == "issuer_ssga"


# ---------------------------------------------------------------------------
# _try_fmp / _try_issuer / _try_nport: each tier returns [] on error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_try_fmp_returns_results_on_success():
    """Happy path: FMPEtfHoldingsFetcher.aextract_data returns rows."""
    expected = [_etf_row("AAPL", data_source="fmp")]
    with patch.object(FMPEtfHoldingsFetcher, "aextract_data",
                      new=AsyncMock(return_value=expected)):
        result = await _try_fmp(_fake_query(), "XLK", credentials={"fmp_api_key": "x"})
    assert result == expected


@pytest.mark.asyncio
async def test_try_fmp_returns_empty_on_402():
    """402 from FMP -> [] (the original #97 motivation)."""
    with patch.object(FMPEtfHoldingsFetcher, "aextract_data",
                      new=AsyncMock(side_effect=Exception("402 Restricted Endpoint"))):
        result = await _try_fmp(_fake_query(), "XLK", credentials={"fmp_api_key": "x"})
    assert result == []


@pytest.mark.asyncio
async def test_try_issuer_returns_rows_for_spdr_etf():
    """Issuer-tier wraps fetch_issuer_holdings; XLK is in ISSUER_REGISTRY."""
    expected = [_etf_row("AAPL", data_source="issuer_ssga"),
                _etf_row("MSFT", 0.19, data_source="issuer_ssga")]
    with patch("openbb_fmp_cached.models.etf_holdings_issuer.fetch_issuer_holdings",
               return_value=expected):
        result = await _try_issuer("XLK")
    assert result == expected


@pytest.mark.asyncio
async def test_try_issuer_returns_empty_on_error():
    """Any exception from the issuer-tier helper -> [] (graceful)."""
    with patch("openbb_fmp_cached.models.etf_holdings_issuer.fetch_issuer_holdings",
               side_effect=RuntimeError("issuer broke")):
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
    with patch("openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
               return_value=cached), \
         patch("openbb_fmp_cached.models.etf_holdings.init_database"), \
         patch("openbb_fmp_cached.models.etf_holdings._try_fmp",
               side_effect=AssertionError("must NOT be called")), \
         patch("openbb_fmp_cached.models.etf_holdings._try_issuer",
               side_effect=AssertionError("must NOT be called")), \
         patch("openbb_fmp_cached.models.etf_holdings._try_nport",
               side_effect=AssertionError("must NOT be called")):
        result = await FMPCachedEtfHoldingsFetcher.aextract_data(
            _fake_query(), credentials={"fmp_api_key": "x"},
        )
    assert result == cached


@pytest.mark.asyncio
async def test_chain_fmp_402_falls_through_to_issuer():
    """When FMP returns [] (e.g. 402), issuer tier fires next."""
    issuer_rows = [_etf_row("AAPL", data_source="issuer_ssga")]
    with patch("openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
               return_value=[]), \
         patch("openbb_fmp_cached.models.etf_holdings.init_database"), \
         patch("openbb_fmp_cached.models.etf_holdings._try_fmp",
               new=AsyncMock(return_value=[])), \
         patch("openbb_fmp_cached.models.etf_holdings._try_issuer",
               new=AsyncMock(return_value=issuer_rows)), \
         patch("openbb_fmp_cached.models.etf_holdings._try_nport",
               side_effect=AssertionError("must NOT be called")), \
         patch("openbb_fmp_cached.models.etf_holdings._store_etf_holdings"):
        result = await FMPCachedEtfHoldingsFetcher.aextract_data(
            _fake_query(), credentials={"fmp_api_key": "x"},
        )
    assert result == issuer_rows


@pytest.mark.asyncio
async def test_chain_issuer_empty_falls_through_to_nport():
    """Issuer-tier empty -> N-PORT tier fires."""
    nport_rows = [_etf_row("AAPL", data_source="sec_nport")]
    with patch("openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
               return_value=[]), \
         patch("openbb_fmp_cached.models.etf_holdings.init_database"), \
         patch("openbb_fmp_cached.models.etf_holdings._try_fmp",
               new=AsyncMock(return_value=[])), \
         patch("openbb_fmp_cached.models.etf_holdings._try_issuer",
               new=AsyncMock(return_value=[])), \
         patch("openbb_fmp_cached.models.etf_holdings._try_nport",
               new=AsyncMock(return_value=nport_rows)), \
         patch("openbb_fmp_cached.models.etf_holdings._store_etf_holdings"):
        result = await FMPCachedEtfHoldingsFetcher.aextract_data(
            _fake_query(), credentials={"fmp_api_key": "x"},
        )
    assert result == nport_rows


@pytest.mark.asyncio
async def test_chain_all_tiers_empty_returns_empty_never_raises():
    """Everything empty -> [] (never raises)."""
    with patch("openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
               return_value=[]), \
         patch("openbb_fmp_cached.models.etf_holdings.init_database"), \
         patch("openbb_fmp_cached.models.etf_holdings._try_fmp",
               new=AsyncMock(return_value=[])), \
         patch("openbb_fmp_cached.models.etf_holdings._try_issuer",
               new=AsyncMock(return_value=[])), \
         patch("openbb_fmp_cached.models.etf_holdings._try_nport",
               new=AsyncMock(return_value=[])), \
         patch("openbb_fmp_cached.models.etf_holdings._store_etf_holdings"):
        result = await FMPCachedEtfHoldingsFetcher.aextract_data(
            _fake_query(), credentials={"fmp_api_key": "x"},
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
    with patch("openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
               return_value=[]), \
         patch("openbb_fmp_cached.models.etf_holdings.init_database"), \
         patch("openbb_fmp_cached.models.etf_holdings._try_fmp",
               new=AsyncMock(return_value=[])), \
         patch("openbb_fmp_cached.models.etf_holdings._try_issuer",
               new=AsyncMock(return_value=issuer_rows)), \
         patch("openbb_fmp_cached.models.etf_holdings._try_nport",
               new=AsyncMock(return_value=[])), \
         patch("openbb_fmp_cached.models.etf_holdings._store_etf_holdings",
               side_effect=fake_store):
        await FMPCachedEtfHoldingsFetcher.aextract_data(
            _fake_query(), credentials={"fmp_api_key": "x"},
        )
    assert captured == {"etf": "XLK", "data_source": "issuer_ssga"}


@pytest.mark.asyncio
async def test_chain_fmp_winning_stores_with_fmp_tag():
    """FMP wins -> stored with 'fmp' tag."""
    fmp_rows = [_etf_row("AAPL", data_source="fmp")]
    captured = {}
    with patch("openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
               return_value=[]), \
         patch("openbb_fmp_cached.models.etf_holdings.init_database"), \
         patch("openbb_fmp_cached.models.etf_holdings._try_fmp",
               new=AsyncMock(return_value=fmp_rows)), \
         patch("openbb_fmp_cached.models.etf_holdings._try_issuer",
               side_effect=AssertionError("must NOT be called")), \
         patch("openbb_fmp_cached.models.etf_holdings._try_nport",
               side_effect=AssertionError("must NOT be called")), \
         patch("openbb_fmp_cached.models.etf_holdings._store_etf_holdings",
               side_effect=lambda etf, rows, data_source: captured.update({"ds": data_source})):
        await FMPCachedEtfHoldingsFetcher.aextract_data(
            _fake_query(), credentials={"fmp_api_key": "x"},
        )
    assert captured == {"ds": "fmp"}


# ---------------------------------------------------------------------------
# bd-3ka: fallback-tier rescue must NOT emit user-facing WARNINGs
# ---------------------------------------------------------------------------
#
# Pre-fix behavior: _try_fmp unconditionally emitted a WARNING for any
# exception (including plan-gated 402), even when Tier 2 (issuer file)
# successfully recovered rows. On an 11-sector cold-cache scan this
# produced 11 WARNING lines that looked like fatal auth errors but were
# actually benign — Tier 2 rescued each call end-to-end.
#
# The fix moves per-tier failure logging DOWN to DEBUG and adds a single
# aggregate WARNING at the aextract_data level ONLY when ALL tiers fail.
# When a fallback tier rescues, the caller sees INFO ("recovered via
# {tier}") — clearly not a fatal failure.
#
# R7.11 mutation-verified: reverting the log-level change makes both
# test_no_warning_when_issuer_rescues_after_fmp_402 fail; the aggregate
# WARNING test catches regressions in the ALL-tiers-fail path.


@pytest.mark.asyncio
async def test_no_warning_when_issuer_rescues_after_fmp_402(caplog):
    """bd-3ka: Tier 1 (FMP) fails with 402, Tier 2 (issuer) recovers
    75 rows. The caller must see NO WARNING (this is the exact fingerprint
    of the pre-fix behavior — plan-gated 402 looked like fatal auth error)."""
    import logging
    fmp_402 = Exception(
        "Unauthorized FMP request -> 402 -> Restricted Endpoint: "
        "This endpoint is not available under your current subscription"
    )
    issuer_rows = [_etf_row("SYM%d" % i, data_source="issuer_ssga")
                   for i in range(75)]

    with patch("openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
               return_value=[]), \
         patch("openbb_fmp_cached.models.etf_holdings.init_database"), \
         patch.object(FMPEtfHoldingsFetcher, "aextract_data",
                      new=AsyncMock(side_effect=fmp_402)), \
         patch("openbb_fmp_cached.models.etf_holdings_issuer.fetch_issuer_holdings",
               return_value=issuer_rows), \
         patch("openbb_fmp_cached.models.etf_holdings._store_etf_holdings"):
        with caplog.at_level(logging.WARNING,
                             logger="openbb_fmp_cached.models.etf_holdings"):
            result = await FMPCachedEtfHoldingsFetcher.aextract_data(
                _fake_query(), credentials={"fmp_api_key": "x"},
            )

    assert len(result) == 75, "Tier 2 must rescue with 75 rows"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, (
        "bd-3ka: fallback-rescue path must not emit WARNING; got "
        + str([r.getMessage() for r in warnings])
    )


@pytest.mark.asyncio
async def test_warning_when_all_tiers_fail(caplog):
    """bd-3ka: when Tier 1 AND Tier 2 AND Tier 3 all return empty, a
    single aggregate WARNING must fire. This is the ONLY situation the
    user should see a WARNING at the etf_holdings level (real failure
    that ops needs to see, not benign 402-then-rescue)."""
    import logging
    fmp_402 = Exception("Unauthorized FMP request -> 402 -> Restricted")

    with patch("openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
               return_value=[]), \
         patch("openbb_fmp_cached.models.etf_holdings.init_database"), \
         patch.object(FMPEtfHoldingsFetcher, "aextract_data",
                      new=AsyncMock(side_effect=fmp_402)), \
         patch("openbb_fmp_cached.models.etf_holdings_issuer.fetch_issuer_holdings",
               return_value=[]):
        with caplog.at_level(logging.WARNING,
                             logger="openbb_fmp_cached.models.etf_holdings"):
            result = await FMPCachedEtfHoldingsFetcher.aextract_data(
                _fake_query(), credentials={"fmp_api_key": "x"},
            )

    assert result == [], "all tiers empty must yield []"
    warnings = [r for r in caplog.records
                if r.levelno >= logging.WARNING
                and "all tiers exhausted" in r.getMessage().lower()]
    assert len(warnings) == 1, (
        "bd-3ka: all-tiers-fail path must emit exactly one aggregate "
        "WARNING; got " + str([r.getMessage() for r in caplog.records])
    )


# ---------------------------------------------------------------------------
# bd-5in: schema-drift must emit WARNING (not silent DEBUG)
# ---------------------------------------------------------------------------
#
# Pre-fix behavior: transform_data caught every Pydantic ValidationError at
# DEBUG level. If FMP upstream renamed 'asset' to 'ticker', EVERY row
# would fail validation, 'validated' stayed [], and downstream saw
# rows_returned=0 with only a rows_returned=0 WARNING at fetch level.
# The actual root cause (schema drift) was invisible unless you cranked
# up logging to DEBUG.
#
# The fix: if N/N rows fail validation AND N > 0, promote to WARNING
# with a sample validation-error message. This makes schema drift LOUD
# per R7.3 while keeping the tolerant behavior for MIXED cases (partial
# schema drift where some rows validate — those still succeed silently).
#
# R7.11 mutation-verified: reverting the level from WARNING back to DEBUG
# makes test_schema_drift_all_rows_fail_emits_warning fail.


def test_schema_drift_all_rows_fail_emits_warning(caplog):
    """bd-5in: when every row in a non-empty response fails validation
    (schema drift scenario), transform_data must emit a WARNING carrying
    a sample of the underlying validation error."""
    import logging
    from openbb_fmp_cached.models.etf_holdings import FMPCachedEtfHoldingsFetcher
    # Type-clash records that actually fail model_validate (an unknown
    # field like 'ticker' would silently accept as extra; forcing a
    # wrong type on a known scalar field is what triggers ValidationError).
    bad_records = [
        {"weight": "not_a_number", "symbol": "AAPL"},
        {"weight": "also_not_a_number", "symbol": "MSFT"},
        {"weight": "still_wrong", "symbol": "NVDA"},
    ]
    with caplog.at_level(logging.WARNING,
                         logger="openbb_fmp_cached.models.etf_holdings"):
        result = FMPCachedEtfHoldingsFetcher.transform_data(
            _fake_query(), bad_records,
        )

    assert result == [], "all-rows-fail must produce empty validated list"
    warnings = [r for r in caplog.records
                if r.levelno >= logging.WARNING
                and "schema" in r.getMessage().lower()]
    assert len(warnings) >= 1, (
        "bd-5in: 100% validation failure must WARN about schema drift; got "
        + str([r.getMessage() for r in caplog.records])
    )


def test_schema_drift_partial_still_succeeds_silently(caplog):
    """bd-5in: when SOME rows validate and some don't (partial schema
    drift or a few bad records), transform_data still returns the
    validated rows without emitting a WARNING. The all-fail WARNING is
    only for the schema-drift-affects-everything case — mixed failures
    stay at DEBUG per existing tolerance."""
    import logging
    from openbb_fmp_cached.models.etf_holdings import FMPCachedEtfHoldingsFetcher
    good = [_etf_row("AAPL"), _etf_row("MSFT")]
    # Bad record with type-clash on 'weight' — actually fails validation.
    bad = [{"weight": "not_a_number", "symbol": "NVDA"}]
    with caplog.at_level(logging.WARNING,
                         logger="openbb_fmp_cached.models.etf_holdings"):
        result = FMPCachedEtfHoldingsFetcher.transform_data(
            _fake_query(), good + bad,
        )
    assert len(result) == 2, "2 valid records must validate; 1 skipped"
    warnings = [r for r in caplog.records
                if r.levelno >= logging.WARNING
                and "schema" in r.getMessage().lower()]
    assert not warnings, (
        "bd-5in: partial failures must NOT WARN (only all-fail case); got "
        + str([r.getMessage() for r in caplog.records])
    )


def test_schema_drift_empty_input_is_silent(caplog):
    """bd-5in: empty input list is not schema drift; must not emit any
    schema WARNING. Distinguishes 'endpoint returned []' from
    'endpoint returned garbage'."""
    import logging
    from openbb_fmp_cached.models.etf_holdings import FMPCachedEtfHoldingsFetcher
    with caplog.at_level(logging.WARNING,
                         logger="openbb_fmp_cached.models.etf_holdings"):
        result = FMPCachedEtfHoldingsFetcher.transform_data(_fake_query(), [])
    assert result == []
    warnings = [r for r in caplog.records
                if r.levelno >= logging.WARNING
                and "schema" in r.getMessage().lower()]
    assert not warnings, (
        "bd-5in: empty input must NOT WARN; got "
        + str([r.getMessage() for r in caplog.records])
    )
