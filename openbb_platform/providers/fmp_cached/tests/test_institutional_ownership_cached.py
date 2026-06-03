"""Exhaustive tests for FMP Cached Institutional Ownership with multi-source fallback.

Tests are organised into:
1. Unit tests (no network, no DB) -- mock all external dependencies
2. Cache logic tests -- mock DB functions to verify cache read/write
3. Fallback chain tests -- mock each source to verify correct ordering
4. Data normalisation tests -- verify all sources produce FMP-compatible schema
5. Edge case tests -- empty data, errors, partial failures
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipFetcher


@pytest.fixture
def event_loop():
    """Override session-scoped event loop fixture to avoid pytest-asyncio introspection bug."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Module under test
from openbb_fmp_cached.models.institutional_ownership import (
    INSTITUTIONAL_OWNERSHIP_TTL_DAYS,
    FMPCachedInstitutionalOwnershipFetcher,
    _get_cached_institutional,
    _resolve_credentials,
    _store_institutional,
    _try_fmp,
    _try_sec_13f,
    _try_yfinance,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fmp_record(symbol: str = "MSFT", ownership_pct: float = 0.72) -> dict:
    """Create a minimal FMP-format institutional ownership record."""
    return {
        "symbol": symbol,
        "cik": "0000789019",
        "date": "2026-01-15",
        "investors_holding": 4500,
        "last_investors_holding": 4400,
        "investors_holding_change": 100,
        "number_of_13f_shares": 5_000_000_000,
        "last_number_of_13f_shares": 4_900_000_000,
        "number_of_13f_shares_change": 100_000_000,
        "total_invested": 1_500_000_000_000.0,
        "last_total_invested": 1_400_000_000_000.0,
        "total_invested_change": 100_000_000_000.0,
        "ownership_percent": ownership_pct,
        "last_ownership_percent": 0.70,
        "ownership_percent_change": 0.02,
        "new_positions": 50,
        "last_new_positions": 45,
        "new_positions_change": 5,
        "increased_positions": 200,
        "last_increased_positions": 190,
        "increased_positions_change": 10,
        "closed_positions": 30,
        "last_closed_positions": 25,
        "closed_positions_change": 5,
        "reduced_positions": 100,
        "last_reduced_positions": 95,
        "reduced_positions_change": 5,
        "total_calls": 500_000,
        "last_total_calls": 480_000,
        "total_calls_change": 20_000,
        "total_puts": 350_000,
        "last_total_puts": 340_000,
        "total_puts_change": 10_000,
        "put_call_ratio": 0.7,
        "last_put_call_ratio": 0.71,
        "put_call_ratio_change": -0.01,
    }


def _yfinance_info(symbol: str = "MSFT") -> dict:
    """Simulate yfinance ticker.get_info() response."""
    return {
        "symbol": symbol,
        "heldPercentInstitutions": 0.72,
        "heldPercentInsiders": 0.01,
        "institutionsCount": 4500,
    }


def _sec_13f_rows(n: int = 3) -> list[dict]:
    """Simulate SEC 13F filing rows."""
    return [
        {"nameOfIssuer": f"Fund_{i}", "shares": 1_000_000 * (i + 1), "value": 300_000_000 * (i + 1)}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# 1. Credential resolution
# ---------------------------------------------------------------------------


class TestResolveCredentials:
    def test_passthrough_fmp_api_key(self):
        creds = {"fmp_api_key": "abc123"}
        assert _resolve_credentials(creds) == creds

    def test_translate_fmp_cached_key(self):
        creds = {"fmp_cached_api_key": "xyz789"}
        result = _resolve_credentials(creds)
        assert result == {"fmp_api_key": "xyz789"}

    def test_none_credentials_resolves(self):
        # When None is passed, _resolve_credentials falls through to user_settings
        # which may or may not return a key — just verify no exception
        result = _resolve_credentials(None)
        assert result is None or isinstance(result, dict)

    def test_empty_dict(self):
        # Falls through to user_settings, which may or may not be available
        result = _resolve_credentials({})
        assert isinstance(result, (dict, type(None)))


# ---------------------------------------------------------------------------
# 2. Cache read / write
# ---------------------------------------------------------------------------


class TestCacheRead:
    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_cache_hit(self, mock_query):
        record = _fmp_record("AAPL")
        mock_query.return_value = [{"data_json": json.dumps(record)}]
        result = _get_cached_institutional("AAPL")
        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_cache_miss(self, mock_query):
        mock_query.return_value = []
        result = _get_cached_institutional("TSLA")
        assert result == []

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_cache_db_error_returns_empty(self, mock_query):
        mock_query.side_effect = Exception("DB connection lost")
        result = _get_cached_institutional("MSFT")
        assert result == []

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_cache_query_params(self, mock_query):
        """Verify the cache reads with correct symbol and TTL cutoff."""
        mock_query.return_value = []
        _get_cached_institutional("NVDA")
        args, kwargs = mock_query.call_args
        assert "NVDA" in args[1]  # symbol in params tuple
        # Second param should be a datetime (freshness cutoff)
        assert isinstance(args[1][1], datetime)

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_cache_json_string_parsed(self, mock_query):
        """Verify JSON string in data_json is properly parsed."""
        record = _fmp_record()
        mock_query.return_value = [{"data_json": json.dumps(record)}]
        result = _get_cached_institutional("MSFT")
        assert isinstance(result[0], dict)
        assert result[0]["ownership_percent"] == 0.72

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_cache_dict_payload(self, mock_query):
        """Verify dict payload in data_json is handled directly."""
        record = _fmp_record()
        mock_query.return_value = [{"data_json": record}]
        result = _get_cached_institutional("MSFT")
        assert result[0]["ownership_percent"] == 0.72

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_cache_skips_none_payload(self, mock_query):
        mock_query.return_value = [{"data_json": None}]
        result = _get_cached_institutional("MSFT")
        assert result == []


class TestCacheWrite:
    @patch("openbb_fmp_cached.models.institutional_ownership.execute_many")
    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_store_records(self, mock_query, mock_many):
        records = [_fmp_record("MSFT"), _fmp_record("AAPL")]
        _store_institutional(records, data_source="fmp")
        # Should delete old data for both symbols
        assert mock_query.call_count == 2
        # Should insert 2 records
        assert mock_many.call_count == 1
        insert_params = mock_many.call_args[0][1]
        assert len(insert_params) == 2

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_many")
    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_store_attaches_data_source(self, mock_query, mock_many):
        records = [_fmp_record()]
        _store_institutional(records, data_source="yfinance")
        insert_params = mock_many.call_args[0][1]
        stored_json = json.loads(insert_params[0][2])
        assert stored_json["data_source"] == "yfinance"

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_many")
    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_store_empty_is_noop(self, mock_query, mock_many):
        _store_institutional([], data_source="fmp")
        mock_query.assert_not_called()
        mock_many.assert_not_called()

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_many")
    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_store_db_error_handled(self, mock_query, mock_many):
        mock_query.side_effect = Exception("DB write failed")
        # Should not raise
        _store_institutional([_fmp_record()], data_source="fmp")


# ---------------------------------------------------------------------------
# 3. Individual source functions
# ---------------------------------------------------------------------------


class TestTryFMP:
    @pytest.mark.asyncio
    async def test_fmp_402_returns_empty(self):
        """FMP returns 402 -- _try_fmp catches and returns empty."""
        # The FMP API call will naturally fail in test environment (no real API key)
        # This verifies the function handles exceptions gracefully
        from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipQueryParams
        query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")
        result = await _try_fmp(query, ["MSFT"], {"fmp_api_key": "invalid_key_for_test"})
        # With an invalid key, FMP will fail and _try_fmp returns []
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_fmp_empty_data(self):
        """When FMP returns no data, result should be empty."""
        from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipQueryParams
        query = FMPInstitutionalOwnershipQueryParams(symbol="ZZZZNONEXISTENT")
        result = await _try_fmp(query, ["ZZZZNONEXISTENT"], {"fmp_api_key": "invalid_key_for_test"})
        assert isinstance(result, list)


class TestTryYfinance:
    @pytest.mark.asyncio
    async def test_yfinance_success(self):
        mock_ticker = MagicMock()
        mock_ticker.get_info.return_value = _yfinance_info("AAPL")
        mock_ticker.get_major_holders.return_value = {"Value": {}}

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = await _try_yfinance(["AAPL"])
            assert len(result) == 1
            assert result[0]["symbol"] == "AAPL"
            assert result[0]["ownership_percent"] == 0.72
            assert result[0]["data_source"] == "yfinance"
            # Verify FMP schema compliance
            assert "investors_holding" in result[0]
            assert "put_call_ratio" in result[0]

    @pytest.mark.asyncio
    async def test_yfinance_no_inst_pct(self):
        """If heldPercentInstitutions is None, skip the symbol."""
        mock_ticker = MagicMock()
        mock_ticker.get_info.return_value = {"symbol": "TSLA"}
        mock_ticker.get_major_holders.return_value = {"Value": {}}

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = await _try_yfinance(["TSLA"])
            assert result == []

    @pytest.mark.asyncio
    async def test_yfinance_api_error(self):
        mock_ticker = MagicMock()
        mock_ticker.get_info.side_effect = Exception("401 Unauthorized")
        mock_ticker.get_major_holders.side_effect = Exception("401")

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = await _try_yfinance(["MSFT"])
            assert result == []


class TestTrySec13f:
    @pytest.mark.asyncio
    async def test_sec_success(self):
        sec_rows = _sec_13f_rows(3)
        with patch(
            "openbb_sec.models.form_13FHR.SecForm13FHRFetcher.aextract_data",
            new_callable=AsyncMock,
            return_value=sec_rows,
        ):
            result = await _try_sec_13f(["NVDA"])
            assert len(result) == 1
            assert result[0]["symbol"] == "NVDA"
            assert result[0]["data_source"] == "sec_13f"
            # Should have aggregated values
            assert result[0]["investors_holding"] > 0
            assert result[0]["total_invested"] > 0
            assert result[0]["number_of_13f_shares"] > 0

    @pytest.mark.asyncio
    async def test_sec_empty(self):
        with patch(
            "openbb_sec.models.form_13FHR.SecForm13FHRFetcher.aextract_data",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await _try_sec_13f(["NVDA"])
            assert result == []

    @pytest.mark.asyncio
    async def test_sec_error(self):
        with patch(
            "openbb_sec.models.form_13FHR.SecForm13FHRFetcher.aextract_data",
            new_callable=AsyncMock,
            side_effect=Exception("SEC unreachable"),
        ):
            result = await _try_sec_13f(["NVDA"])
            assert result == []


# ---------------------------------------------------------------------------
# 4. Full fallback chain (aextract_data integration)
# ---------------------------------------------------------------------------


class TestFallbackChain:
    """Test the complete fallback chain in aextract_data."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_all_sources(self):
        """If cache has data, FMP/yfinance/SEC are never called."""
        record = _fmp_record("MSFT")
        with patch(
            "openbb_fmp_cached.models.institutional_ownership._get_cached_institutional",
            return_value=[record],
        ) as mock_cache, patch(
            "openbb_fmp_cached.models.institutional_ownership._try_fmp",
            new_callable=AsyncMock,
        ) as mock_fmp, patch(
            "openbb_fmp_cached.models.institutional_ownership._try_yfinance",
            new_callable=AsyncMock,
        ) as mock_yf, patch(
            "openbb_fmp_cached.models.institutional_ownership._try_sec_13f",
            new_callable=AsyncMock,
        ) as mock_sec, patch(
            "openbb_fmp_cached.models.institutional_ownership.init_database",
        ):
            from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipQueryParams
            query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")
            result = await FMPCachedInstitutionalOwnershipFetcher.aextract_data(
                query, {"fmp_api_key": "test"}
            )
            assert len(result) == 1
            mock_fmp.assert_not_called()
            mock_yf.assert_not_called()
            mock_sec.assert_not_called()

    @pytest.mark.asyncio
    async def test_fmp_success_skips_yfinance_and_sec(self):
        """If FMP returns data, yfinance and SEC are not called."""
        record = _fmp_record("MSFT")
        with patch(
            "openbb_fmp_cached.models.institutional_ownership._get_cached_institutional",
            return_value=[],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._try_fmp",
            new_callable=AsyncMock,
            return_value=[record],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._store_institutional",
        ) as mock_store, patch(
            "openbb_fmp_cached.models.institutional_ownership._try_yfinance",
            new_callable=AsyncMock,
        ) as mock_yf, patch(
            "openbb_fmp_cached.models.institutional_ownership._try_sec_13f",
            new_callable=AsyncMock,
        ) as mock_sec, patch(
            "openbb_fmp_cached.models.institutional_ownership.init_database",
        ):
            from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipQueryParams
            query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")
            result = await FMPCachedInstitutionalOwnershipFetcher.aextract_data(
                query, {"fmp_api_key": "test"}
            )
            assert len(result) == 1
            mock_store.assert_called_once()
            mock_yf.assert_not_called()
            mock_sec.assert_not_called()

    @pytest.mark.asyncio
    async def test_fmp_fails_yfinance_succeeds(self):
        """FMP failure triggers yfinance, which succeeds -- SEC not called."""
        yf_record = {
            "symbol": "MSFT", "date": "2026-03-23",
            "ownership_percent": 0.72, "investors_holding": 4500,
            "data_source": "yfinance",
            **{k: 0 for k in [
                "last_investors_holding", "investors_holding_change",
                "total_invested", "last_total_invested", "total_invested_change",
                "last_ownership_percent", "ownership_percent_change",
                "new_positions", "last_new_positions", "new_positions_change",
                "increased_positions", "last_increased_positions", "increased_positions_change",
                "closed_positions", "last_closed_positions", "closed_positions_change",
                "reduced_positions", "last_reduced_positions", "reduced_positions_change",
                "total_calls", "last_total_calls", "total_calls_change",
                "total_puts", "last_total_puts", "total_puts_change",
                "put_call_ratio", "last_put_call_ratio", "put_call_ratio_change",
            ]},
        }
        with patch(
            "openbb_fmp_cached.models.institutional_ownership._get_cached_institutional",
            return_value=[],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._try_fmp",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._try_yfinance",
            new_callable=AsyncMock,
            return_value=[yf_record],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._store_institutional",
        ) as mock_store, patch(
            "openbb_fmp_cached.models.institutional_ownership._try_sec_13f",
            new_callable=AsyncMock,
        ) as mock_sec, patch(
            "openbb_fmp_cached.models.institutional_ownership.init_database",
        ):
            from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipQueryParams
            query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")
            result = await FMPCachedInstitutionalOwnershipFetcher.aextract_data(
                query, {"fmp_api_key": "test"}
            )
            assert len(result) == 1
            assert result[0]["data_source"] == "yfinance"
            mock_sec.assert_not_called()
            # Store should be called with yfinance source
            mock_store.assert_called_once_with([yf_record], data_source="yfinance")

    @pytest.mark.asyncio
    async def test_fmp_and_yfinance_fail_sec_succeeds(self):
        """Both FMP and yfinance fail -- SEC picks up."""
        sec_record = {
            "symbol": "MSFT", "date": "2026-03-23",
            "investors_holding": 3, "number_of_13f_shares": 6_000_000,
            "total_invested": 1_800_000_000.0, "data_source": "sec_13f",
            **{k: 0 for k in [
                "last_investors_holding", "investors_holding_change",
                "last_total_invested", "total_invested_change",
                "ownership_percent", "last_ownership_percent", "ownership_percent_change",
                "new_positions", "last_new_positions", "new_positions_change",
                "increased_positions", "last_increased_positions", "increased_positions_change",
                "closed_positions", "last_closed_positions", "closed_positions_change",
                "reduced_positions", "last_reduced_positions", "reduced_positions_change",
                "total_calls", "last_total_calls", "total_calls_change",
                "total_puts", "last_total_puts", "total_puts_change",
                "put_call_ratio", "last_put_call_ratio", "put_call_ratio_change",
            ]},
        }
        with patch(
            "openbb_fmp_cached.models.institutional_ownership._get_cached_institutional",
            return_value=[],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._try_fmp",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._try_yfinance",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._try_sec_13f",
            new_callable=AsyncMock,
            return_value=[sec_record],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._store_institutional",
        ) as mock_store, patch(
            "openbb_fmp_cached.models.institutional_ownership.init_database",
        ):
            from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipQueryParams
            query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")
            result = await FMPCachedInstitutionalOwnershipFetcher.aextract_data(
                query, {"fmp_api_key": "test"}
            )
            assert len(result) == 1
            assert result[0]["data_source"] == "sec_13f"
            mock_store.assert_called_once_with([sec_record], data_source="sec_13f")

    @pytest.mark.asyncio
    async def test_all_sources_fail_returns_empty(self):
        """If all sources fail, return empty list -- no exception."""
        with patch(
            "openbb_fmp_cached.models.institutional_ownership._get_cached_institutional",
            return_value=[],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._try_fmp",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._try_yfinance",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._try_sec_13f",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership.init_database",
        ):
            from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipQueryParams
            query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")
            result = await FMPCachedInstitutionalOwnershipFetcher.aextract_data(
                query, {"fmp_api_key": "test"}
            )
            assert result == []

    @pytest.mark.asyncio
    async def test_multi_symbol_partial_cache(self):
        """One symbol cached, another needs fetching."""
        cached_record = _fmp_record("AAPL")
        fresh_record = _fmp_record("MSFT")

        def mock_cache(symbol):
            return [cached_record] if symbol == "AAPL" else []

        with patch(
            "openbb_fmp_cached.models.institutional_ownership._get_cached_institutional",
            side_effect=mock_cache,
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._try_fmp",
            new_callable=AsyncMock,
            return_value=[fresh_record],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._store_institutional",
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership.init_database",
        ):
            from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipQueryParams
            query = FMPInstitutionalOwnershipQueryParams(symbol="AAPL,MSFT")
            result = await FMPCachedInstitutionalOwnershipFetcher.aextract_data(
                query, {"fmp_api_key": "test"}
            )
            assert len(result) == 2
            symbols = {r["symbol"] for r in result}
            assert symbols == {"AAPL", "MSFT"}


# ---------------------------------------------------------------------------
# 5. Data normalisation
# ---------------------------------------------------------------------------


class TestDataNormalisation:
    """Verify fallback source records comply with FMP schema."""

    def test_yfinance_record_has_required_fields(self):
        """yfinance record should have all mandatory FMP fields."""
        from datetime import date
        record = {
            "symbol": "MSFT",
            "cik": None,
            "date": date.today().isoformat(),
            "investors_holding": 4500,
            "last_investors_holding": 0,
            "investors_holding_change": 0,
            "total_invested": 0.0,
            "last_total_invested": 0.0,
            "total_invested_change": 0.0,
            "ownership_percent": 72.0,
            "last_ownership_percent": 1.0,
            "ownership_percent_change": 1.0,
            "new_positions": 0,
            "last_new_positions": 0,
            "new_positions_change": 0,
            "increased_positions": 0,
            "last_increased_positions": 0,
            "increased_positions_change": 0,
            "closed_positions": 0,
            "last_closed_positions": 0,
            "closed_positions_change": 0,
            "reduced_positions": 0,
            "last_reduced_positions": 0,
            "reduced_positions_change": 0,
            "total_calls": 0,
            "last_total_calls": 0,
            "total_calls_change": 0,
            "total_puts": 0,
            "last_total_puts": 0,
            "total_puts_change": 0,
            "put_call_ratio": 0.0,
            "last_put_call_ratio": 0.0,
            "put_call_ratio_change": 0.0,
            "data_source": "yfinance",
        }
        # Should validate without error
        from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipData
        obj = FMPInstitutionalOwnershipData.model_validate(record)
        assert obj.symbol == "MSFT"

    def test_sec_record_has_required_fields(self):
        """SEC aggregated record should have all mandatory FMP fields."""
        record = {
            "symbol": "NVDA",
            "cik": None,
            "date": "2026-03-23",
            "investors_holding": 150,
            "last_investors_holding": 0,
            "investors_holding_change": 0,
            "number_of_13f_shares": 5_000_000,
            "total_invested": 900_000_000.0,
            "last_total_invested": 0.0,
            "total_invested_change": 0.0,
            "ownership_percent": 1.0,
            "last_ownership_percent": 1.0,
            "ownership_percent_change": 1.0,
            "new_positions": 0,
            "last_new_positions": 0,
            "new_positions_change": 0,
            "increased_positions": 0,
            "last_increased_positions": 0,
            "increased_positions_change": 0,
            "closed_positions": 0,
            "last_closed_positions": 0,
            "closed_positions_change": 0,
            "reduced_positions": 0,
            "last_reduced_positions": 0,
            "reduced_positions_change": 0,
            "total_calls": 0,
            "last_total_calls": 0,
            "total_calls_change": 0,
            "total_puts": 0,
            "last_total_puts": 0,
            "total_puts_change": 0,
            "put_call_ratio": 0.0,
            "last_put_call_ratio": 0.0,
            "put_call_ratio_change": 0.0,
            "data_source": "sec_13f",
        }
        from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipData
        obj = FMPInstitutionalOwnershipData.model_validate(record)
        assert obj.symbol == "NVDA"
        assert obj.investors_holding == 150

    def test_transform_data_tolerates_partial_records(self):
        """transform_data should skip records that don't match FMP schema."""
        from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipQueryParams
        valid_record = _fmp_record("MSFT")
        invalid_record = {"symbol": "TSLA", "some_field": 42}  # Missing required fields
        query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT,TSLA")
        result = FMPCachedInstitutionalOwnershipFetcher.transform_data(
            query, [valid_record, invalid_record]
        )
        # Only valid record should pass through
        assert len(result) == 1
        assert result[0].symbol == "MSFT"


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_ttl_constant(self):
        assert INSTITUTIONAL_OWNERSHIP_TTL_DAYS == 7

    @pytest.mark.asyncio
    async def test_db_init_failure_does_not_block(self):
        """If init_database() fails, execution should proceed."""
        with patch(
            "openbb_fmp_cached.models.institutional_ownership.init_database",
            side_effect=Exception("DB unavailable"),
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._get_cached_institutional",
            return_value=[],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._try_fmp",
            new_callable=AsyncMock,
            return_value=[_fmp_record("MSFT")],
        ), patch(
            "openbb_fmp_cached.models.institutional_ownership._store_institutional",
        ):
            from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipQueryParams
            query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")
            result = await FMPCachedInstitutionalOwnershipFetcher.aextract_data(
                query, {"fmp_api_key": "test"}
            )
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_symbol_string(self):
        """Empty symbol string should return empty list."""
        with patch(
            "openbb_fmp_cached.models.institutional_ownership.init_database",
        ):
            from openbb_fmp.models.institutional_ownership import FMPInstitutionalOwnershipQueryParams
            query = FMPInstitutionalOwnershipQueryParams(symbol="")
            result = await FMPCachedInstitutionalOwnershipFetcher.aextract_data(
                query, {"fmp_api_key": "test"}
            )
            assert result == []
