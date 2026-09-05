"""Local Workspace Viewer for the portfolio backend (#1798).

A minimal, offline-capable dashboard that renders *this* backend's own
``apps.json`` tabs and ``widgets.json`` widgets (table, chart, metric, and
markdown types — #1805) plus a chat pane wired to the copilot ``/query`` SSE
endpoint (#1794).

It is **not** a replacement for OpenBB Workspace (whose UI is proprietary) — it
is a zero-cloud, zero-license dev-loop tool for eyeballing widgets and
exercising the local copilot proxy without pro.openbb.co.

The page is served same-origin from the FastAPI backend so it needs no CORS and
reuses the backend's already-trusted (self-signed) cert. All markup, styles and
scripts are inlined into a single ``index.html`` so the viewer works fully
offline — no external CDN.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

# assets/ sits next to the ``openbb_portfolio`` package dir (this file's parent
# is ``openbb_portfolio/``; its parent is the extension root holding ``assets/``).
_VIEWER_HTML = (
    Path(__file__).resolve().parent.parent / "assets" / "local_viewer" / "index.html"
)
_BUGCONTEXT_LOADER_BLOCK = (
    "\n  <!-- Bug Context feedback widget (CSP-friendly: no inline script) -->\n"
    '  <script src="https://demo.bugcontext.com/loader.js"'
    ' data-project-key="pk_3a55167dc4b50c71f7886e58f40dab43efa859b0e7459bdf"'
    " defer></script>\n"
)


def read_viewer_html(*, include_bugcontext: bool = True) -> str:
    """Return the self-contained viewer SPA HTML.

    Shared by the 6902 ``portfolio`` backend (this module) and the 6120
    ``portfolio_intel`` backend (which reuses this canonical asset rather than
    duplicating it — see #1805). The SPA is backend-neutral: it drives relative
    ``/apps.json`` + ``/widgets.json`` + ``/query`` endpoints, so whichever
    backend serves it same-origin gets its own apps rendered.
    """
    html = _VIEWER_HTML.read_text(encoding="utf-8")
    if include_bugcontext:
        return html
    return html.replace(_BUGCONTEXT_LOADER_BLOCK, "", 1)


@router.get("/viewer", include_in_schema=False)
@router.get("/viewer/help", include_in_schema=False)
async def viewer(request: Request) -> HTMLResponse:
    """Serve the self-contained local viewer page and same-origin help route."""
    include_bugcontext = request.scope.get("path") != "/viewer/help"
    return HTMLResponse(content=read_viewer_html(include_bugcontext=include_bugcontext))


__all__ = ["router", "read_viewer_html"]
