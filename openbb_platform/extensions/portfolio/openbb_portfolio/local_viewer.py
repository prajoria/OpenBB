"""Local Workspace Viewer for the portfolio backend (#1798).

A minimal, offline-capable dashboard that renders *this* backend's own
``apps.json`` tabs and ``widgets.json`` widgets (tables today) plus a chat pane
wired to the copilot ``/query`` SSE endpoint (#1794).

It is **not** a replacement for OpenBB Workspace (whose UI is proprietary) — it
is a zero-cloud, zero-license dev-loop tool for eyeballing widgets and
exercising the local copilot proxy without pro.openbb.co.

The page is served same-origin from the FastAPI backend so it needs no CORS and
reuses the backend's already-trusted (self-signed) cert. All markup, styles and
scripts are inlined into a single ``index.html`` so the viewer works fully
offline — no external CDN.
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

# assets/ sits next to the ``openbb_portfolio`` package dir (this file's parent
# is ``openbb_portfolio/``; its parent is the extension root holding ``assets/``).
_VIEWER_HTML = (
    Path(__file__).resolve().parent.parent / "assets" / "local_viewer" / "index.html"
)


@router.get("/viewer", include_in_schema=False)
async def viewer() -> HTMLResponse:
    """Serve the self-contained local viewer page."""
    return HTMLResponse(content=_VIEWER_HTML.read_text(encoding="utf-8"))


__all__ = ["router"]
