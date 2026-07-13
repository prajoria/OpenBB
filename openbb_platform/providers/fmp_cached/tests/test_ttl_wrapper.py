"""Unit tests for create_ttl_wrapper_class (P2.2).

Verifies:
  - First call: cache MISS -> SELECT returns None -> inner fetcher called
    -> UPSERT with fresh payload
  - Second call within TTL: cache HIT -> SELECT returns payload -> inner
    fetcher NOT called -> no UPSERT
  - DB failure on SELECT: fall through to live fetch (never fail-fast) +
    still attempt to UPSERT afterward
  - Wrapper class __name__ reflects source for debugging clarity
  - Reused by ExchangeMarketHours (integration-level smoke: cached class
    is a Fetcher subclass and has the expected __name__)

Environment: MySQL is mocked via unittest.mock.patch on execute_query /
execute_many — no live server needed. This file lives at
openbb_platform/providers/fmp_cached/tests/test_ttl_wrapper.py (one level
up from openbb_fmp_cached/, alongside test_cache_schema.py — matches the
convention P2.1's tests established).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class _FakeQuery:
    """Minimal query stub with a stable JSON serialization for cache_key hashing."""

    def model_dump_json(self, exclude_none=True):
        return '{"date":"2026-07-09"}'


def _fresh_inner():
    """Build a fresh _FakeInner class each test so AsyncMock state doesn't leak."""

    class _FakeInner:
        aextract_data = AsyncMock(
            return_value=[{"exchange": "NASDAQ", "is_open": True}]
        )
        transform_query = staticmethod(lambda p: _FakeQuery())
        transform_data = staticmethod(lambda q, d, **k: d)

    return _FakeInner


class TestFirstCallMissesAndUpserts:
    """First call: cache MISS -> inner fetcher runs -> UPSERT records payload."""

    @pytest.mark.asyncio
    async def test_miss_triggers_inner_fetch_and_upsert(self):
        from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

        inner = _fresh_inner()
        cls = create_ttl_wrapper_class(inner, "ExchangeMarketHours", 86400)

        with patch(
            "openbb_fmp_cached.utils.database.execute_query", return_value=[]
        ) as mock_select, patch(
            "openbb_fmp_cached.utils.database.execute_many"
        ) as mock_upsert:
            result = await cls.aextract_data(_FakeQuery())

        assert result == [{"exchange": "NASDAQ", "is_open": True}]
        inner.aextract_data.assert_awaited_once()  # inner fetch happened
        mock_select.assert_called_once()  # SELECT ran and MISSed
        mock_upsert.assert_called_once()  # UPSERT ran

        # UPSERT contract: single row of (cache_name, cache_key, payload)
        upsert_sql = mock_upsert.call_args[0][0]
        upsert_params = mock_upsert.call_args[0][1]
        assert "INSERT INTO ttl_cache" in upsert_sql
        assert "ON DUPLICATE KEY UPDATE" in upsert_sql
        assert len(upsert_params) == 1
        cache_name, cache_key, payload = upsert_params[0]
        assert cache_name == "ExchangeMarketHours"
        assert len(cache_key) == 64  # SHA-256 hex


class TestSecondCallWithinTTLHitsCache:
    """Second call within TTL: cache HIT -> inner fetcher NOT called -> no UPSERT."""

    @pytest.mark.asyncio
    async def test_hit_short_circuits_inner_fetch(self):
        from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

        inner = _fresh_inner()
        cls = create_ttl_wrapper_class(inner, "ExchangeMarketHours", 86400)

        # SELECT returns a fresh cached row
        cached_row = [
            {"payload": '[{"exchange":"NASDAQ","is_open":true}]'}
        ]
        with patch(
            "openbb_fmp_cached.utils.database.execute_query",
            return_value=cached_row,
        ), patch(
            "openbb_fmp_cached.utils.database.execute_many"
        ) as mock_upsert:
            result = await cls.aextract_data(_FakeQuery())

        assert result == [{"exchange": "NASDAQ", "is_open": True}]
        inner.aextract_data.assert_not_awaited()  # NO inner fetch
        mock_upsert.assert_not_called()  # NO UPSERT (no fresh data to record)


class TestDBFailureFallsThroughToInnerFetch:
    """DB unavailable -> aextract_data still returns fresh data (never fail-fast)."""

    @pytest.mark.asyncio
    async def test_select_failure_still_returns_fresh_data(self):
        from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

        inner = _fresh_inner()
        cls = create_ttl_wrapper_class(inner, "ExchangeMarketHours", 86400)

        with patch(
            "openbb_fmp_cached.utils.database.execute_query",
            side_effect=RuntimeError("DB down"),
        ), patch(
            "openbb_fmp_cached.utils.database.execute_many"
        ) as mock_upsert:
            result = await cls.aextract_data(_FakeQuery())

        assert result == [{"exchange": "NASDAQ", "is_open": True}]
        inner.aextract_data.assert_awaited_once()  # fell through to live fetch
        # Best-effort UPSERT still attempted after fresh fetch:
        mock_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_failure_still_returns_fresh_data(self):
        from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

        inner = _fresh_inner()
        cls = create_ttl_wrapper_class(inner, "ExchangeMarketHours", 86400)

        with patch(
            "openbb_fmp_cached.utils.database.execute_query", return_value=[]
        ), patch(
            "openbb_fmp_cached.utils.database.execute_many",
            side_effect=RuntimeError("DB down mid-write"),
        ):
            # Should not raise — best-effort persistence
            result = await cls.aextract_data(_FakeQuery())

        assert result == [{"exchange": "NASDAQ", "is_open": True}]


class TestWrapperClassNameReflectsSource:
    """__name__ set for debugging clarity — e.g. 'ExchangeMarketHoursTTLCached'."""

    def test_class_name_suffix(self):
        from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

        cls = create_ttl_wrapper_class(
            _fresh_inner(), "ExchangeMarketHours", 86400
        )
        assert cls.__name__ == "ExchangeMarketHoursTTLCached"
        assert cls.__qualname__ == "ExchangeMarketHoursTTLCached"

    def test_class_name_uses_provided_name(self):
        from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

        cls = create_ttl_wrapper_class(
            _fresh_inner(), "Holidays", 86400
        )
        assert cls.__name__ == "HolidaysTTLCached"


class TestCredentialTranslation:
    """The wrapper translates fmp_cached_api_key -> fmp_api_key like create_fallback does."""

    @pytest.mark.asyncio
    async def test_fmp_cached_key_translated_before_inner_fetch(self):
        from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

        inner = _fresh_inner()
        cls = create_ttl_wrapper_class(inner, "ExchangeMarketHours", 86400)

        with patch(
            "openbb_fmp_cached.utils.database.execute_query", return_value=[]
        ), patch("openbb_fmp_cached.utils.database.execute_many"):
            await cls.aextract_data(
                _FakeQuery(), credentials={"fmp_cached_api_key": "abc123"}
            )

        # Inner fetcher was called — check its credentials arg was translated
        args, _kwargs = inner.aextract_data.call_args
        # aextract_data(query, translated_credentials, **kwargs)
        assert args[1] == {"fmp_api_key": "abc123"}

    @pytest.mark.asyncio
    async def test_no_credentials_passes_none_through(self):
        from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

        inner = _fresh_inner()
        cls = create_ttl_wrapper_class(inner, "ExchangeMarketHours", 86400)

        with patch(
            "openbb_fmp_cached.utils.database.execute_query", return_value=[]
        ), patch("openbb_fmp_cached.utils.database.execute_many"):
            await cls.aextract_data(_FakeQuery())  # credentials defaults to None

        args, _kwargs = inner.aextract_data.call_args
        assert args[1] is None


class TestExchangeMarketHoursIntegration:
    """P2.2 shipped ExchangeMarketHours as the first consumer of the wrapper.

    Integration-level smoke: verify the cached class was constructed with
    the right name + TTL, and that it's the class registered in the fmp_cached
    dedicated_fetchers dict (not the raw tier-2 wrapper).
    """

    def test_cached_class_uses_expected_name(self):
        from openbb_fmp_cached.models.exchange_market_hours import (
            FMPCachedExchangeMarketHoursFetcher,
        )

        assert (
            FMPCachedExchangeMarketHoursFetcher.__name__
            == "ExchangeMarketHoursTTLCached"
        )

    def test_ttl_constant_is_86400(self):
        from openbb_fmp_cached.models import exchange_market_hours

        assert exchange_market_hours._TTL_SECONDS == 86400

    def test_registered_in_dedicated_fetchers(self):
        """AC-parity check — ExchangeMarketHours resolves to the tier-1 class."""
        from openbb_fmp_cached import fmp_cached_provider
        from openbb_fmp_cached.models.exchange_market_hours import (
            FMPCachedExchangeMarketHoursFetcher,
        )

        registered = fmp_cached_provider.fetcher_dict.get("ExchangeMarketHours")
        assert registered is FMPCachedExchangeMarketHoursFetcher, (
            "ExchangeMarketHours must resolve to the tier-1 TTL-wrapped class, "
            "not the tier-2 fallback wrapper"
        )
