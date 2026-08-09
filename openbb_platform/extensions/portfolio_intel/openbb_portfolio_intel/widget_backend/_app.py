"""FastAPI ``app`` instance for the widget backend (#1007).

Leaf module holding just the ``app`` singleton so both ``main.py``
(register discovery + core endpoints) and ``widgets_endpoints.py``
(register the batch endpoints for #529-#577) can decorate routes
onto it without importing each other.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import anyio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import MutableHeaders

logger = logging.getLogger(__name__)

# CORS: only pro.openbb.co reaches this backend.
_ALLOWED_ORIGINS = ["https://pro.openbb.co"]

# Response header carrying the provider tier that served the request
# (e.g. ``fmp_cached`` vs ``stub``) so the local viewer can render a
# live-vs-demo badge (#1953).
_DATA_SOURCE_HEADER = "x-pi-data-source"


def _default_openbb_builder() -> None:
    """Build + prime the generated ``openbb`` package (the real warmup work).

    ``openbb.build()`` regenerates ``core/openbb/package/`` on disk;
    touching ``obb.equity`` then forces the lazy attribute tree to
    materialize so the first request pays no import cost. Isolated from
    :func:`_warm_openbb` so unit tests can inject a fake builder.
    """
    import openbb  # pylint: disable=import-outside-toplevel

    openbb.build()
    from openbb import obb  # pylint: disable=import-outside-toplevel

    _ = obb.equity


def _warm_openbb(builder: Callable[[], None] | None = None) -> None:
    """Build/prime the generated ``openbb`` package before serving (#1957).

    A cold backend whose generated package under ``core/openbb/package/`` is
    not yet built fails *every* live tier call inside the request handler:
    ``from openbb import obb`` triggers a multi-second ``openbb.build()`` the
    first time, and until it finishes the ChainedFetcher's tier dispatch
    raises, the chain exhausts, and the endpoint falls back to ``stub``. That
    is the recurring "everything says stub" symptom on a freshly-started
    backend — the Provider Health strip faithfully reports it. Building at
    startup (before uvicorn accepts requests) guarantees the first real
    request finds a built, importable package and serves live.

    Best-effort: any failure is logged and swallowed so a build hiccup never
    blocks server startup (widgets simply keep serving stub as before).
    Set ``PI_WIDGET_BACKEND_SKIP_WARMUP`` to skip (fast dev restarts when the
    package is known-built). ``builder`` is injectable for hermetic tests.
    """
    if os.environ.get("PI_WIDGET_BACKEND_SKIP_WARMUP"):
        logger.info("openbb warmup skipped (PI_WIDGET_BACKEND_SKIP_WARMUP set)")
        return
    try:
        (builder or _default_openbb_builder)()
        logger.info("openbb warmup complete — live-wired widgets ready to serve")
    except Exception:  # noqa: BLE001 - startup must not die on warmup
        logger.warning(
            "openbb warmup (build/prime) failed; live-wired widgets may serve "
            "stub until the generated package is built",
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
            "provider-health prober registration failed; strip will show "
            "'unknown' until probers are available",
            exc_info=True,
        )


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Server lifespan — registers real provider-health probers on boot (#1956).

    This runs when uvicorn (the real server) starts. A bare ``TestClient(app)``
    used in the unit suite does NOT run lifespan, so the prober registry stays
    empty there and ``provider_health`` returns an instant 'unknown' — keeping
    unit tests hermetic (no network).

    The ``openbb`` package is warmed FIRST (offloaded to a worker thread so the
    multi-second cold build doesn't block the event loop) so the first real
    request finds a built package and serves live instead of stub (#1957).
    """
    await anyio.to_thread.run_sync(_warm_openbb)
    _register_health_probers()
    try:
        yield
    finally:
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
