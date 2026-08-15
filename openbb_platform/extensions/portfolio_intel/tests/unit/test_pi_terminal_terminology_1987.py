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
