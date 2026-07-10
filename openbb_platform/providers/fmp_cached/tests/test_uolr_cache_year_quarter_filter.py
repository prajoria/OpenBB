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
