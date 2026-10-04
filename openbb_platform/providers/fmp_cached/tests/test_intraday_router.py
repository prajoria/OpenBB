"""Intraday, aftermarket and market-session route tests."""

import inspect
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError
from openbb_fmp_cached import fmp_cached_provider
from openbb_fmp_cached.models import equity_intraday_historical
from openbb_fmp_cached.routers.intraday_router import router
from pydantic import ValidationError

INTRADAY_MODELS = {
    "EquityIntradayHistorical": "equity_intraday_historical",
    "ExchangeMarketHours": "exchange_market_hours",
    "AftermarketTrade": "aftermarket_trade",
    "AftermarketQuote": "aftermarket_quote",
    "CompanyNotes": "company_notes",
    "ExecutiveCompensationBenchmark": "executive_compensation_benchmark",
    "HolidaysByExchange": "holidays_by_exchange",
    "TechnicalIndicatorIntraday": "technical_indicator_intraday",
    "EquityQuoteBatchShort": "equity_quote_batch_short",
}


def _manifest() -> list[dict]:
    path = (
        Path(__file__).parents[1] / "openbb_fmp_cached" / "assets" / "model_routes.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))["routes"]


def test_nine_intraday_models_have_stable_typed_routes():
    """All assigned registrations have one explicit operation."""
    evidence = {
        row["model"]: row for row in _manifest() if row["model"] in INTRADAY_MODELS
    }
    assert set(evidence) == set(INTRADAY_MODELS)
    paths = {route.path for route in router.api_router.routes}
    for model, command in INTRADAY_MODELS.items():
        assert evidence[model]["command"] == command
        assert f"/{command}" in paths


def test_intraday_interval_date_and_session_filters_are_typed():
    """Intraday history preserves dates, intervals and session selection."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "interval": "15min",
            "start_date": "2025-01-02",
            "end_date": "2025-01-03",
            "extended_hours": True,
        }
    )
    assert query.symbol == "AAPL"
    assert query.interval == "15min"
    assert query.start_date.date().isoformat() == "2025-01-02"
    assert query.end_date.date().isoformat() == "2025-01-03"
    assert query.extended_hours is True


def test_unsupported_intraday_intervals_are_rejected():
    """Unsupported intervals never reach provider transport."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    with pytest.raises(ValidationError):
        fetcher.transform_query({"symbol": "AAPL", "interval": "2min"})


@pytest.mark.asyncio
async def test_empty_market_sessions_preserve_provider_errors():
    """Closed-session EmptyDataError remains explicit, not success-shaped."""
    fetcher = fmp_cached_provider.fetcher_dict["AftermarketTrade"]
    original = fetcher.__mro__[1]
    query = fetcher.transform_query({"symbol": "AAPL"})
    with (
        patch.object(
            original,
            "aextract_data",
            new=AsyncMock(side_effect=EmptyDataError("No aftermarket session")),
        ),
        pytest.raises(EmptyDataError, match="No aftermarket session"),
    ):
        await fetcher.aextract_data(
            query,
            {"fmp_cached_api_key": "test"},
        )


def test_fallback_none_fetchers_preserve_credential_translation_wrappers():
    """The three assigned fallback-only registrations remain wrappers."""
    for model in (
        "AftermarketTrade",
        "EquityQuoteBatchShort",
        "TechnicalIndicatorIntraday",
    ):
        fetcher = fmp_cached_provider.fetcher_dict[model]
        assert fetcher.__name__.startswith("FallbackFMP")
        assert fetcher.__module__.endswith("base_cached")


def test_exchange_market_hours_retains_separate_ttl_descriptor():
    """Market-hours keeps its one-day TTL wrapper, not fallback semantics."""
    fetcher = fmp_cached_provider.fetcher_dict["ExchangeMarketHours"]
    closure = inspect.getclosurevars(fetcher.aextract_data).nonlocals
    assert fetcher.__name__ == "ExchangeMarketHoursTTLCached"
    assert closure["ttl"] == timedelta(days=1)
    assert closure["name"] == "ExchangeMarketHours"


@pytest.mark.parametrize(
    "model",
    [
        "EquityIntradayHistorical",
        "AftermarketQuote",
        "CompanyNotes",
        "ExecutiveCompensationBenchmark",
        "HolidaysByExchange",
    ],
)
def test_dedicated_intraday_fetchers_remain_cached(model):
    """Dedicated registrations cannot silently regress to fallback wrappers."""
    fetcher = fmp_cached_provider.fetcher_dict[model]
    assert fetcher.__module__.startswith("openbb_fmp_cached.models.")
    assert fetcher.__module__ != "openbb_fmp_cached.models.base_cached"
    assert fetcher.__name__.startswith("FMPCached")


def test_technical_indicator_query_is_strictly_typed():
    """Indicator and timeframe values preserve the real provider contract."""
    fetcher = fmp_cached_provider.fetcher_dict["TechnicalIndicatorIntraday"]
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "indicator": "SMA",
            "period_length": 20,
            "timeframe": "15min",
        }
    )
    assert query.indicator == "SMA"
    assert query.period_length == 20
    assert query.timeframe == "15min"
    with pytest.raises(ValidationError):
        fetcher.transform_query(
            {
                "symbol": "AAPL",
                "indicator": "NOT_REAL",
            }
        )


def test_intraday_cache_uses_inclusive_date_and_session_bounds():
    """Date-only end bounds include that day and session selection reaches SQL."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "interval": "5min",
            "start_date": "2025-01-02",
            "end_date": "2025-01-02",
            "extended_hours": False,
        }
    )
    rows = [
        {
            "symbol": "AAPL",
            "interval_type": "5min",
            "ts": datetime(2025, 1, 2, 9, 30),
            "open_price": 1,
            "high_price": 2,
            "low_price": 1,
            "close_price": 2,
            "volume": 10,
            "is_extended": False,
            "is_valid": True,
        },
        {
            "symbol": "AAPL",
            "interval_type": "5min",
            "ts": datetime(2025, 1, 2, 15, 55),
            "open_price": 2,
            "high_price": 3,
            "low_price": 2,
            "close_price": 3,
            "volume": 11,
            "is_extended": False,
            "is_valid": True,
        },
    ]
    with patch.object(
        equity_intraday_historical,
        "execute_query",
        return_value=rows,
    ) as execute:
        cached, has_gap = equity_intraday_historical._analyze_intraday_cache(query)
    params = execute.call_args.args[1]
    assert params[2] == datetime(2025, 1, 2)
    assert params[3] == datetime(2025, 1, 3)
    assert params[4] is False
    assert len(cached) == 2
    assert has_gap is True


def test_intraday_timezone_and_extended_markers_are_preserved():
    """Aware bounds stay aware and off-session bars receive explicit markers."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "interval": "5min",
            "start_date": "2025-01-02T00:00:00-05:00",
            "end_date": "2025-01-02T23:59:00-05:00",
            "extended_hours": True,
        }
    )
    assert query.start_date.tzinfo is not None
    with patch.object(
        equity_intraday_historical,
        "execute_query",
        return_value=[],
    ) as query_cache:
        equity_intraday_historical._analyze_intraday_cache(query)
    assert query_cache.call_args.args[1][2].tzinfo is None
    assert query_cache.call_args.args[1][3].tzinfo is None
    with patch.object(
        equity_intraday_historical,
        "execute_many",
    ) as execute:
        equity_intraday_historical._upsert_intraday_rows(
            "AAPL",
            "5min",
            [
                {"date": "2025-01-02 08:00:00", "close": 1},
                {"date": "2025-01-02 10:00:00", "close": 2},
            ],
        )
    params = execute.call_args.args[1]
    assert params[0][-1] is True
    assert params[1][-1] is False


def test_early_close_uses_exchange_calendar_session():
    """NYSE early-close bars after 13:00 are marked extended."""
    assert (
        equity_intraday_historical._is_extended_row(
            {"date": "2025-07-03 12:55:00"},
        )
        is False
    )
    assert (
        equity_intraday_historical._is_extended_row(
            {"date": "2025-07-03 13:05:00"},
        )
        is True
    )


def test_aware_bounds_convert_to_new_york_wall_time():
    """UTC instants are converted before comparing naïve cache timestamps."""
    value = datetime.fromisoformat("2025-01-02T14:30:00+00:00")
    assert equity_intraday_historical._local_naive(value) == datetime(
        2025,
        1,
        2,
        9,
        30,
    )


@pytest.mark.asyncio
async def test_non_us_regular_session_filter_fails_closed():
    """Known non-US suffixes are never filtered with NYSE hours."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    query = fetcher.transform_query(
        {
            "symbol": "RELIANCE.NS",
            "interval": "5min",
            "extended_hours": False,
        }
    )
    with (
        patch.object(
            equity_intraday_historical,
            "init_database",
            side_effect=RuntimeError("db unavailable"),
        ),
        pytest.raises(OpenBBError, match="US-listed symbols only"),
    ):
        await fetcher.aextract_data(
            query,
            {"fmp_cached_api_key": "test"},
        )


def test_invalid_same_session_tail_forces_refresh():
    """An invalidated extending bar prevents a false cache hit."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "interval": "5min",
            "start_date": "2025-01-02",
            "end_date": "2025-01-02",
        }
    )
    rows = [
        {
            "symbol": "AAPL",
            "interval_type": "5min",
            "ts": datetime(2025, 1, 2, 9, 30),
            "open_price": 1,
            "high_price": 1,
            "low_price": 1,
            "close_price": 1,
            "volume": 1,
            "is_extended": False,
            "is_valid": True,
        },
        {
            "symbol": "AAPL",
            "interval_type": "5min",
            "ts": datetime(2025, 1, 2, 10),
            "open_price": 1,
            "high_price": 1,
            "low_price": 1,
            "close_price": 1,
            "volume": 1,
            "is_extended": False,
            "is_valid": False,
        },
    ]
    with patch.object(
        equity_intraday_historical,
        "execute_query",
        return_value=rows,
    ):
        cached, has_gap = equity_intraday_historical._analyze_intraday_cache(query)
    assert len(cached) == 1
    assert has_gap is True


@pytest.mark.asyncio
async def test_unbounded_intraday_query_returns_fresh_rows():
    """A successful unbounded fetch is returned instead of discarded."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    raw_fetcher = equity_intraday_historical.FMPEquityIntradayHistoricalFetcher
    query = fetcher.transform_query({"symbol": "AAPL", "interval": "5min"})
    fresh = [
        {
            "symbol": "AAPL",
            "interval": "5min",
            "date": "2025-01-02 08:00:00",
            "close": 0.5,
        },
        {
            "symbol": "AAPL",
            "interval": "5min",
            "date": "2025-01-02 10:00:00",
            "close": 1,
        },
    ]
    with (
        patch.object(equity_intraday_historical, "init_database"),
        patch.object(
            raw_fetcher,
            "aextract_data",
            new=AsyncMock(return_value=fresh),
        ),
        patch.object(equity_intraday_historical, "_upsert_intraday_rows"),
        patch.object(equity_intraday_historical, "_invalidate_same_session_tail"),
    ):
        result = await fetcher.aextract_data(
            query,
            {"fmp_cached_api_key": "test"},
        )
    assert result == [fresh[1]]


@pytest.mark.asyncio
async def test_cache_outage_fallback_applies_session_filter():
    """Direct-FMP fallback preserves regular-session selection."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    raw_fetcher = equity_intraday_historical.FMPEquityIntradayHistoricalFetcher
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "interval": "5min",
            "extended_hours": False,
        }
    )
    fresh = [
        {"date": "2025-01-02 08:00:00", "close": 0.5},
        {"date": "2025-01-02 10:00:00", "close": 1},
    ]
    with (
        patch.object(
            equity_intraday_historical,
            "init_database",
            side_effect=RuntimeError("db unavailable"),
        ),
        patch.object(
            raw_fetcher,
            "aextract_data",
            new=AsyncMock(return_value=fresh),
        ),
    ):
        result = await fetcher.aextract_data(
            query,
            {"fmp_cached_api_key": "test"},
        )
    assert result == [fresh[1]]


@pytest.mark.asyncio
async def test_direct_fallback_applies_explicit_timestamp_bounds():
    """Raw date-granularity responses are trimmed to the requested times."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    raw_fetcher = equity_intraday_historical.FMPEquityIntradayHistoricalFetcher
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "interval": "5min",
            "start_date": "2025-01-02T10:00:00",
            "end_date": "2025-01-02T11:00:00",
        }
    )
    fresh = [
        {"date": "2025-01-02 09:30:00", "close": 0.5},
        {"date": "2025-01-02 10:30:00", "close": 1},
        {"date": "2025-01-02 15:55:00", "close": 2},
    ]
    with (
        patch.object(
            equity_intraday_historical,
            "init_database",
            side_effect=RuntimeError("db unavailable"),
        ),
        patch.object(
            raw_fetcher,
            "aextract_data",
            new=AsyncMock(return_value=fresh),
        ) as raw_fetch,
    ):
        result = await fetcher.aextract_data(
            query,
            {"fmp_cached_api_key": "test"},
        )
    assert result == [fresh[1]]
    raw_query = raw_fetch.await_args.args[0]
    assert raw_query.start_date == datetime(2025, 1, 2, 10)
    assert raw_query.end_date == datetime(2025, 1, 2, 11)


@pytest.mark.asyncio
async def test_direct_fallback_converts_utc_bounds_to_exchange_date():
    """Raw fetch and cache paths use the same New York calendar date."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    raw_fetcher = equity_intraday_historical.FMPEquityIntradayHistoricalFetcher
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "interval": "5min",
            "start_date": "2025-01-03T04:00:00+00:00",
            "end_date": "2025-01-03T04:30:00+00:00",
            "extended_hours": True,
        }
    )
    with (
        patch.object(
            equity_intraday_historical,
            "init_database",
            side_effect=RuntimeError("db unavailable"),
        ),
        patch.object(
            raw_fetcher,
            "aextract_data",
            new=AsyncMock(return_value=[]),
        ) as raw_fetch,
    ):
        await fetcher.aextract_data(
            query,
            {"fmp_cached_api_key": "test"},
        )
    raw_query = raw_fetch.await_args.args[0]
    assert raw_query.start_date == datetime(2025, 1, 2, 23)
    assert raw_query.end_date == datetime(2025, 1, 2, 23, 30)


def test_cache_write_failure_does_not_discard_fresh_data():
    """Best-effort persistence absorbs database write failures."""
    with patch.object(
        equity_intraday_historical,
        "_upsert_intraday_rows",
        side_effect=RuntimeError("write failed"),
    ):
        persisted = equity_intraday_historical._safe_upsert_intraday_rows(
            "AAPL",
            "5min",
            [{"date": "2025-01-02 10:00:00"}],
        )
    assert persisted is False


@pytest.mark.asyncio
async def test_bounded_fetch_survives_cache_write_failure():
    """Fresh bounded rows remain available when persistence fails."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    raw_fetcher = equity_intraday_historical.FMPEquityIntradayHistoricalFetcher
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "interval": "5min",
            "start_date": "2025-01-02",
            "end_date": "2025-01-02",
        }
    )
    fresh = [{"date": "2025-01-02 10:00:00", "close": 1}]
    with (
        patch.object(equity_intraday_historical, "init_database"),
        patch.object(
            equity_intraday_historical,
            "_analyze_intraday_cache",
            return_value=([], True),
        ) as analyze,
        patch.object(
            raw_fetcher,
            "aextract_data",
            new=AsyncMock(return_value=fresh),
        ),
        patch.object(
            equity_intraday_historical,
            "_safe_upsert_intraday_rows",
            return_value=False,
        ),
        patch.object(equity_intraday_historical, "_invalidate_same_session_tail"),
    ):
        result = await fetcher.aextract_data(
            query,
            {"fmp_cached_api_key": "test"},
        )
    assert result == fresh
    analyze.assert_called_once()


def test_explicit_datetime_end_bound_is_inclusive():
    """A bar exactly at an explicit end timestamp remains in the SQL range."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "interval": "5min",
            "start_date": "2025-01-02T09:30:00",
            "end_date": "2025-01-02T10:00:00",
        }
    )
    with patch.object(
        equity_intraday_historical,
        "execute_query",
        return_value=[],
    ) as execute:
        equity_intraday_historical._analyze_intraday_cache(query)
    assert execute.call_args.args[1][3] == datetime(2025, 1, 2, 10, 0, 1)


def test_explicit_midnight_is_not_treated_as_a_date_only_bound():
    """An explicit midnight timestamp includes one second, not a full day."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "interval": "5min",
            "start_date": "2025-01-01T23:55:00",
            "end_date": "2025-01-02T00:00:00",
        }
    )
    with patch.object(
        equity_intraday_historical,
        "execute_query",
        return_value=[],
    ) as execute:
        equity_intraday_historical._analyze_intraday_cache(query)
    assert execute.call_args.args[1][3] == datetime(2025, 1, 2, 0, 0, 1)


def test_timestamp_range_detects_missing_leading_and_trailing_bars():
    """Same-date rows do not prove timestamp-level cache coverage."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "interval": "5min",
            "start_date": "2025-01-02T09:30:00",
            "end_date": "2025-01-02T10:00:00",
        }
    )
    rows = []
    for timestamp in (datetime(2025, 1, 2, 9, 45), datetime(2025, 1, 2, 9, 55)):
        rows.append(
            {
                "symbol": "AAPL",
                "interval_type": "5min",
                "ts": timestamp,
                "open_price": 1,
                "high_price": 1,
                "low_price": 1,
                "close_price": 1,
                "volume": 1,
                "is_extended": False,
                "is_valid": True,
            }
        )
    with patch.object(
        equity_intraday_historical,
        "execute_query",
        return_value=rows,
    ):
        _, has_gap = equity_intraday_historical._analyze_intraday_cache(query)
    assert has_gap is True


def test_non_aligned_timestamp_range_uses_bar_start_coverage():
    """Complete bars satisfy requests whose bounds fall inside intervals."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "interval": "5min",
            "start_date": "2025-01-02T10:02:00",
            "end_date": "2025-01-02T11:02:00",
        }
    )
    rows = []
    for minute in range(5, 61, 5):
        timestamp = datetime(2025, 1, 2, 10) + timedelta(minutes=minute)
        rows.append(
            {
                "symbol": "AAPL",
                "interval_type": "5min",
                "ts": timestamp,
                "open_price": 1,
                "high_price": 1,
                "low_price": 1,
                "close_price": 1,
                "volume": 1,
                "is_extended": False,
                "is_valid": True,
            }
        )
    with patch.object(
        equity_intraday_historical,
        "execute_query",
        return_value=rows,
    ):
        _, has_gap = equity_intraday_historical._analyze_intraday_cache(query)
    assert has_gap is False


def test_hourly_alignment_uses_exchange_open_origin():
    """Hourly bars align from 09:30 rather than midnight."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    query = fetcher.transform_query(
        {
            "symbol": "AAPL",
            "interval": "1hour",
            "start_date": "2025-01-02T10:02:00",
            "end_date": "2025-01-02T15:00:00",
        }
    )
    rows = []
    for hour in range(10, 15):
        rows.append(
            {
                "symbol": "AAPL",
                "interval_type": "1hour",
                "ts": datetime(2025, 1, 2, hour, 30),
                "open_price": 1,
                "high_price": 1,
                "low_price": 1,
                "close_price": 1,
                "volume": 1,
                "is_extended": False,
                "is_valid": True,
            }
        )
    with patch.object(
        equity_intraday_historical,
        "execute_query",
        return_value=rows,
    ):
        _, has_gap = equity_intraday_historical._analyze_intraday_cache(query)
    assert has_gap is False


def test_fresh_rows_are_sorted_like_cache_hits():
    """Raw fallback order is deterministic across symbols and timestamps."""
    fetcher = fmp_cached_provider.fetcher_dict["EquityIntradayHistorical"]
    query = fetcher.transform_query(
        {
            "symbol": "AAPL,MSFT",
            "interval": "5min",
            "extended_hours": True,
        }
    )
    rows = [
        {"symbol": "MSFT", "date": "2025-01-02 10:05:00"},
        {"symbol": "AAPL", "date": "2025-01-02 10:05:00"},
        {"symbol": "AAPL", "date": "2025-01-02 10:00:00"},
    ]
    assert equity_intraday_historical._filter_fresh_rows(rows, query) == [
        rows[2],
        rows[1],
        rows[0],
    ]


def test_tail_invalidation_only_marks_an_open_bar():
    """Completed bars are immutable while the current bar is invalidated."""
    now = datetime.now(equity_intraday_historical.ZoneInfo("America/New_York")).replace(
        tzinfo=None
    )
    completed = [{"date": now - timedelta(minutes=10)}]
    with patch.object(
        equity_intraday_historical,
        "execute_query",
    ) as execute:
        equity_intraday_historical._invalidate_same_session_tail(
            "AAPL",
            "5min",
            completed,
        )
    execute.assert_not_called()

    active = [{"date": now - timedelta(minutes=1)}]
    with (
        patch.object(
            equity_intraday_historical,
            "_us_session_bounds",
            return_value=(datetime.min.time(), datetime.max.time()),
        ),
        patch.object(
            equity_intraday_historical,
            "execute_query",
        ) as execute,
    ):
        equity_intraday_historical._invalidate_same_session_tail(
            "AAPL",
            "5min",
            active,
        )
    execute.assert_called_once()


def test_active_after_hours_tail_is_invalidated():
    """An extending post-market bar is refreshed before its interval closes."""
    current = datetime(2025, 1, 2, 18, 3)
    tail = [{"date": datetime(2025, 1, 2, 18), "is_extended": True}]
    with patch.object(
        equity_intraday_historical,
        "execute_query",
    ) as execute:
        equity_intraday_historical._invalidate_same_session_tail(
            "AAPL",
            "5min",
            tail,
            now=current,
        )
    execute.assert_called_once()


def test_missing_exchange_session_is_a_cache_gap():
    """A whole missing trading day cannot be hidden by cross-date rows."""
    rows = [
        {"date": datetime(2025, 1, 3, 9, 30)},
        {"date": datetime(2025, 1, 7, 16)},
    ]
    assert (
        equity_intraday_historical._has_session_gap(
            rows,
            datetime(2025, 1, 3),
            datetime(2025, 1, 7, 23, 59),
            "1hour",
            False,
        )
        is True
    )
