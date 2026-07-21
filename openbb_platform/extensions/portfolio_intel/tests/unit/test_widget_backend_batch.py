"""Smoke tests for the batch-shipped widget endpoints (#529-#577).

Each test asserts one thing: the endpoint returns the shape declared
by its ``widgets.json`` type (markdown -> str, chart+raw -> list-of-
dicts, table -> list-of-dicts, metric -> scalar dict). If Workspace
would render the widget blank because of a shape mismatch, the test
fails here at PR time.

Uses the same loopback-dev env-var override the base backend test
file installs at import time.
"""

from __future__ import annotations

import os

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import pytest
from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)


# ---------------------------------------------------------------------------
# X-Ray Country + Look-Through + Concentration (#529, #530)
# ---------------------------------------------------------------------------


def test_xray_country_demo_returns_non_empty_country_rows() -> None:
    """chart+raw contract: list of {country, weight}."""
    resp = _client.get("/pi/xray/country?account_id=demo")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows and all("country" in r and "weight" in r for r in rows)


def test_lookthrough_top25_returns_ranked_rows() -> None:
    """Table contract: <=25 rows with symbol/name/effective_weight/rank."""
    resp = _client.get("/pi/lookthrough/top25?account_id=demo")
    assert resp.status_code == 200
    rows = resp.json()
    assert 0 < len(rows) <= 25
    ranks = [r["rank"] for r in rows]
    assert ranks == sorted(ranks), "rank column must be monotonically increasing"


def test_concentration_returns_metric_dict_with_value_field() -> None:
    """Metric contract: dict with a numeric value."""
    resp = _client.get("/pi/concentration?account_id=demo")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)
    assert isinstance(body.get("value"), (int, float))
    assert 0.0 <= body["value"] <= 1.0, "HHI must be in [0, 1]"


# ---------------------------------------------------------------------------
# Event Calendar (#531)
# ---------------------------------------------------------------------------


def test_events_calendar_returns_rows_with_type_field() -> None:
    """Table contract: rows carry event type + date."""
    resp = _client.get("/pi/events/calendar?account_id=demo&horizon_days=14")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows
    valid_types = {"earnings", "ex_dividend", "form_8k", "info"}
    for r in rows:
        assert r["type"] in valid_types


def test_events_calendar_rejects_bad_horizon() -> None:
    """horizon_days must parse to int in [1, 365]."""
    resp = _client.get("/pi/events/calendar?account_id=demo&horizon_days=abc")
    assert resp.status_code == 400
    resp = _client.get("/pi/events/calendar?account_id=demo&horizon_days=9999")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Smart-Money ribbon (#532)
# ---------------------------------------------------------------------------


def test_smart_money_ribbon_rows_carry_actor_and_kind() -> None:
    """Table contract for the smart-money ribbon."""
    resp = _client.get("/pi/smart-money/ribbon?account_id=demo")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows and all("kind" in r and "actor" in r for r in rows)


# ---------------------------------------------------------------------------
# Risk widgets (#533)
# ---------------------------------------------------------------------------


def test_risk_dashboard_returns_named_metrics() -> None:
    """Metric contract with vol/var/beta."""
    resp = _client.get("/pi/risk/dashboard?account_id=demo")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("vol_annualized", "var_95_1d", "beta_spy"):
        assert key in body


def test_risk_vol_chart_returns_time_series_rows() -> None:
    """chart+raw contract: list of {date, vol_20d, vol_60d}."""
    resp = _client.get("/pi/risk/vol?account_id=demo")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows and all("date" in r and "vol_20d" in r for r in rows)


# ---------------------------------------------------------------------------
# Paper trading (#549, #550, #551)
# ---------------------------------------------------------------------------


def test_paper_ticket_preview_labeled_correctly() -> None:
    """First call (confirm=false) returns a PREVIEW markdown card."""
    resp = _client.get(
        "/pi/paper/ticket?account_id=demo&symbol=AAPL&side=buy&quantity=100"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, str)
    assert "PREVIEW" in body and "BUY" in body


def test_paper_ticket_commit_labeled_correctly() -> None:
    """Second call (confirm=true) returns a COMMITTED markdown card."""
    resp = _client.get(
        "/pi/paper/ticket?account_id=demo&symbol=AAPL&side=buy&quantity=100&confirm=true"
    )
    assert resp.status_code == 200
    assert "COMMITTED" in resp.json()


@pytest.mark.parametrize(
    "params,expect_code",
    [
        ("account_id=demo&symbol=AAPL&side=neither&quantity=1", 400),  # bad side
        ("account_id=demo&symbol=AAPL&side=buy&quantity=0", 400),  # non-positive qty
        ("account_id=demo&symbol=AAPL&side=buy&quantity=abc", 400),  # non-int qty
        ("account_id=demo&symbol=<bad>&side=buy&quantity=1", 400),  # bad symbol
    ],
)
def test_paper_ticket_rejects_bad_inputs(params: str, expect_code: int) -> None:
    """Bad side / non-positive qty / non-int qty / bad symbol all raise 400."""
    resp = _client.get(f"/pi/paper/ticket?{params}")
    assert resp.status_code == expect_code


def test_paper_blotter_returns_orders_table() -> None:
    """Table contract with time/symbol/side/qty/status/avg_price."""
    resp = _client.get("/pi/paper/blotter?account_id=demo")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows and all(
        {"time", "symbol", "side", "qty", "status", "avg_price"} <= set(r.keys())
        for r in rows
    )


def test_paper_performance_returns_equity_curve() -> None:
    """chart+raw contract: list of {date, equity}."""
    resp = _client.get("/pi/paper/performance?account_id=demo")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows and all("date" in r and "equity" in r for r in rows)
    equities = [r["equity"] for r in rows]
    assert all(e > 0 for e in equities), "equity values must be positive"


def test_paper_perf_kpis_returns_named_scalars() -> None:
    """Metric contract with total_return / Sharpe / max_drawdown."""
    resp = _client.get("/pi/paper/perf-kpis?account_id=demo")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("total_return_pct", "sharpe_annualized", "max_drawdown_pct"):
        assert key in body


# ---------------------------------------------------------------------------
# What-If diff card (#552)
# ---------------------------------------------------------------------------


def test_whatif_card_returns_before_after_delta_rows() -> None:
    """Table contract: rows carry {metric, before, after, delta}."""
    resp = _client.get("/pi/whatif/card?symbol=AAPL&delta_shares=100")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows
    for r in rows:
        assert {"metric", "before", "after", "delta"} <= set(r.keys())
        # Invariant: delta == after - before (up to float error)
        assert abs(r["delta"] - (r["after"] - r["before"])) < 1e-9


# ---------------------------------------------------------------------------
# P3 widgets — News, Sentiment, Alerts, Backtest (#575, #576, #577)
# ---------------------------------------------------------------------------


def test_news_returns_rows_with_severity() -> None:
    """Table contract for news feed."""
    resp = _client.get("/pi/news?account_id=demo&horizon_days=7")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows and all("severity" in r for r in rows)


def test_news_rejects_out_of_range_horizon() -> None:
    """horizon_days > 90 is rejected as out-of-range."""
    resp = _client.get("/pi/news?account_id=demo&horizon_days=91")
    assert resp.status_code == 400


def test_sentiment_returns_scalar_metric_in_range() -> None:
    """Metric contract; value in [-1, 1]."""
    resp = _client.get("/pi/sentiment?account_id=demo")
    assert resp.status_code == 200
    body = resp.json()
    assert -1.0 <= body["value"] <= 1.0


def test_alerts_returns_rows_with_severity_and_kind() -> None:
    """Table contract: each alert row has severity + kind."""
    resp = _client.get("/pi/alerts?account_id=demo")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows and all("severity" in r and "kind" in r for r in rows)


def test_backtest_button_returns_markdown_confirmation() -> None:
    """Markdown contract; body confirms the backtest was queued."""
    resp = _client.get("/pi/backtest/oneclick?account_id=demo")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, str) and "Backtest" in body


# ---------------------------------------------------------------------------
# All batch endpoints inherit the same auth + account-id guards
# ---------------------------------------------------------------------------


BATCH_ACCOUNT_ENDPOINTS = [
    "/pi/xray/country",
    "/pi/lookthrough/top25",
    "/pi/concentration",
    "/pi/events/calendar",
    "/pi/smart-money/ribbon",
    "/pi/risk/dashboard",
    "/pi/risk/vol",
    "/pi/paper/blotter",
    "/pi/paper/performance",
    "/pi/paper/perf-kpis",
    "/pi/news",
    "/pi/sentiment",
    "/pi/alerts",
    "/pi/backtest/oneclick",
]


@pytest.mark.parametrize("path", BATCH_ACCOUNT_ENDPOINTS)
def test_batch_endpoints_reject_bad_account_id(path: str) -> None:
    """Every account_id-taking endpoint must reject metacharacters."""
    resp = _client.get(f"{path}?account_id=demo;rm+-rf")
    assert resp.status_code == 400, f"{path} accepted bad account_id"


@pytest.mark.parametrize("path", BATCH_ACCOUNT_ENDPOINTS)
def test_batch_endpoints_reject_empty_account_id(path: str) -> None:
    """Every account_id-taking endpoint rejects empty string."""
    resp = _client.get(f"{path}?account_id=")
    assert resp.status_code == 400, f"{path} accepted empty account_id"
