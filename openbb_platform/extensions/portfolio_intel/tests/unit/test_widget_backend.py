"""Tests for the OpenBB Workspace backend for portfolio-intel widgets (#1007).

Discriminators:

- **Manifest schema** — every widget declares the required fields
  (``name``, ``description``, ``endpoint``, ``type``). A widget with a
  broken manifest is invisible in Workspace, so schema validation is
  the gate before shipping.
- **Manifest ↔ FastAPI parity** — every ``endpoint`` in
  ``widgets.json`` MUST resolve to an actual FastAPI route. A drift
  between the two is the classic "widget appears in Workspace but
  returns 404" bug and this test catches it at PR time.
- **CORS** — only ``https://pro.openbb.co`` is allowed. A wildcard
  ``*`` would silently open the backend to any origin.
- **Type contracts** — ``markdown`` endpoints return str, ``chart``
  with ``raw: true`` returns list-of-dicts, etc. Wrong shape = the
  widget renders blank in Workspace with no error indicator.
- **Loud empties on demo path** — the demo account_id returns real-
  shaped rows so Workspace always has something to draw; a live
  account with no positions returns a single marker row rather than
  an empty list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)


def _manifest() -> dict:
    return json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "openbb_portfolio_intel"
            / "widget_backend"
            / "widgets.json"
        ).read_text()
    )


# ---------------------------------------------------------------------------
# 1. Manifest schema
# ---------------------------------------------------------------------------


def test_widgets_json_is_valid_json_object() -> None:
    """widgets.json must be a JSON object keyed by widget id."""
    m = _manifest()
    assert isinstance(m, dict)
    assert m, "widgets.json is empty — Workspace would show no widgets"


@pytest.mark.parametrize("wid", list(_manifest().keys()))
def test_every_widget_has_required_manifest_fields(wid: str) -> None:
    """Missing name/description/endpoint/type = the widget is unrenderable."""
    w = _manifest()[wid]
    for field in ("name", "description", "endpoint", "type"):
        assert w.get(field), f"widget {wid!r} missing required field {field!r}"


@pytest.mark.parametrize("wid", list(_manifest().keys()))
def test_every_widget_has_gridData_dimensions(wid: str) -> None:
    """Workspace requires gridData for layout; missing = widget can't be placed."""
    w = _manifest()[wid]
    grid = w.get("gridData")
    assert grid, f"{wid}: missing gridData"
    assert isinstance(grid.get("w"), int) and grid["w"] > 0, f"{wid}: gridData.w"
    assert isinstance(grid.get("h"), int) and grid["h"] > 0, f"{wid}: gridData.h"


def test_widget_types_are_known_values() -> None:
    """Sanity check — reject typos in the type field."""
    known = {
        "markdown",
        "chart",
        "chart-highcharts",
        "table",
        "metric",
        "html",
        "pdf",
        "note",
    }
    for wid, w in _manifest().items():
        assert (
            w["type"] in known
        ), f"{wid}: unknown type {w['type']!r}; expected one of {sorted(known)}"


# ---------------------------------------------------------------------------
# 2. Manifest ↔ FastAPI route parity — THE anti-drift discriminator
# ---------------------------------------------------------------------------


def test_every_manifest_endpoint_maps_to_a_registered_route() -> None:
    """Any widget whose endpoint isn't wired in FastAPI would 404 in Workspace."""
    routes = {r.path for r in app.routes}
    for wid, w in _manifest().items():
        # Manifest endpoints are relative ("pi/xray/sector"); FastAPI
        # routes are absolute ("/pi/xray/sector"). Normalize.
        ep = w["endpoint"]
        candidate = ep if ep.startswith("/") else f"/{ep}"
        assert candidate in routes, (
            f"widget {wid!r} declares endpoint {ep!r} but no FastAPI "
            f"route is registered at {candidate!r}. Available: "
            f"{sorted(routes)}"
        )


# ---------------------------------------------------------------------------
# 3. Discovery endpoints (Workspace hits these on connect)
# ---------------------------------------------------------------------------


def test_widgets_json_endpoint_serves_the_manifest() -> None:
    """Workspace fetches /widgets.json on connect; content must match the file."""
    resp = _client.get("/widgets.json")
    assert resp.status_code == 200
    assert resp.json() == _manifest()


def test_apps_json_endpoint_serves_valid_app_list() -> None:
    """apps.json must be a list of apps, each with tabs+layout wiring widget ids."""
    resp = _client.get("/apps.json")
    assert resp.status_code == 200
    apps = resp.json()
    assert isinstance(apps, list) and apps, "apps.json must be a non-empty list"
    widget_ids = set(_manifest().keys())
    for app_def in apps:
        for tab in app_def.get("tabs", {}).values():
            for slot in tab.get("layout", []):
                assert slot["i"] in widget_ids, (
                    f"apps.json layout references unknown widget id {slot['i']!r}; "
                    f"known: {sorted(widget_ids)}"
                )


# ---------------------------------------------------------------------------
# 4. CORS — only pro.openbb.co, never wildcard
# ---------------------------------------------------------------------------


def test_cors_allows_pro_openbb_co() -> None:
    """Preflight from pro.openbb.co must succeed."""
    resp = _client.options(
        "/widgets.json",
        headers={
            "Origin": "https://pro.openbb.co",
            "Access-Control-Request-Method": "GET",
        },
    )
    # FastAPI/starlette returns 200 on successful preflight.
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == "https://pro.openbb.co"


def test_cors_does_NOT_use_wildcard() -> None:
    """A wildcard origin would silently open the backend to any site."""
    from openbb_portfolio_intel.widget_backend.main import _ALLOWED_ORIGINS

    assert (
        "*" not in _ALLOWED_ORIGINS
    ), "CORS is wildcarded — Workspace backends must NOT be open to any origin"


# ---------------------------------------------------------------------------
# 5. Widget endpoints — type contract smoke tests
# ---------------------------------------------------------------------------


def test_xray_sector_demo_returns_non_empty_records_list() -> None:
    """Chart with raw=true must return list-of-dicts (loud empty guard)."""
    resp = _client.get("/pi/xray/sector?account_id=demo")
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list) and rows, "demo path must never return []"
    for r in rows:
        assert "sector" in r and "weight" in r


def test_xray_sector_non_demo_returns_marker_row_not_empty_list() -> None:
    """Account-resolver-not-wired path returns a marker row, not silent [] ."""
    resp = _client.get("/pi/xray/sector?account_id=NOT_WIRED_YET")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "must NOT return empty list — Workspace would render blank"


def test_xray_sector_rejects_empty_account_id() -> None:
    """Empty account_id is a caller bug — reject rather than silently demo."""
    resp = _client.get("/pi/xray/sector?account_id=")
    assert resp.status_code == 400


def test_whatif_markdown_returns_string() -> None:
    """Markdown widget contract: response body must be a str."""
    resp = _client.get("/pi/whatif?symbol=AAPL&delta_shares=100")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, str)
    assert "AAPL" in body and "BUY" in body


def test_whatif_sell_side_labeled_correctly() -> None:
    """Negative delta → SELL label; sign handling is the load-bearing bit."""
    resp = _client.get("/pi/whatif?symbol=NVDA&delta_shares=-50")
    assert resp.status_code == 200
    assert "SELL" in resp.json()


def test_whatif_invalid_delta_shares_handled_gracefully() -> None:
    """Bad input returns a markdown error, not a 500."""
    resp = _client.get("/pi/whatif?symbol=AAPL&delta_shares=abc")
    assert resp.status_code == 200
    assert "invalid input" in resp.json().lower()


def test_attribution_returns_waterfall_rows() -> None:
    """Chart with raw=true — records with allocation/selection/interaction/total."""
    resp = _client.get("/pi/attribution?window=1Y&benchmark_symbol=SPY")
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list) and rows
    for r in rows:
        for field in ("sector", "allocation", "selection", "interaction", "total"):
            assert field in r, f"attribution row missing {field}"
        # per-row invariant: total == alloc + selc + inter
        assert (
            abs(r["total"] - (r["allocation"] + r["selection"] + r["interaction"]))
            < 1e-12
        )


def test_root_endpoint_returns_info_payload() -> None:
    """Root is human-facing; must self-document the manifest URL."""
    resp = _client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("manifest") == "/widgets.json"
