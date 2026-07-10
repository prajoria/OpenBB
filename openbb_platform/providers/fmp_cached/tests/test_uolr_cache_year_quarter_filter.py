"""Unit tests for institutional_ownership cache-read year/quarter filter — bd-uolr.

Pre-fix ``_get_cached_institutional(symbol)`` filtered only by symbol,
is_valid, and cached_at TTL — NOT by year/quarter. Result: a call for
(sym=AAPL, year=2024, quarter=1) would return whatever period happened
to be cached, silently poisoning historical time-series analytics.

Post-fix the function takes (symbol, year, quarter) and filters payloads
by exact (year, quarter) match on the JSON payload. When year OR quarter
is None on the query, treat as cache-miss to avoid duplicating FMP's
default-latest-quarter logic (D2 in design spec).
"""

from __future__ import annotations

import json
from unittest.mock import patch


def _cached_row(year: int, quarter: int, extra: dict | None = None) -> dict:
    """Build a fake execute_query result row with JSON payload."""
    payload = {
        "symbol": "AAPL",
        "year": year,
        "quarter": quarter,
        "date": f"{year}-{quarter * 3:02d}-30",
        "investor": "Vanguard",
    }
    if extra:
        payload.update(extra)
    return {"data_json": json.dumps(payload)}


class TestGetCachedInstitutionalYearQuarterFilter:
    """_get_cached_institutional filters by (symbol, year, quarter) — bd-uolr."""

    def test_cache_hit_returns_matching_year_quarter(self):
        """Cache has AAPL {2024, Q1}; call for (2024, Q1) → returns it."""
        from openbb_fmp_cached.models.institutional_ownership import (
            _get_cached_institutional,
        )

        with patch(
            "openbb_fmp_cached.models.institutional_ownership.execute_query",
            return_value=[_cached_row(2024, 1)],
        ):
            result = _get_cached_institutional("AAPL", year=2024, quarter=1)

        assert len(result) == 1
        assert result[0]["year"] == 2024
        assert result[0]["quarter"] == 1

    def test_cache_miss_on_different_year(self):
        """Cache has {2024, Q1}; call for (2023, Q1) → cache-miss (returns [])."""
        from openbb_fmp_cached.models.institutional_ownership import (
            _get_cached_institutional,
        )

        with patch(
            "openbb_fmp_cached.models.institutional_ownership.execute_query",
            return_value=[_cached_row(2024, 1)],
        ):
            result = _get_cached_institutional("AAPL", year=2023, quarter=1)

        assert result == [], (
            "Different year MUST be treated as cache-miss. Pre-fix bd-uolr "
            "returned the 2024/Q1 row silently, poisoning historical "
            "time-series analytics."
        )

    def test_cache_miss_on_different_quarter(self):
        """Cache has {2024, Q1}; call for (2024, Q2) → cache-miss."""
        from openbb_fmp_cached.models.institutional_ownership import (
            _get_cached_institutional,
        )

        with patch(
            "openbb_fmp_cached.models.institutional_ownership.execute_query",
            return_value=[_cached_row(2024, 1)],
        ):
            result = _get_cached_institutional("AAPL", year=2024, quarter=2)

        assert result == []

    def test_none_year_is_cache_miss(self):
        """D2: year=None → cache-miss (fall through to FMP for defaulting).

        FMP applies default-latest-quarter logic when year/quarter is None.
        Duplicating that logic client-side would drift over time. Simpler:
        skip cache if either is None and let FMP compute the default.
        """
        from openbb_fmp_cached.models.institutional_ownership import (
            _get_cached_institutional,
        )

        with patch(
            "openbb_fmp_cached.models.institutional_ownership.execute_query",
            return_value=[_cached_row(2024, 1)],
        ):
            result = _get_cached_institutional("AAPL", year=None, quarter=1)

        assert result == [], (
            "year=None MUST be cache-miss (D2). Pre-fix returned the cached "
            "row regardless of query params. Alternative would be to "
            "duplicate FMP's default-latest logic here, which risks drift."
        )

    def test_none_quarter_is_cache_miss(self):
        """D2: quarter=None → cache-miss."""
        from openbb_fmp_cached.models.institutional_ownership import (
            _get_cached_institutional,
        )

        with patch(
            "openbb_fmp_cached.models.institutional_ownership.execute_query",
            return_value=[_cached_row(2024, 1)],
        ):
            result = _get_cached_institutional("AAPL", year=2024, quarter=None)

        assert result == []

    def test_multiple_periods_cached_returns_only_matching(self):
        """Cache has {2024, Q1} AND {2024, Q2}; call (2024, Q1) → only Q1."""
        from openbb_fmp_cached.models.institutional_ownership import (
            _get_cached_institutional,
        )

        with patch(
            "openbb_fmp_cached.models.institutional_ownership.execute_query",
            return_value=[_cached_row(2024, 1), _cached_row(2024, 2)],
        ):
            result = _get_cached_institutional("AAPL", year=2024, quarter=1)

        assert len(result) == 1, (
            f"Expected exactly 1 row (Q1), got {len(result)}. Filter must "
            f"partition rows by (year, quarter) not return everything."
        )
        assert result[0]["quarter"] == 1

    def test_empty_cache_returns_empty(self):
        """No cached rows for the symbol → []."""
        from openbb_fmp_cached.models.institutional_ownership import (
            _get_cached_institutional,
        )

        with patch(
            "openbb_fmp_cached.models.institutional_ownership.execute_query",
            return_value=[],
        ):
            result = _get_cached_institutional("AAPL", year=2024, quarter=1)

        assert result == []

    def test_already_decoded_dict_payload(self):
        """PR #426 code-reviewer P1: MySQL JSON columns may return dict, not str.

        The isinstance(payload, str) branch means dict-payloads take a
        different code path. Test that both routes work — a future MySQL
        driver upgrade that starts returning dicts must not break the
        year/quarter filter.
        """
        from openbb_fmp_cached.models.institutional_ownership import (
            _get_cached_institutional,
        )

        # Payload already a dict (not a JSON string) — MySQL JSON columns
        # may return this shape depending on driver + column type.
        already_dict = {
            "symbol": "AAPL",
            "year": 2024,
            "quarter": 1,
            "investor": "BlackRock",
        }
        with patch(
            "openbb_fmp_cached.models.institutional_ownership.execute_query",
            return_value=[{"data_json": already_dict}],
        ):
            result = _get_cached_institutional("AAPL", year=2024, quarter=1)

        assert len(result) == 1
        assert result[0]["investor"] == "BlackRock"

    def test_execute_query_exception_returns_empty_with_warning(self, caplog):
        """PR #426 code-reviewer P1: cache-read exception logs warning + returns []."""
        from openbb_fmp_cached.models.institutional_ownership import (
            _get_cached_institutional,
        )

        with patch(
            "openbb_fmp_cached.models.institutional_ownership.execute_query",
            side_effect=RuntimeError("mysql down"),
        ), caplog.at_level(
            "WARNING", logger="openbb_fmp_cached.models.institutional_ownership"
        ):
            result = _get_cached_institutional("AAPL", year=2024, quarter=1)

        assert result == [], "DB error MUST safely return [] (best-effort cache)."
        assert any(
            "Cache read failed for AAPL" in rec.message for rec in caplog.records
        ), (
            "Cache-read exception MUST log WARNING with the symbol so "
            "operators can trace which symbol's cache read failed."
        )

    def test_string_year_in_payload_coerces_to_int(self):
        """PR #426 code-reviewer P1: FMP's JSON may drift to string year.

        Historically FMP has returned numeric fields as strings in some
        API versions. Post-fix defensively coerces payload year/quarter
        to int before comparison — otherwise `"2024" == 2024` would be
        False and every FMP row would silently become a cache-miss,
        triggering a permanent refetch storm.
        """
        from openbb_fmp_cached.models.institutional_ownership import (
            _get_cached_institutional,
        )

        # Simulate FMP returning year/quarter as strings.
        payload_with_string_year = {
            "symbol": "AAPL",
            "year": "2024",  # STRING, not int
            "quarter": "1",  # STRING, not int
            "investor": "State Street",
        }
        with patch(
            "openbb_fmp_cached.models.institutional_ownership.execute_query",
            return_value=[{"data_json": json.dumps(payload_with_string_year)}],
        ):
            result = _get_cached_institutional("AAPL", year=2024, quarter=1)

        assert len(result) == 1, (
            f"String year/quarter in payload MUST coerce to int for comparison "
            f"— otherwise every FMP row silently becomes a cache-miss. "
            f"Got {len(result)} rows."
        )

    def test_malformed_year_in_payload_skips_row_silently(self):
        """Legacy/malformed row with non-int year → skip that row, don't crash."""
        from openbb_fmp_cached.models.institutional_ownership import (
            _get_cached_institutional,
        )

        good_row = {"symbol": "AAPL", "year": 2024, "quarter": 1, "x": "good"}
        bad_row = {"symbol": "AAPL", "year": "not-a-number", "quarter": 1}
        with patch(
            "openbb_fmp_cached.models.institutional_ownership.execute_query",
            return_value=[
                {"data_json": json.dumps(good_row)},
                {"data_json": json.dumps(bad_row)},
            ],
        ):
            result = _get_cached_institutional("AAPL", year=2024, quarter=1)

        # Only the good row survives; bad row silently skipped (safe degrade).
        assert len(result) == 1
        assert result[0]["x"] == "good"


class TestStoreInstitutionalStampsYearQuarter:
    """_store_institutional stamps year/quarter into every payload — PR #426 hunter P1."""

    @patch("openbb_fmp_cached.models.institutional_ownership.replace_rows")
    def test_yfinance_record_gets_year_quarter_stamped(self, mock_replace):
        """PR #426 silent-failure-hunter P1: yfinance/SEC records don't include
        year/quarter, so _store_institutional MUST stamp them from the caller.

        Without this, every yfinance/SEC cache-write would produce rows the
        cache-read filter treats as cache-miss (year=None != 2024) →
        permanent refetch storm for every symbol not served by FMP.
        """
        from openbb_fmp_cached.models.institutional_ownership import (
            _store_institutional,
        )

        # yfinance-shaped record: no year/quarter keys.
        yf_records = [
            {"symbol": "TSLA", "investor": "Vanguard", "shares": 12345},
        ]
        _store_institutional(yf_records, data_source="yfinance", year=2024, quarter=1)

        assert mock_replace.call_count == 1
        rows = mock_replace.call_args.args[3]
        payload = json.loads(rows[0]["data_json"])
        assert payload["year"] == 2024, (
            "Post-fix MUST stamp year onto yfinance/SEC records so cache-read "
            "filter can match them. Pre-fix rows would have year=None."
        )
        assert payload["quarter"] == 1
        assert payload["data_source"] == "yfinance"

    @patch("openbb_fmp_cached.models.institutional_ownership.replace_rows")
    def test_fmp_record_year_quarter_overwritten_by_caller(self, mock_replace):
        """Even for FMP records (which include year/quarter), the caller's
        effective values overwrite — ensures cache-write consistency
        across all 3 sources.
        """
        from openbb_fmp_cached.models.institutional_ownership import (
            _store_institutional,
        )

        fmp_records = [
            {"symbol": "MSFT", "year": 2023, "quarter": 4, "investor": "V"},
        ]
        _store_institutional(fmp_records, data_source="fmp", year=2024, quarter=1)

        payload = json.loads(mock_replace.call_args.args[3][0]["data_json"])
        assert payload["year"] == 2024, (
            "Caller's effective year MUST win — otherwise cache-write and "
            "cache-read use different keys and hits become misses."
        )
        assert payload["quarter"] == 1


class TestEffectiveYearQuarter:
    """_effective_year_quarter mirrors FMP's default-latest logic."""

    def test_both_provided_returns_as_is(self):
        from openbb_fmp_cached.models.institutional_ownership import (
            _effective_year_quarter,
        )

        assert _effective_year_quarter(2023, 2) == (2023, 2)

    def test_both_none_returns_current_quarter(self):
        """None + None → latest computed quarter (never None)."""
        from openbb_fmp_cached.models.institutional_ownership import (
            _effective_year_quarter,
        )

        y, q = _effective_year_quarter(None, None)
        # Sanity: real int values, plausible year.
        assert isinstance(y, int)
        assert isinstance(q, int)
        assert 1 <= q <= 4
        assert y >= 2020  # sanity — not a pre-Y2K date

    def test_year_only_computes_quarter(self):
        from openbb_fmp_cached.models.institutional_ownership import (
            _effective_year_quarter,
        )

        # Historical year → q=4 (year is complete).
        y, q = _effective_year_quarter(2020, None)
        assert y == 2020
        assert q == 4

    def test_quarter_only_defaults_year_to_current(self):
        from openbb_fmp_cached.models.institutional_ownership import (
            _effective_year_quarter,
        )

        y, q = _effective_year_quarter(None, 3)
        assert isinstance(y, int)
        assert q == 3
