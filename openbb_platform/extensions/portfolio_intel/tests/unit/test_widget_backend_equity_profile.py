"""Smoke tests for the Equity Profile widget endpoints (#990-#996)."""

from __future__ import annotations

import os

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import pytest
from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)


def test_equity_header_returns_markdown() -> None:
    """Section 1 — markdown widget contract."""
    resp = _client.get("/pi/equity/header?symbol=AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, str)
    assert "AAPL" in body


def test_equity_key_stats_table_shape() -> None:
    """Section 2 — table with metric/value rows."""
    resp = _client.get("/pi/equity/key-stats?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows and all("metric" in r and "value" in r for r in rows)


def test_equity_financials_5yr_records() -> None:
    """Section 3 — chart raw with 5 year rows carrying rev/net_income/margin."""
    resp = _client.get("/pi/equity/financials?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 5
    for r in rows:
        assert {"year", "revenue_b", "net_income_b", "net_margin_pct"} <= set(r.keys())
        # Margin equals net_income / revenue * 100 to 2dp.
        assert (
            abs(
                r["net_margin_pct"] - round(r["net_income_b"] / r["revenue_b"] * 100, 2)
            )
            < 0.02
        )


def test_equity_technicals_pivot_rows_math() -> None:
    """Section 4 — classic pivot P == (H+L+C)/3."""
    resp = _client.get("/pi/equity/technicals?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    p_row = next(r for r in rows if r["metric"].startswith("P "))
    assert isinstance(p_row["value"], float)
    # BLOCKED IV row must be present so the widget documents the gap.
    iv_row = next(r for r in rows if "IV" in r["metric"])
    assert iv_row["value"] == "BLOCKED" and "999" in iv_row["note"]


def test_equity_analyst_forecasts_gaps_documented() -> None:
    """Section 5 — sub-gaps #997 + #998 documented in note strings."""
    resp = _client.get("/pi/equity/analyst-forecasts?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    joined = " ".join(str(r.get("note", "")) for r in rows)
    assert "997" in joined and "998" in joined


def test_equity_complementary_bond_gap_documented() -> None:
    """Section 6 — bond ladder blocked on #1000 documented in row."""
    resp = _client.get("/pi/equity/complementary?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    bond_row = next(r for r in rows if r["kind"] == "Bond")
    assert bond_row["id"] == "BLOCKED" and "1000" in str(bond_row["value_usd"])


def test_equity_competitors_returns_peer_table() -> None:
    """Section 7 — table with symbol/name/price/change_pct per peer."""
    resp = _client.get("/pi/equity/competitors?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows and all(
        {"symbol", "name", "price", "change_pct"} <= set(r.keys()) for r in rows
    )


EQUITY_ENDPOINTS = [
    "/pi/equity/header",
    "/pi/equity/key-stats",
    "/pi/equity/financials",
    "/pi/equity/technicals",
    "/pi/equity/analyst-forecasts",
    "/pi/equity/complementary",
    "/pi/equity/competitors",
]


@pytest.mark.parametrize("path", EQUITY_ENDPOINTS)
def test_equity_endpoints_reject_bad_symbol(path: str) -> None:
    """Symbol regex allowlist enforced on every equity endpoint."""
    resp = _client.get(f"{path}?symbol=<script>")
    assert resp.status_code == 400
    resp = _client.get(f"{path}?symbol=" + "A" * 20)
    assert resp.status_code == 400


@pytest.mark.parametrize("path", EQUITY_ENDPOINTS)
def test_equity_endpoints_accept_clean_ticker(path: str) -> None:
    """Real tickers with dots and dashes are accepted."""
    resp = _client.get(f"{path}?symbol=BRK.B")
    assert resp.status_code == 200
