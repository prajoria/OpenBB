"""
TTL async cache for the OpenBB Portfolio extension.

Extracted from the original portfolio_app/src/main.py.
Provides a simple in-memory cache keyed by an arbitrary tuple,
with a configurable time-to-live (default 5 minutes).

This prevents redundant OpenBB SDK calls when multiple widgets
load for the same symbol simultaneously (profile, peers, price
history are all shared within the TTL window).

Usage:
    from openbb_portfolio._cache import cached

    result = await cached(
        key=("fundamentals", "MSFT", 5),
        coro_factory=lambda: fetch_fundamentals("MSFT", limit=5),
    )
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Tuple

_CACHE_TTL_SEC: float = 300  # 5 minutes — matches Workspace default staleTime

_stock_cache: dict[Tuple, "_CacheEntry"] = {}
_cache_lock: asyncio.Lock = asyncio.Lock()


@dataclass
class _CacheEntry:
    data: Any
    ts: float = field(default_factory=time.monotonic)

    def is_fresh(self, ttl: float = _CACHE_TTL_SEC) -> bool:
        return (time.monotonic() - self.ts) < ttl


async def cached(
    key: Tuple,
    coro_factory: Callable[[], Coroutine],
    ttl: float = _CACHE_TTL_SEC,
) -> Any:
    """Return cached result for *key* or await coro_factory() and cache it.

    Parameters
    ----------
    key:
        Hashable tuple that uniquely identifies the cached result.
    coro_factory:
        Zero-argument async callable whose result will be cached.
    ttl:
        Cache lifetime in seconds (default 300 s = 5 min).
    """
    async with _cache_lock:
        entry = _stock_cache.get(key)
        if entry and entry.is_fresh(ttl):
            return entry.data
    result = await coro_factory()
    async with _cache_lock:
        _stock_cache[key] = _CacheEntry(data=result)
    return result
