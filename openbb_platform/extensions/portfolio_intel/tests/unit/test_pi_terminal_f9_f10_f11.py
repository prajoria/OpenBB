"""F9 + F10 + F11 tab-layout tests (regression-lock).

Covers three "composition only" sub-tasks — all widgets already exist
in widgets.json since day one; each issue requires the correct set of
widgets to be laid out on its respective tab.

- **#1673 T9.1** — F9 Risk tab must include: pi_risk_dashboard,
  pi_risk_vol_chart, pi_brinson_attribution, pi_whatif_card,
  pi_whatif_diff.
- **#1675 T10.1** — F10 Paper Trading Desk tab must include:
  pi_paper_ticket, pi_paper_blotter, pi_paper_performance,
  pi_paper_perf_kpis, pi_backtest_button.
- **#1677 T11.1** — F11 Alerts & Catalysts tab must include:
  pi_event_calendar, pi_smart_money_ribbon, pi_news_ribbon,
  pi_sentiment_gauge, pi_alerts_panel.

These tests lock the tab compositions so any future refactor that
drops one of the required widgets fails loudly at PR time.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

_APPS_JSON = (
    Path(__file__).resolve().parents[2]
    / "openbb_portfolio_intel"
    / "widget_backend"
    / "apps.json"
)


def _tab_widget_ids(tab_id: str) -> set[str]:
    apps = json.loads(_APPS_JSON.read_text(encoding="utf-8"))
    term = [a for a in apps if a.get("id") == "portfolio-intelligence-terminal"][0]
    return {slot["i"] for slot in term["tabs"][tab_id]["layout"]}


# ---------------------------------------------------------------------------
# #1673 — F9 Risk & Attribution tab
# ---------------------------------------------------------------------------

_F9_REQUIRED = {
    "pi_risk_dashboard",
    "pi_risk_vol_chart",
    "pi_brinson_attribution",
    "pi_whatif_card",
    "pi_whatif_diff",
}


def test_f9_risk_tab_contains_all_required_widgets() -> None:
    """#1673 — F9 Risk tab must lay out all 5 required widgets."""
    ids = _tab_widget_ids("risk")
    missing = _F9_REQUIRED - ids
    assert not missing, f"F9 Risk tab missing required widgets: {missing}"


# ---------------------------------------------------------------------------
# #1675 — F10 Paper Trading Desk tab
# ---------------------------------------------------------------------------

_F10_REQUIRED = {
    "pi_paper_ticket",
    "pi_paper_blotter",
    "pi_paper_performance",
    "pi_paper_perf_kpis",
    "pi_backtest_button",
}


def test_f10_paper_tab_contains_all_required_widgets() -> None:
    """#1675 — F10 Paper tab must lay out all 5 required widgets."""
    ids = _tab_widget_ids("paper")
    missing = _F10_REQUIRED - ids
    assert not missing, f"F10 Paper tab missing required widgets: {missing}"


# ---------------------------------------------------------------------------
# #1677 — F11 Alerts & Catalysts tab
# ---------------------------------------------------------------------------

_F11_REQUIRED = {
    "pi_event_calendar",
    "pi_smart_money_ribbon",
    "pi_news_ribbon",
    "pi_sentiment_gauge",
    "pi_alerts_panel",
}


def test_f11_alerts_tab_contains_all_required_widgets() -> None:
    """#1677 — F11 Alerts tab must lay out all 5 required widgets."""
    ids = _tab_widget_ids("alerts")
    missing = _F11_REQUIRED - ids
    assert not missing, f"F11 Alerts tab missing required widgets: {missing}"


# ---------------------------------------------------------------------------
# Non-overlap invariant per tab (extends test_pi_terminal_t0_context guard)
# ---------------------------------------------------------------------------


def test_f9_f10_f11_tabs_have_no_slot_overlap() -> None:
    """Same (x, y, w, h) on two slots = one occludes the other."""
    apps = json.loads(_APPS_JSON.read_text(encoding="utf-8"))
    term = [a for a in apps if a.get("id") == "portfolio-intelligence-terminal"][0]
    for tid in ("risk", "paper", "alerts"):
        seen: set[tuple] = set()
        for slot in term["tabs"][tid]["layout"]:
            key = (slot["x"], slot["y"], slot["w"], slot["h"])
            assert key not in seen, f"tab {tid!r} has slot overlap at {key}"
            seen.add(key)
