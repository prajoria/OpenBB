"""F1 Batch B tests: 4 new BUILD widgets over fmp_cached endpoints (stub-shaped).

Covers:

- **#1645 T1.3** — pi_price_performance table widget over
  FMPPricePerformanceFetcher schema; rows are perf-period/return pairs
  (1D/1M/3M/6M/YTD/1Y/3Y/5Y). Endpoint /pi/equity/price-performance.
- **#1648 T1.6** — pi_management_team table widget over
  FMPKeyExecutivesFetcher schema; rows are name/title/pay/tenure.
  Endpoint /pi/equity/management-team.
- **#1649 T1.7** — pi_revenue_geography chart widget (raw=true) over
  FMPRevenueGeographicFetcher schema; rows are region/revenue.
  Endpoint /pi/equity/revenue-geography.
- **#1650 T1.8** — pi_revenue_business_line chart widget (raw=true)
  over FMPRevenueBusinessLineFetcher schema; rows are segment/revenue.
  Endpoint /pi/equity/revenue-business-line.

Values remain stubbed — same policy every other F0/F1 widget follows.
Real fmp_cached fetcher wiring lands per-widget in a follow-up cycle.
The shape contract is what unlocks Workspace rendering.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import pytest
from fastapi.testclient import TestClient
from openbb_portfolio_intel.providers.retrofit import _TIER_CALLS
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)


@pytest.fixture(autouse=True)
def _force_stub_path():
    """Keep these endpoint smoke tests hermetic (network-free).

    Since #1900 wired an ``fmp_cached`` live tier for
    ``equity/price-performance``, hitting that endpoint would otherwise
    dispatch a real ``obb`` call through the provider chain. Clearing the
    dispatch table for the duration of each test forces the stub-body path,
    preserving the original "unit tests never touch the network" intent.
    Live-tier behavior is covered by ``test_tier_calls.py`` (shaping unit
    tests + endpoint served-from-tier + integration).
    """
    saved = dict(_TIER_CALLS)
    _TIER_CALLS.clear()
    try:
        yield
    finally:
        _TIER_CALLS.clear()
        _TIER_CALLS.update(saved)


_MANIFEST_DIR = (
    Path(__file__).resolve().parents[2] / "openbb_portfolio_intel" / "widget_backend"
)


def _widgets() -> dict:
    return json.loads((_MANIFEST_DIR / "widgets.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Widget manifest declarations
# ---------------------------------------------------------------------------


def test_price_performance_widget_declared() -> None:
    """#1645 — pi_price_performance in widgets.json with a symbol param."""
    w = _widgets().get("pi_price_performance")
    assert w is not None, "pi_price_performance missing from widgets.json"
    assert w["type"] == "table"
    assert w["endpoint"] == "pi/equity/price-performance"
    params = {p["paramName"] for p in w.get("params", [])}
    assert "symbol" in params


def test_management_team_widget_declared() -> None:
    """#1648 — pi_management_team in widgets.json."""
    w = _widgets().get("pi_management_team")
    assert w is not None, "pi_management_team missing from widgets.json"
    assert w["type"] == "table"
    assert w["endpoint"] == "pi/equity/management-team"
    params = {p["paramName"] for p in w.get("params", [])}
    assert "symbol" in params


def test_revenue_geography_widget_declared() -> None:
    """#1649 — pi_revenue_geography in widgets.json (chart raw)."""
    w = _widgets().get("pi_revenue_geography")
    assert w is not None, "pi_revenue_geography missing from widgets.json"
    assert w["type"] == "chart"
    assert w.get("raw") is True
    assert w["endpoint"] == "pi/equity/revenue-geography"


def test_revenue_business_line_widget_declared() -> None:
    """#1650 — pi_revenue_business_line in widgets.json (chart raw)."""
    w = _widgets().get("pi_revenue_business_line")
    assert w is not None, "pi_revenue_business_line missing from widgets.json"
    assert w["type"] == "chart"
    assert w.get("raw") is True
    assert w["endpoint"] == "pi/equity/revenue-business-line"


# ---------------------------------------------------------------------------
# Endpoint smoke — shape contract per widget
# ---------------------------------------------------------------------------


def test_price_performance_returns_period_return_rows() -> None:
    """#1645 — table rows carry a 'period' + numeric 'return_pct' pair."""
    r = _client.get("/pi/equity/price-performance?symbol=AAPL")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list) and rows, "must not return empty list"
    for row in rows:
        assert "period" in row, f"missing 'period' in row {row!r}"
        assert "return_pct" in row, f"missing 'return_pct' in row {row!r}"
        assert isinstance(row["return_pct"], (int, float))
    # Must cover a range of horizons — not just one row.
    periods = {row["period"] for row in rows}
    assert len(periods) >= 4, f"too few horizons — got {periods!r}"


def test_management_team_returns_executive_rows() -> None:
    """#1648 — table rows carry name + title (pay may be null on younger firms)."""
    r = _client.get("/pi/equity/management-team?symbol=AAPL")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list) and rows
    for row in rows:
        assert "name" in row, f"missing 'name' in row {row!r}"
        assert "title" in row, f"missing 'title' in row {row!r}"


def test_revenue_geography_returns_region_revenue_rows() -> None:
    """#1649 — chart rows carry region + revenue for pie rendering."""
    r = _client.get("/pi/equity/revenue-geography?symbol=AAPL")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list) and rows
    for row in rows:
        assert "region" in row
        assert "revenue" in row
        assert isinstance(row["revenue"], (int, float))


def test_revenue_business_line_returns_segment_revenue_rows() -> None:
    """#1650 — chart rows carry segment + revenue."""
    r = _client.get("/pi/equity/revenue-business-line?symbol=AAPL")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list) and rows
    for row in rows:
        assert "segment" in row
        assert "revenue" in row
        assert isinstance(row["revenue"], (int, float))


# ---------------------------------------------------------------------------
# Symbol allowlist (echoes into row bodies)
# ---------------------------------------------------------------------------


def test_price_performance_rejects_bad_symbol() -> None:
    for bad in ("<script>", "A;B", "A" * 20):
        r = _client.get(f"/pi/equity/price-performance?symbol={bad}")
        assert r.status_code == 400, f"{bad!r} accepted"


def test_management_team_rejects_bad_symbol() -> None:
    for bad in ("<script>", "A;B"):
        r = _client.get(f"/pi/equity/management-team?symbol={bad}")
        assert r.status_code == 400


def test_revenue_geography_rejects_bad_symbol() -> None:
    for bad in ("<script>", "A;B"):
        r = _client.get(f"/pi/equity/revenue-geography?symbol={bad}")
        assert r.status_code == 400


def test_revenue_business_line_rejects_bad_symbol() -> None:
    for bad in ("<script>", "A;B"):
        r = _client.get(f"/pi/equity/revenue-business-line?symbol={bad}")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Route parity — Workspace 404 guard
# ---------------------------------------------------------------------------


def test_batch_b_endpoints_registered_as_routes() -> None:
    routes = {r.path for r in app.routes}
    for path in (
        "/pi/equity/price-performance",
        "/pi/equity/management-team",
        "/pi/equity/revenue-geography",
        "/pi/equity/revenue-business-line",
    ):
        assert path in routes, f"missing route {path}"
