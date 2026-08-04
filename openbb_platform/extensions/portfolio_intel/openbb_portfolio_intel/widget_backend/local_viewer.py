"""Serve the Local Workspace Viewer on the portfolio_intel (6120) backend (#1805).

The viewer SPA is a single self-contained ``index.html`` owned by the sibling
``openbb_portfolio`` extension (``assets/local_viewer/index.html``). Both
backends are part of the same local dev loop, so rather than duplicating the
asset we reuse the canonical copy through a lazy import. The SPA drives relative
``/apps.json`` + ``/widgets.json`` endpoints, so when it is served same-origin
from *this* (6120) backend it renders the ``portfolio_intel`` apps — Overview,
Terminal, and Techtrade — with the chart/metric/markdown renderers added in
#1805.

Serving same-origin (rather than a cross-origin ``?backend=`` param) sidesteps
the backend's CORS lock (``https://pro.openbb.co`` only): a browser loading the
viewer from ``https://127.0.0.1:6120/viewer`` is already same-origin with the
data endpoints it calls.

If ``openbb_portfolio`` is not installed the route returns 503 with a clear
message instead of breaking backend startup — the mount is best-effort.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse

router = APIRouter()


def _load_viewer_html() -> str | None:
    """Return the shared viewer HTML, or ``None`` if the asset is unavailable."""
    try:
        from openbb_portfolio.local_viewer import (  # pylint: disable=import-outside-toplevel
            read_viewer_html,
        )
    except ImportError:
        return None
    try:
        return read_viewer_html()
    except OSError:
        return None


@router.get("/viewer", include_in_schema=False, response_model=None)
async def viewer() -> HTMLResponse | PlainTextResponse:
    """Serve the self-contained Local Workspace Viewer for the 6120 apps."""
    html = _load_viewer_html()
    if html is None:
        return PlainTextResponse(
            "Local Workspace Viewer asset unavailable: the 'openbb_portfolio' "
            "extension (which owns assets/local_viewer/index.html) is not "
            "importable in this environment. Install it to enable /viewer.",
            status_code=503,
        )
    return HTMLResponse(content=html)


__all__ = ["router"]
