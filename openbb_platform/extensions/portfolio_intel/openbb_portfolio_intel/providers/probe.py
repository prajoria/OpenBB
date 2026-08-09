"""Async provider probes for the health widget (#1715).

Each tier gets pinged with a 2s timeout (spec §T12.1 P0-1). We DO NOT
route through the ChainedFetcher for probes — probes are cheap synthetic
liveness checks whose only output is a :class:`TierHealth`; a fallback
between probes would defeat the diagnostic purpose.

The set of allowed ``note`` values is a closed allowlist so a raw
exception string can never leak into the widget markdown (spec §T12.1
P0-3).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


ALLOWED_NOTES: frozenset[str] = frozenset(
    {
        "timeout",
        "auth_failed",
        "rate_limited",
        "http_5xx",
        "network",
        "probe_failed_cold_cache",
        "snapshot_age_2h",
        "high_latency",
        "unknown_error",
    }
)


@dataclass(frozen=True)
class TierHealth:
    """One tier's health after a probe.

    Fields:
        name: canonical tier name (matches TIER_REGISTRY entries)
        status: one of ``{"healthy", "degraded", "down", "unknown"}``
        latency_ms: observed latency in ms; ``0`` when status is
            ``"unknown"`` (cold cache) or ``"down"`` (immediate connect fail)
        note: optional annotation from the closed allowlist above
    """

    name: str
    status: str  # "healthy" | "degraded" | "down" | "unknown"
    latency_ms: int
    note: str | None = None

    def __post_init__(self) -> None:
        """Enforce status enum + note allowlist at construction."""
        if self.status not in {"healthy", "degraded", "down", "unknown"}:
            raise ValueError(
                f"status must be one of the 4 canonicals; got {self.status!r}"
            )
        if self.note is not None and self.note not in ALLOWED_NOTES:
            raise ValueError(
                f"note {self.note!r} not in ALLOWED_NOTES — allowlist "
                "enforced to prevent raw-exception leaks into widget markdown"
            )


# Threshold: any probe over this is degraded rather than healthy.
_HIGH_LATENCY_MS = 1000

# Default probe timeout — spec §T12.1 says 2s per tier.
DEFAULT_PROBE_TIMEOUT_S: float = 2.0


# ---------------------------------------------------------------------------
# Seams
# ---------------------------------------------------------------------------


# A "prober" is an async callable that resolves the tier's synthetic
# liveness check. The registry below maps tier names to their probers.
# Injectable so tests can monkeypatch.
Prober = Callable[[], Awaitable[None]]


async def _default_prober() -> None:
    """No-op probe used when a tier has no registered prober.

    Immediately returns — the caller wraps this in ``asyncio.wait_for``
    with a timeout so a hang still gets caught.
    """
    return None


_PROBER_REGISTRY: dict[str, Prober] = {}


def register_prober(tier: str, prober: Prober) -> None:
    """Register a real prober for a tier (called by wiring code)."""
    _PROBER_REGISTRY[tier] = prober


def unregister_prober(tier: str) -> None:
    """Undo :func:`register_prober` — used by tests."""
    _PROBER_REGISTRY.pop(tier, None)


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------


async def probe_tier(
    tier: str, timeout_s: float = DEFAULT_PROBE_TIMEOUT_S
) -> TierHealth:
    """Async ping of one tier. Never raises — always returns a TierHealth.

    Status decision matrix:

    * probe returns within ``timeout_s`` and ``< 1000ms``: ``healthy``
    * probe returns within ``timeout_s`` and ``>= 1000ms``: ``degraded``
      with note=``high_latency``
    * ``asyncio.TimeoutError``: ``down`` with note=``timeout``
    * any other exception: ``down`` with a note from the closed
      allowlist (never the raw message)

    Cold-cache callers may prefer to seed the health widget with a
    single ``unknown`` sentinel per tier and kick this off in the
    background — see :func:`.widgets_endpoints.provider_health`.
    """
    prober = _PROBER_REGISTRY.get(tier)
    if prober is None:
        # No registered prober => we can't actually test connectivity.
        # Rather than lie "healthy", return unknown with a diagnostic
        # note that the reader can act on.
        return TierHealth(
            name=tier, status="unknown", latency_ms=0, note="probe_failed_cold_cache"
        )

    start = time.monotonic()
    try:
        await asyncio.wait_for(prober(), timeout=timeout_s)
    except asyncio.TimeoutError:
        return TierHealth(
            name=tier, status="down", latency_ms=int(timeout_s * 1000), note="timeout"
        )
    except Exception as exc:  # noqa: BLE001
        note = _classify_probe_exception(exc)
        return TierHealth(name=tier, status="down", latency_ms=0, note=note)

    latency_ms = int((time.monotonic() - start) * 1000)
    if latency_ms >= _HIGH_LATENCY_MS:
        return TierHealth(
            name=tier, status="degraded", latency_ms=latency_ms, note="high_latency"
        )
    return TierHealth(name=tier, status="healthy", latency_ms=latency_ms)


def _classify_probe_exception(exc: Exception) -> str:
    """Map an exception to a note from :data:`ALLOWED_NOTES`.

    Classifies by exception *type* first, then message text. Type-first
    matters because several real probe exceptions carry an EMPTY message —
    notably ``httpx.ConnectTimeout()`` whose ``str()`` is ``''`` — so a
    message-only classifier silently mislabels them ``unknown_error``. That
    was the live cause of the ``✕ cboe (0ms) (unknown_error)`` strip (#1960):
    a slow TLS handshake tripping the socket timeout raised an empty-message
    ``ConnectTimeout`` that matched no substring branch.

    We inspect the exception's class hierarchy names (module-qualified) so the
    probe engine stays transport-agnostic — no ``httpx`` import here — while
    still recognising timeout / connection / transport failures by type. Only
    allowlist notes are ever returned, so a raw exception string (possibly
    carrying PII) can never leak into the widget markdown.
    """
    type_blob = " ".join(
        f"{klass.__module__}.{klass.__qualname__}" for klass in type(exc).__mro__
    ).lower()
    msg = str(exc).lower()
    hay = f"{type_blob} {msg}"

    # Timeouts first: a *connect* timeout is both a timeout and a transport
    # error; label it the more actionable "timeout".
    if "timeout" in hay or "timedout" in hay:
        return "timeout"
    if "401" in msg or "unauthor" in msg or "forbidden" in msg or "api key" in msg:
        return "auth_failed"
    if "429" in msg or "rate limit" in msg or "too many" in msg:
        return "rate_limited"
    if "500" in msg or "502" in msg or "503" in msg or "504" in msg:
        return "http_5xx"
    if (
        "network" in hay
        or "connect" in hay  # httpx.ConnectError / builtin ConnectionError
        or "dns" in msg
        or "resolve" in hay
        or "transport" in hay  # httpx.TransportError base
        or "protocol" in hay  # httpx.RemoteProtocolError
        or "readerror" in type_blob  # httpx.ReadError
    ):
        return "network"
    return "unknown_error"
