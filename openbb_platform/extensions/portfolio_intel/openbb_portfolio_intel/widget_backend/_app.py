"""FastAPI ``app`` instance for the widget backend (#1007).

Leaf module holding just the ``app`` singleton so both ``main.py``
(register discovery + core endpoints) and ``widgets_endpoints.py``
(register the batch endpoints for #529-#577) can decorate routes
onto it without importing each other.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import MutableHeaders

# CORS: only pro.openbb.co reaches this backend.
_ALLOWED_ORIGINS = ["https://pro.openbb.co"]

# Response header carrying the provider tier that served the request
# (e.g. ``fmp_cached`` vs ``stub``) so the local viewer can render a
# live-vs-demo badge (#1953).
_DATA_SOURCE_HEADER = "x-pi-data-source"


app = FastAPI(
    title="OpenBB Portfolio Intelligence — Workspace backend",
    description=(
        "Custom-backend widgets for the OpenBB Workspace. Wraps the "
        "portfolio_intel extension's analytics modules as Workspace-"
        "consumable HTTP endpoints."
    ),
    version="0.1.0",
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
