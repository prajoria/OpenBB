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

CORS is locked to ``https://pro.openbb.co`` on purpose. Auth policy is
in :mod:`._shared` (bearer token via ``PI_WIDGET_BACKEND_TOKEN``, or
explicit ``loopback-dev`` opt-out).

Design notes:

- Each endpoint is a thin adapter over an existing analytics module.
  NO new financial math lives here.
- Widget responses match the ``type`` declared in ``widgets.json``.
- Loud empties: never return silent empty responses.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from openbb_portfolio_intel.widget_backend._app import _ALLOWED_ORIGINS, app
from openbb_portfolio_intel.widget_backend._shared import (
    _SYMBOL_RE,
    require_auth,
    validate_account,
)

logger = logging.getLogger(__name__)

_MANIFEST_DIR = Path(__file__).parent.resolve()


# ---------------------------------------------------------------------------
# Discovery endpoints — Workspace fetches these on connect (unauthenticated)
# ---------------------------------------------------------------------------


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
    # Force ``charset=utf-8`` so Workspace decodes em-dashes and other
    # UTF-8 bytes in widget titles correctly (see #1632). Without this
    # the em-dashes render as ``â€"`` mojibake.
    return JSONResponse(
        content=json.loads(
            (_MANIFEST_DIR / "widgets.json").read_text(encoding="utf-8")
        ),
        media_type="application/json; charset=utf-8",
    )


@app.get("/apps.json")
def get_apps() -> JSONResponse:
    """Return the pre-built dashboard layout Workspace ingests on connect."""
    # Same charset guard as /widgets.json (see #1632).
    return JSONResponse(
        content=json.loads((_MANIFEST_DIR / "apps.json").read_text(encoding="utf-8")),
        media_type="application/json; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# Context-bar endpoints — shared by every tab in the terminal (#1638, #1639)
# ---------------------------------------------------------------------------


@app.get("/pi/context/symbol")
def context_symbol(request: Request, symbol: str = "AAPL") -> str:
    """Symbol context bar (#1638) — echoes the ticker as markdown.

    The point of a "context bar" widget is to hold + display the shared
    ``symbol`` param so Workspace can link it across tabs 1-7. The
    response is intentionally minimal (a one-line markdown badge); the
    param wiring is what matters for the persona surface.
    """
    require_auth(request)
    sym = symbol.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(
            status_code=400,
            detail=(
                "symbol must match [A-Z0-9.\\-]{1,10}; "
                f"got {symbol!r} (rejected before markdown formatting)"
            ),
        )
    return f"**Symbol:** `{sym}`  \nResearch tabs (F1-F7) share this ticker."


@app.get("/pi/context/book")
def context_book(request: Request, account_id: str = "demo") -> str:
    """Book (account) context bar (#1639) — echoes account_id as markdown.

    Companion to ``/pi/context/symbol``. Holds the shared ``account_id``
    param for portfolio tabs 8-11.
    """
    require_auth(request)
    validate_account(account_id)
    return (
        f"**Book:** `{account_id}`  \nPortfolio tabs (F8-F11) share this " f"account."
    )


# ---------------------------------------------------------------------------
# Core widget endpoints — the three shipped in the original #1008 cut
# ---------------------------------------------------------------------------


@app.get("/pi/xray/sector")
def xray_sector(
    request: Request, account_id: str = "demo"
) -> list[dict[str, float | str]]:
    """X-Ray sector-weight rows for ``account_id``."""
    require_auth(request)
    validate_account(account_id)

    if account_id == "demo":
        return [
            {"sector": "Information Technology", "weight": 0.38},
            {"sector": "Healthcare", "weight": 0.22},
            {"sector": "Financials", "weight": 0.15},
            {"sector": "Consumer Discretionary", "weight": 0.12},
            {"sector": "Energy", "weight": 0.08},
            {"sector": "Other", "weight": 0.05},
        ]

    logger.warning("xray/sector: account resolver not wired for %r", account_id)
    return [{"sector": "(no data — account resolver not wired)", "weight": 0.0}]


@app.get("/pi/whatif")
def whatif(request: Request, symbol: str = "AAPL", delta_shares: str = "100") -> str:
    """Markdown widget — human-readable What-If diff summary."""
    require_auth(request)
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
        return "**What-If (invalid input)**\n\n`delta_shares` is not an integer."

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
    """Brinson-Fachler attribution waterfall."""
    require_auth(request)
    bm = benchmark_symbol.strip().upper()
    if not _SYMBOL_RE.match(bm):
        raise HTTPException(status_code=400, detail="benchmark_symbol invalid")
    if window not in {"1M", "3M", "6M", "1Y", "YTD", "MTD"}:
        raise HTTPException(status_code=400, detail=f"unknown window {window!r}")
    # pylint: disable=import-outside-toplevel
    import pandas as pd

    from openbb_portfolio_intel.analytics.attribution_engine import (
        build_from_dataframe,
    )

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


# Batch of P1/P2/P3 widget endpoints (#529-#577) — imported for side
# effects; every function in that module registers a route on `app`.
# Import at bottom so `app` is already defined.
# pylint: disable=wrong-import-position,unused-import
# Live provider tier-call registrations (#1898 onward) — imported for side
# effects; registering ``(family, "fmp_cached")`` calls makes the provider
# chain serve live data for wired widgets, falling back to each endpoint's
# stub on exhaustion. Import after widgets_endpoints so the families exist.
from openbb_portfolio_intel.widget_backend import (  # noqa: E402, F401  # noqa: E402, F401
    tier_calls as _tier_calls,
    widgets_endpoints as _widgets_endpoints,
)

# Local Workspace Viewer (#1805): serve the self-contained dashboard SPA at
# ``/viewer`` same-origin so the 6120 apps (Overview / Terminal / Techtrade)
# render locally without pro.openbb.co. The asset is owned by the sibling
# ``openbb_portfolio`` extension and reused via a lazy import (graceful 503 if
# absent).
from openbb_portfolio_intel.widget_backend.local_viewer import (  # noqa: E402
    router as _local_viewer_router,
)

app.include_router(_local_viewer_router)

# ---------------------------------------------------------------------------
# Back-compat: existing tests reach into private attrs. Re-export.
# ---------------------------------------------------------------------------
from openbb_portfolio_intel.widget_backend._shared import (  # noqa: E402
    _ACCOUNT_ID_RE,
    _AUTH_MODE,
    _AUTH_TOKEN,
)

# ``require_auth`` is also exposed as the legacy underscored name.
_require_auth = require_auth

__all__ = [
    "app",
    "_ALLOWED_ORIGINS",
    "_ACCOUNT_ID_RE",
    "_AUTH_MODE",
    "_AUTH_TOKEN",
    "_SYMBOL_RE",
    "_require_auth",
]
