"""F2 Financials redesign + provider-health table + provenance strip (#1976).

Covers three deliverables:

1. ``pi_provider_health`` converts from a truncated ``markdown`` strip to a
   sortable ``table`` (Tier / Role / Status / Latency / Serving / Note).
2. ``pi_data_provenance`` — a new thin ``markdown`` chrome bar answering the
   analyst's trust question (Data mode / Serving source / Providers).
3. The **F2: Financials** tab is rebuilt into a top-down fundamentals layout
   using widgets already shipped in the backend.

The provider-health *behaviour* regression tests live alongside the older
``test_provider_health_*`` modules; this file focuses on the widget/layout
contracts introduced by #1976.
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

_CHROME_IDS = {"pi_provider_health", "pi_data_provenance"}


def _widgets() -> dict:
    return json.loads((_MANIFEST_DIR / "widgets.json").read_text(encoding="utf-8"))


def _apps() -> list:
    apps = json.loads((_MANIFEST_DIR / "apps.json").read_text(encoding="utf-8"))
    return apps if isinstance(apps, list) else list(apps.values())


def _terminal_app() -> dict:
    for a in _apps():
        if a.get("id") == "portfolio-intelligence-terminal":
            return a
    return {}


def _f2_layout() -> list:
    return _terminal_app().get("tabs", {}).get("financials", {}).get("layout", [])


# ---------------------------------------------------------------------------
# Deliverable 1 — provider-health is now a table with a decent height
# ---------------------------------------------------------------------------


def test_provider_health_is_a_table_with_columns() -> None:
    w = _widgets().get("pi_provider_health")
    assert w and w["type"] == "table"
    fields = {
        c["field"] for c in w.get("data", {}).get("table", {}).get("columnsDefs", [])
    }
    assert {"tier", "role", "status", "latency_ms", "serving"} <= fields


def test_provider_health_has_readable_height() -> None:
    """The old h:2 strip truncated ~11 lines; the table needs real height."""
    w = _widgets()["pi_provider_health"]
    assert w["gridData"]["h"] >= 6


def test_provider_health_rows_carry_role_and_status() -> None:
    rows = _client.get("/pi/health/providers").json()
    assert isinstance(rows, list) and rows
    fmp_cached = next(r for r in rows if r["tier"] == "fmp_cached")
    assert fmp_cached["role"] == "Primary (cache)"
    # status is a badge + word, e.g. "🟢 healthy" / "⚪ unknown"
    assert any(word in fmp_cached["status"] for word in ("healthy", "unknown", "down"))


# ---------------------------------------------------------------------------
# Deliverable 2 — data-provenance strip
# ---------------------------------------------------------------------------


def test_provenance_widget_declared() -> None:
    w = _widgets().get("pi_data_provenance")
    assert w and w["type"] == "markdown"
    assert w["endpoint"] == "pi/context/provenance"


def test_provenance_endpoint_returns_markdown() -> None:
    r = _client.get("/pi/context/provenance")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, str)
    assert "Data mode" in body and "Serving source" in body and "Providers" in body


def test_provenance_endpoint_registered() -> None:
    routes = {r.path for r in app.routes}
    assert "/pi/context/provenance" in routes


def test_provenance_reflects_serving_source() -> None:
    """When the ledger says fmp_cached serves an endpoint, mode is LIVE."""
    from openbb_portfolio_intel.widget_backend import widgets_endpoints as we

    we._TIER_IN_USE.clear()
    we.record_tier_used("pi/equity/financials", "fmp_cached")
    try:
        body = _client.get("/pi/context/provenance").json()
    finally:
        we._TIER_IN_USE.clear()
    assert "LIVE" in body
    assert "fmp_cached" in body


# ---------------------------------------------------------------------------
# Deliverable 3 — F2 fundamentals layout
# ---------------------------------------------------------------------------

_F2_EXPECTED = {
    "pi_data_provenance",
    "pi_symbol_context",
    "pi_equity_key_stats",
    "pi_equity_financial_charts",
    "pi_financial_statements",
    "pi_peer_multiples",
    "pi_earnings_history",
    "pi_revenue_business_line",
    "pi_revenue_geography",
    "pi_price_target_history",
    "pi_dividend_payment",
    "pi_provider_health",
}


def test_f2_contains_full_fundamentals_set() -> None:
    ids = {s["i"] for s in _f2_layout()}
    missing = _F2_EXPECTED - ids
    assert not missing, f"F2 is missing fundamentals widgets: {sorted(missing)}"


def test_f2_provenance_is_top_chrome_and_health_is_bottom() -> None:
    layout = _f2_layout()
    assert layout[0]["i"] == "pi_data_provenance", "provenance must be the top strip"
    assert layout[-1]["i"] == "pi_provider_health", "health table must be the bottom slot"


def test_f2_chrome_bars_are_decently_sized() -> None:
    """The original bug: provenance/context/health opened too short."""
    by_id = {s["i"]: s for s in _f2_layout()}
    assert by_id["pi_data_provenance"]["h"] >= 3
    assert by_id["pi_symbol_context"]["h"] >= 3
    assert by_id["pi_provider_health"]["h"] >= 6


def test_f2_first_content_slot_is_symbol_context() -> None:
    non_chrome = [s for s in _f2_layout() if s["i"] not in _CHROME_IDS]
    top = min(non_chrome, key=lambda s: (s["y"], s["x"]))
    assert top["i"] == "pi_symbol_context"


def test_every_terminal_tab_has_provenance_chrome() -> None:
    for tid, tab in _terminal_app().get("tabs", {}).items():
        ids = {s["i"] for s in tab.get("layout", [])}
        assert "pi_data_provenance" in ids, f"tab {tid!r} missing provenance strip"
        assert "pi_provider_health" in ids, f"tab {tid!r} missing provider-health table"
