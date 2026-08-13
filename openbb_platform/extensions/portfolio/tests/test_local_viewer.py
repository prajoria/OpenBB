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
    """Offline-first: the only permitted external *fetch* is the Bug Context
    feedback widget (#1980).

    The viewer inlines/vendors all its assets so it works without network
    access. The single sanctioned exception is the Bug Context feedback widget
    loader. This test blocks accidental CDN creep by asserting no other host is
    loaded via a ``src=``/``href=`` attribute. Attribution URLs that live inside
    vendored-library *strings/comments* (apache.org, tradingview.com) and the
    SVG XML *namespace identifier* (w3.org) are not network fetches, so matching
    only ``src=``/``href=`` attributes correctly ignores them.
    """
    import re  # noqa: PLC0415

    body = _client().get("/viewer").text
    assert "<script" in body  # it has inline JS
    fetched = set(
        re.findall(
            r"""(?:src|href)\s*=\s*["']https?://([a-z0-9.\-]+)""", body, re.IGNORECASE
        )
    )
    allowed = {"demo.bugcontext.com"}
    extra = fetched - allowed
    assert (
        not extra
    ), f"unexpected external src/href hosts in viewer shell: {sorted(extra)}"
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


def test_viewer_embeds_bugcontext_feedback_widget():
    """#1980: the Bug Context feedback widget loader must be wired in.

    It is added just before ``</body>`` as a CSP-friendly external ``<script>``
    (no inline code) carrying the publishable project key and ``defer``. This is
    the single sanctioned external fetch (see ``test_viewer_html_is_self_contained``).
    """
    body = _client().get("/viewer").text
    assert 'src="https://demo.bugcontext.com/loader.js"' in body
    assert (
        'data-project-key="pk_3a55167dc4b50c71f7886e58f40dab43efa859b0e7459bdf"' in body
    )
    assert "defer" in body
    # CSP-friendly: the widget must not require an inline script tag.
    marker = "Bug Context feedback widget"
    assert marker in body
    # It must sit before the closing body tag.
    assert body.index("bugcontext.com/loader.js") < body.rindex("</body>")
