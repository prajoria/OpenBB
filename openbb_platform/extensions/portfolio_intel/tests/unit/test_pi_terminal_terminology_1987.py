"""Load-bearing Terminal terminology contracts for #1987 child widgets."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend.main import app

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_WIDGETS = _PACKAGE_ROOT / "openbb_portfolio_intel" / "widget_backend" / "widgets.json"
_VIEWER = _PACKAGE_ROOT.parent / "portfolio" / "assets" / "local_viewer" / "index.html"
_CLIENT = TestClient(app)


def _widgets() -> dict:
    return json.loads(_WIDGETS.read_text(encoding="utf-8"))


def _widget(widget_id: str) -> dict:
    return _widgets()[widget_id]


def test_1989_statement_period_headers_match_backend_semantics() -> None:
    columns = _widget("pi_financial_statements")["data"]["table"]["columnsDefs"]
    assert {column["field"]: column["headerName"] for column in columns} == {
        "line_item": "Line Item",
        "period_1": "Latest Period",
        "period_2": "Prior Period",
    }


def test_1998_lookthrough_fraction_uses_explicit_percent_formatter() -> None:
    column = next(
        column
        for column in _widget("pi_lookthrough_top25")["data"]["table"]["columnsDefs"]
        if column["field"] == "effective_weight"
    )
    assert column == {
        "field": "effective_weight",
        "headerName": "Effective Weight (%)",
        "glossaryKey": "effective_weight",
        "formatterFn": "percentFraction",
    }
    response = _CLIENT.get("/pi/lookthrough/top25?account_id=demo")
    assert response.status_code == 200
    assert response.json()[0]["effective_weight"] == 0.078


def test_1999_single_value_concentration_card_has_label_and_help_mapping() -> None:
    metric = _widget("pi_concentration_gauge")["data"]["metric"]
    assert metric == {
        "labels": {"value": "Concentration (HHI)"},
        "metricGlossary": {"Concentration (HHI)": "herfindahl_hirschman_index"},
    }


def test_1993_technical_rows_match_actual_classic_pivot_strings() -> None:
    widget = _widget("pi_equity_technicals")
    response = _CLIENT.get("/pi/equity/technicals?symbol=AAPL")
    assert response.status_code == 200
    rows = response.json()
    expected = {
        "Consensus": ("Analyst Consensus", "analyst_consensus"),
        "R3 (Classic)": ("Resistance 3", "resistance"),
        "R2 (Classic)": ("Resistance 2", "resistance"),
        "R1 (Classic)": ("Resistance 1", "resistance"),
        "P (Classic)": ("Pivot", "pivot"),
        "S1 (Classic)": ("Support 1", "support"),
        "S2 (Classic)": ("Support 2", "support"),
        "S3 (Classic)": ("Support 3", "support"),
        "ATM IV term structure": (
            "ATM Implied Volatility Term Structure",
            "atm_implied_volatility",
        ),
    }
    assert {row["metric"] for row in rows} == set(expected)
    labels = widget["data"]["table"]["rowLabels"]
    glossary = widget["data"]["metricGlossary"]
    for raw, (rendered, key) in expected.items():
        assert labels[raw] == rendered
        assert glossary[raw] == key


def test_1996_forecast_endpoint_emits_canonical_glossary_backed_rows() -> None:
    widget = _widget("pi_equity_analyst_forecasts")
    response = _CLIENT.get("/pi/equity/analyst-forecasts?symbol=AAPL")
    assert response.status_code == 200
    labels = {row["metric"] for row in response.json()}
    expected = {
        "12-Month Price Target": "twelve_month_price_target",
        "Target Range": "target_range",
        "Upside vs Current Price": "implied_upside",
        "Rating Distribution": "rating_distribution",
        "EPS Surprise": "eps_surprise",
        "Historical Revenue Estimate": "revenue_estimate",
    }
    assert set(expected) <= labels
    glossary = widget["data"]["metricGlossary"]
    assert glossary == expected
    assert widget["data"]["table"]["rowLabels"] == {label: label for label in expected}


def test_time_series_widgets_have_exact_labels_and_glossary_keys() -> None:
    expected = {
        "pi_price_target_history": (
            {
                "date": "Date",
                "close": "Closing Price",
                "target": "Analyst Price Target",
            },
            {
                "Closing Price": "closing_price",
                "Analyst Price Target": "analyst_price_target",
            },
        ),
        "pi_risk_vol_chart": (
            {"vol_20d": "20-Day Volatility", "vol_60d": "60-Day Volatility"},
            {
                "20-Day Volatility": "twenty_day_volatility",
                "60-Day Volatility": "sixty_day_volatility",
            },
        ),
        "pi_paper_performance": (
            {"date": "Date", "equity": "Portfolio Equity"},
            {"Portfolio Equity": "portfolio_equity"},
        ),
    }
    for widget_id, (labels, glossary) in expected.items():
        data = _widget(widget_id)["data"]
        assert data["chart"]["labels"] == labels
        assert data["metricGlossary"] == glossary


def test_glossary_records_are_specific_and_link_to_term_pages() -> None:
    text = _VIEWER.read_text(encoding="utf-8")
    assert "A curated portfolio-analysis term" not in text
    assert "financial-term-dictionary" not in text
    records = _widgets()["pi_equity_analyst_forecasts"]["data"]["metricGlossary"]
    for key in records.values():
        marker = f"{key}: Object.freeze({{"
        record = text[text.index(marker) : text.index("    }),", text.index(marker))]
        assert (
            "summary:" in record
            and "definition:" in record
            and "interpretation:" in record
        )
        assert 'source: "https://www.investopedia.com/terms/' in record
