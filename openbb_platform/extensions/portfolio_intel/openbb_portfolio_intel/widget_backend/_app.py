"""FastAPI ``app`` instance for the widget backend (#1007).

Leaf module holding just the ``app`` singleton so both ``main.py``
(register discovery + core endpoints) and ``widgets_endpoints.py``
(register the batch endpoints for #529-#577) can decorate routes
onto it without importing each other.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# CORS: only pro.openbb.co reaches this backend.
_ALLOWED_ORIGINS = ["https://pro.openbb.co"]


app = FastAPI(
    title="OpenBB Portfolio Intelligence — Workspace backend",
    description=(
        "Custom-backend widgets for the OpenBB Workspace. Wraps the "
        "portfolio_intel extension's analytics modules as Workspace-"
        "consumable HTTP endpoints."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
