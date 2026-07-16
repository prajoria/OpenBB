"""Tier-1 cached aftermarket-quote fetcher — 60s TTL (fmp-day-trading PRD §5.2).

Single-row-per-symbol cache. HIT if cached_at > now - 60s; MISS otherwise.
No gap detection — ephemeral one-value-per-symbol data with an explicit
freshness contract:

  * HIT  = row present AND cached_at within TTL window AND is_valid=TRUE
  * MISS = anything else (missing row, stale row, invalidated row) triggers
           a fresh FMP fetch for exactly the missing symbols

Partial-hit optimization: when a batch of N symbols is 60% cached and 40%
stale, we fetch only the 40% missing — the 60% cached rows are served from
DB without hitting FMP.
"""

# pylint: disable=logging-fstring-interpolation

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_fmp.models.aftermarket_quote import (
    FMPAftermarketQuoteData,
    FMPAftermarketQuoteFetcher,
    FMPAftermarketQuoteQueryParams,
)

from openbb_fmp_cached.utils.database import execute_many, execute_query, init_database

logger = logging.getLogger(__name__)

# 60-second TTL per PRD §5.2. Chosen so a fast tick loop (5s poll) still
# saves ~12x on aftermarket-quote calls without ever serving a >60s-stale
# price to a downstream RiskManager gate.
_TTL_SECONDS: int = 60


class FMPCachedAftermarketQuoteQueryParams(FMPAftermarketQuoteQueryParams):
    """Cached aftermarket-quote query params (no additional fields)."""


class FMPCachedAftermarketQuoteData(FMPAftermarketQuoteData):
    """Cached aftermarket-quote row (no additional fields)."""


class FMPCachedAftermarketQuoteFetcher(
    Fetcher[
        FMPCachedAftermarketQuoteQueryParams,
        list[FMPCachedAftermarketQuoteData],
    ]
):
    """Tier-1 60-second-TTL cached aftermarket-quote fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FMPCachedAftermarketQuoteQueryParams:
        return FMPCachedAftermarketQuoteQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPCachedAftermarketQuoteQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Serve fresh (<60s) rows from cache; fetch only stale/missing symbols."""
        fmp_credentials = _translate_credentials(credentials)

        try:
            init_database()
        except Exception as exc:
            logger.warning(
                f"Cache DB init failed, falling back to direct FMP: {exc}"
            )
            return await FMPAftermarketQuoteFetcher.aextract_data(
                query, fmp_credentials, **kwargs
            )

        symbols = [s.strip().upper() for s in query.symbol.split(",") if s.strip()]
        if not symbols:
            return []

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=_TTL_SECONDS
        )
        try:
            hit_rows, miss_symbols = _fetch_fresh_rows(symbols, cutoff)
        except Exception as exc:
            logger.warning(
                f"Aftermarket-quote cache read failed: {exc}; "
                "falling back to direct FMP fetch for all symbols"
            )
            fresh = await FMPAftermarketQuoteFetcher.aextract_data(
                query, fmp_credentials, **kwargs
            )
            if fresh:
                try:
                    _upsert_aftermarket_rows(fresh)
                except Exception as up_exc:
                    logger.warning(f"UPSERT after fallback fetch failed: {up_exc}")
            return fresh

        if not miss_symbols:
            logger.info(
                f"Aftermarket-quote cache HIT for all {len(symbols)} symbols"
            )
            return hit_rows

        logger.info(
            f"Aftermarket-quote cache PARTIAL: {len(hit_rows)}/{len(symbols)} "
            f"HIT, fetching {len(miss_symbols)} MISS"
        )
        miss_query = query.model_copy(update={"symbol": ",".join(miss_symbols)})
        fresh = await FMPAftermarketQuoteFetcher.aextract_data(
            miss_query, fmp_credentials, **kwargs
        )
        if fresh:
            try:
                _upsert_aftermarket_rows(fresh)
            except Exception as up_exc:
                logger.warning(f"UPSERT after MISS fetch failed: {up_exc}")
        return hit_rows + fresh

    @staticmethod
    def transform_data(
        query: FMPCachedAftermarketQuoteQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FMPCachedAftermarketQuoteData]:
        """Validate raw dicts into typed aftermarket-quote rows."""
        return [FMPCachedAftermarketQuoteData.model_validate(d) for d in data]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _translate_credentials(
    credentials: dict[str, Any] | None,
) -> dict[str, str] | None:
    """Same shape as equity_intraday_historical._translate_credentials.

    Duplicated here rather than importing to keep the two fetchers loosely
    coupled — if one needs a bespoke credential path (e.g. a future extended-
    hours-specific key) it can diverge without cross-module churn.
    """
    if credentials and "fmp_cached_api_key" in credentials:
        raw = credentials["fmp_cached_api_key"]
        key_val = raw.get_secret_value() if hasattr(raw, "get_secret_value") else str(raw)
        return {"fmp_api_key": key_val}
    if credentials and "fmp_api_key" in credentials:
        return credentials
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


def _fetch_fresh_rows(
    symbols: list[str], cutoff: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (fresh_hits, stale_or_missing_symbols)."""
    # Empty input → nothing can be fresh. Guard here rather than build
    # `WHERE symbol IN ()`, which MySQL rejects with a 1064 syntax error.
    # See #774 (fmp_cached: SQL syntax error on empty symbols list).
    if not symbols:
        return [], []
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
    SELECT symbol, price, bid, ask, bid_size, ask_size, volume, timestamp
    FROM aftermarket_quote
    WHERE symbol IN ({placeholders})
      AND cached_at > %s
      AND is_valid = TRUE
    """
    rows = execute_query(sql, (*symbols, cutoff))
    hits: list[dict[str, Any]] = []
    hit_symbols: set[str] = set()
    for row in rows:
        hits.append({
            "symbol": row["symbol"],
            "price": float(row["price"]) if row["price"] is not None else None,
            "bid": float(row["bid"]) if row["bid"] is not None else None,
            "ask": float(row["ask"]) if row["ask"] is not None else None,
            "bid_size": int(row["bid_size"]) if row["bid_size"] is not None else None,
            "ask_size": int(row["ask_size"]) if row["ask_size"] is not None else None,
            "volume": int(row["volume"]) if row["volume"] is not None else None,
            "timestamp": row["timestamp"],
        })
        hit_symbols.add(row["symbol"])
    miss = [s for s in symbols if s not in hit_symbols]
    return hits, miss


def _upsert_aftermarket_rows(rows: list[dict[str, Any]]) -> None:
    """UPSERT fresh FMP quotes; refreshes cached_at + flips is_valid=TRUE."""
    if not rows:
        return
    sql = """
    INSERT INTO aftermarket_quote
        (symbol, price, bid, ask, bid_size, ask_size, volume, timestamp, is_valid)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
    ON DUPLICATE KEY UPDATE
        price = VALUES(price),
        bid = VALUES(bid),
        ask = VALUES(ask),
        bid_size = VALUES(bid_size),
        ask_size = VALUES(ask_size),
        volume = VALUES(volume),
        timestamp = VALUES(timestamp),
        cached_at = CURRENT_TIMESTAMP,
        is_valid = TRUE
    """
    params_list = [
        (
            r["symbol"], r.get("price"),
            r.get("bid"), r.get("ask"),
            r.get("bid_size"), r.get("ask_size"),
            r.get("volume"), r.get("timestamp"),
        )
        for r in rows
    ]
    execute_many(sql, params_list)
