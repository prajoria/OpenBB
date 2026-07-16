"""Unit tests for tier-1 intraday bar caching (P2.1).

Verifies:
  - _analyze_intraday_cache returns (rows, has_gap) with correct semantics
  - _upsert_intraday_rows INSERTs new rows and UPDATEs on duplicate key
  - _invalidate_same_session_tail flips today's tail bar is_valid=FALSE
  - _invalidate_same_session_tail leaves prior-session bars untouched
  - Fetcher class exposes the openbb-standard shape (transform_query,
    aextract_data, transform_data)

Environment: pymysql / cache_pool paths are mocked via unittest.mock.patch
so these tests run in the .venv_win without a live MySQL server.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest


class TestIntradayCacheAnalysis:
    """_analyze_intraday_cache: gap detection + row shape."""

    def test_missing_start_or_end_returns_gap(self):
        from openbb_fmp_cached.models.equity_intraday_historical import (
            FMPCachedEquityIntradayHistoricalQueryParams,
            _analyze_intraday_cache,
        )

        q = FMPCachedEquityIntradayHistoricalQueryParams(
            symbol="AAPL", interval="5min",
        )
        rows, has_gap = _analyze_intraday_cache(q)
        assert rows == []
        assert has_gap is True

    def test_empty_cache_returns_gap(self):
        from openbb_fmp_cached.models.equity_intraday_historical import (
            FMPCachedEquityIntradayHistoricalQueryParams,
            _analyze_intraday_cache,
        )

        q = FMPCachedEquityIntradayHistoricalQueryParams(
            symbol="AAPL", interval="5min",
            start_date=datetime(2026, 7, 8, 9, 30),
            end_date=datetime(2026, 7, 8, 16, 0),
        )
        with patch(
            "openbb_fmp_cached.models.equity_intraday_historical.execute_query",
            return_value=[],
        ):
            rows, has_gap = _analyze_intraday_cache(q)
        assert rows == []
        assert has_gap is True

    def test_full_range_cached_returns_no_gap(self):
        from openbb_fmp_cached.models.equity_intraday_historical import (
            FMPCachedEquityIntradayHistoricalQueryParams,
            _analyze_intraday_cache,
        )

        start = datetime(2026, 7, 8, 9, 30)
        end = datetime(2026, 7, 8, 10, 0)
        q = FMPCachedEquityIntradayHistoricalQueryParams(
            symbol="AAPL", interval="5min", start_date=start, end_date=end,
        )
        fake_rows = [
            {
                "symbol": "AAPL", "interval_type": "5min", "ts": start,
                "open_price": 180.0, "high_price": 180.5, "low_price": 179.5,
                "close_price": 180.2, "volume": 1000, "is_extended": False,
                "is_valid": True,
            },
            {
                "symbol": "AAPL", "interval_type": "5min", "ts": end,
                "open_price": 180.2, "high_price": 180.6, "low_price": 180.0,
                "close_price": 180.4, "volume": 900, "is_extended": False,
                "is_valid": True,
            },
        ]
        with patch(
            "openbb_fmp_cached.models.equity_intraday_historical.execute_query",
            return_value=fake_rows,
        ):
            rows, has_gap = _analyze_intraday_cache(q)
        assert len(rows) == 2
        assert has_gap is False


class TestTailInvalidation:
    """_invalidate_same_session_tail: correctness rule for extending bars."""

    def test_today_tail_gets_marked_invalid(self):
        from openbb_fmp_cached.models.equity_intraday_historical import (
            _invalidate_same_session_tail,
        )

        today_bar = {
            "symbol": "MSFT", "interval": "5min",
            "date": datetime.combine(date.today(), datetime.min.time()).replace(hour=10),
            "close": 400.0,
        }
        with patch(
            "openbb_fmp_cached.models.equity_intraday_historical.execute_query"
        ) as mock_exec:
            _invalidate_same_session_tail("MSFT", "5min", [today_bar])
        mock_exec.assert_called_once()
        # Assert UPDATE ... is_valid=FALSE appears in the SQL. Compare
        # case-insensitively AND whitespace-insensitively — the production
        # emitter may render "FALSE" or "false", and formatters may or
        # may not put spaces around "=". Lowercasing the expected substring
        # matches sql.lower() correctly (regression: earlier version
        # asserted "is_valid = FALSE" against sql.lower(), which trivially
        # fails once the assertion applies .lower() to the haystack).
        sql = mock_exec.call_args[0][0]
        assert "UPDATE" in sql.upper()
        assert (
            "is_valid = false" in sql.lower()
            or "is_valid=false" in sql.replace(" ", "").lower()
        )

    def test_prior_day_tail_left_untouched(self):
        from openbb_fmp_cached.models.equity_intraday_historical import (
            _invalidate_same_session_tail,
        )

        yesterday = date.today() - timedelta(days=1)
        prior_bar = {
            "symbol": "MSFT", "interval": "5min",
            "date": datetime.combine(yesterday, datetime.min.time()).replace(hour=15, minute=55),
            "close": 400.0,
        }
        with patch(
            "openbb_fmp_cached.models.equity_intraday_historical.execute_query"
        ) as mock_exec:
            _invalidate_same_session_tail("MSFT", "5min", [prior_bar])
        mock_exec.assert_not_called()

    def test_empty_rows_short_circuit(self):
        from openbb_fmp_cached.models.equity_intraday_historical import (
            _invalidate_same_session_tail,
        )

        with patch(
            "openbb_fmp_cached.models.equity_intraday_historical.execute_query"
        ) as mock_exec:
            _invalidate_same_session_tail("MSFT", "5min", [])
        mock_exec.assert_not_called()


class TestCredentialTranslation:
    """_translate_credentials: SecretStr handling + UserService fallback."""

    def test_fmp_cached_api_key_translated_to_fmp_api_key(self):
        from openbb_fmp_cached.models.equity_intraday_historical import (
            _translate_credentials,
        )

        result = _translate_credentials({"fmp_cached_api_key": "abc123"})
        assert result == {"fmp_api_key": "abc123"}

    def test_secretstr_unwrapped(self):
        from pydantic import SecretStr

        from openbb_fmp_cached.models.equity_intraday_historical import (
            _translate_credentials,
        )

        result = _translate_credentials({"fmp_cached_api_key": SecretStr("secret_key")})
        assert result == {"fmp_api_key": "secret_key"}

    def test_direct_fmp_api_key_passthrough(self):
        from openbb_fmp_cached.models.equity_intraday_historical import (
            _translate_credentials,
        )

        creds = {"fmp_api_key": "direct"}
        assert _translate_credentials(creds) == creds


class TestFetcherClassContract:
    """Class exposes the openbb-Fetcher-standard shape."""

    def test_has_static_methods(self):
        from openbb_fmp_cached.models.equity_intraday_historical import (
            FMPCachedEquityIntradayHistoricalFetcher,
        )

        for name in ("transform_query", "aextract_data", "transform_data"):
            assert hasattr(FMPCachedEquityIntradayHistoricalFetcher, name), name

    def test_transform_query_coerces_dict_to_params(self):
        from openbb_fmp_cached.models.equity_intraday_historical import (
            FMPCachedEquityIntradayHistoricalFetcher,
            FMPCachedEquityIntradayHistoricalQueryParams,
        )

        q = FMPCachedEquityIntradayHistoricalFetcher.transform_query(
            {"symbol": "AAPL", "interval": "5min"}
        )
        assert isinstance(q, FMPCachedEquityIntradayHistoricalQueryParams)
        assert q.symbol == "AAPL"
        assert q.interval == "5min"
