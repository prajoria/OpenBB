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


def test_viewer_help_route_returns_same_origin_html_shell():
    """GET /viewer/help returns the same SPA shell for help-route dispatch."""
    resp = _client().get("/viewer/help?metric=pe_ttm")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert body.lstrip().lower().startswith("<!doctype html")
    assert "function metricHelpPageHtml" in body
    assert 'pathname !== "/viewer/help"' in body
    assert (
        'new URLSearchParams((window.location && window.location.search) || "")' in body
    )
    assert "bugcontext.com/loader.js" not in body
    assert "Bug Context feedback widget" not in body


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
    """Offline-first: the viewer must never execute external resources."""
    import re  # noqa: PLC0415

    body = _client().get("/viewer").text
    assert "<script" in body  # it has inline JS
    fetched = set(
        re.findall(
            r"""(?:src|href)\s*=\s*["']https?://([a-z0-9.\-]+)""", body, re.IGNORECASE
        )
    )
    assert not fetched, (
        "unexpected external src/href hosts in viewer shell: " f"{sorted(fetched)}"
    )
    assert "https://cdn" not in body.lower()


def test_viewer_renders_chart_markdown_metric_types():
    """#1805: chart/markdown/metric renderers exist and the old placeholder
    is gone. If any renderer disappears those widget types silently revert to
    the "not supported" state that #1805 removed.
    """
    body = _client().get("/viewer").text
    for fn in (
        "function renderMarkdown",
        "function renderMetric",
        "function renderChart",
        "function mdToHtml",
        "function inferChartModel",
        "function svgForChart",
        "function metricModel",
    ):
        assert fn in body, f"viewer is missing renderer {fn!r}"
    assert "is not supported in the local viewer yet" not in body


def test_viewer_has_multi_app_switcher():
    """#1805 + sidebar refactor: the viewer must expose an app switcher and no
    longer hard-code apps[0]. The switcher moved from a ``<select
    id="app-select">`` to a sidebar of ``data-app`` buttons rendered by
    ``sidebarAppsHtml`` / ``renderSidebar`` and wired through ``selectApp``.
    """
    body = _client().get("/viewer").text
    assert "function selectApp" in body
    assert "function sidebarAppsHtml" in body
    assert "data-app=" in body
    assert "APP = Array.isArray(apps) ? apps[0]" not in body


def test_viewer_preserves_xss_guards():
    """#1805: the DOM-XSS discipline (escapeHtml everywhere, textContent in
    chat) must survive the renderer additions.
    """
    body = _client().get("/viewer").text
    assert "function escapeHtml" in body
    # markdown renderer must route through mdToHtml (which escapes first)
    assert "div.innerHTML = mdToHtml(" in body
    # javascript: link scheme must be rejected in markdown links
    assert "https?:\\/\\/" in body


def test_viewer_omits_remote_feedback_code():
    """Remote scripts must not receive same-origin access to portfolio data."""
    body = _client().get("/viewer").text
    assert "bugcontext.com/loader.js" not in body
    assert "Bug Context feedback widget" not in body


def test_viewer_help_route_omits_bugcontext_feedback_widget():
    """#1984: the help route must not include or fetch the external loader."""
    body = _client().get("/viewer/help?metric=market_cap").text
    assert "bugcontext.com/loader.js" not in body
    assert "Bug Context feedback widget" not in body
