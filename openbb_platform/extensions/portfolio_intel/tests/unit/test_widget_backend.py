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

import importlib
import json
import os
from pathlib import Path

# The widget backend requires either PI_WIDGET_BACKEND_TOKEN or an
# explicit PI_WIDGET_BACKEND_AUTH_MODE=loopback-dev opt-in at import
# time (fails startup otherwise — that's the point). Set the dev-mode
# override BEFORE importing the module so most tests exercise the
# happy path without threading a token through every call. Individual
# tests that verify the auth wiring reload the module with a token
# set instead.
os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import pytest
from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend import (
    _shared as backend_shared,
    main as backend_main,
)
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)


def _reload_backend() -> object:
    """Reload _shared FIRST (owns auth config) then main."""
    importlib.reload(backend_shared)
    return importlib.reload(backend_main)


def _manifest() -> dict:
    return json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "openbb_portfolio_intel"
            / "widget_backend"
            / "widgets.json"
        ).read_text(encoding="utf-8")
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


# ---------------------------------------------------------------------------
# 6. Input-validation guards (reflected-content-injection prevention)
# ---------------------------------------------------------------------------


def test_xray_sector_rejects_account_id_with_metacharacters() -> None:
    """Reflected-injection guard — account_id echoes into log + marker row."""
    resp = _client.get("/pi/xray/sector?account_id=demo;rm%20-rf")
    assert resp.status_code == 400
    resp = _client.get("/pi/xray/sector?account_id=" + "A" * 200)
    assert resp.status_code == 400


def test_whatif_rejects_symbol_with_backticks_or_html() -> None:
    """Symbol echoes into markdown body; reject markdown/HTML metacharacters."""
    for bad in ("A`B", "<script>", "AAA BBB", "A" * 20, "sym[bol"):
        resp = _client.get(f"/pi/whatif?symbol={bad}&delta_shares=1")
        assert resp.status_code == 400, f"{bad!r} accepted; should be rejected"


def test_whatif_accepts_clean_ticker() -> None:
    """Allowlist covers real-world tickers (dots, dashes, digits)."""
    for good in ("BRK.B", "BF-A", "AAPL", "GOOG", "1234"):
        resp = _client.get(f"/pi/whatif?symbol={good}&delta_shares=1")
        assert resp.status_code == 200, f"{good!r} rejected; should be accepted"


def test_attribution_rejects_unknown_window() -> None:
    """Window is a fixed enum; arbitrary strings must be rejected."""
    resp = _client.get("/pi/attribution?window=' OR 1=1&benchmark_symbol=SPY")
    assert resp.status_code == 400


def test_attribution_rejects_benchmark_with_metacharacters() -> None:
    """benchmark_symbol echoes into engine kwargs + response rows."""
    resp = _client.get("/pi/attribution?window=1Y&benchmark_symbol=<script>")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 7. Authentication — bearer token gate on /pi/*
# ---------------------------------------------------------------------------


def test_pi_routes_allow_loopback_dev_mode_without_token() -> None:
    """When PI_WIDGET_BACKEND_AUTH_MODE=loopback-dev (test default), no token needed."""
    resp = _client.get("/pi/xray/sector?account_id=demo")
    assert resp.status_code == 200


def test_pi_routes_require_bearer_token_when_mode_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PI_WIDGET_BACKEND_AUTH_MODE=required + token set gates every request."""
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "required")
    monkeypatch.setenv("PI_WIDGET_BACKEND_TOKEN", "s3cret")
    reloaded = _reload_backend()
    client = TestClient(reloaded.app)

    assert client.get("/pi/xray/sector?account_id=demo").status_code == 401
    assert (
        client.get(
            "/pi/xray/sector?account_id=demo",
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/pi/xray/sector?account_id=demo",
            headers={"Authorization": "Bearer s3cret"},
        ).status_code
        == 200
    )

    # Restore for subsequent tests.
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")
    monkeypatch.delenv("PI_WIDGET_BACKEND_TOKEN", raising=False)
    _reload_backend()


def test_startup_fails_fast_when_required_mode_missing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default 'required' mode + no token = refuse to import; loud, not silent."""
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "required")
    monkeypatch.delenv("PI_WIDGET_BACKEND_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="required"):
        _reload_backend()
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")
    _reload_backend()


def test_startup_rejects_invalid_auth_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Typo in mode env var is loud rather than a silent auth-disable."""
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "on")
    with pytest.raises(RuntimeError, match="invalid"):
        _reload_backend()
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")
    _reload_backend()


def test_auth_does_not_depend_on_request_client_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: gate is env-var mode, NOT request.client.host.

    An earlier version bypassed auth when client.host looked like
    loopback — spoofable behind proxies. The gate now depends only
    on PI_WIDGET_BACKEND_AUTH_MODE, so a proxy claiming loopback
    origin cannot skip auth.
    """
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "required")
    monkeypatch.setenv("PI_WIDGET_BACKEND_TOKEN", "tok")
    reloaded = _reload_backend()
    client = TestClient(reloaded.app)
    resp = client.get(
        "/pi/xray/sector?account_id=demo",
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    assert resp.status_code == 401
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")
    monkeypatch.delenv("PI_WIDGET_BACKEND_TOKEN", raising=False)
    _reload_backend()


def test_discovery_endpoints_are_NOT_gated_by_auth() -> None:
    """Workspace fetches widgets.json/apps.json anonymously on connect."""
    assert _client.get("/widgets.json").status_code == 200
    assert _client.get("/apps.json").status_code == 200
    assert _client.get("/").status_code == 200


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
    """Bad input returns a markdown error, not a 500. Does NOT echo user value."""
    resp = _client.get("/pi/whatif?symbol=AAPL&delta_shares=abc")
    assert resp.status_code == 200
    body = resp.json()
    assert "invalid input" in body.lower()
    # Guard: never reflect the bad user value back into the markdown body.
    assert "abc" not in body


def test_attribution_returns_waterfall_rows() -> None:
    """Chart values are percent points with allocation/selection/interaction/total."""
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
    assert rows[0]["sector"] == "S0"
    assert {
        key: rows[0][key] for key in ("allocation", "selection", "interaction", "total")
    } == (
        pytest.approx(
            {
                "allocation": -0.06843181714558489,
                "selection": -0.05476594628924076,
                "interaction": 0.02539967271489473,
                "total": -0.09779809071993094,
            }
        )
    )


def test_root_endpoint_returns_info_payload() -> None:
    """Root is human-facing; must self-document the manifest URL."""
    resp = _client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("manifest") == "/widgets.json"
