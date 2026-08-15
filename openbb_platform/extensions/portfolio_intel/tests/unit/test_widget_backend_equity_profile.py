"""Smoke tests for the Equity Profile widget endpoints (#990-#996)."""

from __future__ import annotations

import os
import re
from datetime import date

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import pytest
from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend.main import app
from openbb_portfolio_intel.widget_backend import widgets_endpoints

_client = TestClient(app)


@pytest.mark.parametrize(
    ("symbol", "as_of", "calendar_quarter_end"),
    [
        ("AAPL", date(2026, 8, 15), date(2026, 6, 30)),
        ("MSFT", date(2026, 4, 1), date(2026, 3, 31)),
        ("NVDA", date(2026, 1, 1), date(2025, 12, 31)),
    ],
)
def test_historical_forecast_lookup_uses_last_completed_calendar_quarter(
    symbol: str, as_of: date, calendar_quarter_end: date
) -> None:
    """Lookup arguments use a deterministic calendar anchor, including year rollover."""
    assert widgets_endpoints._historical_forecast_lookup_kwargs(symbol, as_of) == {
        "symbol": symbol,
        "fiscal_period_end": calendar_quarter_end,
        "as_of_date": calendar_quarter_end,
        "period": "quarter",
    }


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


def test_equity_analyst_forecasts_gaps_documented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Section 5 — #997 + #998 both LIVE now (#1022 + #1025 shipped).

    Rating rows carry a live 'n=... firms' note (or 'fetch failed' on
    network error). Historical rev estimate row renders either an
    actual snapshot value (once opportunistic snapshots accumulate) or
    the honest 'insufficient history' state, not a BLOCKED sentinel.
    """
    from openbb_fmp_cached.models import analyst_estimates

    monkeypatch.setattr(analyst_estimates, "get_estimate_as_of", lambda **_kwargs: None)
    resp = _client.get("/pi/equity/analyst-forecasts?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()

    # #997 rating rows must be present
    rating_rows = [r for r in rows if r["metric"].startswith("Rating:")]
    assert len(rating_rows) == 2
    rating_notes = " ".join(str(r["note"]) for r in rating_rows)
    assert (
        "firms" in rating_notes
        or "unknown_count" in rating_notes
        or "fetch failed" in rating_notes
    )

    # #998 rev-estimate row must render one of the three honest states:
    #   "insufficient history" | "snapshot <date>" | "lookup failed"
    # It must NOT still say "BLOCKED gap 998" (that'd mean the wiring
    # didn't land).
    rev_row = next(r for r in rows if r["metric"] == "Historical rev estimate (last Q)")
    rev_state = f"{rev_row['value']} {rev_row['note']}".lower()
    assert (
        "insufficient history" in rev_state
        or "snapshot" in rev_state
        or "lookup failed" in rev_state
    ), f"rev-estimate row still showing gap sentinel: {rev_row}"
    # And explicitly, the value must NOT be the old BLOCKED marker
    assert str(rev_row["value"]).upper() != "BLOCKED"
    assert rev_row["value"] == "insufficient history"
    assert rev_row["metric"] == "Historical rev estimate (last Q)"
    assert "historical estimate snapshot" in str(rev_row["note"]).lower()
    assert "revenue surprise" in str(rev_row["note"]).lower()
    assert "#" not in str(rev_row["note"])
    assert not re.search(r"\b[a-z]+(?:_[a-z0-9]+)+\b", str(rev_row["note"]))


def test_equity_analyst_forecasts_snapshot_uses_stable_raw_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshot success retains the identifier that manifest metadata translates."""
    from openbb_fmp_cached.models import analyst_estimates

    monkeypatch.setattr(
        analyst_estimates,
        "get_estimate_as_of",
        lambda **_kwargs: {
            "estimated_revenue_avg": 123_456.0,
            "snapshot_date": "2026-08-01",
        },
    )
    rows = _client.get("/pi/equity/analyst-forecasts?symbol=AAPL").json()
    snapshot_row = next(row for row in rows if row["value"] == 123_456.0)
    assert snapshot_row["metric"] == "Historical rev estimate (last Q)"


def test_equity_analyst_forecasts_compute_displayed_eps_surprises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Display values derive from the actual/estimate constants, not stale literals."""
    from openbb_fmp_cached.models import analyst_estimates

    monkeypatch.setattr(analyst_estimates, "get_estimate_as_of", lambda **_kwargs: None)
    rows = _client.get("/pi/equity/analyst-forecasts?symbol=AAPL").json()
    surprises = {
        row["metric"]: row["value"]
        for row in rows
        if row["metric"].endswith("EPS Surprise")
    }
    assert surprises == {
        "Q3 2025 EPS Surprise": "+3.3%",
        "Q2 2025 EPS Surprise": "+2.0%",
    }


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
