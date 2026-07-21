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
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

_MANIFEST_DIR = Path(__file__).parent.resolve()

# CORS: only pro.openbb.co reaches this backend. Extend to a self-hosted
# Workspace only if you're running one; do NOT open to "*".
_ALLOWED_ORIGINS = ["https://pro.openbb.co"]


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
def xray_sector(account_id: str = "demo") -> list[dict[str, float | str]]:
    """X-Ray sector-weight rows for ``account_id``.

    ``chart`` widget with ``raw: true`` → Workspace renders the returned
    records list as a chart per the manifest's chart config. For the
    demo account we return a deterministic 3-sector shape so Workspace
    always has something to draw even without a paper account attached.
    """
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id required")

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
def whatif(symbol: str = "AAPL", delta_shares: str = "100") -> str:
    """Markdown widget — human-readable What-If diff summary.

    Wraps ``analytics.whatif`` in a text response so Workspace's
    ``markdown`` widget renders it directly. The full structured diff
    (from #558) belongs to a separate ``table`` widget; this one is
    the quick-look card.
    """
    try:
        delta = int(delta_shares)
    except ValueError:
        return f"**What-If (invalid input)**\n\n`delta_shares={delta_shares!r}` is not an integer."

    # NOTE: Full wiring calls analytics.whatif.diff(symbol=symbol,
    # delta_shares=delta, positions=..., prices=...). That needs a
    # positions store + a price fetcher — wired in a follow-up PR
    # (tracked separately). This endpoint currently returns a stub
    # that matches the widget's contract shape so Workspace has
    # something to render on connect.
    action = "BUY" if delta >= 0 else "SELL"
    return (
        f"## What-If: {action} `{symbol}` × {abs(delta)}\n\n"
        f"- **Symbol:** {symbol}\n"
        f"- **Delta shares:** {delta}\n\n"
        "> ⚠ Preview stub — full analytics.whatif wiring lands with the "
        "positions-store integration follow-up. See #558."
    )


@app.get("/pi/attribution")
def attribution(
    window: str = "1Y", benchmark_symbol: str = "SPY"
) -> list[dict[str, float | str]]:
    """Brinson-Fachler attribution waterfall.

    Uses the #559 engine against a #935 golden fixture so the widget
    ALWAYS renders a valid waterfall shape on connect, even without a
    live portfolio + benchmark constituent-history feed. Real wiring
    against a live book is a follow-up.
    """
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
    waterfall = build_from_dataframe(
        df, window=window, benchmark_symbol=benchmark_symbol
    )
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
