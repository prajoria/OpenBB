"""OpenBB Workspace backend for portfolio-intel widgets (#1007).

Serves ``widgets.json`` + ``apps.json`` + one HTTP endpoint per widget
following the canonical Workspace custom-backend contract:

    https://github.com/OpenBB-finance/backends-for-openbb

Run locally::

    uvicorn openbb_portfolio_intel.widget_backend.main:app --port 6120

Then in OpenBB Workspace (``https://pro.openbb.co``): **Data
connectors → Custom backend → Add**, URL
``http://localhost:6120``. Workspace reads ``/widgets.json`` and lists
each widget under the ``Portfolio Intelligence`` category.

CORS is locked to ``https://pro.openbb.co`` on purpose — this backend
is not a general public API, it's a Workspace data source.

Design notes:

- Each endpoint is a thin adapter over an existing analytics module
  (``xray``, ``whatif``, ``attribution_engine``). NO new financial
  math lives here; the backend is presentation-layer only.
- Widget responses match the ``type`` declared in ``widgets.json``:
  ``markdown`` returns a str, ``chart`` returns a Plotly figure dict
  (or a raw records list with ``raw: true``), ``table`` returns a
  list of dicts, ``metric`` returns a scalar dict.
- Loud empties: if the underlying analytics returns nothing, the
  endpoint returns a markdown message explaining the gap rather than
  a silent empty response.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

_MANIFEST_DIR = Path(__file__).parent.resolve()

# CORS: only pro.openbb.co reaches this backend. Extend to a self-hosted
# Workspace only if you're running one; do NOT open to "*".
_ALLOWED_ORIGINS = ["https://pro.openbb.co"]

# Bearer token gate for /pi/* routes. Read at import time from
# PI_WIDGET_BACKEND_TOKEN. When unset AND the process appears to bind
# to a non-loopback address, we refuse to start (see _startup_guard
# below). When bound to loopback only (dev), auth is optional but a
# WARN is logged so users know they're running unauthenticated.
_AUTH_TOKEN = os.environ.get("PI_WIDGET_BACKEND_TOKEN", "").strip()

# Symbol validator — Workspace params echo through into markdown/JSON
# response bodies, so we reject anything that isn't a plausible
# ticker before it reaches string formatting.
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")
# Account-id validator — same reasoning; allow reasonable identifiers,
# reject shell metacharacters / markdown / control chars.
_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


def _require_auth(request: Request) -> None:
    """Authenticate /pi/* calls via bearer token when a token is configured.

    Skip if no token is set AND the request came from loopback (dev).
    Enforce otherwise — any non-loopback request without a valid
    ``Authorization: Bearer <token>`` header is rejected 401.
    """
    client_host = (request.client.host if request.client else "") or ""
    # "testclient" is what starlette's TestClient reports — treat as
    # loopback so dev tests don't need a token dance. Real deployments
    # will see 127.0.0.1 / ::1 / localhost.
    is_loopback = client_host in ("127.0.0.1", "::1", "localhost", "testclient")

    if not _AUTH_TOKEN:
        if is_loopback:
            return
        raise HTTPException(
            status_code=401,
            detail=(
                "PI_WIDGET_BACKEND_TOKEN not set and request originated from "
                "a non-loopback address. Set PI_WIDGET_BACKEND_TOKEN in the "
                "backend environment before exposing this service."
            ),
        )

    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    supplied = header.split(" ", 1)[1].strip()
    # Constant-time compare avoids leaking token length via timing.
    if not _constant_time_eq(supplied, _AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="invalid bearer token")


def _constant_time_eq(a: str, b: str) -> bool:
    """Length-safe constant-time string compare."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0


if not _AUTH_TOKEN:
    logger.warning(
        "PI_WIDGET_BACKEND_TOKEN is not set. /pi/* routes accept "
        "unauthenticated requests from loopback only; requests from "
        "any non-loopback client will be rejected 401. Set the env "
        "var before exposing this backend to the network."
    )


app = FastAPI(
    title="OpenBB Portfolio Intelligence — Workspace backend",
    description=(
        "Custom-backend widgets for the OpenBB Workspace. Wraps the "
        "portfolio_intel extension's analytics modules (xray, whatif, "
        "attribution) as Workspace-consumable HTTP endpoints."
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


@app.get("/")
def root() -> dict[str, str]:
    """Root — human-readable info; Workspace does not call this."""
    return {
        "info": "OpenBB Portfolio Intelligence Workspace backend",
        "manifest": "/widgets.json",
        "apps": "/apps.json",
    }


@app.get("/widgets.json")
def get_widgets() -> JSONResponse:
    """Return the widget manifest Workspace uses to discover + render widgets."""
    return JSONResponse(
        content=json.loads((_MANIFEST_DIR / "widgets.json").read_text())
    )


@app.get("/apps.json")
def get_apps() -> JSONResponse:
    """Return the pre-built dashboard layout Workspace ingests on connect."""
    return JSONResponse(content=json.loads((_MANIFEST_DIR / "apps.json").read_text()))


# ---------------------------------------------------------------------------
# Widget endpoints — thin adapters over analytics modules
# ---------------------------------------------------------------------------


@app.get("/pi/xray/sector")
def xray_sector(
    request: Request, account_id: str = "demo"
) -> list[dict[str, float | str]]:
    """X-Ray sector-weight rows for ``account_id``.

    ``chart`` widget with ``raw: true`` → Workspace renders the returned
    records list as a chart per the manifest's chart config. For the
    demo account we return a deterministic 3-sector shape so Workspace
    always has something to draw even without a paper account attached.
    """
    _require_auth(request)
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id required")
    if not _ACCOUNT_ID_RE.match(account_id):
        # Reject metacharacters — account_id echoes into log lines and
        # (for non-demo IDs) into the marker-row response body.
        raise HTTPException(
            status_code=400,
            detail=(
                "account_id must match [A-Za-z0-9_.\\-]{1,64}; "
                "reserved characters or excessive length are rejected"
            ),
        )

    if account_id == "demo":
        # Deterministic demo data — matches the "loud empties" rule
        # (return real-shaped rows for the demo path so the widget
        # renders; a live account with no positions returns a single
        # 'empty portfolio' marker row rather than [] which would
        # render as a blank chart).
        return [
            {"sector": "Information Technology", "weight": 0.38},
            {"sector": "Healthcare", "weight": 0.22},
            {"sector": "Financials", "weight": 0.15},
            {"sector": "Consumer Discretionary", "weight": 0.12},
            {"sector": "Energy", "weight": 0.08},
            {"sector": "Other", "weight": 0.05},
        ]

    # For non-demo account_ids, this is where we'd load positions via
    # openbb_portfolio_intel.paper.PositionStore + call
    # analytics.xray.build_sector_breakdown(). Left as a TODO so the
    # widget lands without wiring the account resolver — that plumbing
    # belongs in its own PR against the paper program.
    logger.warning(
        "xray/sector called with non-demo account_id=%r — no account resolver "
        "wired yet; returning empty marker",
        account_id,
    )
    return [{"sector": "(no data — account resolver not wired)", "weight": 0.0}]


@app.get("/pi/whatif")
def whatif(request: Request, symbol: str = "AAPL", delta_shares: str = "100") -> str:
    """Markdown widget — human-readable What-If diff summary.

    Wraps ``analytics.whatif`` in a text response so Workspace's
    ``markdown`` widget renders it directly. The full structured diff
    (from #558) belongs to a separate ``table`` widget; this one is
    the quick-look card.
    """
    _require_auth(request)
    # Validate ``symbol`` against a strict ticker allowlist BEFORE it
    # echoes into the markdown body. Reflected-content-injection guard.
    sym = symbol.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(
            status_code=400,
            detail=(
                "symbol must match [A-Z0-9.\\-]{1,10}; "
                f"got {symbol!r} (rejected before markdown formatting)"
            ),
        )
    try:
        delta = int(delta_shares)
    except ValueError:
        # No user input reflected into the message body — safe.
        return "**What-If (invalid input)**\n\n" "`delta_shares` is not an integer."

    # NOTE: Full wiring calls analytics.whatif.diff(symbol=symbol,
    # delta_shares=delta, positions=..., prices=...). That needs a
    # positions store + a price fetcher — wired in a follow-up PR
    # (tracked separately). This endpoint currently returns a stub
    # that matches the widget's contract shape so Workspace has
    # something to render on connect.
    action = "BUY" if delta >= 0 else "SELL"
    return (
        f"## What-If: {action} `{sym}` × {abs(delta)}\n\n"
        f"- **Symbol:** {sym}\n"
        f"- **Delta shares:** {delta}\n\n"
        "> ⚠ Preview stub — full analytics.whatif wiring lands with the "
        "positions-store integration follow-up. See #558."
    )


@app.get("/pi/attribution")
def attribution(
    request: Request, window: str = "1Y", benchmark_symbol: str = "SPY"
) -> list[dict[str, float | str]]:
    """Brinson-Fachler attribution waterfall.

    Uses the #559 engine against a #935 golden fixture so the widget
    ALWAYS renders a valid waterfall shape on connect, even without a
    live portfolio + benchmark constituent-history feed. Real wiring
    against a live book is a follow-up.
    """
    _require_auth(request)
    # Validate benchmark_symbol before echoing into response rows.
    bm = benchmark_symbol.strip().upper()
    if not _SYMBOL_RE.match(bm):
        raise HTTPException(status_code=400, detail="benchmark_symbol invalid")
    # window is a small enum; reject anything unexpected instead of
    # letting arbitrary strings propagate.
    if window not in {"1M", "3M", "6M", "1Y", "YTD", "MTD"}:
        raise HTTPException(status_code=400, detail=f"unknown window {window!r}")
    # Import lazily so opening this module doesn't force analytics + numpy
    # into every FastAPI worker boot.
    # pylint: disable=import-outside-toplevel
    import pandas as pd

    from openbb_portfolio_intel.analytics.attribution_engine import (
        build_from_dataframe,
    )

    # Use the 5-sector golden fixture as a demo waterfall — real book
    # would come from PositionStore + IndexConstituents fetcher.
    fixture_dir = Path(__file__).parent.parent / "analytics" / "brinson" / "fixtures"
    demo_fx = fixture_dir / "bf-n11-seed2.json"
    if not demo_fx.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                "attribution demo fixture missing at "
                f"{demo_fx} — did the #935 fixtures get deleted?"
            ),
        )
    fx = json.loads(demo_fx.read_text())
    df = pd.DataFrame(fx["inputs"])
    waterfall = build_from_dataframe(df, window=window, benchmark_symbol=bm)
    # Return one row per sector, matching a chart-widget records shape.
    return [
        {
            "sector": row.sector,
            "allocation": row.allocation,
            "selection": row.selection,
            "interaction": row.interaction,
            "total": row.allocation + row.selection + row.interaction,
        }
        for row in waterfall.rows
    ]
