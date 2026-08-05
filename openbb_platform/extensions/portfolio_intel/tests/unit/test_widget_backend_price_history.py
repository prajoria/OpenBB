"""Tests for the price-history widget with line ↔ candlestick toggle (#1702).

Verifies:

- Backend endpoint ``/pi/equity/price-history`` accepts a ``chart_type``
  query param and returns different row shapes based on it.
- Default (``chart_type=line`` or omitted) returns ``{date, close}`` rows.
- ``chart_type=candle`` returns ``{date, open, high, low, close}`` OHLC rows.
- Invalid ``chart_type`` values are rejected with 400.
- The widget appears in ``widgets.json`` with a dropdown-typed
  ``chart_type`` param.
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
    """Keep these endpoint tests hermetic (network-free).

    Since #1898 wired an ``fmp_cached`` live tier for ``equity/price-history``,
    hitting the endpoint would otherwise dispatch a real ``obb`` call through
    the provider chain. These tests assert the endpoint's own shape/validation
    contract (which holds for both the live and stub paths), so we clear the
    dispatch table to force the chain to exhaust to the stub — matching the
    original "unit tests never touch the network" intent. Live-tier behavior
    is covered by ``test_tier_calls.py`` (shaping unit tests + integration).
    """
    saved = dict(_TIER_CALLS)
    _TIER_CALLS.clear()
    try:
        yield
    finally:
        _TIER_CALLS.clear()
        _TIER_CALLS.update(saved)


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
# Endpoint shape tests
# ---------------------------------------------------------------------------


def test_price_history_default_is_line_shape() -> None:
    """Omitting ``chart_type`` returns line shape ``{date, close}``."""
    resp = _client.get("/pi/equity/price-history?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "line shape must return non-empty rows"
    assert all(
        set(r.keys()) == {"date", "close"} for r in rows
    ), f"expected exactly date+close keys, got {rows[0].keys()}"
    assert all(isinstance(r["close"], (int, float)) for r in rows)


def test_price_history_line_explicit() -> None:
    """Explicit ``chart_type=line`` returns the same shape as default."""
    resp = _client.get("/pi/equity/price-history?symbol=AAPL&chart_type=line")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows and all(set(r.keys()) == {"date", "close"} for r in rows)


def test_price_history_candle_returns_ohlc_shape() -> None:
    """``chart_type=candle`` returns ``{date, open, high, low, close}``."""
    resp = _client.get("/pi/equity/price-history?symbol=AAPL&chart_type=candle")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "candle shape must return non-empty rows"
    expected = {"date", "open", "high", "low", "close"}
    assert all(
        expected.issubset(set(r.keys())) for r in rows
    ), f"expected OHLC keys, got {rows[0].keys()}"
    # Sanity: high >= low, high >= open, high >= close (per-bar invariant).
    for r in rows:
        assert r["high"] >= r["low"], f"high < low on {r}"
        assert r["high"] >= r["open"], f"high < open on {r}"
        assert r["high"] >= r["close"], f"high < close on {r}"


def test_price_history_rejects_invalid_chart_type() -> None:
    """Unknown ``chart_type`` returns 400 with a discriminating error."""
    resp = _client.get("/pi/equity/price-history?symbol=AAPL&chart_type=heikinashi")
    assert resp.status_code == 400
    detail = resp.json().get("detail", "")
    assert "chart_type" in detail
    assert "line" in detail and "candle" in detail


def test_price_history_symbol_validation() -> None:
    """XSS-shaped symbol is rejected pre-fetch (shared _SYMBOL_RE)."""
    resp = _client.get("/pi/equity/price-history?symbol=<script>")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Widget-manifest tests — widgets.json must declare the toggle param
# ---------------------------------------------------------------------------


def test_manifest_registers_price_history_widget() -> None:
    """``pi_equity_price_history`` widget is declared in widgets.json."""
    m = _manifest()
    assert "pi_equity_price_history" in m, "widget missing from manifest"
    w = m["pi_equity_price_history"]
    assert w["type"] == "chart"
    assert w["endpoint"] == "pi/equity/price-history"


def test_manifest_price_history_has_chart_type_param() -> None:
    """The widget declares a ``chart_type`` param as a dropdown enum."""
    m = _manifest()
    w = m["pi_equity_price_history"]
    params = {p["paramName"]: p for p in w.get("params", [])}
    assert "chart_type" in params, "chart_type param missing from widget"
    p = params["chart_type"]
    # OpenBB Workspace uses type='endpoint' or 'text' for enums via
    # options list. Options must contain exactly the two supported modes.
    opts = p.get("options") or []
    values = {o.get("value") for o in opts}
    assert values == {"line", "candle"}, f"expected line+candle options, got {values}"
    assert p.get("value") == "line", "default should be line for backward compat"
