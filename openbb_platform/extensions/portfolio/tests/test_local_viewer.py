"""Tests for the Local Workspace Viewer route (#1798, #1799).

Contract-level tests only: the route must serve a self-contained HTML shell
that references the backend contract endpoints the client-side JS drives
(``/apps.json``, ``/widgets.json``, ``/agents.json``, ``/query``). Browser
behaviour (tab/table/chat rendering) is smoke-verified against the live
backend in the dev-cycle harness step, not here.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openbb_portfolio.local_viewer import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_viewer_route_returns_html():
    """GET /viewer returns 200 with an HTML content type."""
    resp = _client().get("/viewer")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert resp.text.lstrip().lower().startswith("<!doctype html")


def test_viewer_html_references_contract_endpoints():
    """The shell must wire every backend endpoint the JS depends on.

    If any of these markers disappears the client can no longer load apps,
    widgets, the agent descriptor, or stream chat — so they are load-bearing
    contract markers, not decoration.
    """
    body = _client().get("/viewer").text
    for marker in ("/apps.json", "/widgets.json", "/agents.json", "/query"):
        assert marker in body, f"viewer shell is missing endpoint marker {marker!r}"


def test_viewer_html_is_self_contained():
    """No external script/style CDNs — the viewer must work fully offline."""
    body = _client().get("/viewer").text.lower()
    assert "<script" in body  # it has inline JS
    # No external network dependencies (would break the offline promise).
    assert "http://" not in body.replace("http://127.0.0.1", "").replace(
        "http://localhost", ""
    )
    assert "https://cdn" not in body
    assert "src=\"http" not in body
