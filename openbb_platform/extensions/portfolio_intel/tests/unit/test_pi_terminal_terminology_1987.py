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
