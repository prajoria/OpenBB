"""Portfolio Intelligence provider modules (#1715).

Generalizes the fmp_cached ``free_yield_service._fetch_with_fallback``
pattern into a reusable dispatcher (``ChainedFetcher``) plus a static
registry mapping endpoint families to ordered tier lists.

Public API:

- :class:`ChainedFetcher` — walks a tier chain, catching failures per
  tier, classifying transitions, returning a
  ``(result, ChainOutcome)`` tuple.
- :class:`ChainOutcome` — dataclass carrying which tier finally
  produced the result, the list of transitions taken to get there, and
  per-tier latency measurements. Consumed by the provider-health
  widget so the strip can show real *current-in-use* tier per
  endpoint.
- :class:`TierHealth` — per-tier probe result (name, status,
  latency_ms, note-from-allowlist).
- :func:`probe_tier` — async 2s-timeout ping used by the health widget.
- :data:`TIER_REGISTRY` — the immutable ``endpoint_family -> tier
  list`` map.

See design plan: ``.claude/plans/twinkling-twirling-island.md``.
"""

from __future__ import annotations

from .chain import (
    ChainedFetcher,
    ChainedFetcherAllTiersFailed,
    ChainOutcome,
    Trigger,
)
from .probe import TierHealth, probe_tier
from .registry import TIER_REGISTRY, TierList, track_key

__all__ = [
    "ChainedFetcher",
    "ChainedFetcherAllTiersFailed",
    "ChainOutcome",
    "TIER_REGISTRY",
    "TierHealth",
    "TierList",
    "Trigger",
    "probe_tier",
    "track_key",
]
