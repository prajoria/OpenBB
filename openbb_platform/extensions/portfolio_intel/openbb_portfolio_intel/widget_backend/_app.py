"""FastAPI ``app`` instance for the widget backend (#1007).

Leaf module holding just the ``app`` singleton so both ``main.py``
(register discovery + core endpoints) and ``widgets_endpoints.py``
(register the batch endpoints for #529-#577) can decorate routes
onto it without importing each other.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

# Disable openbb's import-time ``auto_build`` BEFORE openbb is ever imported in
# this process (#1962). ``openbb/__init__.py`` calls
# ``_PackageBuilder(_this_dir).auto_build()`` at import; when the committed
# ``reference.json`` differs from the installed extensions it triggers a
# multi-minute ``openbb.build()``. That build (a) is slow on every cold boot
# and (b) calls ``signal.signal(SIGTERM)`` which raises on any non-main thread
# (the lifespan warms up on an anyio worker thread) — a delete-then-fail that
# CORRUPTS the on-disk package and makes every widget serve ``stub``. The
# committed generated package already serves the live tier calls WITHOUT a
# rebuild, so the backend disables auto-build and simply primes it. ``setdefault``
# lets an operator force ``OPENBB_AUTO_BUILD=true`` back on if they really want a
# boot-time rebuild.
_AUTO_BUILD_ENV = "OPENBB_AUTO_BUILD"


def _default_auto_build_off() -> None:
    """Default ``OPENBB_AUTO_BUILD`` to ``false`` unless an operator overrode it.

    Called once at module import (before any ``import openbb``). Idempotent and
    directly unit-testable without reloading the module.
    """
    os.environ.setdefault(_AUTO_BUILD_ENV, "false")


_default_auto_build_off()

import anyio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from starlette.datastructures import MutableHeaders  # noqa: E402

logger = logging.getLogger(__name__)

# CORS: only pro.openbb.co reaches this backend.
_ALLOWED_ORIGINS = ["https://pro.openbb.co"]

# Response header carrying the provider tier that served the request
# (e.g. ``fmp_cached`` vs ``stub``) so the local viewer can render a
# live-vs-demo badge (#1953).
_DATA_SOURCE_HEADER = "x-pi-data-source"


def _prime_openbb() -> None:
    """Import + touch ``obb.equity`` so the lazy attribute tree materializes.

    With ``OPENBB_AUTO_BUILD=false`` (set at module load, see top of file) this
    ``import openbb`` does NOT trigger a build — openbb's import-time
    ``auto_build`` is short-circuited by ``Env().AUTO_BUILD``. The committed
    generated package under ``core/openbb/package/`` already wires the live tier
    providers (``fmp_cached`` et al.), so priming is a fast, main-thread-signal-
    free import that materializes ``obb.equity`` and makes the first real request
    pay no import cost. Safe to run on the lifespan's worker thread precisely
    because no ``signal.signal`` call happens (no build).
    """
    from openbb import obb  # pylint: disable=import-outside-toplevel

    _ = obb.equity


def _default_openbb_builder() -> None:
    """Prime the generated ``openbb`` package (the real warmup work).

    No build happens: the committed package is functional and ``auto_build`` is
    disabled (#1962). This just imports ``obb`` and touches ``obb.equity`` so the
    first request finds a materialized, live-wired package instead of paying the
    import cost mid-request (which used to exhaust the ChainedFetcher and serve
    ``stub``). Isolated from :func:`_warm_openbb` so unit tests can inject a fake
    builder.
    """
    _prime_openbb()


def _warm_openbb(builder: Callable[[], None] | None = None) -> None:
    """Prime the generated ``openbb`` package before serving (#1957, #1962).

    A cold backend whose generated package under ``core/openbb/package/`` is not
    yet materialized in-process pays a multi-second ``import openbb`` on the
    first live tier call inside the request handler; until it finishes the
    ChainedFetcher's tier dispatch raises, the chain exhausts, and the endpoint
    falls back to ``stub``. That is the recurring "everything says stub" symptom
    on a freshly-started backend — the Provider Health strip faithfully reports
    it. Priming at startup (before uvicorn accepts requests) guarantees the first
    real request finds a materialized, live-wired package and serves live.

    No ``openbb.build()`` runs: ``OPENBB_AUTO_BUILD`` is disabled at module load
    (see top of file) because the committed package already wires the live tier
    providers. This avoids the slow cold-boot rebuild AND the worker-thread
    ``signal.signal`` failure that used to corrupt the package and force stub
    (#1962).

    Best-effort: any failure is logged and swallowed so a prime hiccup never
    blocks server startup (widgets simply keep serving stub as before).
    Set ``PI_WIDGET_BACKEND_SKIP_WARMUP`` to skip (fast dev restarts). ``builder``
    is injectable for hermetic tests.
    """
    if os.environ.get("PI_WIDGET_BACKEND_SKIP_WARMUP"):
        logger.info("openbb warmup skipped (PI_WIDGET_BACKEND_SKIP_WARMUP set)")
        return
    try:
        (builder or _default_openbb_builder)()
        logger.info("openbb warmup complete — live-wired widgets ready to serve")
    except Exception:  # noqa: BLE001 - startup must not die on warmup
        logger.warning(
            "openbb warmup (prime) failed; live-wired widgets may serve stub until the generated package is importable",
            exc_info=True,
        )


def _register_health_probers() -> None:
    """Register the default provider-health reachability probers (#1956).

    Extracted from the lifespan so it can be unit-tested directly. Best-effort:
    a failure here must never abort server startup — the health strip simply
    keeps showing 'unknown' for any tier whose prober failed to register.
    """
    try:
        from openbb_portfolio_intel.providers.health_probers import (
            register_default_probers,
        )

        register_default_probers()
    except Exception:  # noqa: BLE001 - startup must not die on probe wiring
        logger.warning(
            "provider-health prober registration failed; strip will show 'unknown' until probers are available",
            exc_info=True,
        )


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Server lifespan — registers real provider-health probers on boot (#1956).

    This runs when uvicorn (the real server) starts. A bare ``TestClient(app)``
    used in the unit suite does NOT run lifespan, so the prober registry stays
    empty there and ``provider_health`` returns an instant 'unknown' — keeping
    unit tests hermetic (no network).

    The ``openbb`` package is warmed FIRST so the first real request finds a
    materialized package and serves live instead of stub (#1957). No
    ``openbb.build()`` runs — ``OPENBB_AUTO_BUILD`` is disabled at module load
    and the committed package already wires the live tiers; the prior
    boot-time rebuild both slowed cold starts AND corrupted the package via a
    worker-thread ``signal.signal`` failure that forced stub (#1962). Priming is
    offloaded via ``anyio.to_thread`` to keep the event loop responsive during
    the import.
    """
    await anyio.to_thread.run_sync(_warm_openbb)
    _register_health_probers()
    try:
        yield
    finally:
        background_tasks = set(getattr(_app.state, "background_tasks", set()))
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        _app.state.background_tasks.clear()

        # Best-effort teardown of the pooled probe client so httpx doesn't warn
        # about an unclosed client at interpreter shutdown.
        try:
            from openbb_portfolio_intel.providers.health_probers import (
                aclose_shared_client,
            )

            await aclose_shared_client()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            logger.debug("provider-health probe client close failed", exc_info=True)


app = FastAPI(
    title="OpenBB Portfolio Intelligence — Workspace backend",
    description=(
        "Custom-backend widgets for the OpenBB Workspace. Wraps the "
        "portfolio_intel extension's analytics modules as Workspace-"
        "consumable HTTP endpoints."
    ),
    version="0.1.0",
    lifespan=_lifespan,
)
app.state.background_tasks = set()


class _DataSourceHeaderMiddleware:
    """Mirror the per-endpoint serving tier onto ``X-PI-Data-Source`` (#1953).

    Read-only, pure-ASGI. After the wrapped app has run the endpoint, look
    up the tier the request was served by in the ``_TIER_IN_USE`` ledger —
    keyed by request path, since every retrofitted endpoint registers its
    ledger key as ``path.lstrip("/")`` (e.g. route ``/pi/equity/price-history``
    -> ledger key ``pi/equity/price-history``) — and stamp it on the response
    so the local viewer can show a *live* (``fmp_cached``) vs *demo* (``stub``)
    badge. The ledger dict is written by ``record_tier_used`` during endpoint
    execution (visible here because it is a shared module global); the value is
    best-effort under concurrent same-path requests, which is acceptable for a
    single-user local dev viewer.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Lazy import avoids an import cycle: widgets_endpoints imports ``app``
        # from this module, so importing it at module load would be circular.
        from openbb_portfolio_intel.widget_backend.widgets_endpoints import (
            _TIER_IN_USE,
        )

        key = scope.get("path", "").lstrip("/")

        async def send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                tier = _TIER_IN_USE.get(key)
                if tier:
                    headers = MutableHeaders(scope=message)
                    headers[_DATA_SOURCE_HEADER] = tier
                    # Let the (cross-origin) Workspace read the header too.
                    existing = headers.get("access-control-expose-headers")
                    exposed = (
                        _DATA_SOURCE_HEADER
                        if not existing
                        else (f"{existing}, {_DATA_SOURCE_HEADER}")
                    )
                    headers["access-control-expose-headers"] = exposed
            await send(message)

        await self.app(scope, receive, send_wrapper)


# Order matters: add the CORS middleware LAST so it wraps outermost (runs
# first on the way in / last on the way out), keeping preflight handling and
# CORS headers intact while the data-source middleware sits just inside it.
app.add_middleware(_DataSourceHeaderMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
