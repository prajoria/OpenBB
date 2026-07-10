"""Base fallback for FMP cached models - provides only credential translation."""

import logging
from typing import Any, Dict, Type

from openbb_core.provider.abstract.fetcher import Fetcher

logger = logging.getLogger(__name__)

# NOTE: This base class provides only fallback functionality with credential translation.
# Each endpoint should implement its own dedicated database persistence logic in its specific model file.
# This is NOT caching - it's persistent database storage to avoid unnecessary API calls.


def create_fallback_fetcher_class(original_fetcher_class: Type[Fetcher], endpoint_name: str) -> Type[Fetcher]:
    """Create a fallback version of an FMP fetcher class with only credential translation.
    
    This is a simple fallback for endpoints that don't have dedicated database persistence.
    Each endpoint should implement its own database persistence logic in its specific model file.
    
    Args:
        original_fetcher_class: The original FMP fetcher class
        endpoint_name: Name of the endpoint for identification
        
    Returns:
        New fallback fetcher class with credential translation only
    """
    
    class FallbackFMPFetcher(original_fetcher_class):
        """Fallback FMP fetcher with credential translation only."""
        
        @staticmethod
        def transform_query(params: Dict[str, Any]):
            """Use original transform_query method."""
            return original_fetcher_class.transform_query(params)
        
        @staticmethod
        async def aextract_data(query, credentials, **kwargs):
            """Extract data with credential translation only - no database persistence."""
            logger.info(
                "Using fallback fetcher implementation for endpoint=%s",
                endpoint_name,
            )
            
            # Fix credential mapping: fmp_cached_api_key -> fmp_api_key
            if credentials and 'fmp_cached_api_key' in credentials:
                translated_credentials = {
                    'fmp_api_key': credentials['fmp_cached_api_key']
                }
            else:
                translated_credentials = credentials
            
            try:
                # Return raw extracted data; OpenBB runtime will call transform_data.
                return await original_fetcher_class.aextract_data(
                    query,
                    translated_credentials,
                    **kwargs,
                )
                
            except Exception as e:
                logger.error(f"Failed to fetch data from FMP for {endpoint_name}: {e}")
                raise
        
        @staticmethod
        def transform_data(query, data, **kwargs):
            """Use original transform_data method."""
            return original_fetcher_class.transform_data(query, data, **kwargs)
    
    # Set class name and module for better debugging
    FallbackFMPFetcher.__name__ = f"Fallback{original_fetcher_class.__name__}"
    FallbackFMPFetcher.__qualname__ = f"Fallback{original_fetcher_class.__qualname__}"
    
    return FallbackFMPFetcher


# Deprecated: Use create_fallback_fetcher_class instead
# This function is kept for backward compatibility only
def create_cached_fetcher_class(original_fetcher_class: Type[Fetcher], endpoint_name: str) -> Type[Fetcher]:
    """Deprecated: Use create_fallback_fetcher_class instead."""
    # logger.warning(f"create_cached_fetcher_class is deprecated for {endpoint_name}. Use dedicated database persistence in the specific model file.")
    return create_fallback_fetcher_class(original_fetcher_class, endpoint_name)


def create_ttl_wrapper_class(
    inner_fetcher_cls: Type[Fetcher],
    name: str,
    ttl_seconds: int,
) -> Type[Fetcher]:
    """Wrap a fetcher with a global TTL cache keyed by (name, query_hash).

    Distinct from :func:`create_fallback_fetcher_class`:
      * fallback wrapper: same-session credential translation only, no persistence
      * TTL wrapper:      persistent multi-hour caching backed by the ``ttl_cache``
                          MySQL table (see ``cache_schema.create_ttl_cache_table``)

    HIT semantics: ``cached_at > now - ttl_seconds AND payload IS NOT NULL``.
    On MISS the wrapper delegates to the inner fetcher, UPSERTs the payload
    (via ``INSERT ... ON DUPLICATE KEY UPDATE``), then returns the fresh
    data. DB failures never fail-fast — cached read errors fall through to a
    live fetch, cached write errors are best-effort suppressed. This matches
    the resilience pattern the tier-1 fetchers established in P2.1.

    Reuse targets (fmp-day-trading PRD §5.5):
      * ExchangeMarketHours  → 86400s TTL   (P2.2, shipped alongside this helper)
      * holidays             → 86400s TTL   (future)
      * market_status        → any TTL      (future)

    Args:
        inner_fetcher_cls: The raw FMP fetcher class to wrap.
        name:              Unique cache_name used as one half of the primary
                           key in the ttl_cache table (max 80 chars). Use the
                           OpenBB endpoint name (e.g. "ExchangeMarketHours")
                           so debugging + eviction queries stay readable.
        ttl_seconds:       Cache freshness horizon in seconds. 86400 = 24h.

    Returns:
        A new Fetcher subclass whose ``__name__`` is
        ``f"{name}TTLCached"`` for debugging clarity.
    """
    # Local imports keep the base_cached top-level dependencies unchanged
    # (only Fetcher is unconditionally imported at module load; hashlib/json/
    # datetime/db-helpers are pulled lazily on wrapper construction).
    import hashlib
    import json
    from datetime import datetime, timedelta

    from openbb_fmp_cached.utils.database import execute_many, execute_query

    ttl = timedelta(seconds=ttl_seconds)

    def _hash_query(query) -> str:
        """Stable 64-char SHA-256 hex digest of the query params."""
        if hasattr(query, "model_dump_json"):
            payload = query.model_dump_json(exclude_none=True)
        else:
            payload = json.dumps(query, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _load_ttl_cache(cache_name: str, cache_key: str, cutoff: datetime):
        """SELECT payload if a fresh row exists; None on MISS or DB error."""
        rows = execute_query(
            "SELECT payload FROM ttl_cache "
            "WHERE cache_name = %s AND cache_key = %s AND cached_at > %s",
            (cache_name, cache_key, cutoff),
        )
        if not rows:
            return None
        return json.loads(rows[0]["payload"])

    def _upsert_ttl_cache(cache_name: str, cache_key: str, data) -> None:
        """UPSERT the payload; refreshes cached_at via ON DUPLICATE KEY UPDATE."""
        execute_many(
            """INSERT INTO ttl_cache (cache_name, cache_key, payload)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 payload = VALUES(payload),
                 cached_at = CURRENT_TIMESTAMP""",
            [(cache_name, cache_key, json.dumps(data, default=str))],
        )

    def _translate_creds(credentials):
        """Same fmp_cached_api_key -> fmp_api_key mapping create_fallback uses.

        Inlined here rather than imported so the TTL wrapper stays a
        drop-in — if create_fallback_fetcher_class's credential shape ever
        diverges, this local copy can follow independently.
        """
        if not credentials:
            return credentials
        if "fmp_cached_api_key" in credentials:
            raw = credentials["fmp_cached_api_key"]
            val = raw.get_secret_value() if hasattr(raw, "get_secret_value") else str(raw)
            return {"fmp_api_key": val}
        return credentials

    class _TTLWrapped(Fetcher):
        """Generated at runtime by create_ttl_wrapper_class."""

        @staticmethod
        def transform_query(params):
            return inner_fetcher_cls.transform_query(params)

        @staticmethod
        async def aextract_data(query, credentials=None, **kwargs):
            cache_key = _hash_query(query)
            cutoff = datetime.utcnow() - ttl
            try:
                cached = _load_ttl_cache(name, cache_key, cutoff)
                if cached is not None:
                    logger.debug(f"TTL cache HIT for {name} (key={cache_key[:8]})")
                    return cached
            except Exception as exc:  # pragma: no cover - defensive path
                logger.warning(
                    f"TTL cache SELECT failed for {name}: {exc}; "
                    "falling through to live fetch"
                )
            fresh = await inner_fetcher_cls.aextract_data(
                query, _translate_creds(credentials), **kwargs
            )
            try:
                _upsert_ttl_cache(name, cache_key, fresh)
            except Exception as exc:  # pragma: no cover - defensive path
                logger.warning(
                    f"TTL cache UPSERT failed for {name}: {exc}; "
                    "returning fresh data anyway"
                )
            return fresh

        @staticmethod
        def transform_data(query, data, **kwargs):
            return inner_fetcher_cls.transform_data(query, data, **kwargs)

    _TTLWrapped.__name__ = f"{name}TTLCached"
    _TTLWrapped.__qualname__ = f"{name}TTLCached"
    return _TTLWrapped