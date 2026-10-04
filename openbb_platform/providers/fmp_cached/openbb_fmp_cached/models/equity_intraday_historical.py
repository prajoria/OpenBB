"""Tier-1 cached intraday historical bars fetcher (fmp-day-trading PRD §5.2).

Gap-detection caching over the FMP /stable/historical-chart/{interval}
endpoint. Mirrors equity_historical.py's shape but with:

  * `interval_type` in the cache key (not just `date`)
  * `ts` is a DATETIME(0) bar-start (not a `date`)
  * Same-session tail-invalidation: the most recent bar of the current
    trading session is marked is_valid=FALSE after serving so the next
    call forces re-fetch. The 10:00-10:05 bar isn't finalized at 10:03;
    treating it as complete would leak an incomplete bar to consumers.

The tier-1 upgrade replaces the tier-2 passthrough registered in Phase 0
(see openbb_fmp_cached/__init__.py fetcher_mapping — the entry
"EquityIntradayHistorical" now resolves to THIS class instead of the
create_fallback_fetcher_class-wrapped tier-2 version).
"""

# pylint: disable=logging-fstring-interpolation,import-outside-toplevel,unused-argument

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars
import pandas as pd
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_fmp.models.equity_intraday_historical import (
    FMPEquityIntradayHistoricalData,
    FMPEquityIntradayHistoricalFetcher,
    FMPEquityIntradayHistoricalQueryParams,
)
from openbb_fmp.utils.definitions import AvailableExchanges

from openbb_fmp_cached.utils.database import execute_many, execute_query, init_database

logger = logging.getLogger(__name__)
_NON_US_SUFFIXES = tuple(
    sorted(
        {
            str(exchange["symbol_suffix"]).upper()
            for exchange in AvailableExchanges.values()
            if exchange.get("symbol_suffix")
        },
        key=len,
        reverse=True,
    )
)


# Public convenience — matches the alias types shipped by the raw fmp fetcher
# so router bindings can reference the cached class interchangeably.
class FMPCachedEquityIntradayHistoricalQueryParams(
    FMPEquityIntradayHistoricalQueryParams
):
    """Cached intraday-bars query params (no additional fields)."""


class FMPCachedEquityIntradayHistoricalData(FMPEquityIntradayHistoricalData):
    """Cached intraday-bars data row (no additional fields)."""


class FMPCachedEquityIntradayHistoricalFetcher(
    Fetcher[
        FMPCachedEquityIntradayHistoricalQueryParams,
        list[FMPCachedEquityIntradayHistoricalData],
    ]
):
    """Tier-1 gap-detection cached intraday bars fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FMPCachedEquityIntradayHistoricalQueryParams:
        """Validate cached intraday query parameters."""
        query = FMPCachedEquityIntradayHistoricalQueryParams(**params)
        for name in ("start_date", "end_date"):
            raw = params.get(name)
            object.__setattr__(
                query,
                f"_{name}_date_only",
                isinstance(raw, date)
                and not isinstance(raw, datetime)
                or isinstance(raw, str)
                and len(raw.strip()) == 10,
            )
        return query

    @staticmethod
    async def aextract_data(
        query: FMPCachedEquityIntradayHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Serve intraday bars from MySQL cache; fetch only missing ranges from FMP."""
        # Credential translation: fmp_cached_api_key -> fmp_api_key.
        fmp_credentials = _translate_credentials(credentials)
        normalized_query = FMPCachedEquityIntradayHistoricalQueryParams(
            symbol=query.symbol,
            interval=query.interval,
            start_date=_local_naive(query.start_date),
            end_date=_local_naive(query.end_date),
            extended_hours=query.extended_hours,
        )
        for name in ("start_date", "end_date"):
            object.__setattr__(
                normalized_query,
                f"_{name}_date_only",
                getattr(query, f"_{name}_date_only", False),
            )
        query = normalized_query

        symbol_text = str(query.symbol)
        symbols = [
            symbol.strip().upper()
            for symbol in symbol_text.split(",")
            if symbol.strip()
        ]
        unsupported = [
            symbol for symbol in symbols if symbol.endswith(_NON_US_SUFFIXES)
        ]
        if unsupported:
            raise OpenBBError(
                "Cached intraday sessions currently support US-listed "
                f"symbols only; use provider=fmp for {unsupported}."
            )

        # DB init; fall back to raw fmp on any DB failure (Phase 0 tier-2 posture).
        try:
            init_database()
        except Exception as exc:
            logger.warning(f"Cache DB init failed, falling back to direct FMP: {exc}")
            fresh = await FMPEquityIntradayHistoricalFetcher.aextract_data(
                query, fmp_credentials, **kwargs
            )
            return _filter_fresh_rows(fresh, query)

        # Multi-symbol fanout — one gap-analysis + optional fetch per symbol.
        all_rows: list[dict[str, Any]] = []
        for symbol in symbols:
            single_query = FMPCachedEquityIntradayHistoricalQueryParams(
                symbol=symbol,
                interval=query.interval,
                start_date=query.start_date,
                end_date=query.end_date,
                extended_hours=query.extended_hours,
            )
            for name in ("start_date", "end_date"):
                object.__setattr__(
                    single_query,
                    f"_{name}_date_only",
                    getattr(query, f"_{name}_date_only", False),
                )
            try:
                cached_rows, has_gap = _analyze_intraday_cache(single_query)
            except Exception as exc:
                logger.warning(
                    f"Intraday cache analysis failed for {symbol}: {exc}; "
                    "falling back to direct FMP fetch"
                )
                fallback = await FMPEquityIntradayHistoricalFetcher.aextract_data(
                    single_query, fmp_credentials, **kwargs
                )
                if fallback:
                    _safe_upsert_intraday_rows(symbol, query.interval, fallback)
                all_rows.extend(_filter_fresh_rows(fallback, single_query))
                continue

            if has_gap:
                logger.info(
                    f"Cache MISS/PARTIAL for {symbol} intraday ({query.interval}); "
                    f"fetching from FMP"
                )
                fresh = await FMPEquityIntradayHistoricalFetcher.aextract_data(
                    single_query, fmp_credentials, **kwargs
                )
                persisted = False
                if fresh:
                    persisted = _safe_upsert_intraday_rows(
                        symbol,
                        query.interval,
                        fresh,
                    )
                if query.start_date is None or query.end_date is None:
                    cached_rows = _filter_fresh_rows(fresh, single_query)
                elif persisted:
                    # Re-read now-complete range from cache so
                    # tail-invalidation applies consistently to fresh writes.
                    cached_rows, _ = _analyze_intraday_cache(single_query)
                else:
                    cached_rows = _filter_fresh_rows(fresh, single_query)
            else:
                logger.info(
                    f"Cache HIT for {symbol} intraday ({query.interval}): "
                    f"{len(cached_rows)} rows"
                )

            # Correctness: same-session tail bar may still be extending.
            _invalidate_same_session_tail(symbol, query.interval, cached_rows)
            all_rows.extend(cached_rows)

        return all_rows

    @staticmethod
    def transform_data(
        query: FMPCachedEquityIntradayHistoricalQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FMPCachedEquityIntradayHistoricalData]:
        """Validate raw dicts into typed intraday-bar rows."""
        return [FMPCachedEquityIntradayHistoricalData.model_validate(d) for d in data]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _translate_credentials(
    credentials: dict[str, Any] | None,
) -> dict[str, str] | None:
    """Translate fmp_cached_api_key -> fmp_api_key for the raw fmp fetcher.

    Mirrors the pattern in equity_historical.py; also falls through to the
    UserService when no explicit credentials were passed.
    """
    if credentials and "fmp_cached_api_key" in credentials:
        raw = credentials["fmp_cached_api_key"]
        # Handle SecretStr transparently.
        key_val = (
            raw.get_secret_value() if hasattr(raw, "get_secret_value") else str(raw)
        )
        return {"fmp_api_key": key_val}
    if credentials and "fmp_api_key" in credentials:
        return credentials
    # Neither present; try UserService.
    try:
        from openbb_core.app.service.user_service import UserService

        settings = UserService().default_user_settings
        for attr in ("fmp_cached_api_key", "fmp_api_key"):
            key = getattr(settings.credentials, attr, None)
            if key:
                val = (
                    key.get_secret_value()
                    if hasattr(key, "get_secret_value")
                    else str(key)
                )
                return {"fmp_api_key": val}
    except Exception as exc:
        logger.debug(f"UserService credential lookup skipped: {exc}")
    return credentials


def _analyze_intraday_cache(
    query: FMPCachedEquityIntradayHistoricalQueryParams,
) -> tuple[list[dict[str, Any]], bool]:
    """Return (cached_rows, has_gap).

    Simple gap detection: any-gap-in-range triggers a refetch of the full
    range from FMP. Intraday bar counts are impractical to enumerate ahead
    of time (holidays, half-days, mid-session halts) — the equity_historical
    pattern uses the same "refetch full range on any gap" heuristic for
    non-daily intervals.
    """
    sql = """
    SELECT symbol, interval_type, ts,
           open_price, high_price, low_price, close_price, volume,
           is_extended, is_valid
    FROM equity_intraday_historical
    WHERE symbol = %s
      AND interval_type = %s
      AND ts >= %s
      AND ts < %s
      AND (%s = TRUE OR is_extended = FALSE)
    ORDER BY ts ASC
    """
    start = _local_naive(query.start_date)
    end = _local_naive(query.end_date)
    if start is None or end is None:
        # No range constraint — treat as cache miss so we fetch fresh.
        return [], True
    end_date_only = getattr(query, "_end_date_date_only", False)
    start_date_only = getattr(query, "_start_date_date_only", False)
    end_exclusive = (
        end + timedelta(days=1) if end_date_only else end + timedelta(seconds=1)
    )
    rows = execute_query(
        sql,
        (
            query.symbol,
            query.interval,
            start,
            end_exclusive,
            query.extended_hours,
        ),
    )
    if not rows:
        return [], True

    cached: list[dict[str, Any]] = []
    has_invalid = False
    for row in rows:
        if not row["is_valid"]:
            has_invalid = True
            continue
        cached.append(
            {
                "symbol": row["symbol"],
                "interval": row["interval_type"],
                "date": row["ts"],
                "open": (
                    float(row["open_price"]) if row["open_price"] is not None else None
                ),
                "high": (
                    float(row["high_price"]) if row["high_price"] is not None else None
                ),
                "low": (
                    float(row["low_price"]) if row["low_price"] is not None else None
                ),
                "close": (
                    float(row["close_price"])
                    if row["close_price"] is not None
                    else None
                ),
                "volume": int(row["volume"]) if row["volume"] is not None else None,
                "is_extended": bool(row["is_extended"]),
            }
        )
    if not cached:
        return [], True
    # Coverage check — earliest & latest cached bar bracket the requested range.
    first_ts, last_ts = cached[0]["date"], cached[-1]["date"]
    interval_delta = _interval_delta(query.interval)
    expected_start = _align_session_bound(
        start,
        interval_delta,
        query.extended_hours,
        ceiling=True,
    )
    expected_end = _align_session_bound(
        end,
        interval_delta,
        query.extended_hours,
        ceiling=False,
    )
    missing_start = not start_date_only and first_ts > expected_start
    requested_last = end_exclusive - timedelta(seconds=1)
    missing_end = not end_date_only and last_ts < expected_end
    has_interior_gap = any(
        current["date"].date() == following["date"].date()
        and following["date"] - current["date"] > interval_delta
        for current, following in zip(cached, cached[1:])
    )
    has_session_gap = _has_session_gap(
        cached,
        start,
        requested_last,
        query.interval,
        query.extended_hours,
    )
    if (
        has_invalid
        or missing_start
        or missing_end
        or has_interior_gap
        or has_session_gap
    ):
        return cached, True
    return cached, False


def _upsert_intraday_rows(
    symbol: str,
    interval: str,
    rows: list[dict[str, Any]],
) -> None:
    """UPSERT fresh FMP rows into equity_intraday_historical.

    FMP returns rows keyed by ``date`` (bar-start datetime string) — we
    normalize to our ``ts`` column. ``ON DUPLICATE KEY UPDATE`` covers
    the tail-bar refresh case: same (symbol, interval_type, ts) rewrites
    the OHLCV values and flips is_valid back to TRUE.
    """
    if not rows:
        return
    sql = """
    INSERT INTO equity_intraday_historical
        (symbol, interval_type, ts, open_price, high_price, low_price,
         close_price, volume, is_extended, is_valid)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
    ON DUPLICATE KEY UPDATE
        open_price = VALUES(open_price),
        high_price = VALUES(high_price),
        low_price = VALUES(low_price),
        close_price = VALUES(close_price),
        volume = VALUES(volume),
        is_extended = VALUES(is_extended),
        is_valid = TRUE,
        updated_at = CURRENT_TIMESTAMP
    """
    params_list = []
    for r in rows:
        ts = r.get("date") or r.get("ts")
        if isinstance(ts, str):
            # FMP returns "YYYY-MM-DD HH:MM:SS" for intraday.
            ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        is_extended = _is_extended_row(r, ts=ts)
        params_list.append(
            (
                symbol,
                interval,
                ts,
                r.get("open"),
                r.get("high"),
                r.get("low"),
                r.get("close"),
                r.get("volume"),
                bool(is_extended),
            )
        )
    execute_many(sql, params_list)


def _safe_upsert_intraday_rows(
    symbol: str,
    interval: str,
    rows: list[dict[str, Any]],
) -> bool:
    try:
        _upsert_intraday_rows(symbol, interval, rows)
    except Exception as exc:
        logger.warning("Intraday cache write failed for %s: %s", symbol, exc)
        return False
    return True


def _is_extended_row(
    row: dict[str, Any],
    *,
    ts: datetime | None = None,
) -> bool:
    explicit = row.get("is_extended")
    if explicit is not None:
        return bool(explicit)
    value = ts or row.get("date") or row.get("ts")
    if isinstance(value, str):
        value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    if not isinstance(value, datetime):
        return False
    market_open, market_close = _us_session_bounds(value.date())
    return value.time() < market_open or value.time() >= market_close


def _filter_fresh_rows(
    rows: list[dict[str, Any]],
    query: FMPCachedEquityIntradayHistoricalQueryParams,
) -> list[dict[str, Any]]:
    filtered = (
        rows
        if query.extended_hours
        else [row for row in rows if not _is_extended_row(row)]
    )
    start = _local_naive(query.start_date)
    end = _local_naive(query.end_date)
    end_date_only = getattr(query, "_end_date_date_only", False)
    end_exclusive = (
        end + timedelta(days=1)
        if end is not None and end_date_only
        else end + timedelta(seconds=1) if end is not None else None
    )
    result = []
    for row in filtered:
        value = row.get("date") or row.get("ts")
        if isinstance(value, str):
            value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        if not isinstance(value, datetime):
            continue
        if start is not None and value < start:
            continue
        if end_exclusive is not None and value >= end_exclusive:
            continue
        result.append(row)
    result.sort(
        key=lambda row: (
            str(row.get("symbol", "")),
            str(row.get("date") or row.get("ts") or ""),
        )
    )
    return result


def _interval_delta(interval: str) -> timedelta:
    value = interval.lower()
    if value.endswith("min"):
        return timedelta(minutes=int(value.removesuffix("min")))
    if value.endswith("hour"):
        return timedelta(hours=int(value.removesuffix("hour")))
    return timedelta(days=1)


def _align_session_bound(
    value: datetime,
    interval: timedelta,
    extended_hours: bool,
    *,
    ceiling: bool,
) -> datetime:
    market_open, _ = _us_session_bounds(value.date())
    origin_time = time(4) if extended_hours else market_open
    origin = datetime.combine(value.date(), origin_time)
    elapsed = value - origin
    steps, remainder = divmod(elapsed, interval)
    if ceiling and remainder:
        steps += 1
    return origin + steps * interval


def _has_session_gap(
    rows: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    interval: str,
    extended_hours: bool,
) -> bool:
    """Validate expected NYSE sessions and their boundary bars."""
    calendar = exchange_calendars.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(
        pd.Timestamp(start.date()),
        pd.Timestamp(end.date()),
    )
    by_date: dict[date, list[datetime]] = {}
    for row in rows:
        by_date.setdefault(row["date"].date(), []).append(row["date"])
    delta = _interval_delta(interval)
    for session in sessions:
        session_date = session.date()
        timestamps = sorted(by_date.get(session_date, []))
        if not timestamps:
            return True
        if extended_hours:
            expected_open = datetime.combine(session_date, time(4))
            expected_close = datetime.combine(session_date, time(20)) - delta
        else:
            market_open, market_close = _us_session_bounds(session_date)
            expected_open = datetime.combine(session_date, market_open)
            expected_close = datetime.combine(session_date, market_close) - delta
        bounded_open = max(
            expected_open,
            _align_session_bound(
                start,
                delta,
                extended_hours,
                ceiling=True,
            ),
        )
        bounded_close = min(
            expected_close,
            _align_session_bound(
                end,
                delta,
                extended_hours,
                ceiling=False,
            ),
        )
        if timestamps[0] > bounded_open or timestamps[-1] < bounded_close:
            return True
    return False


def _local_naive(value: datetime | None) -> datetime | None:
    """Keep exchange-local wall time while removing an explicit offset."""
    if value and value.tzinfo:
        return value.astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)
    return value


@lru_cache(maxsize=512)
def _us_session_bounds(session_date: date) -> tuple[time, time]:
    """Return NYSE local open/close, including holiday early closes."""
    calendar = exchange_calendars.get_calendar("XNYS")
    session = pd.Timestamp(session_date)
    if not calendar.is_session(session):
        return time.max, time.min
    market_open = calendar.session_open(session).tz_convert("America/New_York")
    market_close = calendar.session_close(session).tz_convert("America/New_York")
    return market_open.time(), market_close.time()


def _invalidate_same_session_tail(
    symbol: str,
    interval: str,
    cached_rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> None:
    """Mark the last-bar-of-today is_valid=FALSE so the next call refetches it.

    Critical correctness rule (PRD §5.2): a 5-min bar opened at 10:00 doesn't
    finalize until 10:05. Serving it as complete at 10:03 would give consumers
    an incomplete bar. Prior-session bars stay valid — they're immutable.
    """
    if not cached_rows:
        return
    tail = cached_rows[-1]
    tail_ts = tail.get("date") or tail.get("ts")
    if tail_ts is None:
        return
    if not isinstance(tail_ts, datetime):
        return
    current = now or datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    if tail_ts.date() != current.date():
        return  # Prior-session bar; leave immutable.
    _, market_close = _us_session_bounds(tail_ts.date())
    session_close = time(20) if tail.get("is_extended") else market_close
    if (
        tail_ts.time() >= session_close
        or tail_ts + _interval_delta(interval) <= current
    ):
        return
    sql = """
    UPDATE equity_intraday_historical
    SET is_valid = FALSE
    WHERE symbol = %s AND interval_type = %s AND ts = %s
    """
    try:
        execute_query(sql, (symbol, interval, tail_ts))
    except Exception as exc:
        logger.warning(f"Tail-invalidation UPDATE failed for {symbol}: {exc}")
