"""Load-bearing Terminal terminology contracts for #1987 child widgets."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

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


def test_1996_forecast_endpoint_keeps_raw_contract_with_pattern_metadata() -> None:
    widget = _widget("pi_equity_analyst_forecasts")
    response = _CLIENT.get("/pi/equity/analyst-forecasts?symbol=AAPL")
    assert response.status_code == 200
    labels = {row["metric"] for row in response.json()}
    assert {
        "1Y target (consensus)",
        "Target range",
        "Upside vs current",
        "Rating: Strong Buy / Buy",
        "Rating: Hold / Sell / Strong Sell",
        "Q3 2025 EPS Surprise",
        "Q2 2025 EPS Surprise",
    } <= labels
    table = widget["data"]["table"]
    assert table["rowLabels"] == {
        "1Y target (consensus)": "12-Month Price Target",
        "Target range": "Target Range",
        "Upside vs current": "Upside vs Current Price",
        "Historical rev estimate (last Q)": "Historical Revenue Estimate",
    }
    assert table["rowLabelPatterns"] == [
        {
            "pattern": r"^Rating:\s*(.+)$",
            "labelTemplate": "Rating Distribution: $1",
            "glossaryKey": "rating_distribution",
        },
        {
            "pattern": r"^(Q\d\s+\d{4})\s+EPS Surprise$",
            "labelTemplate": "$1 EPS Surprise",
            "glossaryKey": "eps_surprise",
        },
    ]


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
        assert 'source: "https://' in record


@pytest.mark.parametrize(
    ("widget_id", "labels", "glossary"),
    [
        (
            "pi_equity_key_stats",
            {},
            {
                "Volume": "volume",
                "52-Week High": "fifty_two_week_high",
                "52-Week Low": "fifty_two_week_low",
            },
        ),
        (
            "pi_financial_statements",
            {
                "line_item": "Line Item",
                "period_1": "Latest Period",
                "period_2": "Prior Period",
            },
            {"Revenue": "revenue", "Free Cash Flow": "free_cash_flow"},
        ),
        (
            "pi_peer_multiples",
            {
                "symbol": "Symbol",
                "pe_ttm": "P/E (TTM)",
                "pe_fwd": "P/E (Forward)",
                "ev_ebitda": "EV/EBITDA",
                "ps_ttm": "P/S (TTM)",
            },
            {
                "P/E (TTM)": "pe_ttm",
                "P/E (Forward)": "pe_forward",
                "EV/EBITDA": "ev_ebitda",
                "P/S (TTM)": "ps_ttm",
            },
        ),
        (
            "pi_earnings_history",
            {
                "quarter": "Quarter",
                "eps_actual": "Actual EPS",
                "eps_estimate": "Estimated EPS",
                "surprise_pct": "Surprise (%)",
            },
            {
                "Actual EPS": "actual_eps",
                "Estimated EPS": "estimated_eps",
                "Surprise (%)": "earnings_surprise",
            },
        ),
        (
            "pi_dividend_payment",
            {
                "ex_date": "Ex-Dividend Date",
                "payment_date": "Payment Date",
                "amount": "Dividend Amount ($/share)",
            },
            {
                "Ex-Dividend Date": "ex_dividend_date",
                "Dividend Amount ($/share)": "dividend_amount_per_share",
            },
        ),
        (
            "pi_price_target_history",
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
        (
            "pi_equity_technicals",
            {
                "Consensus": "Analyst Consensus",
                "R3 (Classic)": "Resistance 3",
                "P (Classic)": "Pivot",
                "S3 (Classic)": "Support 3",
            },
            {
                "R3 (Classic)": "resistance",
                "P (Classic)": "pivot",
                "S3 (Classic)": "support",
            },
        ),
        (
            "pi_equity_competitors",
            {
                "symbol": "Symbol",
                "name": "Company",
                "price": "Price",
                "change_pct": "Change (%)",
            },
            {"Change (%)": "percentage_price_change"},
        ),
        (
            "pi_equity_complementary",
            {
                "kind": "Asset Type",
                "id": "Identifier",
                "name": "Name",
                "weight_pct": "Portfolio Weight (%)",
                "value_usd": "Market Value ($)",
            },
            {
                "Portfolio Weight (%)": "portfolio_weight",
                "Market Value ($)": "market_value",
            },
        ),
        (
            "pi_equity_analyst_forecasts",
            {
                "1Y target (consensus)": "12-Month Price Target",
                "Target range": "Target Range",
                "Upside vs current": "Upside vs Current Price",
            },
            {
                "Rating Distribution": "rating_distribution",
                "EPS Surprise": "eps_surprise",
                "Historical Revenue Estimate": "revenue_estimate",
            },
        ),
        (
            "pi_basket_analyst_consensus",
            {
                "symbol": "Symbol",
                "avg_target": "Average Price Target",
                "buy": "Buy Ratings",
                "hold": "Hold Ratings",
                "sell": "Sell Ratings",
                "consensus": "Consensus Rating",
            },
            {
                "Average Price Target": "average_price_target",
                "Consensus Rating": "consensus_rating",
            },
        ),
        (
            "pi_lookthrough_top25",
            {
                "symbol": "Symbol",
                "name": "Holding",
                "effective_weight": "Effective Weight (%)",
                "rank": "Rank",
            },
            {"Effective Weight (%)": "effective_weight"},
        ),
        (
            "pi_concentration_gauge",
            {"value": "Concentration (HHI)"},
            {"Concentration (HHI)": "herfindahl_hirschman_index"},
        ),
        (
            "pi_risk_dashboard",
            {
                "vol_annualized": "Annualized Volatility",
                "var_95_1d": "1-Day VaR (95%)",
                "beta_spy": "Beta vs SPY",
            },
            {
                "Annualized Volatility": "annualized_volatility",
                "1-Day VaR (95%)": "one_day_var_95",
                "Beta vs SPY": "beta_vs_spy",
            },
        ),
        (
            "pi_risk_vol_chart",
            {"vol_20d": "20-Day Volatility", "vol_60d": "60-Day Volatility"},
            {
                "20-Day Volatility": "twenty_day_volatility",
                "60-Day Volatility": "sixty_day_volatility",
            },
        ),
        (
            "pi_brinson_attribution",
            {
                "sector": "Sector",
                "allocation": "Allocation Effect",
                "selection": "Selection Effect",
                "interaction": "Interaction Effect",
                "total": "Total Active Return",
            },
            {
                "Allocation Effect": "allocation_effect",
                "Selection Effect": "selection_effect",
                "Interaction Effect": "interaction_effect",
                "Total Active Return": "total_active_return",
            },
        ),
        (
            "pi_whatif_card",
            {
                "symbol_weight_%": "Symbol Weight (%)",
                "sector_weight_%": "Sector Weight (%)",
                "cash_%": "Cash Weight (%)",
                "beta_spy": "Beta vs SPY",
            },
            {
                "symbol_weight_%": "symbol_weight",
                "sector_weight_%": "sector_weight",
                "cash_%": "cash_weight",
                "beta_spy": "beta_vs_spy",
            },
        ),
        (
            "pi_paper_perf_kpis",
            {
                "total_return_pct": "Total Return (%)",
                "sharpe_annualized": "Annualized Sharpe Ratio",
                "max_drawdown_pct": "Maximum Drawdown (%)",
            },
            {
                "Total Return (%)": "total_return",
                "Annualized Sharpe Ratio": "sharpe_ratio",
                "Maximum Drawdown (%)": "maximum_drawdown",
            },
        ),
        (
            "pi_paper_performance",
            {"date": "Date", "equity": "Portfolio Equity"},
            {"Portfolio Equity": "portfolio_equity"},
        ),
        (
            "pi_paper_blotter",
            {
                "time": "Time",
                "symbol": "Symbol",
                "side": "Side",
                "qty": "Quantity",
                "status": "Status",
                "avg_price": "Average Execution Price",
            },
            {"Average Execution Price": "average_execution_price"},
        ),
        (
            "pi_smart_money_ribbon",
            {
                "symbol": "Symbol",
                "kind": "Activity Type",
                "actor": "Actor",
                "value_usd": "Transaction Value ($)",
                "date": "Date",
            },
            {"Transaction Value ($)": "transaction_value"},
        ),
    ],
)
def test_all_21_widgets_have_exact_label_and_glossary_contracts(
    widget_id: str, labels: dict[str, str], glossary: dict[str, str]
) -> None:
    widget = _widget(widget_id)
    data = widget["data"]
    if widget["type"] == "metric":
        actual_labels = data["metric"]["labels"]
        actual_glossary = data["metric"]["metricGlossary"]
    elif widget["type"] == "chart":
        actual_labels = data["chart"]["labels"]
        actual_glossary = data["metricGlossary"]
    elif "rowLabels" in data.get("table", {}):
        actual_labels = data["table"]["rowLabels"]
        actual_glossary = data["metricGlossary"]
    elif "columnsDefs" in data.get("table", {}):
        actual_labels = {
            column["field"]: column["headerName"]
            for column in data["table"]["columnsDefs"]
        }
        actual_glossary = data["metricGlossary"]
    else:
        actual_labels = {}
        actual_glossary = data["metricGlossary"]
    for raw, label in labels.items():
        assert actual_labels[raw] == label
    for label, key in glossary.items():
        assert actual_glossary[label] == key


def test_1997_basket_consensus_columns_match_endpoint_shape() -> None:
    """The renderer must request only fields emitted by the endpoint."""
    widget = _widget("pi_basket_analyst_consensus")
    response = _CLIENT.get("/pi/equity/basket-analyst-consensus?basket_id=demo")
    assert response.status_code == 200
    rows = response.json()
    fields = {column["field"] for column in widget["data"]["table"]["columnsDefs"]}
    assert fields == {"symbol", "avg_target", "buy", "hold", "sell", "consensus"}
    assert all(fields <= set(row) for row in rows)
    assert "buy_hold_sell" not in fields
    consensus = next(
        row["consensus"] for row in rows if row["consensus"] == "STRONG_BUY"
    )
    assert consensus == "STRONG_BUY"
    mapping = next(
        column["valueLabels"]
        for column in widget["data"]["table"]["columnsDefs"]
        if column["field"] == "consensus"
    )
    assert mapping == {"STRONG_BUY": "Strong Buy"}


def test_2007_smart_money_activity_labels_are_explicit() -> None:
    widget = _widget("pi_smart_money_ribbon")
    response = _CLIENT.get("/pi/smart-money/ribbon?account_id=demo")
    assert response.status_code == 200
    assert {row["kind"] for row in response.json()} == {
        "insider_buy",
        "13F_increase",
        "insider_sell",
    }
    kind_column = next(
        column
        for column in widget["data"]["table"]["columnsDefs"]
        if column["field"] == "kind"
    )
    assert kind_column["valueLabels"] == {
        "insider_buy": "Insider Buy",
        "13F_increase": "13F Increase",
        "insider_sell": "Insider Sell",
    }


def test_all_glossary_sources_are_https_non_generic_and_curated() -> None:
    text = _VIEWER.read_text(encoding="utf-8")
    sources = [
        source for source in __import__("re").findall(r'source: "([^"]+)"', text)
    ]
    assert len(sources) >= 64
    allowed_hosts = {
        "www.investopedia.com",
        "en.wikipedia.org",
        "www.cfainstitute.org",
    }
    for source in sources:
        parsed = urlparse(source)
        assert parsed.scheme == "https"
        assert parsed.netloc in allowed_hosts
        assert "financial-term-dictionary" not in parsed.path


def test_dividend_payment_glossary_records_are_curated_and_https() -> None:
    text = _VIEWER.read_text(encoding="utf-8")
    for key, label, summary, source in (
        (
            "ex_dividend_date",
            "Ex-Dividend Date",
            "First trading day when a buyer is not entitled to the next dividend.",
            "https://www.investopedia.com/terms/e/ex-dividend.asp",
        ),
        (
            "dividend_amount_per_share",
            "Dividend Amount per Share",
            "Cash dividend declared for each share.",
            "https://www.investopedia.com/terms/d/dividend.asp",
        ),
    ):
        marker = f"{key}: Object.freeze({{"
        record = text[text.index(marker) : text.index("    }),", text.index(marker))]
        assert label in record
        assert summary in record
        assert f'source: "{source}"' in record


def test_2010_key_stats_columns_match_endpoint_shape() -> None:
    """Key-stat labels must be explicit without changing the endpoint rows."""
    widget = _widget("pi_equity_key_stats")
    response = _CLIENT.get("/pi/equity/key-stats?symbol=AAPL")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("metric", "Financial Metric"),
        ("value", "Value"),
    ]
    assert rows and all({"metric", "value"} <= set(row) for row in rows)


def test_2011_technicals_columns_match_endpoint_shape() -> None:
    """Technical rows retain their endpoint fields under explicit headers."""
    widget = _widget("pi_equity_technicals")
    response = _CLIENT.get("/pi/equity/technicals?symbol=AAPL")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("metric", "Technical Indicator"),
        ("value", "Value"),
        ("note", "Interpretation"),
    ]
    assert rows and all({"metric", "value", "note"} <= set(row) for row in rows)


def test_2012_event_calendar_columns_and_values_match_endpoint_shape() -> None:
    """Calendar metadata must label the raw event types emitted by its endpoint."""
    widget = _widget("pi_event_calendar")
    response = _CLIENT.get("/pi/events/calendar?account_id=demo&horizon_days=14")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("symbol", "Symbol"),
        ("type", "Event Type"),
        ("date", "Event Date"),
        ("detail", "Details"),
    ]
    event_type = columns[1]
    assert event_type["glossaryKey"] == "event_type"
    assert event_type["valueLabels"] == {
        "ex_dividend": "Ex-Dividend",
        "form_8k": "Form 8-K",
    }
    assert {"ex_dividend", "form_8k"} <= {row["type"] for row in rows}


def test_2013_forecast_columns_match_endpoint_shape() -> None:
    """Forecast metadata must preserve the endpoint's metric/value/note rows."""
    widget = _widget("pi_equity_analyst_forecasts")
    response = _CLIENT.get("/pi/equity/analyst-forecasts?symbol=AAPL")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("metric", "Forecast Measure"),
        ("value", "Value"),
        ("note", "Context"),
    ]
    assert rows and all({"metric", "value", "note"} <= set(row) for row in rows)


def test_2014_whatif_columns_match_endpoint_shape() -> None:
    """What-if presentation labels must preserve before/after endpoint values."""
    widget = _widget("pi_whatif_card")
    response = _CLIENT.get("/pi/whatif/card?symbol=AAPL&delta_shares=100")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("metric", "Portfolio Metric"),
        ("before", "Before Trade"),
        ("after", "After Trade"),
        ("delta", "Change"),
    ]
    assert rows and all(
        {"metric", "before", "after", "delta"} <= set(row) for row in rows
    )


def test_2015_alert_columns_and_values_match_endpoint_shape() -> None:
    """Alert labels must map the endpoint's explicit alert category values."""
    widget = _widget("pi_alerts_panel")
    response = _CLIENT.get("/pi/alerts?account_id=demo")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("severity", "Severity"),
        ("kind", "Alert Type"),
        ("symbol", "Symbol"),
        ("detail", "Details"),
    ]
    alert_type = columns[1]
    assert alert_type["glossaryKey"] == "alert_type"
    assert alert_type["valueLabels"] == {
        "form_8k_for_held": "Held-Security Form 8-K",
        "earnings_upcoming": "Upcoming Earnings",
        "news_material": "Material News",
    }
    assert set(alert_type["valueLabels"]) <= {row["kind"] for row in rows}


def test_2016_news_columns_match_endpoint_shape_without_glossary() -> None:
    """News operational fields are explicit labels, not glossary concepts."""
    widget = _widget("pi_news_ribbon")
    response = _CLIENT.get("/pi/news?account_id=demo&horizon_days=7")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("symbol", "Symbol"),
        ("when", "Published"),
        ("title", "Headline"),
        ("severity", "Severity"),
    ]
    assert all("glossaryKey" not in column for column in columns)
    assert rows and all(
        {"symbol", "when", "title", "severity"} <= set(row) for row in rows
    )


def test_2017_sentiment_label_and_glossary_match_endpoint_shape() -> None:
    """Sentiment metadata must relabel, but not change, the endpoint value."""
    widget = _widget("pi_sentiment_gauge")
    response = _CLIENT.get("/pi/sentiment?account_id=demo")
    assert response.status_code == 200
    payload = response.json()
    metric = widget["data"]["metric"]
    assert metric == {
        "labels": {"value": "News Sentiment Score (-1 to +1)"},
        "metricGlossary": {"News Sentiment Score (-1 to +1)": "news_sentiment_score"},
    }
    assert payload["label"] == "Sentiment (-1..+1)"
    assert -1 <= payload["value"] <= 1
