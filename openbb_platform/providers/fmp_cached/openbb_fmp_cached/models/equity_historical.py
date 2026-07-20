"""Cached equity_historical model for FMP with intelligent gap detection.

This module provides intelligent caching for FMP equity historical data with the following features:

1. **Gap Detection**: Analyzes cached data to detect missing date ranges
2. **Incremental Fetching**: Only fetches missing data from FMP API
3. **Multi-Symbol Support**: Handles comma-separated symbols efficiently
4. **Interval Awareness**: Caches different intervals (1d, 1h, etc.) separately
5. **Adjustment Support**: Handles different price adjustment types
6. **Market Day Logic**: Understands weekends and basic holidays

Usage:
    The fetcher automatically handles caching. First requests populate the cache,
    subsequent requests use cached data and only fetch missing ranges.

Database Schema:
    Uses optimized schema with minimal fields mapped 1:1 to FMP API responses.
    Includes interval_type and adjustment_type for proper cache differentiation.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Literal

from dateutil.relativedelta import relativedelta
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_historical import (
    EquityHistoricalData,
    EquityHistoricalQueryParams,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator, model_validator

from openbb_fmp_cached.utils.database import execute_many, execute_query, init_database

logger = logging.getLogger(__name__)


# ── FMP endpoint URL construction ─────────────────────────────────────────
#
# Explicit (adjustment, interval) -> URL-path map for the FMP stable API.
# Central table used by both ``_fetch_from_fmp_direct`` (async) and
# ``_fetch_from_fmp_sync`` (sync) so a future maintainer can't
# accidentally desync the two ladders (they had already diverged
# pre-fix — the async version was missing branches for 15m/30m/4h and
# both silently fell through to the daily endpoint on any non-
# splits_only adjustment). bd-o61s.
_FMP_BASE = "https://financialmodelingprep.com/stable/"

# Intraday interval -> FMP historical-chart endpoint suffix. All six
# intraday ``Literal`` values on ``FMPCachedEquityHistoricalQueryParams.interval``
# are represented; missing an entry means a fetch would silently 4xx
# from FMP with an empty endpoint path.
_INTRADAY_ENDPOINTS: dict[str, str] = {
    "1m": "historical-chart/1min",
    "5m": "historical-chart/5min",
    "15m": "historical-chart/15min",
    "30m": "historical-chart/30min",
    "1h": "historical-chart/1hour",
    "4h": "historical-chart/4hour",
}


def _build_fmp_endpoint(adjustment: str, interval: str) -> str:
    """Return the FMP endpoint URL for ``(adjustment, interval)``.

    The query params' ``model_validator`` already enforces the
    invariant that ``adjustment != 'splits_only'`` implies
    ``interval == '1d'``, so by the time we get here every combination
    is representable. But this helper is defence-in-depth: if a future
    refactor drops the validator, unknown interval values raise
    ``ValueError`` here instead of falling through to an empty endpoint
    (which used to happen for ``15m``/``30m``/``4h`` before bd-o61s).

    Return value has NO trailing ``?`` — callers pass query params via
    the underlying HTTP layer's ``params=`` kwarg (bd-6641 / bd-ir3f).
    """
    # Adjusted endpoints only exist for daily EOD data.
    if adjustment == "unadjusted":
        return _FMP_BASE + "historical-price-eod/non-split-adjusted"
    if adjustment == "splits_and_dividends":
        return _FMP_BASE + "historical-price-eod/dividend-adjusted"
    # adjustment == "splits_only" — either daily EOD or one of the intraday
    # historical-chart endpoints.
    if interval == "1d":
        return _FMP_BASE + "historical-price-eod/full"
    endpoint = _INTRADAY_ENDPOINTS.get(interval)
    if endpoint is None:
        raise ValueError(
            f"Unsupported FMP interval {interval!r}; "
            f"expected one of {sorted(_INTRADAY_ENDPOINTS) + ['1d']}"
        )
    return _FMP_BASE + endpoint


class FMPCachedEquityHistoricalQueryParams(EquityHistoricalQueryParams):
    """FMP Cached Equity Historical Query Parameters.

    Independent query parameters for the cached provider.
    """

    __json_schema_extra__ = {
        "symbol": {
            "multiple_items_allowed": True,
            "choices": None,
        }
    }

    interval: Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"] = Field(
        default="1d",
        description=QUERY_DESCRIPTIONS.get("interval", "Time interval of the data."),
    )
    adjustment: Literal["splits_only", "splits_and_dividends", "unadjusted"] = Field(
        default="splits_only",
        description="The adjustment type for the data. "
        "'splits_only' is adjusted for splits only. "
        "'splits_and_dividends' is adjusted for both splits and dividends. "
        "'unadjusted' is the raw, unadjusted data.",
    )
    include_dividends: bool = Field(
        default=True,
        description="Include dividend data in the results. "
        "When True, fetches dividend information from FMP and merges it with price data.",
    )

    @model_validator(mode="before")
    @classmethod
    def _validate_interval_adjustment(cls, values):
        """Reject adjustment != 'splits_only' on intraday intervals (bd-o61s).

        Mirrors the upstream ``FMPEquityHistoricalFetcher._validate_params``
        guard: FMP only exposes ``unadjusted`` and ``splits_and_dividends``
        adjustments on the daily EOD endpoint. Requesting them on an
        intraday interval used to silently return daily bars — a critical
        data-corruption footgun for backtests.
        """
        if isinstance(values, dict):
            interval = values.get("interval", "1d")
            adjustment = values.get("adjustment", "splits_only")
            if adjustment != "splits_only" and interval != "1d":
                raise ValueError(
                    "Adjustment can only be applied to daily ('1d') interval."
                )
        return values


class FMPCachedEquityHistoricalData(EquityHistoricalData):
    """FMP Cached Equity Historical Data.

    Independent data model for the cached provider.
    """

    __alias_dict__ = {
        "change_percent": "changePercent",
    }

    change: float | None = Field(
        default=None,
        description="Change in price.",
    )
    change_percent: float | None = Field(
        default=None,
        description="Change in price as a percentage.",
        json_schema_extra={"x-unit_measurement": "percent", "x-frontend_multiply": 100},
    )
    vwap: float | None = Field(
        default=None,
        description="Volume weighted average price.",
    )
    dividend: float | None = Field(
        default=None,
        description="Dividend amount paid on this date (if any).",
    )

    @field_validator("change_percent", mode="before", check_fields=False)
    @classmethod
    def _normalize_percent(cls, v):
        """Normalize percent."""
        return v / 100 if v else None


class FMPCachedEquityHistoricalFetcher(
    Fetcher[
        FMPCachedEquityHistoricalQueryParams,
        list[FMPCachedEquityHistoricalData],
    ]
):
    """FMP Cached Equity Historical Price Fetcher with dedicated database caching."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPCachedEquityHistoricalQueryParams:
        """Transform the query params."""
        transformed_params = params

        now = datetime.now().date()
        if params.get("start_date") is None:
            transformed_params["start_date"] = now - relativedelta(years=1)

        if params.get("end_date") is None:
            transformed_params["end_date"] = now

        return FMPCachedEquityHistoricalQueryParams(**transformed_params)

    @staticmethod
    async def aextract_data(
        query: FMPCachedEquityHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract equity historical data with intelligent gap detection and caching."""

        # Get credentials from user settings if not provided
        if credentials is None or not credentials.get("fmp_api_key"):
            try:
                # Import here to avoid circular imports
                from openbb_core.app.service.user_service import UserService

                user_service = UserService()
                user_settings = user_service.default_user_settings
                fmp_api_key = getattr(user_settings.credentials, "fmp_api_key", None)

                if fmp_api_key:
                    # Handle SecretStr type
                    api_key_value = (
                        fmp_api_key.get_secret_value()
                        if hasattr(fmp_api_key, "get_secret_value")
                        else str(fmp_api_key)
                    )
                    credentials = {"fmp_api_key": api_key_value}
                    logger.info("Using FMP API key from user settings")
                else:
                    logger.warning("No FMP API key found in user settings")
            except Exception as e:
                logger.warning(f"Could not load user settings: {e}")

        # Initialize database (simple sync call)
        try:
            init_database()
        except Exception as e:
            logger.warning(
                f"Database initialization failed, falling back to direct FMP: {e}"
            )
            return await _fetch_from_fmp_direct(query, credentials, **kwargs)

        # Fix credential mapping: fmp_cached_api_key -> fmp_api_key
        if credentials and "fmp_cached_api_key" in credentials:
            fmp_credentials = {"fmp_api_key": credentials["fmp_cached_api_key"]}
        else:
            fmp_credentials = credentials  # type: ignore[assignment]

        # Handle multiple symbols
        symbols = query.symbol.split(",") if "," in query.symbol else [query.symbol]
        all_results = []

        for symbol in symbols:
            # Create individual query for each symbol
            single_query = FMPCachedEquityHistoricalQueryParams(
                symbol=symbol.strip(),
                start_date=query.start_date,
                end_date=query.end_date,
                interval=query.interval,
                adjustment=query.adjustment,
            )

            # Check cache and detect gaps (sync call)
            try:
                cached_data, missing_ranges = _analyze_cache_gaps(single_query)

                if not missing_ranges:
                    # Complete cache hit
                    logger.info(
                        f"Cache HIT: Complete data for {symbol} ({len(cached_data)} records)"
                    )
                    all_results.extend(cached_data)
                    continue

                # Partial or complete cache miss - fetch missing data
                logger.info(
                    f"Cache PARTIAL: Found {len(missing_ranges)} gaps for {symbol}"
                )

                # Fetch missing data from FMP
                missing_data = []
                for start_gap, end_gap in missing_ranges:
                    gap_query = FMPCachedEquityHistoricalQueryParams(
                        symbol=symbol,
                        start_date=start_gap,
                        end_date=end_gap,
                        interval=query.interval,
                        adjustment=query.adjustment,
                    )

                    logger.info(f"Fetching gap: {symbol} from {start_gap} to {end_gap}")
                    gap_data = await _fetch_from_fmp_direct(
                        gap_query, fmp_credentials, **kwargs
                    )
                    missing_data.extend(gap_data)

                # Note: Holiday gaps are excluded from missing_ranges by _detect_missing_ranges()
                # so we don't make unnecessary API calls for known market closures.
                # Holidays remain as natural gaps in the final response for accuracy.

                # Store new data in cache (sync call)
                if missing_data:
                    _store_in_database_cache(single_query, missing_data)
                    logger.info(f"Cached {len(missing_data)} new records for {symbol}")

                # Get complete data from cache after update (sync call)
                try:
                    complete_data, remaining_gaps = _analyze_cache_gaps(single_query)
                    if remaining_gaps:
                        # bd-lyzk: severity-scaled logging — small gaps
                        # are legitimate background noise (holidays / IPO
                        # pre-history / delistings), moderate gaps warrant
                        # operator attention with specific dates, and large
                        # gaps escalate to ERROR for ops alerting (almost
                        # certainly a silent fetch failure). Pre-fix the
                        # single logger.warning with just the count gave
                        # operators no way to identify which dates were
                        # missing OR distinguish real fetch failures from
                        # tolerable data holes.
                        trading_days_requested = _count_trading_days_in_range(
                            single_query.start_date, single_query.end_date
                        )
                        _log_partial_gap_severity(
                            symbol, remaining_gaps, trading_days_requested
                        )

                    # Always use complete_data from cache as it includes both previous cache + newly stored data
                    all_results.extend(complete_data)
                except Exception as cache_error:
                    logger.error(
                        f"Second cache analysis failed for {symbol}: {cache_error}"
                    )
                    # Fallback: use the data we know we have (original cached data + newly fetched)
                    all_results.extend(cached_data)
                    all_results.extend(missing_data)

            except Exception as e:
                logger.warning(f"Cache analysis failed for {symbol}: {e}")
                # Fallback to direct API call
                fallback_data = await _fetch_from_fmp_direct(
                    single_query, fmp_credentials, **kwargs
                )
                if fallback_data:
                    _store_in_database_cache(single_query, fallback_data)
                all_results.extend(fallback_data)

        logger.info(f"Returning {len(all_results)} total records for query")

        # Fetch and merge dividends if requested
        if query.include_dividends and query.interval == "1d":
            try:
                dividend_map = await _fetch_dividends_from_fmp(
                    query, fmp_credentials, **kwargs
                )

                if dividend_map:
                    # Merge dividends into the results
                    for item in all_results:
                        symbol = item.get("symbol")
                        date = item.get("date")

                        if symbol in dividend_map and date in dividend_map[symbol]:
                            item["dividend"] = dividend_map[symbol][date]
                            logger.debug(
                                f"Added dividend {item['dividend']} for {symbol} on {date}"
                            )
                        else:
                            item["dividend"] = None

                    logger.info(f"Merged dividends for {len(dividend_map)} symbols")

                    # Update database with dividend data
                    # Group by symbol to update each symbol's data
                    symbol_data_map: dict = {}
                    for item in all_results:
                        sym = item.get("symbol")
                        if sym not in symbol_data_map:
                            symbol_data_map[sym] = []
                        symbol_data_map[sym].append(item)

                    # Update database for each symbol
                    for symbol, symbol_data in symbol_data_map.items():
                        symbol_query = FMPCachedEquityHistoricalQueryParams(
                            symbol=symbol,
                            start_date=query.start_date,
                            end_date=query.end_date,
                            interval=query.interval,
                            adjustment=query.adjustment,
                        )
                        _store_in_database_cache(symbol_query, symbol_data)
                        logger.debug(f"Updated database with dividends for {symbol}")
                else:
                    # No dividends found, set all to None
                    for item in all_results:
                        item["dividend"] = None
            except Exception as e:
                logger.warning(f"Failed to fetch/merge dividends: {e}")
                # Set all dividends to None on error
                for item in all_results:
                    item["dividend"] = None
        else:
            # Dividends not requested or not applicable for this interval
            for item in all_results:
                item["dividend"] = None

        # CRITICAL: Ensure we ALWAYS return dictionaries from aextract_data, never objects
        clean_results = []
        for item in all_results:
            if isinstance(item, dict):
                clean_results.append(item)
            elif hasattr(item, "model_dump"):
                # Convert FMPCachedEquityHistoricalData objects to dictionaries
                logger.warning(f"Converting {type(item)} object to dictionary")
                clean_results.append(item.model_dump())
            elif hasattr(item, "__dict__"):
                # Convert any other object to dictionary
                logger.warning(f"Converting {type(item)} object to dict via __dict__")
                clean_results.append(item.__dict__)
            else:
                logger.error(f"Unknown item type: {type(item)} - {item}")

        logger.info(f"Cleaned results: returning {len(clean_results)} dictionaries")
        return clean_results

    @staticmethod
    def transform_data(
        query: FMPCachedEquityHistoricalQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPCachedEquityHistoricalData]:
        """Transform the raw data to FMPCachedEquityHistoricalData objects."""
        if not data:
            raise EmptyDataError("No data returned from FMP for the given query.")
        return [
            FMPCachedEquityHistoricalData.model_validate(d)
            for d in sorted(
                data,
                key=lambda x: (
                    (x["date"], x["symbol"])
                    if len(query.symbol.split(",")) > 1
                    else x["date"]
                ),
                reverse=False,
            )
        ]


def _analyze_cache_gaps(
    query: FMPCachedEquityHistoricalQueryParams,
) -> tuple[list[dict[str, Any]], list[tuple[date, date]]]:
    """Analyze cache for gaps and return cached data + missing date ranges."""
    import time as _time

    _t0 = _time.time()
    logger.info(
        "Cache check: %s  %s -> %s  interval=%s  adj=%s",
        query.symbol,
        query.start_date,
        query.end_date,
        query.interval,
        query.adjustment,
    )

    cache_query = """
    SELECT symbol, date, open, high, low, close, volume, 
           change_amount, change_percent, vwap, dividend,
           is_filled, fill_source_date, fill_type
    FROM equity_historical 
    WHERE symbol = %s 
    AND date BETWEEN %s AND %s 
    AND interval_type = %s
    AND adjustment_type = %s
    AND is_valid = TRUE
    ORDER BY date ASC
    """

    try:
        # Get cached data using sync function
        results = execute_query(
            cache_query,
            (
                query.symbol,
                query.start_date,
                query.end_date,
                query.interval,
                query.adjustment,
            ),
        )

        # Convert to FMP format
        cached_data = []
        cached_dates: set[date] = set()

        for row in results:
            # row is a dictionary when using DictCursor
            data_dict = {
                "symbol": row["symbol"],
                "date": row["date"].strftime("%Y-%m-%d") if row["date"] else None,
                "open": float(row["open"]) if row["open"] is not None else None,
                "high": float(row["high"]) if row["high"] is not None else None,
                "low": float(row["low"]) if row["low"] is not None else None,
                "close": float(row["close"]) if row["close"] is not None else None,
                "volume": int(row["volume"]) if row["volume"] is not None else None,
                "change": (
                    float(row["change_amount"])
                    if row["change_amount"] is not None
                    else None
                ),
                "changePercent": (
                    float(row["change_percent"])
                    if row["change_percent"] is not None
                    else None
                ),
                "vwap": float(row["vwap"]) if row["vwap"] is not None else None,
                "dividend": (
                    float(row["dividend"]) if row["dividend"] is not None else None
                ),
            }

            # Add fill metadata if this record was filled
            if row.get("is_filled"):
                data_dict["_is_filled"] = True
                if row.get("fill_source_date"):
                    data_dict["_fill_source_date"] = row["fill_source_date"].strftime(
                        "%Y-%m-%d"
                    )
                if row.get("fill_type"):
                    data_dict["_fill_type"] = row["fill_type"]

            cached_data.append(data_dict)
            cached_dates.add(row["date"])

        # Detect gaps in the requested date range
        missing_ranges = _detect_missing_ranges(
            query.start_date, query.end_date, cached_dates, query.interval
        )

        _elapsed = _time.time() - _t0
        if missing_ranges:
            gap_days = sum((e - s).days + 1 for s, e in missing_ranges)
            logger.info(
                "Cache PARTIAL for %s: %d cached rows, %d gap(s) covering ~%d days  (%.2fs)",
                query.symbol,
                len(cached_data),
                len(missing_ranges),
                gap_days,
                _elapsed,
            )
            for idx, (gs, ge) in enumerate(missing_ranges, 1):
                logger.info(
                    "  gap %d: %s -> %s  (%d days)", idx, gs, ge, (ge - gs).days + 1
                )
        else:
            logger.info(
                "Cache HIT for %s: %d rows, no gaps  (%.2fs)",
                query.symbol,
                len(cached_data),
                _elapsed,
            )

        return cached_data, missing_ranges

    except Exception as e:
        logger.error(f"Cache gap analysis error for {query.symbol}: {e}")
        # Return empty cache and full range as missing
        return [], [(query.start_date, query.end_date)]


# bd-isvv: minimum fraction of trading days in the requested window that
# MUST have at least one cached bar before the intraday shortcut can
# declare the cache "complete". Pre-fix any endpoint-covering cache with
# no >7-day gaps passed the shortcut, causing hot-path silent-data-loss
# for sparse caches. 0.9 = at least 90% of trading days represented.
# See ``_detect_missing_ranges`` docstring for why the check has to
# operate at day granularity (cached_dates is a per-day set).
_INTRADAY_MIN_CACHED_DAYS_FRACTION = 0.9


# bd-lyzk: severity thresholds for partial-gap-fill logging after
# a fetch completes but ``_analyze_cache_gaps`` still reports missing
# ranges. Small gaps (< WARN) are legitimate background noise (holidays
# outside the basic holiday set, IPO pre-history, delistings, ranges
# extending into the future); moderate gaps (WARN..ERROR) warrant an
# operator-visible log with specifics; large gaps (>= ERROR) are almost
# certainly a silent fetch failure and escalate to ERROR-level for ops
# alerting. Do NOT raise on any of these — see ``_log_partial_gap_severity``
# docstring for why raising would break legitimate calls.
_PARTIAL_GAP_WARN_FRACTION = 0.05
_PARTIAL_GAP_ERROR_FRACTION = 0.25

# PR #352 code-reviewer P2: cap the number of gap ranges formatted into
# a single log message. 200 single-day gaps → ~5KB log line, risking
# Datadog/syslog truncation on the ERROR-level lines we care about most.
_MAX_FORMATTED_GAP_RANGES = 10


def _format_gap_ranges(remaining_gaps: list[tuple[date, date]]) -> str:
    """Format ``remaining_gaps`` as a compact string, capped at ``_MAX_FORMATTED_GAP_RANGES``.

    PR #352 code-reviewer (P2): pre-review-fix formatted every range
    inline, so a caller with 200 single-day gaps produced a ~5KB log
    line that risked Datadog/syslog truncation on the ERROR-level lines
    that ops alerting depends on. Cap at 10 with a ``... and N more``
    suffix so the log stays scannable and the total line length stays
    predictable.
    """
    if len(remaining_gaps) <= _MAX_FORMATTED_GAP_RANGES:
        return ", ".join(f"({start}→{end})" for start, end in remaining_gaps)
    head = remaining_gaps[:_MAX_FORMATTED_GAP_RANGES]
    remaining = len(remaining_gaps) - _MAX_FORMATTED_GAP_RANGES
    return (
        ", ".join(f"({start}→{end})" for start, end in head)
        + f", ... and {remaining} more"
    )


def _log_partial_gap_severity(
    symbol: str,
    remaining_gaps: list[tuple[date, date]],
    trading_days_requested: int,
) -> None:
    """Log partial-fetch-completion gaps at severity matched to gap fraction (bd-lyzk).

    Called after the post-fetch re-analysis of the cache — if ``remaining_gaps``
    is non-empty, some requested trading days are still absent. The pre-fix
    code emitted a single ``logger.warning`` with just the count, which:

    * Gave operators no way to identify WHICH dates were missing so they could
      re-request specific windows.
    * Buried real silent-fetch-failures under legitimate background noise
      (halts, IPO pre-history, delistings — all of which leave real
      unfillable gaps at WARNING level).

    Post-fix the log severity scales with the gap fraction:

    * ``0 < gap_fraction < _PARTIAL_GAP_WARN_FRACTION`` → INFO. Small gaps
      are usually holidays outside the basic set (regional half-days,
      NYSE special closures) or IPO pre-history — noisy at WARNING.
    * ``_PARTIAL_GAP_WARN_FRACTION <= gap_fraction < _PARTIAL_GAP_ERROR_FRACTION``
      → WARNING. Includes the specific gap ranges + missing count +
      percentage so an operator debugging "why is my backtest sparse?"
      can immediately see what's missing.
    * ``gap_fraction >= _PARTIAL_GAP_ERROR_FRACTION`` → ERROR. Large
      missing fraction is almost certainly a silent fetch failure
      (partial response, upstream 200 with empty body); ERROR is
      the right severity for ops alerting to fire.

    Zero-trading-day denominator is handled defensively (log at
    WARNING with the raw gap list, since we can't compute a fraction).

    Design note — why NOT raise on remaining_gaps
    ----------------------------------------------
    FMP legitimately does not have data for many valid requests:
    trading halts, IPO pre-history, delistings, ranges extending past
    ``today``. Raising on any non-empty ``remaining_gaps`` would break
    all of those legitimate calls. The severity-scaled log makes the
    silent-fetch-failure case (large gap fraction) loud enough for
    ops alerting without penalizing the "FMP has real data holes"
    case.
    """
    if not remaining_gaps:
        return

    if trading_days_requested <= 0:
        # Edge case: 0-trading-day denominator can't compute a fraction,
        # but non-empty gaps in a 0-trading-day window is genuinely
        # unusual — log at WARNING with the raw gap list (capped).
        logger.warning(
            "Partial-fill for %s: %d gap range(s) in a window with 0 "
            "trading days: %s (bd-lyzk).",
            symbol,
            len(remaining_gaps),
            _format_gap_ranges(remaining_gaps),
        )
        return

    # PR #352 code-reviewer P1: numerator must be TRADING DAYS to match
    # the denominator. Pre-review-fix used ``(end - start).days + 1``
    # which counts CALENDAR days, so a weekend-spanning gap inflated
    # the fraction by ~40% (7 calendar / 5 trading). A legitimate
    # 90-cal-day delisting hole in a 260-td year would compute as
    # ~35% ERROR instead of the correct ~25% — exactly the false-
    # positive class the severity guard is supposed to prevent.
    #
    # PR #352 code-reviewer P1: also clip gap end-dates at ``today``
    # so a request with ``end_date = today + 3y`` doesn't ERROR on the
    # future-weekday portion FMP can't have (~750 spurious "missing"
    # trading days over 3 future years). The caller's denominator
    # should already be clipped by _count_trading_days_in_range, but
    # the numerator must clip too so the units stay symmetric.
    today = date.today()
    missing_days = 0
    for gap_start, gap_end in remaining_gaps:
        clipped_end = min(gap_end, today)
        if clipped_end < gap_start:
            continue  # entire gap is in the future — not a real miss
        missing_days += _count_trading_days_in_range(gap_start, clipped_end)

    if missing_days == 0:
        # All gaps were in the future — treat as no-op silently. This
        # is the "user requested end_date past today" happy path.
        return

    gap_fraction = missing_days / trading_days_requested
    percent = gap_fraction * 100

    formatted_ranges = _format_gap_ranges(remaining_gaps)

    if gap_fraction < _PARTIAL_GAP_WARN_FRACTION:
        logger.info(
            "Partial-fill for %s: %d missing trading day(s) / %d requested (%.1f%%) "
            "in ranges [%s]; below WARN threshold %.0f%% so likely holidays "
            "outside the basic set or IPO pre-history (bd-lyzk).",
            symbol,
            missing_days,
            trading_days_requested,
            percent,
            formatted_ranges,
            _PARTIAL_GAP_WARN_FRACTION * 100,
        )
    elif gap_fraction < _PARTIAL_GAP_ERROR_FRACTION:
        logger.warning(
            "Partial-fill for %s: %d missing trading day(s) / %d requested (%.1f%%) "
            "in ranges [%s]; above WARN threshold %.0f%%. Investigate "
            "whether FMP legitimately lacks these dates or the fetch was "
            "incomplete (bd-lyzk).",
            symbol,
            missing_days,
            trading_days_requested,
            percent,
            formatted_ranges,
            _PARTIAL_GAP_WARN_FRACTION * 100,
        )
    else:
        logger.error(
            "Partial-fill for %s: %d missing trading day(s) / %d requested (%.1f%%) "
            "in ranges [%s]; above ERROR threshold %.0f%% — almost certainly "
            "a silent fetch failure (partial 200 response, upstream "
            "unavailable). Re-request the missing ranges (bd-lyzk).",
            symbol,
            missing_days,
            trading_days_requested,
            percent,
            formatted_ranges,
            _PARTIAL_GAP_ERROR_FRACTION * 100,
        )


def _count_trading_days_in_range(start_date: date, end_date: date) -> int:
    """Count US trading days (Mon-Fri, excluding basic holidays) in [start, end].

    Used by the intraday density guard in :func:`_detect_missing_ranges`
    to compute the denominator of the density fraction. Uses the same
    holiday set as the daily-interval branch for consistency.
    """
    if end_date < start_date:
        return 0
    holidays = _get_basic_market_holidays(start_date.year, end_date.year)
    count = 0
    d = start_date
    while d <= end_date:
        if _is_trading_day(d, holidays):
            count += 1
        d += timedelta(days=1)
    return count


def _detect_missing_ranges(
    start_date: date, end_date: date, cached_dates: set[date], interval: str
) -> list[tuple[date, date]]:
    """Detect missing date ranges based on interval and market days.

    Excludes known market holidays from missing ranges to avoid unnecessary API calls.

    Intraday density guard (bd-isvv)
    --------------------------------
    Pre-fix the intraday shortcut returned ``[]`` (i.e. "cache is complete")
    whenever three conditions held: min(cached_dates) ≤ start_date,
    max(cached_dates) ≥ end_date, and no consecutive-cached-date gap
    exceeded 7 days. But ``cached_dates`` is a **set of DAYS** (multiple
    bars on the same day collapse into one entry), so a 6-month intraday
    request whose cache holds only endpoint bars plus a handful of
    weekly samples would satisfy all three conditions and be silently
    reported as complete — hot-path data-loss for every intraday
    backtest.

    Post-fix a density check runs before the shortcut can fire: for each
    intraday interval the number of cached trading days must reach a
    minimum fraction of the trading days in the requested window. If
    density is below threshold, the full range is returned as missing so
    the fetcher refills the cache instead of trusting the sparse
    remnant.

    The density thresholds are all 0.9 (i.e. 90% of trading days in the
    window must have at least one cached bar) because ``cached_dates``
    is a per-day set — it cannot distinguish "one bar per day" from
    "hundreds of bars per day". A conservative "most days must be
    represented" check is the strongest per-day signal we can extract.
    Fine-grained per-timestamp density would need the raw bar list,
    which this function does not receive.
    """

    if interval != "1d":
        # For intraday data, we can't easily predict missing dates, so request full range if any gaps
        if not cached_dates or len(cached_dates) == 0:
            return [(start_date, end_date)]

        # Check if we have any data in range - be more conservative with intraday
        min_cached = min(cached_dates) if cached_dates else None
        max_cached = max(cached_dates) if cached_dates else None

        if (
            not min_cached
            or max_cached is None
            or min_cached > start_date
            or max_cached < end_date
        ):
            return [(start_date, end_date)]

        # For intraday, also check for significant gaps (more than 7 days)
        sorted_dates = sorted(cached_dates)
        for i in range(1, len(sorted_dates)):
            gap = (sorted_dates[i] - sorted_dates[i - 1]).days
            if gap > 7:  # Significant gap detected
                return [(start_date, end_date)]

        # bd-isvv density guard: even if endpoints are covered and no
        # 7-day gap fires, refuse to declare the cache complete unless
        # most trading days in the window have at least one cached bar.
        # This catches the sparse-endpoints-only + weekly-samples class
        # of silent-data-loss where all the endpoint/gap checks pass but
        # the vast majority of the window has zero bars.
        trading_days_in_range = _count_trading_days_in_range(start_date, end_date)
        if trading_days_in_range > 0:
            # PR #348 silent-failure-hunter (P2): use the SAME holiday
            # set for numerator and denominator. Pre-review-fix the
            # numerator filtered with ``_is_trading_day(d, set())`` (no
            # holidays) while ``_count_trading_days_in_range`` used the
            # real holiday set — so a cache with bars ON holidays
            # (MLK/Good Friday/Memorial Day/Juneteenth) inflated the
            # numerator while shrinking the denominator, silently
            # pushing density above the 0.9 threshold when it should
            # have been below. Symmetric filtering closes that hole.
            holidays = _get_basic_market_holidays(start_date.year, end_date.year)
            cached_trading_days = sum(
                1
                for d in cached_dates
                if start_date <= d <= end_date and _is_trading_day(d, holidays)
            )
            density = cached_trading_days / trading_days_in_range
            # 0.9 = at least 90% of trading days must have a cached bar.
            # See docstring for why we can only check density at day
            # granularity, not per-timestamp.
            if density < _INTRADAY_MIN_CACHED_DAYS_FRACTION:
                logger.info(
                    "Intraday cache density below threshold for %s: %d cached "
                    "trading days out of %d in [%s, %s] (%.1f%% < %.0f%%) — "
                    "refetching full range (bd-isvv).",
                    interval,
                    cached_trading_days,
                    trading_days_in_range,
                    start_date,
                    end_date,
                    density * 100,
                    _INTRADAY_MIN_CACHED_DAYS_FRACTION * 100,
                )
                return [(start_date, end_date)]

        return []  # Assume complete for intraday if no significant gaps

    # For daily data, detect business day gaps more intelligently
    missing_ranges = []
    current_date = start_date
    range_start = None

    # Get market holidays from database (avoids hardcoding and enables easy updates)
    holidays = _get_basic_market_holidays(start_date.year, end_date.year)
    logger.debug(f"Checking for gaps with {len(holidays)} known holidays excluded")

    while current_date <= end_date:
        # Skip weekends and basic holidays for daily data
        if _is_trading_day(current_date, holidays):
            if current_date not in cached_dates:
                if range_start is None:
                    range_start = current_date
            elif range_start is not None:
                # Close the missing range
                range_end = current_date - timedelta(days=1)
                # Make sure range_end is a valid trading day
                while range_end >= range_start and not _is_trading_day(
                    range_end, holidays
                ):
                    range_end -= timedelta(days=1)
                if range_end >= range_start:
                    missing_ranges.append((range_start, range_end))
                range_start = None

        current_date += timedelta(days=1)

    # Handle final range
    if range_start is not None:
        range_end = end_date
        # Make sure range_end is a valid trading day
        while range_end >= range_start and not _is_trading_day(range_end, holidays):
            range_end -= timedelta(days=1)
        if range_end >= range_start:
            missing_ranges.append((range_start, range_end))

    return missing_ranges


def _is_trading_day(check_date: date, holidays: set[date]) -> bool:
    """Check if a date is a trading day (not weekend or holiday)."""
    # Skip weekends
    if check_date.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    # Skip holidays
    if check_date in holidays:
        return False

    return True


def _get_basic_market_holidays(start_year: int, end_year: int) -> set[date]:
    """Get US stock market holidays for the given year range.

    First tries the ``market_holidays`` database table.  If that fails (table
    missing, empty, etc.) falls back to a comprehensive computed list covering
    all NYSE/NASDAQ observed closures:

        New Year's Day, MLK Day, Presidents' Day, Good Friday, Memorial Day,
        Juneteenth (2022+), Independence Day, Labor Day, Thanksgiving,
        Christmas, plus selected special closures.
    """
    # ------------------------------------------------------------------
    # 1. Try the database first
    # ------------------------------------------------------------------
    try:
        holiday_query = """
        SELECT holiday_date, holiday_name
        FROM market_holidays
        WHERE market = 'US'
          AND year >= %s AND year <= %s
        ORDER BY holiday_date
        """
        results = execute_query(holiday_query, (start_year, end_year))
        if results:
            holidays = {row["holiday_date"] for row in results}
            logger.debug(
                "Loaded %d market holidays from database for %d-%d",
                len(holidays),
                start_year,
                end_year,
            )
            return holidays
    except Exception as e:
        logger.debug(
            "market_holidays table unavailable (%s); using computed holidays", e
        )

    # ------------------------------------------------------------------
    # 2. Compute holidays (comprehensive fallback)
    # ------------------------------------------------------------------
    holidays: set[date] = set()  # type: ignore[no-redef]

    def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
        """Return the *n*-th occurrence of *weekday* in *month/year*."""
        first = date(year, month, 1)
        # offset to the first occurrence of weekday
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))

    def _last_weekday(year: int, month: int, weekday: int) -> date:
        """Return the last occurrence of *weekday* in *month/year*."""
        # start from 5th week and back off
        d = _nth_weekday(year, month, weekday, 4)
        nxt = d + timedelta(weeks=1)
        return nxt if nxt.month == month else d

    def _easter(year: int) -> date:
        """Anonymous Gregorian algorithm for Easter Sunday."""
        a = year % 19
        b, c = divmod(year, 100)
        d, e = divmod(b, 4)
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i, k = divmod(c, 4)
        l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day = ((h + l - 7 * m + 114) % 31) + 1
        return date(year, month, day)

    def _observed(d: date) -> date:
        """NYSE observed-date rule: Sat->Fri, Sun->Mon."""
        if d.weekday() == 5:  # Saturday
            return d - timedelta(days=1)
        if d.weekday() == 6:  # Sunday
            return d + timedelta(days=1)
        return d

    for year in range(start_year, end_year + 1):
        # New Year's Day
        holidays.add(_observed(date(year, 1, 1)))
        # Martin Luther King Jr. Day — 3rd Monday in January
        holidays.add(_nth_weekday(year, 1, 0, 3))  # Monday=0
        # Presidents' Day — 3rd Monday in February
        holidays.add(_nth_weekday(year, 2, 0, 3))
        # Good Friday — Friday before Easter
        holidays.add(_easter(year) - timedelta(days=2))
        # Memorial Day — last Monday in May
        holidays.add(_last_weekday(year, 5, 0))
        # Juneteenth — June 19 (observed), starting 2022
        if year >= 2022:
            holidays.add(_observed(date(year, 6, 19)))
        # Independence Day — July 4 (observed)
        holidays.add(_observed(date(year, 7, 4)))
        # Labor Day — 1st Monday in September
        holidays.add(_nth_weekday(year, 9, 0, 1))
        # Thanksgiving — 4th Thursday in November
        holidays.add(_nth_weekday(year, 11, 3, 4))  # Thursday=3
        # Christmas — December 25 (observed)
        holidays.add(_observed(date(year, 12, 25)))

    # Special closures
    _specials = [
        date(2018, 12, 5),  # George H.W. Bush funeral
        date(2025, 1, 9),  # Jimmy Carter funeral
    ]
    for s in _specials:
        if start_year <= s.year <= end_year:
            holidays.add(s)

    logger.debug(
        "Computed %d market holidays for %d-%d (fallback)",
        len(holidays),
        start_year,
        end_year,
    )
    return holidays


# DEPRECATED: This function is no longer used. Holiday gaps are now excluded from
# API calls entirely by _detect_missing_ranges() using the market_holidays table.
# Holidays remain as natural gaps in the response for data accuracy.
# Kept for reference only - may be removed in future cleanup.
def _fill_holiday_gaps(
    query: FMPCachedEquityHistoricalQueryParams,
    cached_data: list[dict[str, Any]],
    fetched_data: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fill gaps for holidays/non-trading days with previous close or next open data.

    DEPRECATED: No longer used. Holidays are now excluded from missing ranges.

    Args:
        query: The query parameters
        cached_data: Existing cached data
        fetched_data: Newly fetched data from API

    Returns:
        Enhanced fetched_data with filled gap records
    """
    # Combine all available data
    all_data = cached_data + fetched_data
    if not all_data:
        return fetched_data

    # Sort by date
    all_data_sorted = sorted(
        all_data, key=lambda x: datetime.strptime(x["date"], "%Y-%m-%d").date()
    )

    # Create a map of existing dates
    existing_dates = {
        datetime.strptime(d["date"], "%Y-%m-%d").date(): d for d in all_data_sorted
    }

    # Get holidays for the query range
    holidays = _get_basic_market_holidays(query.start_date.year, query.end_date.year)

    # Find dates that need filling (holidays and weekends within query range)
    filled_records = []
    current_date = query.start_date

    while current_date <= query.end_date:
        # Check if this date needs filling (is a holiday/weekend and not in data)
        if current_date not in existing_dates:
            is_weekend = current_date.weekday() >= 5
            is_holiday = current_date in holidays

            if is_weekend or is_holiday:
                # Try to fill with previous close
                prev_date = current_date - timedelta(days=1)
                attempts = 0
                while prev_date >= query.start_date and attempts < 7:
                    if prev_date in existing_dates:
                        # Found previous trading day data
                        source_data = existing_dates[prev_date]
                        filled_record = {
                            "symbol": query.symbol,
                            "date": current_date.strftime("%Y-%m-%d"),
                            "open": source_data.get("open"),
                            "high": source_data.get("high"),
                            "low": source_data.get("low"),
                            "close": source_data.get("close"),
                            "volume": 0,  # No volume on non-trading days
                            "change": 0.0,
                            "changePercent": 0.0,
                            "vwap": source_data.get("vwap"),
                            # Metadata for tracking the fill
                            "_is_filled": True,
                            "_fill_source_date": prev_date.strftime("%Y-%m-%d"),
                            "_fill_type": "previous_close",
                        }
                        filled_records.append(filled_record)
                        existing_dates[current_date] = filled_record
                        logger.debug(
                            f"Filled {current_date} with previous close from {prev_date}"
                        )
                        break
                    prev_date -= timedelta(days=1)
                    attempts += 1

                # If no previous data found, try next open
                if current_date not in existing_dates:
                    next_date = current_date + timedelta(days=1)
                    attempts = 0
                    while next_date <= query.end_date and attempts < 7:
                        if next_date in existing_dates:
                            # Found next trading day data
                            source_data = existing_dates[next_date]
                            filled_record = {
                                "symbol": query.symbol,
                                "date": current_date.strftime("%Y-%m-%d"),
                                "open": source_data.get("open"),
                                "high": source_data.get("high"),
                                "low": source_data.get("low"),
                                "close": source_data.get("close"),
                                "volume": 0,  # No volume on non-trading days
                                "change": 0.0,
                                "changePercent": 0.0,
                                "vwap": source_data.get("vwap"),
                                # Metadata for tracking the fill
                                "_is_filled": True,
                                "_fill_source_date": next_date.strftime("%Y-%m-%d"),
                                "_fill_type": "next_open",
                            }
                            filled_records.append(filled_record)
                            existing_dates[current_date] = filled_record
                            logger.debug(
                                f"Filled {current_date} with next open from {next_date}"
                            )
                            break
                        next_date += timedelta(days=1)
                        attempts += 1

        current_date += timedelta(days=1)

    if filled_records:
        logger.info(
            f"Filled {len(filled_records)} holiday/weekend gaps for {query.symbol}"
        )

    # Return fetched data + filled records
    return fetched_data + filled_records


def _store_in_database_cache(
    query: FMPCachedEquityHistoricalQueryParams, fmp_data: list[dict[str, Any]]
) -> None:
    """Store FMP data in equity_historical database table with transaction management."""

    if not fmp_data:
        return

    insert_query = """
    INSERT INTO equity_historical 
    (symbol, date, open, high, low, close, volume, change_amount, change_percent, vwap, dividend,
     interval_type, adjustment_type, cached_at, is_valid, is_filled, fill_source_date, fill_type)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) AS new_values
    ON DUPLICATE KEY UPDATE
    open = new_values.open, high = new_values.high, low = new_values.low, 
    close = new_values.close, volume = new_values.volume, 
    change_amount = new_values.change_amount, change_percent = new_values.change_percent,
    vwap = new_values.vwap, dividend = new_values.dividend, 
    updated_at = CURRENT_TIMESTAMP, is_valid = new_values.is_valid,
    is_filled = new_values.is_filled, fill_source_date = new_values.fill_source_date, 
    fill_type = new_values.fill_type
    """

    # Prepare batch data
    batch_data = []
    for row in fmp_data:
        # Extract and convert data
        date_str = row.get("date")
        if date_str:
            try:
                if isinstance(date_str, str):
                    # Try parsing with time first (for intraday data)
                    try:
                        date_obj = datetime.strptime(
                            date_str, "%Y-%m-%d %H:%M:%S"
                        ).date()
                    except ValueError:
                        # Fall back to date-only format (for daily data)
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                else:
                    date_obj = date_str
            except (ValueError, TypeError):
                logger.warning(f"Invalid date format: {date_str}")
                continue
        else:
            continue

        # Check if this is a filled record (has metadata from _fill_holiday_gaps)
        is_filled = row.get("_is_filled", False)
        fill_source_date = None
        fill_type = None

        if is_filled:
            fill_source_str = row.get("_fill_source_date")
            if fill_source_str:
                try:
                    fill_source_date = datetime.strptime(
                        fill_source_str, "%Y-%m-%d"
                    ).date()
                except (ValueError, TypeError):
                    logger.warning(f"Invalid fill_source_date: {fill_source_str}")
            fill_type = row.get("_fill_type")

        row_data = (
            query.symbol,
            date_obj,
            row.get("open"),
            row.get("high"),
            row.get("low"),
            row.get("close"),
            row.get("volume"),
            row.get("change"),
            row.get("changePercent"),
            row.get("vwap"),
            row.get("dividend"),  # Add dividend field
            query.interval,
            query.adjustment,
            datetime.now(),
            True,  # is_valid
            is_filled,
            fill_source_date,
            fill_type,
        )
        batch_data.append(row_data)

    if not batch_data:
        logger.info(
            "Store: no valid rows to insert for %s (all filtered)", query.symbol
        )
        return

    import time as _time

    _t0 = _time.time()
    try:
        # Use executemany for better performance with autocommit
        # Execute batch insert using the existing utility
        rows_affected = execute_many(insert_query, batch_data)
        _elapsed = _time.time() - _t0
        logger.info(
            "Stored %d rows for %s in MySQL cache  (%.2fs)  [%d input -> %d prepared -> %d affected]",
            rows_affected,
            query.symbol,
            _elapsed,
            len(fmp_data),
            len(batch_data),
            rows_affected,
        )

    except Exception as e:
        logger.warning(
            f"Failed to store data in equity_historical table for {query.symbol}: {e}"
        )
        raise


async def _fetch_from_fmp_direct(
    query: FMPCachedEquityHistoricalQueryParams,
    credentials: dict[str, str] | None,
    **kwargs: Any,
) -> list[dict]:
    """Fetch data directly from FMP API - completely independent implementation.

    This function replicates the FMP provider's get_historical_ohlc functionality
    without any dependency on the FMP provider module.
    """
    import asyncio
    from warnings import warn

    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.provider.utils.errors import EmptyDataError, UnauthorizedError
    from openbb_core.provider.utils.helpers import amake_request

    async def response_callback(response, _):
        """Handle FMP API response."""
        if response.status != 200:
            msg = await response.text()
            code = response.status
            raise UnauthorizedError(f"Unauthorized FMP request -> {code} -> {msg}")

        data = await response.json()

        if isinstance(data, dict):
            error_message = data.get("Error Message", data.get("error"))

            if error_message is not None:
                conditions = (
                    "upgrade" in error_message.lower()
                    or "exclusive endpoint" in error_message.lower()
                    or "special endpoint" in error_message.lower()
                    or "premium query parameter" in error_message.lower()
                    or "subscription" in error_message.lower()
                    or "unauthorized" in error_message.lower()
                    or "premium" in error_message.lower()
                )

                if conditions:
                    raise UnauthorizedError(
                        f"Unauthorized FMP request -> {error_message}"
                    )

                raise OpenBBError(
                    f"FMP Error Message -> Status code: {response.status} -> {error_message}"
                )

        return data

    # Get API key
    api_key = credentials.get("fmp_api_key") if credentials else ""

    # Build base URL based on adjustment and interval.
    #
    # Post-fix (bd-o61s): the model_validator on the query params rejects
    # ``adjustment != 'splits_only'`` on any intraday interval, so by
    # the time we reach here the (adjustment, interval) combination is
    # guaranteed valid. Every ``Literal`` interval value has an explicit
    # endpoint mapping — an unknown interval slipping through raises
    # ValueError instead of falling through to an empty endpoint.
    base_url = _build_fmp_endpoint(query.adjustment, query.interval)

    # Strip the trailing '?' — params below will encode into the URL properly
    # via the underlying HTTP layer (keeps apikey OUT of the URL string that
    # would land in tracebacks / proxy access logs — bd-6641 / bd-ir3f).
    base_url = base_url.rstrip("?")

    # Build a params dict (all the query.model_dump() fields except the ones
    # we handle specially: symbol is per-request, adjustment / interval /
    # include_dividends are consumed above to build the base_url).
    # Stringify date/datetime values — yarl (aiohttp's URL builder) rejects
    # non-str/int/float query params, and query.model_dump() emits real
    # `datetime.date` objects that would otherwise raise TypeError from
    # get_str_query_from_sequence_iterable. #785.
    from datetime import (
        date as _date,
        datetime as _datetime,
    )

    query_params = {
        key: (value.isoformat() if isinstance(value, (_date, _datetime)) else value)
        for key, value in query.model_dump().items()
        if value is not None
        and key not in ("symbol", "adjustment", "interval", "include_dividends")
    }

    # Handle multiple symbols
    symbols = query.symbol.split(",")
    results: list = []
    messages: list = []

    async def get_one(symbol):
        """Get data for one symbol."""
        params = {"symbol": symbol, **query_params, "apikey": api_key}
        data: list = []

        response = await amake_request(
            base_url,
            response_callback=response_callback,
            params=params,
            **kwargs,
        )

        if isinstance(response, dict) and response.get("Error Message"):
            message = (
                f"Error fetching data for {symbol}: {response.get('Error Message', '')}"
            )
            warn(message)
            messages.append(message)

        if isinstance(response, list) and len(response) > 0:
            data = response
        elif isinstance(response, dict) and response.get("historical"):
            data = response.get("historical", [])

        if not data:
            message = f"No data found for {symbol}."
            warn(message)
            messages.append(message)
        elif data:
            for d in data:
                d["symbol"] = symbol
                results.append(d)

    # Fetch data for all symbols
    await asyncio.gather(*[get_one(symbol) for symbol in symbols])

    if not results:
        raise EmptyDataError(
            f"{str(','.join(messages)).replace(',', ' ') if messages else 'No data found'}"
        )

    return results


def _fetch_from_fmp_sync(
    query: FMPCachedEquityHistoricalQueryParams,
    credentials: dict[str, str] | None,
    timeout: int = 120,
) -> list[dict]:
    """Fetch data from FMP API using synchronous ``requests``.

    This is the sync counterpart of ``_fetch_from_fmp_direct``.  It is useful
    for scripts and CLI tools that don't need (or can't reliably use) an async
    event loop (e.g. Windows + aiohttp ``CancelledError`` issues).

    Returns a list of dicts with keys matching the FMP JSON response
    (symbol, date, open, high, low, close, volume, change, changePercent, vwap …).
    """
    import time as _time
    from warnings import warn

    import requests as _requests

    api_key = credentials.get("fmp_api_key") if credentials else ""
    if not api_key:
        raise ValueError("No FMP API key provided")

    # Build base URL (shared helper with _fetch_from_fmp_direct — bd-o61s).
    base_url = _build_fmp_endpoint(query.adjustment, query.interval)

    # Strip the trailing '?' — params below encode into the URL properly
    # via ``requests`` (keeps apikey OUT of the URL string that lands in
    # tracebacks and ``HTTPError.url`` — bd-6641 / bd-q4b4).
    base_url = base_url.rstrip("?")

    # Date range for client-side filtering (FMP /full endpoint may ignore
    # start_date/end_date and return ALL history — we filter after download).
    req_start = query.start_date  # date object
    req_end = query.end_date  # date object

    symbols = query.symbol.split(",")
    results: list[dict] = []
    messages: list[str] = []

    for symbol in symbols:
        symbol = symbol.strip()
        # Use both `from`/`to` (FMP stable) and `start_date`/`end_date` (legacy)
        # so the API filters server-side when it can.
        params = {
            "symbol": symbol,
            "from": req_start,
            "to": req_end,
            "apikey": api_key,
        }
        # Log the URL WITHOUT apikey — ``params`` are held separately by
        # ``requests`` and only serialized during the actual HTTP send.
        logger.info(
            "FMP HTTP GET: %s?symbol=%s&from=%s&to=%s  (timeout=%ds)",
            base_url,
            symbol,
            req_start,
            req_end,
            timeout,
        )

        _t0 = _time.time()
        resp = _requests.get(base_url, params=params, timeout=timeout)
        _http_elapsed = _time.time() - _t0
        logger.info(
            "FMP response: HTTP %d, %s bytes  (%.2fs)",
            resp.status_code,
            f"{len(resp.content):,}",
            _http_elapsed,
        )
        # Use the shared redaction wrapper — ``requests`` merges ``params=``
        # into PreparedRequest.url pre-send, so ``resp.url`` contains the
        # plaintext key. Without redaction, the resulting HTTPError message
        # would land in every stderr / Sentry / CI-log surface.
        # bd-6641 / bd-q4b4.
        from openbb_fmp_cached.utils.security import raise_for_status_redacted

        raise_for_status_redacted(resp)
        body = resp.json()

        # Parse response -- FMP may return a list or {"historical": [...]}
        if isinstance(body, dict):
            err = body.get("Error Message", body.get("error"))
            if err:
                logger.warning("FMP error for %s: %s", symbol, err)
                warn(f"FMP error for {symbol}: {err}")
                messages.append(err)
                continue
            data = body.get("historical", [])
        elif isinstance(body, list):
            data = body
        else:
            data = []

        if not data:
            msg = f"No data found for {symbol}."
            logger.warning(msg)
            warn(msg)
            messages.append(msg)
        else:
            # ----- client-side date filter (safety net) --------------------
            raw_len = len(data)
            filtered: list[dict] = []
            for d in data:
                ds = d.get("date", "")[:10]
                if ds:
                    try:
                        row_date = date.fromisoformat(ds)
                        if req_start <= row_date <= req_end:
                            d["symbol"] = symbol
                            filtered.append(d)
                    except ValueError:
                        d["symbol"] = symbol
                        filtered.append(d)
                else:
                    d["symbol"] = symbol
                    filtered.append(d)

            dates = [d.get("date", "")[:10] for d in filtered if d.get("date")]
            first = min(dates) if dates else "?"
            last = max(dates) if dates else "?"
            logger.info(
                "FMP returned %d rows for %s, %d after date filter  (%s -> %s)",
                raw_len,
                symbol,
                len(filtered),
                first,
                last,
            )
            results.extend(filtered)

    if not results:
        from openbb_core.provider.utils.errors import EmptyDataError

        raise EmptyDataError(" ".join(messages) if messages else "No data found")

    return results


async def _fetch_dividends_from_fmp(
    query: FMPCachedEquityHistoricalQueryParams,
    credentials: dict[str, str] | None,
    **kwargs: Any,
) -> dict[str, dict[str, float]]:
    """Fetch dividend data from FMP /dividends endpoint.

    Returns:
        Dictionary mapping symbol -> {date: dividend_amount}
    """
    import asyncio

    from openbb_core.provider.utils.helpers import amake_request

    async def response_callback(response, _):
        """Handle FMP API response."""
        if response.status != 200:
            return []
        data = await response.json()
        return data if isinstance(data, list) else []

    api_key = credentials.get("fmp_api_key") if credentials else ""
    if not api_key:
        logger.warning("No API key provided, skipping dividend fetch")
        return {}

    symbols = query.symbol.split(",")
    dividend_map: dict[str, dict[str, float]] = {}

    async def get_dividends_for_symbol(symbol: str):
        """Fetch dividends for a single symbol."""
        # Build URL for dividends endpoint
        base_url = "https://financialmodelingprep.com/stable/dividends"

        # Route apikey (and every other query field) via ``params`` — keeps
        # the key OUT of any URL string in tracebacks / proxy logs
        # (bd-6641; sibling of bd-ir3f/q4b4 but at a different call site).
        params = {
            "symbol": symbol,
            **{
                key: value
                for key, value in query.model_dump().items()
                if value is not None
                and key not in ("symbol", "adjustment", "interval", "include_dividends")
            },
            "apikey": api_key,
        }

        try:
            response = await amake_request(
                base_url,
                response_callback=response_callback,
                params=params,
                **kwargs,
            )

            if response and isinstance(response, list):
                # Create date -> dividend mapping for this symbol
                symbol_dividends = {}
                for div in response:
                    div_date = div.get("date")
                    div_amount = div.get("dividend")
                    if div_date and div_amount:
                        symbol_dividends[div_date] = float(div_amount)

                if symbol_dividends:
                    dividend_map[symbol] = symbol_dividends
                    logger.info(
                        f"Fetched {len(symbol_dividends)} dividends for {symbol}"
                    )

        except Exception as e:
            logger.warning(f"Failed to fetch dividends for {symbol}: {e}")

    # Fetch dividends for all symbols
    await asyncio.gather(*[get_dividends_for_symbol(s.strip()) for s in symbols])

    return dividend_map


def get_cache_statistics(symbol: str | None = None) -> dict[str, Any]:
    """Get cache statistics for equity historical data."""
    try:
        if symbol:
            stats_query = """
            SELECT 
                symbol,
                COUNT(*) as record_count,
                MIN(date) as earliest_date,
                MAX(date) as latest_date,
                interval_type,
                adjustment_type,
                COUNT(DISTINCT date) as unique_dates
            FROM equity_historical 
            WHERE symbol = %s AND is_valid = TRUE
            GROUP BY symbol, interval_type, adjustment_type
            """
            results = execute_query(stats_query, (symbol,))
        else:
            stats_query = """
            SELECT 
                COUNT(DISTINCT symbol) as unique_symbols,
                COUNT(*) as total_records,
                MIN(date) as earliest_date,
                MAX(date) as latest_date,
                COUNT(DISTINCT interval_type) as interval_types,
                COUNT(DISTINCT adjustment_type) as adjustment_types
            FROM equity_historical 
            WHERE is_valid = TRUE
            """
            results = execute_query(stats_query)

        return {"statistics": results}
    except Exception as e:
        logger.error(f"Failed to get cache statistics: {e}")
        return {"error": str(e)}


def clear_cache_for_symbol(symbol: str) -> bool:
    """Clear all cached data for a specific symbol."""
    try:
        delete_query = """
        DELETE FROM equity_historical 
        WHERE symbol = %s
        """

        # Use sync version
        result = execute_query(delete_query, (symbol,))

        logger.info(f"Cleared cache for symbol {symbol}")
        return True
    except Exception as e:
        logger.error(f"Failed to clear cache for symbol {symbol}: {e}")
        return False


def clean_old_cache(days_old: int = 30) -> int:
    """Clean cache entries older than specified days."""
    try:
        cleanup_query = """
        DELETE FROM equity_historical 
        WHERE cached_at < DATE_SUB(NOW(), INTERVAL %s DAY)
        """
        result = execute_query(cleanup_query, (days_old,))
        logger.info(f"Cleaned {result} old cache entries (older than {days_old} days)")
        return result
    except Exception as e:
        logger.error(f"Failed to clean old cache: {e}")
        return 0


# --------------------------------------------------------------------------- #
#  Synchronous latest-price helper (gap-detect + auto-fetch + cache)
# --------------------------------------------------------------------------- #


def _load_fmp_credentials() -> dict[str, str]:
    """Load FMP API key from OpenBB user settings.

    Returns a dict like ``{"fmp_api_key": "..."}`` or an empty dict
    if the key cannot be resolved.
    """
    try:
        from openbb_core.app.service.user_service import UserService

        user_service = UserService()
        user_settings = user_service.default_user_settings
        fmp_api_key = getattr(user_settings.credentials, "fmp_api_key", None)
        if fmp_api_key:
            key_value = (
                fmp_api_key.get_secret_value()
                if hasattr(fmp_api_key, "get_secret_value")
                else str(fmp_api_key)
            )
            return {"fmp_api_key": key_value}
    except Exception as exc:
        logger.warning("Could not load FMP credentials from user settings: %s", exc)
    return {}


def get_latest_prices_sync(
    symbols: list[str],
    *,
    as_of_date: date | str | None = None,
    lookback_days: int = 14,
    credentials: dict[str, str] | None = None,
) -> list[dict]:
    """Return the most-recent close price per symbol using the full
    gap-detect → fetch → cache pipeline (synchronous).

    This mirrors the logic of ``FMPCachedEquityHistoricalFetcher.aextract_data``
    but is fully synchronous — it uses ``_analyze_cache_gaps``,
    ``_fetch_from_fmp_sync``, and ``_store_in_database_cache``.

    Parameters
    ----------
    symbols : list[str]
        Ticker symbols to look up.
    as_of_date : date | str | None
        Return the most-recent close on or before this date.
        Defaults to today when ``None``.
    lookback_days : int
        Calendar days to look back from *as_of_date*.  Default 14
        covers weekends + holidays comfortably.
    credentials : dict | None
        ``{"fmp_api_key": "..."}`` — loaded from user settings if omitted.

    Returns
    -------
    list[dict]
        One dict per symbol: ``{"symbol", "close", "price_date"}``.
        Symbols with no data are silently omitted.
    """
    if not symbols:
        return []

    creds = credentials or _load_fmp_credentials()

    # Resolve as_of_date
    if as_of_date is None:
        end_date_resolved = datetime.now().date()
    elif isinstance(as_of_date, str):
        end_date_resolved = datetime.strptime(as_of_date, "%Y-%m-%d").date()
    else:
        end_date_resolved = as_of_date

    today = end_date_resolved
    start = today - timedelta(days=lookback_days)

    # Ensure the database exists
    try:
        init_database()
    except Exception as exc:
        logger.warning("init_database() failed: %s — continuing anyway", exc)

    latest: dict[str, dict] = {}  # symbol → {close, price_date}

    for sym in symbols:
        sym = sym.strip()
        if not sym:
            continue

        query = FMPCachedEquityHistoricalQueryParams(
            symbol=sym,
            start_date=start,
            end_date=today,
            interval="1d",
            adjustment="splits_only",
        )

        try:
            cached_data, missing_ranges = _analyze_cache_gaps(query)
        except Exception as exc:
            logger.warning("Cache analysis failed for %s: %s", sym, exc)
            cached_data, missing_ranges = [], [(start, today)]

        # Fetch any gaps via the synchronous FMP HTTP helper
        if missing_ranges and creds:
            for gap_start, gap_end in missing_ranges:
                gap_query = FMPCachedEquityHistoricalQueryParams(
                    symbol=sym,
                    start_date=gap_start,
                    end_date=gap_end,
                    interval="1d",
                    adjustment="splits_only",
                )
                try:
                    logger.info(
                        "Fetching gap for %s: %s → %s",
                        sym,
                        gap_start,
                        gap_end,
                    )
                    gap_data = _fetch_from_fmp_sync(gap_query, creds)
                    if gap_data:
                        _store_in_database_cache(gap_query, gap_data)
                        logger.info(
                            "Cached %d rows for gap %s %s→%s",
                            len(gap_data),
                            sym,
                            gap_start,
                            gap_end,
                        )
                except Exception as exc:
                    logger.warning(
                        "Gap fetch/store failed for %s (%s→%s): %s",
                        sym,
                        gap_start,
                        gap_end,
                        exc,
                    )

            # Re-read cache after filling gaps
            try:
                cached_data, _ = _analyze_cache_gaps(query)
            except Exception:
                pass  # keep whatever we had before

        # Pick the most-recent close on or before as_of_date
        if cached_data:
            # cached_data rows have 'date' as str 'YYYY-MM-DD' and 'close' as float
            cutoff = today.isoformat()  # 'YYYY-MM-DD'
            eligible = [r for r in cached_data if r.get("date", "") <= cutoff]
            if not eligible:
                eligible = cached_data  # fallback: use all if none match
            best = max(eligible, key=lambda r: r.get("date", ""))
            close_val = best.get("close")
            if close_val is not None:
                latest[sym] = {
                    "symbol": sym,
                    "close": float(close_val),
                    "price_date": best["date"],
                }

    result = list(latest.values())
    logger.info(
        "get_latest_prices_sync: %d symbols requested, %d prices returned",
        len(symbols),
        len(result),
    )
    return result


def get_equity_historical_sync(
    symbol: str,
    *,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    interval: str = "1d",
    adjustment: str = "splits_only",
    credentials: dict[str, str] | None = None,
) -> list[dict]:
    """Return cached historical OHLCV data for *symbol* using the full
    gap-detect → fetch → cache pipeline (synchronous).

    This is the sync counterpart of
    ``FMPCachedEquityHistoricalFetcher.aextract_data`` and should be used
    whenever callers need historical price data without running an async
    event loop.

    Parameters
    ----------
    symbol : str
        Single ticker symbol.
    start_date, end_date : date | str | None
        Date range.  Defaults to 1 year ago → today.
    interval : str
        ``"1d"`` (default), ``"1h"``, etc.
    adjustment : str
        ``"splits_only"`` (default), ``"splits_and_dividends"``, ``"unadjusted"``.
    credentials : dict | None
        ``{"fmp_api_key": "..."}`` — loaded from user settings if omitted.

    Returns
    -------
    list[dict]
        FMP-format dicts: ``{symbol, date, open, high, low, close, volume,
        change, changePercent, vwap, dividend}``.
    """
    creds = credentials or _load_fmp_credentials()
    today = datetime.now().date()

    # Resolve dates
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    if isinstance(end_date, str):
        end_date = date.fromisoformat(end_date)
    _start = start_date or (today - relativedelta(years=1))
    _end = end_date or today

    # Ensure the database exists
    try:
        init_database()
    except Exception as exc:
        logger.warning("init_database() failed: %s — continuing anyway", exc)

    query = FMPCachedEquityHistoricalQueryParams(
        symbol=symbol.strip(),
        start_date=_start,
        end_date=_end,
        interval=interval,
        adjustment=adjustment,
    )

    try:
        cached_data, missing_ranges = _analyze_cache_gaps(query)
    except Exception as exc:
        logger.warning("Cache analysis failed for %s: %s", symbol, exc)
        cached_data, missing_ranges = [], [(_start, _end)]

    # Fill gaps via synchronous FMP HTTP helper
    if missing_ranges and creds:
        for gap_start, gap_end in missing_ranges:
            gap_query = FMPCachedEquityHistoricalQueryParams(
                symbol=symbol.strip(),
                start_date=gap_start,
                end_date=gap_end,
                interval=interval,
                adjustment=adjustment,
            )
            try:
                logger.info(
                    "Fetching gap for %s: %s → %s",
                    symbol,
                    gap_start,
                    gap_end,
                )
                gap_data = _fetch_from_fmp_sync(gap_query, creds)
                if gap_data:
                    _store_in_database_cache(gap_query, gap_data)
                    logger.info(
                        "Cached %d rows for gap %s %s→%s",
                        len(gap_data),
                        symbol,
                        gap_start,
                        gap_end,
                    )
            except Exception as exc:
                logger.warning(
                    "Gap fetch/store failed for %s (%s→%s): %s",
                    symbol,
                    gap_start,
                    gap_end,
                    exc,
                )

        # Re-read cache after filling gaps
        try:
            cached_data, _ = _analyze_cache_gaps(query)
        except Exception:
            pass  # keep whatever we had before

    logger.info(
        "get_equity_historical_sync: %s returned %d records (%s → %s)",
        symbol,
        len(cached_data),
        _start,
        _end,
    )
    return cached_data
