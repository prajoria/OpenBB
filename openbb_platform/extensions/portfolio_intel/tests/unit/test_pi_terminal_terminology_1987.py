"""Focused Terminal terminology contracts for #1987 child widgets."""

from __future__ import annotations

import json
from pathlib import Path


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_WIDGETS = _PACKAGE_ROOT / "openbb_portfolio_intel" / "widget_backend" / "widgets.json"
_VIEWER = (
    _PACKAGE_ROOT.parent
    / "portfolio"
    / "assets"
    / "local_viewer"
    / "index.html"
)


def _widget(widget_id: str) -> dict:
    return json.loads(_WIDGETS.read_text(encoding="utf-8"))[widget_id]


def test_1988_key_stats_maps_only_approved_glossary_terms() -> None:
    widget = _widget("pi_equity_key_stats")
    glossary = widget["data"]["metricGlossary"]
    assert {term: glossary[term] for term in ("Volume", "52-Week High", "52-Week Low")} == {
        "Volume": "volume",
        "52-Week High": "fifty_two_week_high",
        "52-Week Low": "fifty_two_week_low",
    }
    viewer = _VIEWER.read_text(encoding="utf-8")
    for key in glossary.values():
        assert f"{key}: Object.freeze({{" in viewer


def test_1989_pi_financial_statements_terminology_contract() -> None:
    widget = _widget("pi_financial_statements")
    expected_fields = {'line_item': 'Line Item', 'period_1': 'Prior Period', 'period_2': 'Latest Period'}
    expected_terms = ['Revenue', 'Gross Profit', 'Operating Income', 'Net Income', 'Total Assets', 'Total Debt', 'Cash & Equivalents', 'Operating Cash Flow', 'Free Cash Flow']
    data = widget.get("data", {})
    if expected_fields:
        assert {c["field"]: c["headerName"] for c in data["table"]["columnsDefs"]} == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_1990_pi_peer_multiples_terminology_contract() -> None:
    widget = _widget("pi_peer_multiples")
    expected_fields = {'symbol': 'Symbol', 'pe_ttm': 'P/E (TTM)', 'pe_fwd': 'P/E (Forward)', 'ev_ebitda': 'EV/EBITDA', 'ps_ttm': 'P/S (TTM)'}
    expected_terms = ['P/E (TTM)', 'P/E (Forward)', 'EV/EBITDA', 'P/S (TTM)']
    data = widget.get("data", {})
    if expected_fields:
        assert {c["field"]: c["headerName"] for c in data["table"]["columnsDefs"]} == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_1991_pi_earnings_history_terminology_contract() -> None:
    widget = _widget("pi_earnings_history")
    expected_fields = {'quarter': 'Quarter', 'eps_actual': 'Actual EPS', 'eps_estimate': 'Estimated EPS', 'surprise_pct': 'Surprise (%)'}
    expected_terms = ['Actual EPS', 'Estimated EPS', 'Earnings Surprise']
    data = widget.get("data", {})
    if expected_fields:
        assert {c["field"]: c["headerName"] for c in data["table"]["columnsDefs"]} == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_1992_pi_price_target_history_terminology_contract() -> None:
    widget = _widget("pi_price_target_history")
    expected_fields = {'date': 'Date', 'close': 'Closing Price', 'target': 'Analyst Price Target'}
    expected_terms = ['Closing Price', 'Analyst Price Target']
    data = widget.get("data", {})
    if expected_fields:
        assert data["chart"]["labels"] == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_1993_pi_equity_technicals_terminology_contract() -> None:
    widget = _widget("pi_equity_technicals")
    expected_fields = {}
    expected_terms = ['Analyst Consensus', 'Resistance', 'Pivot', 'Support', 'ATM Implied Volatility']
    data = widget.get("data", {})
    if expected_fields:
        assert {c["field"]: c["headerName"] for c in data["table"]["columnsDefs"]} == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_1994_pi_equity_competitors_terminology_contract() -> None:
    widget = _widget("pi_equity_competitors")
    expected_fields = {'symbol': 'Symbol', 'name': 'Company', 'price': 'Price', 'change_pct': 'Change (%)'}
    expected_terms = ['Percentage Price Change']
    data = widget.get("data", {})
    if expected_fields:
        assert {c["field"]: c["headerName"] for c in data["table"]["columnsDefs"]} == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_1995_pi_equity_complementary_terminology_contract() -> None:
    widget = _widget("pi_equity_complementary")
    expected_fields = {'kind': 'Asset Type', 'id': 'Identifier', 'name': 'Name', 'weight_pct': 'Portfolio Weight (%)', 'value_usd': 'Market Value ($)'}
    expected_terms = ['Portfolio Weight', 'Market Value']
    data = widget.get("data", {})
    if expected_fields:
        assert {c["field"]: c["headerName"] for c in data["table"]["columnsDefs"]} == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_1996_pi_equity_analyst_forecasts_terminology_contract() -> None:
    widget = _widget("pi_equity_analyst_forecasts")
    expected_fields = {}
    expected_terms = ['12-Month Price Target', 'Target Range', 'Implied Upside', 'Rating Distribution', 'EPS Surprise', 'Revenue Estimate']
    data = widget.get("data", {})
    if expected_fields:
        assert {c["field"]: c["headerName"] for c in data["table"]["columnsDefs"]} == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_1997_pi_basket_analyst_consensus_terminology_contract() -> None:
    widget = _widget("pi_basket_analyst_consensus")
    expected_fields = {'symbol': 'Symbol', 'avg_target': 'Average Price Target', 'buy_hold_sell': 'Buy/Hold/Sell Ratings', 'consensus': 'Consensus Rating'}
    expected_terms = ['Average Price Target', 'Consensus Rating']
    data = widget.get("data", {})
    if expected_fields:
        assert {c["field"]: c["headerName"] for c in data["table"]["columnsDefs"]} == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_1998_pi_lookthrough_top25_terminology_contract() -> None:
    widget = _widget("pi_lookthrough_top25")
    expected_fields = {'symbol': 'Symbol', 'name': 'Holding', 'effective_weight': 'Effective Weight (%)', 'rank': 'Rank'}
    expected_terms = ['Effective Weight']
    data = widget.get("data", {})
    if expected_fields:
        assert {c["field"]: c["headerName"] for c in data["table"]["columnsDefs"]} == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_1999_pi_concentration_gauge_terminology_contract() -> None:
    widget = _widget("pi_concentration_gauge")
    expected_fields = {'value': 'Concentration (HHI)'}
    expected_terms = ['Herfindahl-Hirschman Index']
    data = widget.get("data", {})
    if expected_fields:
        assert data["metric"]["labels"] == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_2000_pi_risk_dashboard_terminology_contract() -> None:
    widget = _widget("pi_risk_dashboard")
    expected_fields = {'vol_annualized': 'Annualized Volatility', 'var_95_1d': '1-Day VaR (95%)', 'beta_spy': 'Beta vs SPY'}
    expected_terms = ['Annualized Volatility', '1-Day VaR (95%)', 'Beta vs SPY']
    data = widget.get("data", {})
    if expected_fields:
        assert data["metric"]["labels"] == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_2001_pi_risk_vol_chart_terminology_contract() -> None:
    widget = _widget("pi_risk_vol_chart")
    expected_fields = {}
    expected_terms = ['20-Day Volatility', '60-Day Volatility']
    data = widget.get("data", {})
    if expected_fields:
        assert data["chart"]["labels"] == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_2002_pi_brinson_attribution_terminology_contract() -> None:
    widget = _widget("pi_brinson_attribution")
    expected_fields = {'sector': 'Sector', 'allocation': 'Allocation Effect', 'selection': 'Selection Effect', 'interaction': 'Interaction Effect', 'total': 'Total Active Return'}
    expected_terms = ['Allocation Effect', 'Selection Effect', 'Interaction Effect', 'Total Active Return']
    data = widget.get("data", {})
    if expected_fields:
        assert data["chart"]["labels"] == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]


def test_2003_pi_whatif_card_terminology_contract() -> None:
    widget = _widget("pi_whatif_card")
    expected_fields = {}
    expected_terms = ['Symbol Weight', 'Sector Weight', 'Cash Weight', 'Beta vs SPY']
    data = widget.get("data", {})
    if expected_fields:
        assert {c["field"]: c["headerName"] for c in data["table"]["columnsDefs"]} == expected_fields
    glossary = data.get("metricGlossary", {})
    for term in expected_terms:
        assert glossary[term]
