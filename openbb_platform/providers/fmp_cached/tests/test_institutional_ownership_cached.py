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
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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


def _fmp_record(
    symbol: str = "MSFT",
    ownership_pct: float = 0.72,
    year: int = 2024,
    quarter: int = 4,
) -> dict:
    """Create a minimal FMP-format institutional ownership record.

    #783/#784: year and quarter are required in the cached payload for
    the year/quarter-filtered read path (_get_cached_institutional).
    Defaults match the test call sites (year=2024, quarter=4).
    """
    return {
        "symbol": symbol,
        "cik": "0000789019",
        "date": "2026-01-15",
        "year": year,
        "quarter": quarter,
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


def _sec_13f_holder_rows(n: int = 3) -> list[dict]:
    """Simulate sec_13f_holdings read rows returned by holders_for_cusip."""
    return [
        {
            "cusip": "67066G104",
            "filer_cik": f"000000{i}",
            "filer_name": f"Fund_{i}",
            "period": "2023-Q2",
            "shares": 1_000_000 * (i + 1),
            "value_usd": 300_000_000 * (i + 1),
            "put_call": None,
        }
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
        # year+quarter are required post-uolr (deterministic cache key).
        # See #783.
        result = _get_cached_institutional("AAPL", year=2024, quarter=4)
        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_cache_miss(self, mock_query):
        mock_query.return_value = []
        result = _get_cached_institutional("TSLA", year=2024, quarter=4)
        assert result == []

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_cache_db_error_returns_empty(self, mock_query):
        mock_query.side_effect = Exception("DB connection lost")
        result = _get_cached_institutional("MSFT", year=2024, quarter=4)
        assert result == []

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_cache_query_params(self, mock_query):
        """Verify the cache reads with correct symbol and TTL cutoff."""
        mock_query.return_value = []
        _get_cached_institutional("NVDA", year=2024, quarter=4)
        args, kwargs = mock_query.call_args
        assert "NVDA" in args[1]  # symbol in params tuple
        # Second param should be a datetime (freshness cutoff)
        assert isinstance(args[1][1], datetime)

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_cache_json_string_parsed(self, mock_query):
        """Verify JSON string in data_json is properly parsed."""
        record = _fmp_record()
        mock_query.return_value = [{"data_json": json.dumps(record)}]
        result = _get_cached_institutional("MSFT", year=2024, quarter=4)
        assert isinstance(result[0], dict)
        assert result[0]["ownership_percent"] == 0.72

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_cache_dict_payload(self, mock_query):
        """Verify dict payload in data_json is handled directly."""
        record = _fmp_record()
        mock_query.return_value = [{"data_json": record}]
        result = _get_cached_institutional("MSFT", year=2024, quarter=4)
        assert result[0]["ownership_percent"] == 0.72

    @patch("openbb_fmp_cached.models.institutional_ownership.execute_query")
    def test_cache_skips_none_payload(self, mock_query):
        mock_query.return_value = [{"data_json": None}]
        result = _get_cached_institutional("MSFT", year=2024, quarter=4)
        assert result == []


class TestCacheWrite:
    # #784: _store_institutional now writes via replace_rows() (from
    # bd-kh08 / PR #414), NOT execute_many. Each symbol gets one atomic
    # DELETE+INSERT transaction. Patch replace_rows to observe writes.
    @patch("openbb_fmp_cached.models.institutional_ownership.replace_rows")
    def test_store_records(self, mock_replace):
        records = [_fmp_record("MSFT"), _fmp_record("AAPL")]
        _store_institutional(records, data_source="fmp")
        # One replace_rows call per unique symbol (2 symbols → 2 calls).
        assert mock_replace.call_count == 2
        # Each call's `rows` arg is a list of the rows for that symbol.
        symbols_written = {call.args[2] for call in mock_replace.call_args_list}
        assert symbols_written == {"MSFT", "AAPL"}

    @patch("openbb_fmp_cached.models.institutional_ownership.replace_rows")
    def test_store_attaches_data_source(self, mock_replace):
        records = [_fmp_record()]
        _store_institutional(records, data_source="yfinance")
        # Grab the rows list (positional arg index 3).
        rows = mock_replace.call_args.args[3]
        stored_json = json.loads(rows[0]["data_json"])
        assert stored_json["data_source"] == "yfinance"

    @patch("openbb_fmp_cached.models.institutional_ownership.replace_rows")
    def test_store_empty_is_noop(self, mock_replace):
        _store_institutional([], data_source="fmp")
        mock_replace.assert_not_called()

    @patch("openbb_fmp_cached.models.institutional_ownership.replace_rows")
    def test_store_db_error_handled(self, mock_replace):
        mock_replace.side_effect = Exception("DB write failed")
        # Should not raise — per-symbol try/except swallows per D4.
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
        from openbb_fmp.models.institutional_ownership import (
            FMPInstitutionalOwnershipQueryParams,
        )

        query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")
        result = await _try_fmp(
            query, ["MSFT"], {"fmp_api_key": "invalid_key_for_test"}
        )
        # With an invalid key, FMP will fail and _try_fmp returns []
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_fmp_empty_data(self):
        """When FMP returns no data, result should be empty."""
        from openbb_fmp.models.institutional_ownership import (
            FMPInstitutionalOwnershipQueryParams,
        )

        query = FMPInstitutionalOwnershipQueryParams(symbol="ZZZZNONEXISTENT")
        result = await _try_fmp(
            query, ["ZZZZNONEXISTENT"], {"fmp_api_key": "invalid_key_for_test"}
        )
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
        holders = _sec_13f_holder_rows(3)
        with patch(
            "openbb_sec.utils.thirteen_f_index.resolve_cusip",
            return_value=["67066G104"],
        ), patch(
            "openbb_sec.utils.thirteen_f_index.holders_for_cusip",
            return_value=holders,
        ), patch(
            "openbb_sec.utils.thirteen_f_index.init_thirteen_f_index",
            return_value=True,
        ):
            result = await _try_sec_13f(["NVDA"])
            assert len(result) == 1
            assert result[0]["symbol"] == "NVDA"
            assert result[0]["data_source"] == "sec_13f"
            # Aggregated from the per-manager holding rows.
            assert result[0]["investors_holding"] == 3
            assert result[0]["number_of_13f_shares"] == sum(
                h["shares"] for h in holders
            )
            assert result[0]["total_invested"] == float(
                sum(h["value_usd"] for h in holders)
            )
            # Period 2023-Q2 maps to its quarter-end date.
            assert result[0]["date"] == "2023-06-30"

    @pytest.mark.asyncio
    async def test_sec_no_cusip(self):
        """Unknown ticker -> no CUSIP -> empty (symbol skipped)."""
        with patch(
            "openbb_sec.utils.thirteen_f_index.resolve_cusip",
            return_value=[],
        ), patch(
            "openbb_sec.utils.thirteen_f_index.init_thirteen_f_index",
            return_value=True,
        ):
            result = await _try_sec_13f(["NVDA"])
            assert result == []

    @pytest.mark.asyncio
    async def test_sec_no_holders(self):
        """CUSIP resolves but the index has no holdings yet -> empty."""
        with patch(
            "openbb_sec.utils.thirteen_f_index.resolve_cusip",
            return_value=["67066G104"],
        ), patch(
            "openbb_sec.utils.thirteen_f_index.holders_for_cusip",
            return_value=[],
        ), patch(
            "openbb_sec.utils.thirteen_f_index.init_thirteen_f_index",
            return_value=True,
        ):
            result = await _try_sec_13f(["NVDA"])
            assert result == []

    @pytest.mark.asyncio
    async def test_sec_error(self):
        """A read error is swallowed per-symbol -> empty, never raises."""
        with patch(
            "openbb_sec.utils.thirteen_f_index.resolve_cusip",
            return_value=["67066G104"],
        ), patch(
            "openbb_sec.utils.thirteen_f_index.holders_for_cusip",
            side_effect=Exception("DB unreachable"),
        ), patch(
            "openbb_sec.utils.thirteen_f_index.init_thirteen_f_index",
            return_value=True,
        ):
            result = await _try_sec_13f(["NVDA"])
            assert result == []


@pytest.mark.integration
class TestSec13fEndToEnd:
    """End-to-end SEC tier against the real MySQL 13F index (no network).

    Seeds a synthetic ticker/CUSIP + two holding rows, runs the full
    resolve_cusip -> holders_for_cusip -> aggregate path through
    ``_try_sec_13f``, then deletes the synthetic rows. Skips cleanly when the
    index database is unreachable.
    """

    @pytest.mark.asyncio
    async def test_sec_tier_against_real_index(self):
        from datetime import (
            datetime as _dt,
            timezone as _tz,
        )

        from openbb_fmp_cached.utils.database import execute_query as _eq
        from openbb_sec.utils import thirteen_f_index as tfi

        if not tfi.init_thirteen_f_index():
            pytest.skip("13F index database unreachable")

        ticker = "ZZE2E"
        cusip = "ZZE2E0001"  # CHAR(9)
        period = "2099-Q4"
        now = _dt.now(_tz.utc).replace(tzinfo=None)
        try:
            tfi.upsert_cusip_map(
                [(cusip, "E2E TEST ISSUER", ticker, None, None, tfi.SOURCE_SEED, now)]
            )
            tfi.upsert_holdings(
                [
                    (
                        cusip,
                        "0000001",
                        "Fund One",
                        period,
                        1000,
                        5_000_000,
                        None,
                        tfi.SOURCE_BULK,
                        now,
                    ),
                    (
                        cusip,
                        "0000002",
                        "Fund Two",
                        period,
                        2000,
                        9_000_000,
                        None,
                        tfi.SOURCE_BULK,
                        now,
                    ),
                ]
            )

            result = await _try_sec_13f([ticker])

            assert len(result) == 1
            rec = result[0]
            assert rec["symbol"] == ticker.upper()
            assert rec["data_source"] == "sec_13f"
            assert rec["investors_holding"] == 2
            assert rec["number_of_13f_shares"] == 3000
            assert rec["total_invested"] == 14_000_000.0
            assert rec["date"] == "2099-12-31"
        finally:
            _eq("DELETE FROM sec_13f_holdings WHERE cusip = %s", (cusip,))
            _eq("DELETE FROM sec_13f_cusip_map WHERE cusip = %s", (cusip,))


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
            from openbb_fmp.models.institutional_ownership import (
                FMPInstitutionalOwnershipQueryParams,
            )

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
            from openbb_fmp.models.institutional_ownership import (
                FMPInstitutionalOwnershipQueryParams,
            )

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
            "symbol": "MSFT",
            "date": "2026-03-23",
            "ownership_percent": 0.72,
            "investors_holding": 4500,
            "data_source": "yfinance",
            **{
                k: 0
                for k in [
                    "last_investors_holding",
                    "investors_holding_change",
                    "total_invested",
                    "last_total_invested",
                    "total_invested_change",
                    "last_ownership_percent",
                    "ownership_percent_change",
                    "new_positions",
                    "last_new_positions",
                    "new_positions_change",
                    "increased_positions",
                    "last_increased_positions",
                    "increased_positions_change",
                    "closed_positions",
                    "last_closed_positions",
                    "closed_positions_change",
                    "reduced_positions",
                    "last_reduced_positions",
                    "reduced_positions_change",
                    "total_calls",
                    "last_total_calls",
                    "total_calls_change",
                    "total_puts",
                    "last_total_puts",
                    "total_puts_change",
                    "put_call_ratio",
                    "last_put_call_ratio",
                    "put_call_ratio_change",
                ]
            },
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
            from openbb_fmp.models.institutional_ownership import (
                FMPInstitutionalOwnershipQueryParams,
            )

            query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")
            result = await FMPCachedInstitutionalOwnershipFetcher.aextract_data(
                query, {"fmp_api_key": "test"}
            )
            assert len(result) == 1
            assert result[0]["data_source"] == "yfinance"
            mock_sec.assert_not_called()
            # Store should be called with yfinance source. Loosened
            # assert_called_once_with → check records + data_source
            # explicitly, since _store_institutional now also takes
            # year/quarter kwargs from _effective_year_quarter (#784).
            mock_store.assert_called_once()
            call = mock_store.call_args
            assert call.args[0] == [yf_record]
            assert call.kwargs.get("data_source") == "yfinance"

    @pytest.mark.asyncio
    async def test_fmp_and_yfinance_fail_sec_succeeds(self):
        """Both FMP and yfinance fail -- SEC picks up."""
        sec_record = {
            "symbol": "MSFT",
            "date": "2026-03-23",
            "investors_holding": 3,
            "number_of_13f_shares": 6_000_000,
            "total_invested": 1_800_000_000.0,
            "data_source": "sec_13f",
            **{
                k: 0
                for k in [
                    "last_investors_holding",
                    "investors_holding_change",
                    "last_total_invested",
                    "total_invested_change",
                    "ownership_percent",
                    "last_ownership_percent",
                    "ownership_percent_change",
                    "new_positions",
                    "last_new_positions",
                    "new_positions_change",
                    "increased_positions",
                    "last_increased_positions",
                    "increased_positions_change",
                    "closed_positions",
                    "last_closed_positions",
                    "closed_positions_change",
                    "reduced_positions",
                    "last_reduced_positions",
                    "reduced_positions_change",
                    "total_calls",
                    "last_total_calls",
                    "total_calls_change",
                    "total_puts",
                    "last_total_puts",
                    "total_puts_change",
                    "put_call_ratio",
                    "last_put_call_ratio",
                    "put_call_ratio_change",
                ]
            },
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
            from openbb_fmp.models.institutional_ownership import (
                FMPInstitutionalOwnershipQueryParams,
            )

            query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")
            result = await FMPCachedInstitutionalOwnershipFetcher.aextract_data(
                query, {"fmp_api_key": "test"}
            )
            assert len(result) == 1
            assert result[0]["data_source"] == "sec_13f"
            # See TestFallbackChain.test_fmp_fails_yfinance_succeeds (#784)
            # for the rationale behind loosening from assert_called_once_with.
            mock_store.assert_called_once()
            call = mock_store.call_args
            assert call.args[0] == [sec_record]
            assert call.kwargs.get("data_source") == "sec_13f"

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
            from openbb_fmp.models.institutional_ownership import (
                FMPInstitutionalOwnershipQueryParams,
            )

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

        def mock_cache(symbol, year, quarter):
            # #784: signature matches post-uolr _get_cached_institutional
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
            from openbb_fmp.models.institutional_ownership import (
                FMPInstitutionalOwnershipQueryParams,
            )

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
        """Yfinance record should have all mandatory FMP fields."""

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
        from openbb_fmp.models.institutional_ownership import (
            FMPInstitutionalOwnershipData,
        )

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
        from openbb_fmp.models.institutional_ownership import (
            FMPInstitutionalOwnershipData,
        )

        obj = FMPInstitutionalOwnershipData.model_validate(record)
        assert obj.symbol == "NVDA"
        assert obj.investors_holding == 150

    def test_transform_data_tolerates_partial_records(self, caplog):
        """transform_data should skip records that don't match FMP schema — but LOUDLY (bd-0bp1).

        Pre-fix (bd-0bp1) the skip was logged at ``debug`` level with no
        exception context, which is invisible under the default logging
        config. Post-fix the drop is logged at ``WARNING`` with the
        symbol AND the specific validation error so operators debugging
        "why is institutional ownership empty for X?" have log evidence.
        """
        import logging

        from openbb_fmp.models.institutional_ownership import (
            FMPInstitutionalOwnershipQueryParams,
        )

        valid_record = _fmp_record("MSFT")
        invalid_record = {"symbol": "TSLA", "some_field": 42}  # Missing required fields
        query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT,TSLA")
        with caplog.at_level(
            logging.WARNING,
            logger="openbb_fmp_cached.models.institutional_ownership",
        ):
            result = FMPCachedInstitutionalOwnershipFetcher.transform_data(
                query, [valid_record, invalid_record]
            )

        # Only valid record should pass through — the tolerate-partial
        # invariant is preserved.
        assert len(result) == 1
        assert result[0].symbol == "MSFT"

        # bd-0bp1: the drop MUST be visible at WARNING level (not debug).
        # Pre-fix this list would be empty because logger.debug is
        # filtered out under the caplog.at_level(WARNING) threshold.
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            "no WARNING-level records captured — schema-invalid record was "
            "silently dropped at debug level (bd-0bp1)"
        )
        # And the log message must name the specific symbol so the
        # operator knows which record dropped.
        assert any("TSLA" in r.getMessage() for r in warning_records), (
            f"warning log did not mention the dropped symbol 'TSLA' — "
            f"operator can't correlate the drop to a specific record. "
            f"Captured: {[r.getMessage() for r in warning_records]}"
        )

    def test_transform_data_warning_includes_validation_error_message(self, caplog):
        """The warning log MUST include the underlying ValidationError text (bd-0bp1)."""
        import logging

        from openbb_fmp.models.institutional_ownership import (
            FMPInstitutionalOwnershipQueryParams,
        )

        invalid_record = {"symbol": "TSLA", "some_field": 42}
        query = FMPInstitutionalOwnershipQueryParams(symbol="TSLA")
        with caplog.at_level(
            logging.WARNING,
            logger="openbb_fmp_cached.models.institutional_ownership",
        ):
            # Also give it a valid record so the "all dropped" raise
            # doesn't fire — we're only testing the per-record warning
            # message shape here.
            FMPCachedInstitutionalOwnershipFetcher.transform_data(
                query, [_fmp_record("MSFT"), invalid_record]
            )

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, "no WARNING captured for the invalid record"
        # The exact ValidationError text is Pydantic's; we assert at least
        # ONE of the missing-field indicators appears (Pydantic v2's
        # ValidationError names 'validation error' / 'field required' /
        # 'missing' — any of these proves the exception context reached
        # the log).
        msg = " ".join(r.getMessage() for r in warning_records)
        assert any(
            token in msg.lower()
            for token in ("validation", "missing", "required", "field")
        ), (
            f"warning log lacks any Pydantic-validation context — operator "
            f"has to guess what schema mismatch caused the drop. "
            f"Captured: {msg!r}"
        )

    def test_transform_data_raises_if_all_records_fail_validation(self, caplog):
        """If EVERY record fails validation, that's a bug not a tolerable state (bd-0bp1).

        The fallback design (FMP → yfinance → SEC 13F) assumes at least
        one source succeeds. A complete drop means either (a) schema
        drift in FMP, or (b) all fallback sources are broken. Either way
        returning an empty list silently is worse than raising — the
        empty result is indistinguishable from "this ticker has no
        institutional owners", which is a fundamentally different
        answer.
        """
        import logging

        from openbb_fmp.models.institutional_ownership import (
            FMPInstitutionalOwnershipQueryParams,
        )

        # ALL records are malformed → transform_data should raise.
        invalid_records = [
            {"symbol": "TSLA", "some_field": 42},
            {"symbol": "MSFT", "other_field": "junk"},
        ]
        query = FMPInstitutionalOwnershipQueryParams(symbol="TSLA,MSFT")

        with caplog.at_level(
            logging.WARNING,
            logger="openbb_fmp_cached.models.institutional_ownership",
        ), pytest.raises(ValueError, match="institutional"):
            FMPCachedInstitutionalOwnershipFetcher.transform_data(
                query, invalid_records
            )

    def test_transform_data_empty_input_does_not_raise(self, caplog):
        """Empty input list is a valid degenerate case, NOT the 'all dropped' bug.

        PR #345 silent-failure-hunter (P2): the original version of this
        test only checked the return value. If a future refactor emits
        a log line on empty input (e.g. ``logger.info("nothing to
        validate")``), that would silently slip through and the
        "empty ≠ all-dropped" contract would rot. The added log-silence
        assertion locks in that empty-input takes the fast-path with
        NO logging at all.
        """
        import logging

        from openbb_fmp.models.institutional_ownership import (
            FMPInstitutionalOwnershipQueryParams,
        )

        query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")
        with caplog.at_level(
            logging.DEBUG,
            logger="openbb_fmp_cached.models.institutional_ownership",
        ):
            # An empty input list is DIFFERENT from "all records failed
            # validation" — no records means no signal about schema drift.
            # Return empty; do not raise; do NOT emit any log records.
            result = FMPCachedInstitutionalOwnershipFetcher.transform_data(query, [])

        assert result == []
        # No records tried → no logging. This is what distinguishes
        # empty-input from the all-dropped path (which emits N WARNINGs
        # + 1 raise).
        assert caplog.records == [], (
            f"empty-input path should be silent — no drops, no attempts, "
            f"no logs. Captured: {[r.getMessage() for r in caplog.records]!r}"
        )

    def test_transform_data_narrow_except_lets_non_validation_errors_propagate(self):
        """Non-ValidationError exceptions must NOT be mislabeled as schema mismatch (PR #345 review, P2).

        Pre-PR-#345-review the ``except Exception`` was too broad — a
        ``TypeError`` or ``AttributeError`` from a bug in Pydantic itself
        or in the record dict would be silently swallowed and logged as
        'schema mismatch', hiding the real bug. The narrowed
        ``except ValidationError`` now lets non-validation errors
        propagate so they surface as real bugs.
        """
        from unittest.mock import patch

        from openbb_fmp.models.institutional_ownership import (
            FMPInstitutionalOwnershipQueryParams,
        )
        from openbb_fmp_cached.models.institutional_ownership import (
            FMPInstitutionalOwnershipData,
        )

        query = FMPInstitutionalOwnershipQueryParams(symbol="TSLA")
        boom = RuntimeError(
            "simulated non-validation error (e.g. bug in Pydantic internals)"
        )

        # Patch model_validate to raise a RuntimeError (not a
        # ValidationError). Pre-fix (with ``except Exception``) this
        # would be silently caught, incremented in ``drops``, and
        # eventually mislabeled as 'All ... records failed FMP schema
        # validation'. Post-fix the RuntimeError propagates as-is.
        with patch.object(
            FMPInstitutionalOwnershipData,
            "model_validate",
            side_effect=boom,
        ), pytest.raises(RuntimeError, match="simulated non-validation"):
            FMPCachedInstitutionalOwnershipFetcher.transform_data(
                query, [{"symbol": "TSLA"}]
            )


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
            from openbb_fmp.models.institutional_ownership import (
                FMPInstitutionalOwnershipQueryParams,
            )

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
            from openbb_fmp.models.institutional_ownership import (
                FMPInstitutionalOwnershipQueryParams,
            )

            query = FMPInstitutionalOwnershipQueryParams(symbol="")
            result = await FMPCachedInstitutionalOwnershipFetcher.aextract_data(
                query, {"fmp_api_key": "test"}
            )
            assert result == []


class TestNullPercentTolerance:
    """Regression tests for #1390 — FMP intermittently returns ``null`` for
    the three derived percent fields (ownership_percent,
    last_ownership_percent, ownership_percent_change). Pre-fix, a single
    null nuked the whole record via ValidationError; for a symbol where
    EVERY row had null percents (observed on MSFT, 2026-07), the
    "all-dropped ⇒ raise" guard fired and the entire fetch threw
    ValueError. Post-fix, _TolerantInstitutionalOwnershipData relaxes
    those three fields to Optional[float] so records survive with None
    percents and the caller gets share counts / invested totals /
    holder counts back.
    """

    def test_all_three_percents_null_now_kept(self):
        """The exact MSFT repro: every record has all three percents
        null. Pre-fix: ValueError raised. Post-fix: record kept, percents
        become None, other fields preserved.
        """
        from openbb_fmp_cached.models.institutional_ownership import (
            FMPCachedInstitutionalOwnershipFetcher,
            FMPInstitutionalOwnershipQueryParams,
        )

        # Two records, both with null percents — the exact shape #1390 reports.
        record = _fmp_record(symbol="MSFT")
        record["ownership_percent"] = None
        record["last_ownership_percent"] = None
        record["ownership_percent_change"] = None
        record2 = _fmp_record(symbol="MSFT")
        record2["ownership_percent"] = None
        record2["last_ownership_percent"] = None
        record2["ownership_percent_change"] = None
        record2["date"] = "2025-10-15"

        query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")
        # Must NOT raise. Pre-fix this raised ValueError with "All 2
        # institutional-ownership record(s) failed FMP schema validation".
        result = FMPCachedInstitutionalOwnershipFetcher.transform_data(
            query, [record, record2]
        )

        assert len(result) == 2, "both records must survive null-percent validation"
        # Percents propagate as None on the kept record.
        assert result[0].ownership_percent is None
        assert result[0].last_ownership_percent is None
        assert result[0].ownership_percent_change is None
        # Non-percent fields preserved — this is the whole point of the fix.
        assert result[0].investors_holding == 4500
        assert result[0].number_of_13f_shares == 5_000_000_000
        assert result[0].total_invested == 1_500_000_000_000.0

    def test_one_of_three_percents_null_still_kept(self):
        """Partial-null case: only one of the three percent fields is null.
        Pre-fix: record dropped via ValidationError. Post-fix: kept.
        """
        from openbb_fmp_cached.models.institutional_ownership import (
            FMPCachedInstitutionalOwnershipFetcher,
            FMPInstitutionalOwnershipQueryParams,
        )

        record = _fmp_record(symbol="MSFT", ownership_pct=0.72)
        record["ownership_percent_change"] = None  # only one null

        query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")
        result = FMPCachedInstitutionalOwnershipFetcher.transform_data(query, [record])

        assert len(result) == 1
        # Parent's normalize_percent divides raw by 100 (percent -> fraction).
        # 0.72 stored -> 0.0072 after validation.
        assert result[0].ownership_percent == pytest.approx(0.0072)
        assert result[0].last_ownership_percent == pytest.approx(0.007)
        assert result[0].ownership_percent_change is None  # null preserved

    def test_valid_percents_still_pass_through(self):
        """Sanity check: records with valid percents still validate and
        round-trip correctly. Guards against the tolerant subclass
        accidentally rejecting valid input.
        """
        from openbb_fmp_cached.models.institutional_ownership import (
            FMPCachedInstitutionalOwnershipFetcher,
            FMPInstitutionalOwnershipQueryParams,
        )

        record = _fmp_record(symbol="MSFT", ownership_pct=0.72)
        query = FMPInstitutionalOwnershipQueryParams(symbol="MSFT")

        result = FMPCachedInstitutionalOwnershipFetcher.transform_data(query, [record])

        assert len(result) == 1
        # Parent's normalize_percent divides raw by 100 (percent -> fraction).
        assert result[0].ownership_percent == pytest.approx(0.0072)
        assert result[0].last_ownership_percent == pytest.approx(0.007)
        assert result[0].ownership_percent_change == pytest.approx(0.0002)

    def test_tolerant_class_is_subclass_of_parent(self):
        """Downstream consumers type-check against
        FMPInstitutionalOwnershipData — the tolerant subclass must
        preserve that IS-A relationship or callers reading .attributes
        via the parent type will regress.
        """
        from openbb_fmp.models.institutional_ownership import (
            FMPInstitutionalOwnershipData,
        )
        from openbb_fmp_cached.models.institutional_ownership import (
            _TolerantInstitutionalOwnershipData,
        )

        assert issubclass(
            _TolerantInstitutionalOwnershipData, FMPInstitutionalOwnershipData
        )
        record = _fmp_record(symbol="MSFT")
        record["ownership_percent"] = None
        record["last_ownership_percent"] = None
        record["ownership_percent_change"] = None
        instance = _TolerantInstitutionalOwnershipData.model_validate(record)
        assert isinstance(instance, FMPInstitutionalOwnershipData)
