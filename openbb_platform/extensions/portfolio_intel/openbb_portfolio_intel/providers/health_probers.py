"""Default provider-health probers (#1956).

Root cause of the always-``?`` Provider Health strip: :func:`register_prober`
was called **only from tests**, so on the running server the prober registry
was empty and every tier fell to :func:`probe_tier`'s ``prober is None`` branch
— an *instant* ``probe_failed_cold_cache`` "unknown". The strip therefore never
showed real liveness (this was NOT a too-tight-timeout problem: with no prober
there is nothing to time out; the probe returns unknown immediately and the
60s cache faithfully stores that emptiness).

This module supplies cheap, quota-free **reachability** probers — an HTTP
``HEAD`` to each provider's public base URL — and registers one per tier. Any
HTTP response below 500 means the host answered → the tier is ``healthy``; a
5xx is surfaced as ``http_5xx`` → ``down``; a connect/timeout error is
``down``. No FMP/API key is used and no data endpoint is hit, so the strip can
refresh on every cache-miss without consuming quota.

Registration is wired into the FastAPI lifespan (see
:mod:`.widget_backend._app`) so it runs only when the real server boots. A bare
``TestClient(app)`` (used throughout the unit suite, without a ``with`` block)
does **not** run lifespan, so the registry stays empty there and
``provider_health`` returns an instant "unknown" — keeping unit tests hermetic
(no network, sub-second).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx

from openbb_portfolio_intel.providers.probe import Prober, register_prober
from openbb_portfolio_intel.providers.registry import (
    TRACK_A_DEFAULT,
    TRACK_B_DEFAULT,
)

logger = logging.getLogger(__name__)


# Public base URLs used purely for a liveness ping. These are NOT data
# endpoints — no API key, no quota. One entry per distinct tier across both
# tracks. Kept in sync with the tier lists in ``registry.py``; the
# ``test_base_url_map_covers_all_track_tiers`` guard fails if a tier is added
# to a track without a matching probe URL here.
BASE_URL_FOR_TIER: dict[str, str] = {
    "fmp_cached": "https://financialmodelingprep.com",
    "fmp": "https://financialmodelingprep.com",
    "cboe": "https://www.cboe.com",
    "sec": "https://www.sec.gov",
    "yfinance": "https://query1.finance.yahoo.com",
    "yfinance-snapshot": "https://query1.finance.yahoo.com",
}


# Per-probe socket timeout. ``probe_tier`` also wraps each probe in its own 2s
# asyncio timeout, but bounding the socket keeps a slow TLS handshake from
# eating the whole per-tier budget.
_PROBE_HTTP_TIMEOUT_S: float = 1.5

# The 8 tier probes for one ``provider_health`` render fire CONCURRENTLY. With a
# fresh ``httpx.AsyncClient`` per probe, 8 simultaneous cold TLS handshakes on
# the single event loop measured ~2.4s and tripped the per-tier 2s timeout — the
# strip then showed every tier ``timeout`` (that was #1956's live symptom even
# after probers were registered). A single SHARED, connection-pooled client
# cuts the same concurrent cold burst to ~0.4s (all healthy) and warm re-probes
# to ~0.1s, because fmp_cached+fmp reuse one connection to financialmodelingprep
# and keepalive connections survive across the 60s cache-miss refreshes. Held
# in a 1-slot dict (not a bare module global) so mutation needs no ``global``.
_SHARED_CLIENT: dict[str, httpx.AsyncClient | None] = {"client": None}


ClientFactory = Callable[[], AbstractAsyncContextManager[httpx.AsyncClient]]


def _get_shared_client() -> httpx.AsyncClient:
    """Lazily create (once) the pooled client used by production probers.

    Bound to the event loop on first use — that's the uvicorn loop, the same
    loop every probe runs on. Unit tests never reach this: they inject a fake
    ``client_factory``, so no network client is ever constructed.
    """
    client = _SHARED_CLIENT["client"]
    if client is None or client.is_closed:
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=20)
        client = httpx.AsyncClient(
            timeout=_PROBE_HTTP_TIMEOUT_S, follow_redirects=True, limits=limits
        )
        _SHARED_CLIENT["client"] = client
    return client


async def aclose_shared_client() -> None:
    """Close the shared client (wired into the FastAPI lifespan shutdown)."""
    client = _SHARED_CLIENT["client"]
    if client is not None and not client.is_closed:
        await client.aclose()
    _SHARED_CLIENT["client"] = None


class _SharedClientHandle(AbstractAsyncContextManager):
    """Async-context proxy that yields the shared client WITHOUT closing it.

    ``make_reachability_prober`` uses ``async with client_factory() as client``.
    For the shared production client we must not close it on exit, or its
    connection pool would be torn down after every single probe — defeating the
    pooling that keeps the concurrent cold burst under budget.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _default_client_factory() -> AbstractAsyncContextManager[httpx.AsyncClient]:
    """Production factory: hand out the pooled shared client (no per-probe
    close). Injectable ``client_factory`` on :func:`make_reachability_prober`
    overrides this in tests with a fake, keeping the suite off the network.
    """
    return _SharedClientHandle(_get_shared_client())


def make_reachability_prober(
    url: str, *, client_factory: ClientFactory = _default_client_factory
) -> Prober:
    """Build an async prober that issues an HTTP ``HEAD`` to ``url``.

    Used as a cheap, quota-free liveness check.

    Contract (consumed by :func:`probe_tier`, which times latency and
    classifies exceptions):

      * returns ``None`` on any HTTP response ``< 500`` → tier ``healthy``
        (a 4xx still means the host is *reachable* — liveness, not authz)
      * raises :class:`httpx.HTTPStatusError` on a 5xx → classified
        ``http_5xx`` → ``down``
      * raises on connect/timeout → classified ``network`` / ``timeout`` →
        ``down``

    ``client_factory`` is injectable so unit tests can supply a fake client
    and stay off the network.
    """

    async def _probe() -> None:
        async with client_factory() as client:
            resp = await client.head(url)
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"{resp.status_code} from {url}",
                    request=resp.request,
                    response=resp,
                )

    return _probe


def register_default_probers(
    *, register: Callable[[str, Prober], None] = register_prober
) -> list[str]:
    """Register a reachability prober for every tier in :data:`BASE_URL_FOR_TIER`.

    Returns the list of tier names registered (handy for tests + logging).
    Idempotent: re-registering a tier overwrites its prober. ``register`` is
    injectable so tests can capture the wiring without touching the real
    global registry.
    """
    registered: list[str] = []
    for tier, url in BASE_URL_FOR_TIER.items():
        register(tier, make_reachability_prober(url))
        registered.append(tier)
    logger.info(
        "registered %d provider-health probers: %s", len(registered), registered
    )
    return registered


def all_probeable_tiers() -> frozenset[str]:
    """Every distinct tier across both fallback tracks — the set a complete
    prober map must cover. Exposed for the drift-guard test.
    """
    return frozenset(TRACK_A_DEFAULT) | frozenset(TRACK_B_DEFAULT)
