"""Complementary market-yield service with internal provider fallback."""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from threading import Thread
from typing import Any

import pandas as pd

from openbb_fmp_cached.complementary import repository
from openbb_fmp_cached.complementary.sources import fmp_source, fred_source, yahoo_source
from openbb_fmp_cached.utils.database import init_database

logger = logging.getLogger(__name__)

DEFAULT_SYMBOL = "^TNX"
DEFAULT_TTL_HOURS = 24
MAX_FMP_RETRIES = 2


def get_us10y_series(
    start_date: str | date | None,
    end_date: str | date | None,
    credentials: dict[str, str] | None = None,
    request_id: str | None = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    **kwargs: Any,
) -> pd.DataFrame:
    """Get normalized US10Y series with cache-first internal fallback."""
    return _run_coro(
        aget_us10y_series(
            start_date=start_date,
            end_date=end_date,
            credentials=credentials,
            request_id=request_id,
            ttl_hours=ttl_hours,
            **kwargs,
        )
    )


async def aget_us10y_series(
    start_date: str | date | None,
    end_date: str | date | None,
    credentials: dict[str, str] | None = None,
    request_id: str | None = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    **kwargs: Any,
) -> pd.DataFrame:
    """Async variant for US10Y retrieval with cache-first internal fallback."""
    start, end = _normalize_dates(start_date, end_date)

    try:
        init_database()
        repository.ensure_table()
    except Exception as exc:
        logger.warning("Complementary cache init failed, continuing without cache: %s", exc)

    freshness_cutoff = datetime.now() - timedelta(hours=ttl_hours)
    cached_rows = _safe_read_cache(start, end, freshness_cutoff)
    if _is_cache_sufficient(cached_rows, start, end):
        return _rows_to_dataframe(cached_rows)

    source_rows = await _fetch_with_fallback(
        start_date=start,
        end_date=end,
        credentials=credentials,
        request_id=request_id,
        **kwargs,
    )

    if source_rows:
        _safe_write_cache(source_rows)
        return _rows_to_dataframe(source_rows)

    logger.warning(
        "No upstream provider returned TNX data: symbol=%s start_date=%s end_date=%s request_id=%s",
        DEFAULT_SYMBOL,
        start,
        end,
        request_id,
    )
    return pd.DataFrame(columns=["date", "yield_pct", "source"])


def get_latest_us10y_rate(
    start_date: str | date | None,
    end_date: str | date | None,
    fallback: float = 0.02,
    credentials: dict[str, str] | None = None,
    request_id: str | None = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    **kwargs: Any,
) -> tuple[float, str]:
    """Get latest US10Y as decimal with fallback-safe return."""
    frame = get_us10y_series(
        start_date=start_date,
        end_date=end_date,
        credentials=credentials,
        request_id=request_id,
        ttl_hours=ttl_hours,
        **kwargs,
    )
    if frame.empty:
        logger.warning(
            "Using static fallback rate after provider/cache exhaustion: symbol=%s request_id=%s",
            DEFAULT_SYMBOL,
            request_id,
        )
        return fallback, "fallback:static"

    latest = frame.sort_values("date", ascending=True).iloc[-1]
    return float(latest["yield_pct"]) / 100.0, str(latest["source"])


async def _fetch_with_fallback(
    start_date: date,
    end_date: date,
    credentials: dict[str, str] | None,
    request_id: str | None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Fetch US10Y with internal silent fallback order: FMP -> FRED -> YFinance."""
    last_exception: Exception | None = None

    for attempt in range(1, MAX_FMP_RETRIES + 1):
        try:
            rows = await fmp_source.fetch_us10y(start_date, end_date, credentials, **kwargs)
            if rows:
                return rows
        except Exception as exc:
            last_exception = exc
            if attempt < MAX_FMP_RETRIES:
                continue

    trigger = _classify_fmp_failure(last_exception)
    _log_fallback_transition("fmp", "fred", trigger, start_date, end_date, request_id)

    try:
        rows = await fred_source.fetch_us10y(start_date, end_date, credentials, **kwargs)
        if rows:
            return rows
    except Exception as exc:
        last_exception = exc

    _log_fallback_transition("fred", "yfinance", "upstream_failure", start_date, end_date, request_id)

    try:
        rows = yahoo_source.fetch_us10y(start_date, end_date, credentials, **kwargs)
        if rows:
            return rows
    except Exception as exc:
        last_exception = exc

    logger.warning(
        "All providers failed for TNX: symbol=%s start_date=%s end_date=%s request_id=%s last_error=%s",
        DEFAULT_SYMBOL,
        start_date,
        end_date,
        request_id,
        str(last_exception) if last_exception else "none",
    )
    return []


def _normalize_dates(
    start_date: str | date | None,
    end_date: str | date | None,
) -> tuple[date, date]:
    """Normalize date inputs to concrete date range."""
    today = datetime.now().date()
    end = _to_date(end_date) if end_date else today
    start = _to_date(start_date) if start_date else (end - timedelta(days=365))
    if start > end:
        raise ValueError("start_date must be less than or equal to end_date")
    return start, end


def _to_date(value: str | date) -> date:
    """Convert supported input date type to date."""
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _safe_read_cache(start: date, end: date, freshness_cutoff: datetime) -> list[dict[str, Any]]:
    """Read cache safely and return empty list if DB is unavailable."""
    try:
        return repository.read_cached_rows(DEFAULT_SYMBOL, start, end, freshness_cutoff)
    except Exception as exc:
        logger.warning("Complementary cache read failed: %s", exc)
        return []


def _safe_write_cache(rows: list[dict[str, Any]]) -> None:
    """Write cache safely and ignore write failures."""
    try:
        repository.upsert_rows(DEFAULT_SYMBOL, rows)
    except Exception as exc:
        logger.warning("Complementary cache write failed: %s", exc)


def _is_cache_sufficient(rows: list[dict[str, Any]], start: date, end: date) -> bool:
    """Determine whether cached rows sufficiently cover requested range."""
    if not rows:
        return False

    try:
        row_dates = [_to_date(str(item.get("date"))) for item in rows if item.get("date")]
    except Exception:
        return False

    if not row_dates:
        return False

    return min(row_dates) <= start and max(row_dates) >= end


def _rows_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert cached/source rows into canonical DataFrame output."""
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        row_date = row.get("date")
        yield_pct = row.get("yield_pct")
        source = row.get("source")

        if yield_pct is None and row.get("close") is not None:
            yield_pct = row.get("close")

        if source is None:
            source = _extract_source_from_row(row)

        if row_date is None or yield_pct is None:
            continue

        normalized_rows.append(
            {
                "date": str(row_date),
                "yield_pct": float(yield_pct),
                "source": source or "unknown",
            }
        )

    if not normalized_rows:
        return pd.DataFrame(columns=["date", "yield_pct", "source"])

    frame = pd.DataFrame(normalized_rows)
    return frame.sort_values("date", ascending=True).reset_index(drop=True)


def _extract_source_from_row(row: dict[str, Any]) -> str | None:
    """Extract source identifier from repository rows."""
    additional_fields = row.get("additional_fields")
    if isinstance(additional_fields, str):
        try:
            parsed = json.loads(additional_fields)
            return parsed.get("source")
        except Exception:
            return None
    if isinstance(additional_fields, dict):
        return additional_fields.get("source")
    return None


def _classify_fmp_failure(exc: Exception | None) -> str:
    """Classify FMP failure trigger for structured fallback logging."""
    if exc is None:
        return "empty_data"

    text = str(exc).lower()
    if any(token in text for token in ["401", "403", "forbidden", "unauthorized", "upgrade", "subscription", "tier"]):
        return "tier_access"
    if any(token in text for token in ["not available", "unsupported", "endpoint"]):
        return "endpoint_unavailable"
    return "transient_after_retries"


def _log_fallback_transition(
    from_provider: str,
    to_provider: str,
    trigger: str,
    start_date: date,
    end_date: date,
    request_id: str | None,
) -> None:
    """Emit structured info log for internal fallback transition."""
    logger.info(
        "fmp_cached fallback transition: symbol=%s from_provider=%s to_provider=%s trigger=%s start_date=%s end_date=%s request_id=%s",
        DEFAULT_SYMBOL,
        from_provider,
        to_provider,
        trigger,
        start_date,
        end_date,
        request_id,
    )


def _run_coro(coro):
    """Run async coroutine from sync code, including notebook event-loop contexts."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {"value": None, "error": None}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:  # pragma: no cover
            result["error"] = exc

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()

    if result["error"] is not None:
        raise result["error"]
    return result["value"]
