"""Tier-1 24h-TTL cached ExchangeMarketHours (fmp-day-trading PRD §5.5).

Uses the shared :func:`create_ttl_wrapper_class` from ``base_cached`` (P2.2).
Market hours change ~daily (holidays, DST transitions) — an 86400-second TTL
saves ~1000 redundant FMP calls per day compared to the tier-2 passthrough
this module replaces.

The class produced here is generated at import time (side-effect of calling
``create_ttl_wrapper_class``). Register in ``openbb_fmp_cached/__init__.py``'s
``dedicated_fetchers`` dict — do NOT re-register in the tier-2
``fetcher_mapping`` list.
"""

from __future__ import annotations

from openbb_fmp.models.exchange_market_hours import FMPExchangeMarketHoursFetcher

from openbb_fmp_cached.models.base_cached import create_ttl_wrapper_class

# 24 hours == 86400 seconds. Locked design decision per PRD §5.5 —
# the whole point of this migration is "market hours changes ~daily so
# cache for a day." A shorter TTL would defeat the ~1000-call/day savings;
# a longer TTL risks serving stale holiday adjustments on the day-after.
_TTL_SECONDS: int = 86400

FMPCachedExchangeMarketHoursFetcher = create_ttl_wrapper_class(
    FMPExchangeMarketHoursFetcher,
    name="ExchangeMarketHours",
    ttl_seconds=_TTL_SECONDS,
)
