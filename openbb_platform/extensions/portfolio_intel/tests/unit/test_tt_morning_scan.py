"""Techtrade Morning Scan tab tests (#1692 T13.1).

Ships 3 new widgets under the tt_ prefix (techtrade) in the existing
portfolio_intel widget_backend server (Option A architecture):

- **tt_segment_movers** — chart+bar top gainers/losers by segment
- **tt_scan_table** — table of filtered ticker scan results
- **tt_export_button** — markdown-link widget for CSV export

Also verifies the new "techtrade-desk" app entry exists in apps.json
with a Morning Scan tab (T1 = first techtrade tab).

Same stub-first policy every F0-F11 widget follows. TODOs cite
gh-1692 for real wiring to openbb_techtrade.engine.scan / segments.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)

_MANIFEST_DIR = (
    Path(__file__).resolve().parents[2] / "openbb_portfolio_intel" / "widget_backend"
)


def _widgets() -> dict:
    return json.loads((_MANIFEST_DIR / "widgets.json").read_text(encoding="utf-8"))


def _apps() -> list:
    apps = json.loads((_MANIFEST_DIR / "apps.json").read_text(encoding="utf-8"))
    return apps if isinstance(apps, list) else list(apps.values())


def _techtrade_app() -> dict:
    for a in _apps():
        if a.get("id") == "techtrade-desk":
            return a
    return {}


# ---------------------------------------------------------------------------
# Widget manifest declarations
# ---------------------------------------------------------------------------


def test_tt_segment_movers_widget_declared() -> None:
    w = _widgets().get("tt_segment_movers")
    assert w and w["type"] == "chart"
    assert w["endpoint"] == "tt/scan/segment-movers"


def test_tt_scan_table_widget_declared() -> None:
    w = _widgets().get("tt_scan_table")
    assert w and w["type"] == "table"
    assert w["endpoint"] == "tt/scan/table"


def test_tt_export_button_widget_declared() -> None:
    w = _widgets().get("tt_export_button")
    assert w and w["type"] == "markdown"
    assert w["endpoint"] == "tt/scan/export"


# ---------------------------------------------------------------------------
# Endpoint shape smoke
# ---------------------------------------------------------------------------


def test_segment_movers_shape() -> None:
    """Segment movers rows carry segment + gain_pct + loser/gainer bucket."""
    r = _client.get("/tt/scan/segment-movers")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert "segment" in row
        assert "change_pct" in row
        assert "bucket" in row  # "gainer" or "loser"
        assert row["bucket"] in ("gainer", "loser")


def test_scan_table_shape() -> None:
    """Scan-table rows carry symbol + score + signal fields."""
    r = _client.get("/tt/scan/table")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert "symbol" in row
        assert "score" in row
        assert "signal" in row


def test_scan_table_accepts_segment_filter() -> None:
    """/tt/scan/table?segment=Tech filters rows."""
    r = _client.get("/tt/scan/table?segment=Technology")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert row.get("segment") == "Technology"


def test_scan_table_rejects_malformed_segment() -> None:
    """Segment must be an allowlisted string; reject XSS."""
    r = _client.get("/tt/scan/table?segment=<script>")
    assert r.status_code == 400


def test_export_button_returns_markdown() -> None:
    """Export widget returns a markdown link + guidance."""
    r = _client.get("/tt/scan/export")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, str)
    assert "csv" in body.lower() or "export" in body.lower()


# ---------------------------------------------------------------------------
# techtrade-desk app entry + Morning Scan tab
# ---------------------------------------------------------------------------


def test_techtrade_desk_app_declared() -> None:
    """techtrade-desk app must exist in apps.json alongside the terminal."""
    a = _techtrade_app()
    assert a, "techtrade-desk app entry missing from apps.json"


def test_techtrade_desk_has_morning_scan_tab() -> None:
    """T1 Morning Scan tab must exist with the 3 widgets."""
    a = _techtrade_app()
    tabs = a.get("tabs", {})
    scan_tab = tabs.get("morning-scan") or tabs.get("morning_scan")
    assert scan_tab, f"Morning Scan tab missing; got tabs {list(tabs)!r}"
    ids = {slot["i"] for slot in scan_tab["layout"]}
    for wid in ("tt_segment_movers", "tt_scan_table", "tt_export_button"):
        assert wid in ids, f"tab missing {wid}; got {ids!r}"


# ---------------------------------------------------------------------------
# Route parity — Workspace 404 guard
# ---------------------------------------------------------------------------


def test_all_tt_endpoints_registered() -> None:
    routes = {r.path for r in app.routes}
    for path in ("/tt/scan/segment-movers", "/tt/scan/table", "/tt/scan/export"):
        assert path in routes, f"missing route {path}"
