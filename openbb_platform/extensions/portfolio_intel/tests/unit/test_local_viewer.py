"""Tests for the Local Workspace Viewer mount on the 6120 backend (#1805).

The ``portfolio_intel`` widget backend reuses the self-contained viewer SPA
owned by the sibling ``openbb_portfolio`` extension, served same-origin at
``/viewer`` so the 6120 apps (Overview / Terminal / Techtrade) render locally
without pro.openbb.co. These tests assert the mount is wired and degrades
gracefully when the asset extension is absent.
"""

from __future__ import annotations

import os

# Same dev-mode auth opt-in as the other widget_backend tests — must be set
# before importing the backend module (fails startup otherwise, by design).
os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import pytest
from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend import local_viewer
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)


def test_viewer_route_is_mounted_on_6120():
    """GET /viewer on the 6120 backend serves the shared viewer HTML.

    Skips only if the sibling ``openbb_portfolio`` asset extension is not
    installed in this environment (the mount is best-effort by design).
    """
    pytest.importorskip("openbb_portfolio")
    resp = _client.get("/viewer")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert resp.text.lstrip().lower().startswith("<!doctype html")


def test_viewer_reuses_canonical_asset_with_new_renderers():
    """The served page is the shared SPA with the #1805 renderers + app
    switcher (proves reuse of the canonical asset, not a stale copy).

    The app switcher moved from a top-bar ``<select id="app-select">`` into a
    collapsible left sidebar (``<nav id="app-nav">``, #1890); assert the new
    marker so the test tracks the current switcher location.
    """
    pytest.importorskip("openbb_portfolio")
    body = _client.get("/viewer").text
    for marker in (
        "function renderChart",
        "function renderMarkdown",
        "function renderMetric",
        'id="app-nav"',
        "function sidebarAppsHtml",
        "/widgets.json",
        "/apps.json",
    ):
        assert marker in body, f"6120 viewer is missing {marker!r}"
    assert "is not supported in the local viewer yet" not in body


def test_viewer_degrades_to_503_when_asset_extension_absent(monkeypatch):
    """If ``openbb_portfolio`` can't be loaded, /viewer returns 503 with a
    clear message rather than 500 or a broken page.
    """
    monkeypatch.setattr(local_viewer, "_load_viewer_html", lambda: None)
    resp = _client.get("/viewer")
    assert resp.status_code == 503
    assert "openbb_portfolio" in resp.text
