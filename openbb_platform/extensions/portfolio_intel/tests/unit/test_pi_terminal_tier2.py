"""Tier 2 tests: F2 Financials + F3 Technicals + F4 Comparison + F8 X-Ray.

Covers 4 issues plus 4 auto-cascade meta-issues:

- **#1653 T2.1** — pi_financial_statements table with period toggle
  (annual|quarterly) over IS/BS/CF stubs. Endpoint /pi/equity/statements.
- **#1655 T3.1** — pi_charting chart widget with OHLC + indicator
  overlays (RSI/MACD/SMA) and a window enum (1M/3M/6M/YTD/1Y).
  Endpoint /pi/equity/charting.
- **#1657 T4.1** — pi_peer_multiples table with peer symbol +
  P/E, EV/EBITDA, P/S columns for comparison. Endpoint
  /pi/equity/peer-multiples.
- **#1671 T8.1** — F8 X-Ray tab in apps.json includes all four
  X-Ray widgets: pi_xray_sector, pi_xray_country, pi_lookthrough_top25,
  and pi_concentration_gauge.

Same stub-first policy every F0/F1 widget follows.
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


def _xray_tab_layout() -> list[dict]:
    for a in _apps():
        if a.get("id") == "portfolio-intelligence-terminal":
            return a["tabs"]["xray"]["layout"]
    return []


# ---------------------------------------------------------------------------
# #1653 — Financial Statements (period toggle)
# ---------------------------------------------------------------------------


def test_financial_statements_widget_declared() -> None:
    w = _widgets().get("pi_financial_statements")
    assert w and w["type"] == "table"
    assert w["endpoint"] == "pi/equity/statements"
    params = {p["paramName"] for p in w.get("params", [])}
    assert "symbol" in params and "period" in params


def test_financial_statements_annual_shape() -> None:
    """#1653 — period=annual returns statement rows: label + latest + prior."""
    r = _client.get("/pi/equity/statements?symbol=AAPL&period=annual")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert "line_item" in row
        assert "period_1" in row
        assert "period_2" in row


def test_financial_statements_quarterly_shape() -> None:
    """#1653 — period=quarterly returns the same shape (different values)."""
    r = _client.get("/pi/equity/statements?symbol=AAPL&period=quarterly")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert "line_item" in row


def test_financial_statements_rejects_bad_period() -> None:
    """Invalid period enum values must be rejected before echoing."""
    r = _client.get("/pi/equity/statements?symbol=AAPL&period=weekly")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# #1655 — Charting (OHLC + indicator overlays)
# ---------------------------------------------------------------------------


def test_charting_widget_declared() -> None:
    w = _widgets().get("pi_charting")
    assert w and w["type"] == "chart"
    assert w["endpoint"] == "pi/equity/charting"
    params = {p["paramName"] for p in w.get("params", [])}
    assert "symbol" in params and "window" in params


def test_charting_default_returns_ohlc_plus_indicators() -> None:
    """#1655 — default window returns OHLC + RSI + SMA20 + SMA50 fields."""
    r = _client.get("/pi/equity/charting?symbol=AAPL")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    row = rows[0]
    for f in ("date", "open", "high", "low", "close", "sma20", "sma50", "rsi14"):
        assert f in row, f"missing {f} in {row!r}"


def test_charting_rejects_bad_window() -> None:
    """Invalid window enum must be rejected."""
    r = _client.get("/pi/equity/charting?symbol=AAPL&window=42Q")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# #1657 — Peer Multiples matrix
# ---------------------------------------------------------------------------


def test_peer_multiples_widget_declared() -> None:
    w = _widgets().get("pi_peer_multiples")
    assert w and w["type"] == "table"
    assert w["endpoint"] == "pi/equity/peer-multiples"


def test_peer_multiples_shape() -> None:
    """#1657 — rows are peer symbol + trailing/forward P/E + EV/EBITDA + P/S."""
    r = _client.get("/pi/equity/peer-multiples?symbol=AAPL")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert "symbol" in row and "pe_ttm" in row
        assert "ev_ebitda" in row and "ps_ttm" in row


def test_peer_multiples_includes_self_and_peers() -> None:
    """First row is the requested symbol; subsequent rows are peers."""
    rows = _client.get("/pi/equity/peer-multiples?symbol=AAPL").json()
    symbols = [r["symbol"] for r in rows]
    assert symbols[0] == "AAPL"
    assert len(set(symbols)) >= 3, "expected at least 2 peers plus self"


# ---------------------------------------------------------------------------
# #1671 — F8 X-Ray tab layout
# ---------------------------------------------------------------------------


def test_xray_tab_includes_sector_widget() -> None:
    ids = {slot["i"] for slot in _xray_tab_layout()}
    assert "pi_xray_sector" in ids


def test_xray_tab_includes_country_widget() -> None:
    ids = {slot["i"] for slot in _xray_tab_layout()}
    assert "pi_xray_country" in ids


def test_xray_tab_includes_lookthrough_widget() -> None:
    ids = {slot["i"] for slot in _xray_tab_layout()}
    assert "pi_lookthrough_top25" in ids


def test_xray_tab_includes_concentration_gauge() -> None:
    """#1671 — pi_concentration_gauge must appear alongside sector/country/top25."""
    ids = {slot["i"] for slot in _xray_tab_layout()}
    assert (
        "pi_concentration_gauge" in ids
    ), "F8 X-Ray tab missing pi_concentration_gauge — #1671 requires it"


# ---------------------------------------------------------------------------
# Symbol allowlist + route parity
# ---------------------------------------------------------------------------


def test_all_tier2_endpoints_reject_bad_symbol() -> None:
    for p in (
        "/pi/equity/statements",
        "/pi/equity/charting",
        "/pi/equity/peer-multiples",
    ):
        r = _client.get(f"{p}?symbol=<script>")
        assert r.status_code == 400, f"{p} accepted bad symbol"


def test_all_tier2_endpoints_registered() -> None:
    routes = {r.path for r in app.routes}
    for path in (
        "/pi/equity/statements",
        "/pi/equity/charting",
        "/pi/equity/peer-multiples",
    ):
        assert path in routes, f"missing route {path}"
