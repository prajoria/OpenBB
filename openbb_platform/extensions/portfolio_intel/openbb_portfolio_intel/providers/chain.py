"""ChainedFetcher — walks a tier chain, catching failures, logging transitions.

Design notes (spec §T12.1 + free_yield_service pattern):

- **Trigger classification**: every transition names WHY the previous
  tier failed. Categories are a closed enum (:class:`Trigger`) so the
  provider-health widget can render deterministic notes without
  echoing raw exception strings (spec §T12.1 P0-3).
- **Loud-empty**: if every tier fails (or every tier returns empty), we
  raise :class:`ChainedFetcherAllTiersFailed`. Callers that want a
  soft-fail contract wrap the call. NEVER return silent ``None`` or
  ``[]`` for a chain that walked through 5 tiers of failure.
- **Latency measurement**: each tier attempt is timed with
  ``time.monotonic()`` so downstream consumers (the health widget) can
  render per-tier latency without a separate probe.
- **Seams**: ``_now()`` and ``_call_provider()`` are module-level so
  tests can monkeypatch. Matches the ``_fetch_news_company`` /
  ``_fetch_filings`` injection pattern already used by the P3
  routers (#1716).

The trigger classifier is a strict superset of
``free_yield_service._classify_fmp_failure`` so we can eventually lift
the shared pieces up if a second retrofit target appears.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class Trigger(str, Enum):
    """Why a tier transition happened. Closed enum — extend deliberately."""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    HTTP_5XX = "http_5xx"
    NOT_AVAILABLE = "not_available"
    EMPTY_RESULT = "empty_result"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Transition:
    """One tier-N -> tier-N+1 hop within a single ``fetch()`` call."""

    from_tier: str
    to_tier: str
    trigger: Trigger


@dataclass
class ChainOutcome:
    """The observable result of one chain walk.

    Consumed by the provider-health widget to render "which tier is
    currently serving endpoint X" and by log analysis to spot chronic
    tier-1 failures.
    """

    endpoint: str
    track: str  # "A" or "B"
    tier_used: str | None  # None only if all tiers failed
    transitions: list[Transition] = field(default_factory=list)
    latency_ms_per_tier: dict[str, int] = field(default_factory=dict)
    #: ISO-8601 timestamp of when the chain walk completed
    at: str = ""


class ChainedFetcherAllTiersFailed(RuntimeError):
    """Raised when every tier in the chain either raised or returned empty.

    Payload carries the ``ChainOutcome`` so callers can decide whether
    to fall back to a stub, propagate as a 502, or degrade gracefully.
    """

    def __init__(self, outcome: ChainOutcome, last_exc: Exception | None) -> None:
        self.outcome = outcome
        self.last_exc = last_exc
        # Walk transitions for the message, but only show the last
        # trigger — full history lives on ``outcome`` for
        # programmatic inspection.
        last_trigger = (
            outcome.transitions[-1].trigger.value if outcome.transitions else "n/a"
        )
        super().__init__(
            f"All {len(outcome.latency_ms_per_tier)} tiers failed for "
            f"{outcome.endpoint} (track {outcome.track}); last trigger="
            f"{last_trigger}"
        )


# ---------------------------------------------------------------------------
# Seams
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """Wall-clock now — monkeypatch in tests to pin timestamps."""
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Trigger classification
# ---------------------------------------------------------------------------


def _classify_exception(exc: Exception) -> Trigger:
    """Map a raised exception to a :class:`Trigger` category.

    Uses substring matching on the exception message rather than
    isinstance checks so we're resilient to provider libs that wrap
    their errors in generic ``Exception`` / ``RuntimeError`` shells.
    """
    if isinstance(exc, asyncio.TimeoutError):
        return Trigger.TIMEOUT
    msg = str(exc).lower()
    if "401" in msg or "unauthor" in msg or "forbidden" in msg or "api key" in msg:
        return Trigger.AUTH
    if "429" in msg or "rate limit" in msg or "too many" in msg:
        return Trigger.RATE_LIMIT
    if "timeout" in msg or "timed out" in msg:
        return Trigger.TIMEOUT
    if "500" in msg or "502" in msg or "503" in msg or "504" in msg:
        return Trigger.HTTP_5XX
    if "network" in msg or "connection" in msg or "connect" in msg or "dns" in msg:
        return Trigger.NETWORK
    if "not available" in msg or "not implemented" in msg or "no such" in msg:
        return Trigger.NOT_AVAILABLE
    return Trigger.UNKNOWN


def _is_empty(result: Any) -> bool:
    """Empty ``[]`` / ``{}`` / ``None`` / empty ``.results`` means try next tier.

    A provider that returns ``NewsList(items=[])`` is still a "fetched
    empty" outcome — we treat it the same as an exception (transition
    with ``EMPTY_RESULT`` trigger) so the widget shows a *loud* empty
    rather than silently rendering "0 rows".
    """
    if result is None:
        return True
    if isinstance(result, (list, dict, tuple, set)) and len(result) == 0:
        return True
    inner = getattr(result, "results", None)
    if inner is not None and isinstance(inner, (list, dict, tuple, set)):
        return len(inner) == 0
    return False


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def _log_fallback_transition(
    endpoint: str, from_tier: str, to_tier: str, trigger: Trigger
) -> None:
    """Structured INFO log of one tier hop."""
    logger.info(
        "chain.transition endpoint=%s from=%s to=%s trigger=%s",
        endpoint,
        from_tier,
        to_tier,
        trigger.value,
    )


class ChainedFetcher:
    """Walks a tier chain until one returns a non-empty result.

    Usage::

        chain = ChainedFetcher(
            endpoint="equity/header",
            track="A",
            tiers=TIER_REGISTRY["equity/header:A"],
            call_tier=lambda tier, **kw: _call_obb(tier, kw["symbol"]),
        )
        result, outcome = chain.fetch(symbol="AAPL")

    ``call_tier`` is a synchronous callable receiving ``(tier_name,
    **kwargs)`` and returning either the result or raising. The
    ``ChainedFetcher`` never touches ``obb.*`` directly — the caller
    injects the provider seam so unit tests can monkeypatch without
    live network.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        track: str,
        tiers: tuple[str, ...],
        call_tier: Callable[..., Any],
    ) -> None:
        if track not in ("A", "B"):
            raise ValueError(f"track must be 'A' or 'B', got {track!r}")
        if not tiers:
            raise ValueError(
                f"tiers must be non-empty for endpoint={endpoint!r} "
                "(an empty chain would silently fail every call — file "
                "a follow-up sub-issue instead of registering ())"
            )
        self.endpoint = endpoint
        self.track = track
        self.tiers = tiers
        self._call_tier = call_tier

    def fetch(self, **kwargs: Any) -> tuple[Any, ChainOutcome]:
        """Walk the chain synchronously. Returns ``(result, outcome)``.

        Raises :class:`ChainedFetcherAllTiersFailed` when every tier
        fails.
        """
        outcome = ChainOutcome(
            endpoint=self.endpoint,
            track=self.track,
            tier_used=None,
            at=_now().isoformat(),
        )
        last_exc: Exception | None = None

        for idx, tier in enumerate(self.tiers):
            start = time.monotonic()
            try:
                result = self._call_tier(tier, **kwargs)
            except Exception as exc:  # noqa: BLE001 — dispatcher's whole job
                outcome.latency_ms_per_tier[tier] = int(
                    (time.monotonic() - start) * 1000
                )
                last_exc = exc
                trigger = _classify_exception(exc)
                if idx + 1 < len(self.tiers):
                    next_tier = self.tiers[idx + 1]
                    outcome.transitions.append(
                        Transition(from_tier=tier, to_tier=next_tier, trigger=trigger)
                    )
                    _log_fallback_transition(self.endpoint, tier, next_tier, trigger)
                continue
            outcome.latency_ms_per_tier[tier] = int((time.monotonic() - start) * 1000)
            if _is_empty(result):
                if idx + 1 < len(self.tiers):
                    next_tier = self.tiers[idx + 1]
                    outcome.transitions.append(
                        Transition(
                            from_tier=tier,
                            to_tier=next_tier,
                            trigger=Trigger.EMPTY_RESULT,
                        )
                    )
                    _log_fallback_transition(
                        self.endpoint, tier, next_tier, Trigger.EMPTY_RESULT
                    )
                continue
            outcome.tier_used = tier
            return result, outcome

        # Every tier failed or was empty.
        raise ChainedFetcherAllTiersFailed(outcome, last_exc)
