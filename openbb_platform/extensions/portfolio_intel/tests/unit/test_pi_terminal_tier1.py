"""Tier 1 tests: F5 Ownership + F6 Calendar + F7 Estimates (12 issues).

Covers new BUILD widgets and one EXTEND (#1669) across three tabs:

**F5 Ownership (#1659, #1660, #1661)**
- pi_institutional_ownership (table) — 13F holders + shares held
- pi_stock_ownership (chart+pie) — insider/inst/retail/etf split
- pi_insider_trading (table) — recent insider transactions

**F6 Company Calendar (#1663, #1664, #1665, #1666, #1667)**
- pi_earnings_history (table) — EPS actual vs. estimate
- pi_stock_splits (table) — historical split events
- pi_dividend_payment (table) — dividend history
- pi_company_filings (table) — recent SEC filings
- pi_earnings_transcripts (markdown) — latest transcript preview

**F7 Estimates (#1669)**
- pi_price_target_history (chart+line) — analyst target evolution

All values stubbed. Same policy every F0/F1 widget follows —
shape-contract-first, real fmp_cached fetcher wiring is a per-widget
follow-up (each endpoint TODO cites its issue number).
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


# ---------------------------------------------------------------------------
# Widget manifest declarations
# ---------------------------------------------------------------------------


def test_institutional_ownership_widget_declared() -> None:
    w = _widgets().get("pi_institutional_ownership")
    assert w and w["type"] == "table"
    assert w["endpoint"] == "pi/equity/institutional-ownership"


def test_stock_ownership_widget_declared() -> None:
    w = _widgets().get("pi_stock_ownership")
    assert w and w["type"] == "chart" and w.get("raw") is True


def test_insider_trading_widget_declared() -> None:
    w = _widgets().get("pi_insider_trading")
    assert w and w["type"] == "table"


def test_earnings_history_widget_declared() -> None:
    w = _widgets().get("pi_earnings_history")
    assert w and w["type"] == "table"


def test_stock_splits_widget_declared() -> None:
    w = _widgets().get("pi_stock_splits")
    assert w and w["type"] == "table"


def test_dividend_payment_widget_declared() -> None:
    w = _widgets().get("pi_dividend_payment")
    assert w and w["type"] == "table"


def test_company_filings_widget_declared() -> None:
    w = _widgets().get("pi_company_filings")
    assert w and w["type"] == "table"


def test_earnings_transcripts_widget_declared() -> None:
    w = _widgets().get("pi_earnings_transcripts")
    assert w and w["type"] == "markdown"


def test_price_target_history_widget_declared() -> None:
    w = _widgets().get("pi_price_target_history")
    assert w and w["type"] == "chart"


# ---------------------------------------------------------------------------
# Endpoint shape smoke — one test per widget
# ---------------------------------------------------------------------------


def test_institutional_ownership_shape() -> None:
    """#1659 — 13F holder rows: holder + shares + pct_owned."""
    rows = _client.get("/pi/equity/institutional-ownership?symbol=AAPL").json()
    assert rows
    for r in rows:
        assert "holder" in r and "shares" in r and "pct_owned" in r


def test_stock_ownership_shape() -> None:
    """#1660 — pie rows: bucket + pct."""
    rows = _client.get("/pi/equity/stock-ownership?symbol=AAPL").json()
    assert rows
    buckets = {r["bucket"] for r in rows}
    assert "Institutions" in buckets or "Insiders" in buckets
    for r in rows:
        assert "pct" in r and isinstance(r["pct"], (int, float))


def test_insider_trading_shape() -> None:
    """#1661 — insider rows: name + date + shares + transaction_type."""
    rows = _client.get("/pi/equity/insider-trading?symbol=AAPL").json()
    assert rows
    for r in rows:
        assert "name" in r and "date" in r and "shares" in r
        assert "transaction_type" in r


def test_earnings_history_shape() -> None:
    """#1663 — earnings rows: quarter + eps_actual + eps_estimate + surprise_pct."""
    rows = _client.get("/pi/equity/earnings-history?symbol=AAPL").json()
    assert rows
    for r in rows:
        assert "quarter" in r and "eps_actual" in r and "eps_estimate" in r


def test_stock_splits_shape() -> None:
    """#1664 — split rows: date + numerator + denominator + ratio."""
    rows = _client.get("/pi/equity/stock-splits?symbol=AAPL").json()
    assert rows
    for r in rows:
        assert "date" in r and "ratio" in r


def test_dividend_payment_shape() -> None:
    """#1665 — dividend rows: ex_date + payment_date + amount."""
    rows = _client.get("/pi/equity/dividend-payment?symbol=AAPL").json()
    assert rows
    for r in rows:
        assert "ex_date" in r and "amount" in r
        assert isinstance(r["amount"], (int, float))


def test_company_filings_shape() -> None:
    """#1666 — filing rows: date + filing_type + description."""
    rows = _client.get("/pi/equity/company-filings?symbol=AAPL").json()
    assert rows
    for r in rows:
        assert "date" in r and "filing_type" in r


def test_earnings_transcripts_returns_markdown() -> None:
    """#1667 — markdown widget: preview of latest transcript."""
    body = _client.get("/pi/equity/earnings-transcripts?symbol=AAPL").json()
    assert isinstance(body, str)
    assert "AAPL" in body


def test_price_target_history_shape() -> None:
    """#1669 — target history rows: date + close + target."""
    rows = _client.get("/pi/equity/price-target-history?symbol=AAPL").json()
    assert rows
    for r in rows:
        assert "date" in r and "close" in r and "target" in r
        assert isinstance(r["close"], (int, float))
        assert isinstance(r["target"], (int, float))


# ---------------------------------------------------------------------------
# Symbol allowlist — one representative check per widget
# ---------------------------------------------------------------------------


def test_all_tier1_endpoints_reject_bad_symbol() -> None:
    """Shared _SYMBOL_RE gate on every new endpoint."""
    paths = [
        "/pi/equity/institutional-ownership",
        "/pi/equity/stock-ownership",
        "/pi/equity/insider-trading",
        "/pi/equity/earnings-history",
        "/pi/equity/stock-splits",
        "/pi/equity/dividend-payment",
        "/pi/equity/company-filings",
        "/pi/equity/earnings-transcripts",
        "/pi/equity/price-target-history",
    ]
    for p in paths:
        r = _client.get(f"{p}?symbol=<script>")
        assert r.status_code == 400, f"{p} accepted bad symbol"


# ---------------------------------------------------------------------------
# Route parity — Workspace 404 guard
# ---------------------------------------------------------------------------


def test_all_tier1_endpoints_registered() -> None:
    """Every new endpoint must be a registered FastAPI route."""
    routes = {r.path for r in app.routes}
    for path in (
        "/pi/equity/institutional-ownership",
        "/pi/equity/stock-ownership",
        "/pi/equity/insider-trading",
        "/pi/equity/earnings-history",
        "/pi/equity/stock-splits",
        "/pi/equity/dividend-payment",
        "/pi/equity/company-filings",
        "/pi/equity/earnings-transcripts",
        "/pi/equity/price-target-history",
    ):
        assert path in routes, f"missing route {path}"
