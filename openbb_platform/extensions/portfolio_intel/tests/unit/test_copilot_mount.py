"""Tests for the Copilot backend mount on the 6120/6130 widget backend (#1881).

The ``portfolio_intel`` widget backend serves the Local Workspace Viewer at
``/viewer``, whose chat pane fetches ``/agents.json`` and streams from
``/query`` same-origin. Those routes come from the sibling ``openbb_portfolio``
extension's copilot router (originally PR #1795 / #1794), which historically
was only mounted on ``openbb_portfolio/launch.py`` (the 6902 backend) — so on
the 6130 widget backend ``/agents.json`` 404'd and the chat pane was dead.

These tests assert the copilot router is now mounted here and degrades
gracefully when the asset extension (or its copilot deps) is absent.
"""

from __future__ import annotations

import os

# Same dev-mode auth opt-in as the other widget_backend tests — must be set
# before importing the backend module (fails startup otherwise, by design).
os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import pytest
from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)


def test_agents_json_is_mounted_on_widget_backend():
    """GET /agents.json on the widget backend returns the copilot descriptor.

    Skips only if the sibling ``openbb_portfolio`` copilot backend is not
    importable in this environment (the mount is best-effort by design).
    ``/agents.json`` returns a static descriptor derived from the request URL —
    it does NOT call the :4141 proxy, so this test needs no live proxy.
    """
    pytest.importorskip("openbb_portfolio.copilot")
    resp = _client.get("/agents.json")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict) and body, "agents.json must be a non-empty object"
    first = next(iter(body.values()))
    assert "name" in first, "agent descriptor must expose a 'name' (viewer reads it)"
    # The query endpoint URL must be same-origin (derived from request.base_url)
    # so the viewer's POST /query lands on this same backend.
    assert "/query" in first["endpoints"]["query"]


def test_query_route_is_registered_on_widget_backend():
    """POST /query is a registered route on this app (not a 404).

    We assert route registration rather than driving the SSE stream, because a
    real /query call needs the copilot-api proxy on :4141. Absence of the route
    would 405/404; presence means the wiring is correct.
    """
    pytest.importorskip("openbb_portfolio.copilot")
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/query" in paths, "copilot /query route is not mounted on the widget backend"
