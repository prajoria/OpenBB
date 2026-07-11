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

# pylint: disable=logging-fstring-interpolation

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_fmp.models.equity_intraday_historical import (
    FMPEquityIntradayHistoricalData,
    FMPEquityIntradayHistoricalFetcher,
    FMPEquityIntradayHistoricalQueryParams,
)

from openbb_fmp_cached.utils.database import execute_many, execute_query, init_database

logger = logging.getLogger(__name__)


# Public convenience — matches the alias types shipped by the raw fmp fetcher
# so router bindings can reference the cached class interchangeably.
class FMPCachedEquityIntradayHistoricalQueryParams(FMPEquityIntradayHistoricalQueryParams):
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
        return FMPCachedEquityIntradayHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPCachedEquityIntradayHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Serve intraday bars from MySQL cache; fetch only missing ranges from FMP."""
        # Credential translation: fmp_cached_api_key -> fmp_api_key.
        fmp_credentials = _translate_credentials(credentials)

        # DB init; fall back to raw fmp on any DB failure (Phase 0 tier-2 posture).
        try:
            init_database()
        except Exception as exc:
            logger.warning(
                f"Cache DB init failed, falling back to direct FMP: {exc}"
            )
            return await FMPEquityIntradayHistoricalFetcher.aextract_data(
                query, fmp_credentials, **kwargs
            )

        # Multi-symbol fanout — one gap-analysis + optional fetch per symbol.
        symbols = [s.strip().upper() for s in query.symbol.split(",") if s.strip()]
        all_rows: list[dict[str, Any]] = []
        for symbol in symbols:
            single_query = FMPCachedEquityIntradayHistoricalQueryParams(
                symbol=symbol,
                interval=query.interval,
                start_date=query.start_date,
                end_date=query.end_date,
                extended_hours=query.extended_hours,
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
                    _upsert_intraday_rows(symbol, query.interval, fallback)
                all_rows.extend(fallback)
                continue

            if has_gap:
                logger.info(
                    f"Cache MISS/PARTIAL for {symbol} intraday ({query.interval}); "
                    f"fetching from FMP"
                )
                fresh = await FMPEquityIntradayHistoricalFetcher.aextract_data(
                    single_query, fmp_credentials, **kwargs
                )
                if fresh:
                    _upsert_intraday_rows(symbol, query.interval, fresh)
                # Re-read now-complete range from cache so tail-invalidation
                # applies consistently to fresh writes too.
                cached_rows, _ = _analyze_intraday_cache(single_query)
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
        key_val = raw.get_secret_value() if hasattr(raw, "get_secret_value") else str(raw)
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
                val = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key)
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
      AND ts BETWEEN %s AND %s
      AND is_valid = TRUE
    ORDER BY ts ASC
    """
    start = query.start_date
    end = query.end_date
    if start is None or end is None:
        # No range constraint — treat as cache miss so we fetch fresh.
        return [], True
    rows = execute_query(sql, (query.symbol, query.interval, start, end))
    if not rows:
        return [], True

    cached: list[dict[str, Any]] = []
    for row in rows:
        cached.append({
            "symbol": row["symbol"],
            "interval": row["interval_type"],
            "date": row["ts"],
            "open": float(row["open_price"]) if row["open_price"] is not None else None,
            "high": float(row["high_price"]) if row["high_price"] is not None else None,
            "low": float(row["low_price"]) if row["low_price"] is not None else None,
            "close": float(row["close_price"]) if row["close_price"] is not None else None,
            "volume": int(row["volume"]) if row["volume"] is not None else None,
            "is_extended": bool(row["is_extended"]),
        })
    # Coverage check — earliest & latest cached bar bracket the requested range.
    first_ts, last_ts = cached[0]["date"], cached[-1]["date"]
    if first_ts > start or last_ts < end:
        return cached, True
    return cached, False


def _upsert_intraday_rows(
    symbol: str, interval: str, rows: list[dict[str, Any]],
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
        params_list.append((
            symbol, interval, ts,
            r.get("open"), r.get("high"), r.get("low"), r.get("close"),
            r.get("volume"), bool(r.get("is_extended", False)),
        ))
    execute_many(sql, params_list)


def _invalidate_same_session_tail(
    symbol: str, interval: str, cached_rows: list[dict[str, Any]],
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
    tail_date: date = tail_ts.date() if isinstance(tail_ts, datetime) else tail_ts
    if tail_date != date.today():
        return  # Prior-session bar; leave immutable.
    sql = """
    UPDATE equity_intraday_historical
    SET is_valid = FALSE
    WHERE symbol = %s AND interval_type = %s AND ts = %s
    """
    try:
        execute_query(sql, (symbol, interval, tail_ts))
    except Exception as exc:
        logger.warning(f"Tail-invalidation UPDATE failed for {symbol}: {exc}")
