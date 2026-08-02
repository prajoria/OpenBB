"""Techtrade Position Workbench tests (#1696 T13.2).

Ships 4 new tt_* widgets on a new "T2: Position Workbench" tab in the
techtrade-desk app. All stub-shaped; real wiring is per-widget TODOs.

- **tt_signal_card** (markdown) — active signal summary for a symbol
- **tt_plan_card** (markdown) — trading plan (entry, stop, target)
- **tt_order_legs** (table) — proposed order legs with side/qty/price
- **tt_simulate_result** (chart raw) — simulated P&L trajectory
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


def test_tt_signal_card_widget_declared() -> None:
    w = _widgets().get("tt_signal_card")
    assert w and w["type"] == "markdown"
    assert w["endpoint"] == "tt/position/signal-card"


def test_tt_plan_card_widget_declared() -> None:
    w = _widgets().get("tt_plan_card")
    assert w and w["type"] == "markdown"
    assert w["endpoint"] == "tt/position/plan-card"


def test_tt_order_legs_widget_declared() -> None:
    w = _widgets().get("tt_order_legs")
    assert w and w["type"] == "table"
    assert w["endpoint"] == "tt/position/order-legs"


def test_tt_simulate_result_widget_declared() -> None:
    w = _widgets().get("tt_simulate_result")
    assert w and w["type"] == "chart"
    assert w.get("raw") is True
    assert w["endpoint"] == "tt/position/simulate"


# ---------------------------------------------------------------------------
# Endpoint smoke
# ---------------------------------------------------------------------------


def test_signal_card_returns_markdown_with_symbol() -> None:
    r = _client.get("/tt/position/signal-card?symbol=NVDA")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, str) and "NVDA" in body


def test_plan_card_returns_entry_stop_target() -> None:
    r = _client.get("/tt/position/plan-card?symbol=NVDA")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, str)
    for token in ("Entry", "Stop", "Target"):
        assert token in body, f"missing {token} in plan card"


def test_order_legs_shape() -> None:
    r = _client.get("/tt/position/order-legs?symbol=NVDA")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        for f in ("side", "quantity", "price", "leg_type"):
            assert f in row, f"missing {f} in {row!r}"
        assert row["side"] in ("BUY", "SELL")


def test_simulate_result_shape() -> None:
    r = _client.get("/tt/position/simulate?symbol=NVDA")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert "day" in row
        assert "pnl" in row
        assert isinstance(row["pnl"], (int, float))


# ---------------------------------------------------------------------------
# Symbol allowlist
# ---------------------------------------------------------------------------


def test_all_position_workbench_endpoints_reject_bad_symbol() -> None:
    for path in (
        "/tt/position/signal-card",
        "/tt/position/plan-card",
        "/tt/position/order-legs",
        "/tt/position/simulate",
    ):
        r = _client.get(f"{path}?symbol=<script>")
        assert r.status_code == 400, f"{path} accepted bad symbol"


# ---------------------------------------------------------------------------
# T2: Position Workbench tab
# ---------------------------------------------------------------------------


def test_position_workbench_tab_exists() -> None:
    tabs = _techtrade_app().get("tabs", {})
    assert (
        "position-workbench" in tabs or "position_workbench" in tabs
    ), "Position Workbench tab missing from techtrade-desk"


def test_position_workbench_tab_has_all_4_widgets() -> None:
    tabs = _techtrade_app().get("tabs", {})
    tab = tabs.get("position-workbench") or tabs.get("position_workbench")
    assert tab
    ids = {slot["i"] for slot in tab["layout"]}
    for wid in (
        "tt_signal_card",
        "tt_plan_card",
        "tt_order_legs",
        "tt_simulate_result",
    ):
        assert wid in ids, f"tab missing {wid}"


# ---------------------------------------------------------------------------
# Route parity
# ---------------------------------------------------------------------------


def test_all_position_workbench_endpoints_registered() -> None:
    routes = {r.path for r in app.routes}
    for path in (
        "/tt/position/signal-card",
        "/tt/position/plan-card",
        "/tt/position/order-legs",
        "/tt/position/simulate",
    ):
        assert path in routes, f"missing route {path}"
