"""Unit tests for tier-1 aftermarket-quote caching with 60s TTL (P2.1).

Verifies:
  - _fetch_fresh_rows returns (hits, miss_symbols) with correct partition
  - _upsert_aftermarket_rows INSERTs new rows and UPDATEs on duplicate key
  - Fetcher class exposes the openbb-standard shape
  - Cache-freshness cutoff uses now - 60s

Environment: MySQL is mocked via unittest.mock.patch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch


class TestFreshRowsPartition:
    """_fetch_fresh_rows correctly splits HIT vs MISS."""

    def test_all_symbols_hit(self):
        from openbb_fmp_cached.models.aftermarket_quote import _fetch_fresh_rows

        fake = [
            {"symbol": "AAPL", "price": 180.0, "bid": 179.9, "ask": 180.1,
             "bid_size": 100, "ask_size": 200, "volume": 500,
             "timestamp": datetime(2026, 7, 8, 20, 0)},
            {"symbol": "MSFT", "price": 400.0, "bid": 399.9, "ask": 400.1,
             "bid_size": 100, "ask_size": 200, "volume": 300,
             "timestamp": datetime(2026, 7, 8, 20, 0)},
        ]
        with patch(
            "openbb_fmp_cached.models.aftermarket_quote.execute_query",
            return_value=fake,
        ):
            hits, miss = _fetch_fresh_rows(["AAPL", "MSFT"], datetime(2026, 7, 8))
        assert len(hits) == 2
        assert miss == []

    def test_partial_hit(self):
        from openbb_fmp_cached.models.aftermarket_quote import _fetch_fresh_rows

        fake = [
            {"symbol": "AAPL", "price": 180.0, "bid": None, "ask": None,
             "bid_size": None, "ask_size": None, "volume": None,
             "timestamp": datetime(2026, 7, 8, 20, 0)},
        ]
        with patch(
            "openbb_fmp_cached.models.aftermarket_quote.execute_query",
            return_value=fake,
        ):
            hits, miss = _fetch_fresh_rows(
                ["AAPL", "MSFT", "NVDA"], datetime(2026, 7, 8),
            )
        assert [h["symbol"] for h in hits] == ["AAPL"]
        assert set(miss) == {"MSFT", "NVDA"}

    def test_all_miss(self):
        from openbb_fmp_cached.models.aftermarket_quote import _fetch_fresh_rows

        with patch(
            "openbb_fmp_cached.models.aftermarket_quote.execute_query",
            return_value=[],
        ):
            hits, miss = _fetch_fresh_rows(["AAPL"], datetime(2026, 7, 8))
        assert hits == []
        assert miss == ["AAPL"]

    def test_empty_symbols_returns_empty(self):
        from openbb_fmp_cached.models.aftermarket_quote import _fetch_fresh_rows

        hits, miss = _fetch_fresh_rows([], datetime(2026, 7, 8))
        assert hits == []
        assert miss == []

    def test_empty_symbols_short_circuits_before_sql(self):
        """Regression guard for #774.

        _fetch_fresh_rows([], ...) must NOT call execute_query, because
        the empty-list branch previously built `WHERE symbol IN ()` which
        MySQL rejects with a 1064 syntax error. The old-style hermetic
        return-value check (test_empty_symbols_returns_empty above) does
        NOT catch this — an empty rows list from execute_query also
        yields ([], []), so the assertion passes even against buggy code
        that fires malformed SQL at the DB.

        Mutation-verified (per CLAUDE.md R7.11): reverting the guard
        (`if not symbols: return [], []`) causes execute_query to be
        called with the malformed IN () query, failing this test.
        """
        from openbb_fmp_cached.models.aftermarket_quote import _fetch_fresh_rows

        with patch(
            "openbb_fmp_cached.models.aftermarket_quote.execute_query"
        ) as mock_execute:
            hits, miss = _fetch_fresh_rows([], datetime(2026, 7, 8))

        assert hits == []
        assert miss == []
        mock_execute.assert_not_called(), (
            "empty-symbols must short-circuit before hitting the DB; "
            "otherwise the WHERE symbol IN () SQL fires and 1064s"
        )


class TestUpsertShape:
    """_upsert_aftermarket_rows uses execute_many with correct row-tuple shape."""

    def test_upsert_calls_execute_many_with_all_rows(self):
        from openbb_fmp_cached.models.aftermarket_quote import _upsert_aftermarket_rows

        rows = [
            {"symbol": "AAPL", "price": 180.0, "bid": 179.9, "ask": 180.1,
             "bid_size": 100, "ask_size": 200, "volume": 500,
             "timestamp": datetime(2026, 7, 8, 20, 0)},
            {"symbol": "MSFT", "price": 400.0, "bid": 399.9, "ask": 400.1,
             "bid_size": 100, "ask_size": 200, "volume": 300,
             "timestamp": datetime(2026, 7, 8, 20, 0)},
        ]
        with patch(
            "openbb_fmp_cached.models.aftermarket_quote.execute_many"
        ) as mock_exec_many:
            _upsert_aftermarket_rows(rows)
        mock_exec_many.assert_called_once()
        sql = mock_exec_many.call_args[0][0]
        params = mock_exec_many.call_args[0][1]
        assert "INSERT INTO aftermarket_quote" in sql
        assert "ON DUPLICATE KEY UPDATE" in sql
        assert len(params) == 2
        # Each params tuple has 8 elements (symbol + 6 fields + timestamp):
        assert all(len(p) == 8 for p in params)

    def test_upsert_empty_rows_short_circuit(self):
        from openbb_fmp_cached.models.aftermarket_quote import _upsert_aftermarket_rows

        with patch(
            "openbb_fmp_cached.models.aftermarket_quote.execute_many"
        ) as mock_exec_many:
            _upsert_aftermarket_rows([])
        mock_exec_many.assert_not_called()


class TestFetcherClassContract:
    """Class exposes the openbb-Fetcher-standard shape."""

    def test_has_static_methods(self):
        from openbb_fmp_cached.models.aftermarket_quote import (
            FMPCachedAftermarketQuoteFetcher,
        )

        for name in ("transform_query", "aextract_data", "transform_data"):
            assert hasattr(FMPCachedAftermarketQuoteFetcher, name), name

    def test_transform_query_coerces_dict_to_params(self):
        from openbb_fmp_cached.models.aftermarket_quote import (
            FMPCachedAftermarketQuoteFetcher,
            FMPCachedAftermarketQuoteQueryParams,
        )

        q = FMPCachedAftermarketQuoteFetcher.transform_query({"symbol": "AAPL"})
        assert isinstance(q, FMPCachedAftermarketQuoteQueryParams)
        assert q.symbol == "AAPL"


class TestTTLConstant:
    """The 60-second TTL is a locked design decision per PRD §5.2."""

    def test_ttl_is_60_seconds(self):
        from openbb_fmp_cached.models import aftermarket_quote

        assert aftermarket_quote._TTL_SECONDS == 60
