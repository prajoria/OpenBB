"""F0 T0.3-T0.6 tests: context bars + default-layout pass + terminal shell smoke.

Covers:

- **#1638** — ``pi_symbol_context`` widget declared in ``widgets.json``,
  endpoint ``/pi/context/symbol`` returns markdown, symbol allowlisted
  via the shared ``_SYMBOL_RE``.
- **#1639** — ``pi_book_context`` widget declared in ``widgets.json``,
  endpoint ``/pi/context/book`` returns markdown, account_id allowlisted
  via the shared ``_ACCOUNT_ID_RE``.
- **#1640** — every F1..F7 tab in the terminal app has the symbol context
  bar as its first slot; every F8..F11 tab has the book context bar as
  its first slot; every layout has sensible non-overlapping default
  positions (no two slots share the exact same (x, y, w, h)).
- **#1641** — Playwright-substitute smoke: each tab in the terminal app
  has at least the minimum expected widget count (per tab spec) and
  every widget id resolves to a real widgets.json entry. This is the
  headless equivalent of "each tab renders N widgets, 0 blank" — a real
  Playwright test would need a running Workspace instance and is
  documented as follow-up.
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


def _apps() -> list:
    apps = json.loads((_MANIFEST_DIR / "apps.json").read_text(encoding="utf-8"))
    return apps if isinstance(apps, list) else list(apps.values())


def _terminal() -> dict:
    for a in _apps():
        if a.get("id") == "portfolio-intelligence-terminal":
            return a
    return {}


# ---------------------------------------------------------------------------
# #1638 — Symbol context bar
# ---------------------------------------------------------------------------


def test_symbol_context_widget_declared() -> None:
    """widgets.json declares pi_symbol_context with markdown type + symbol param."""
    w = _widgets().get("pi_symbol_context")
    assert w is not None, "pi_symbol_context missing from widgets.json"
    assert w["type"] == "markdown"
    assert w["endpoint"] == "pi/context/symbol"
    params = {p["paramName"] for p in w.get("params", [])}
    assert "symbol" in params, "symbol context bar must expose a symbol param"


def test_symbol_context_endpoint_returns_markdown() -> None:
    """/pi/context/symbol returns markdown echoing the ticker."""
    r = _client.get("/pi/context/symbol?symbol=NVDA")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, str)
    assert "NVDA" in body


def test_symbol_context_rejects_bad_ticker() -> None:
    """Shared _SYMBOL_RE gate — reject XSS/HTML-shaped input."""
    for bad in ("<script>", "A;B", "sym bol", "A" * 20):
        r = _client.get(f"/pi/context/symbol?symbol={bad}")
        assert r.status_code == 400, f"{bad!r} accepted; must be rejected"


def test_symbol_context_accepts_dotted_dashed_tickers() -> None:
    """Allowlist covers real-world tickers (BRK.B, BF-A)."""
    for good in ("AAPL", "BRK.B", "BF-A", "GOOG"):
        r = _client.get(f"/pi/context/symbol?symbol={good}")
        assert r.status_code == 200, f"{good!r} rejected"


# ---------------------------------------------------------------------------
# #1639 — Book context bar
# ---------------------------------------------------------------------------


def test_book_context_widget_declared() -> None:
    """widgets.json declares pi_book_context with markdown type + account_id param."""
    w = _widgets().get("pi_book_context")
    assert w is not None, "pi_book_context missing from widgets.json"
    assert w["type"] == "markdown"
    assert w["endpoint"] == "pi/context/book"
    params = {p["paramName"] for p in w.get("params", [])}
    assert "account_id" in params, "book context bar must expose an account_id param"


def test_book_context_endpoint_returns_markdown() -> None:
    """/pi/context/book returns markdown echoing the account_id."""
    r = _client.get("/pi/context/book?account_id=demo")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, str)
    assert "demo" in body


def test_book_context_rejects_bad_account_id() -> None:
    """Shared _ACCOUNT_ID_RE gate — reject shell metacharacters."""
    for bad in ("demo;rm", "book$(x)", "a b", "x" * 200):
        r = _client.get(f"/pi/context/book?account_id={bad}")
        assert r.status_code == 400, f"{bad!r} accepted; must be rejected"


def test_book_context_accepts_safe_account_ids() -> None:
    """Allowlist covers realistic account identifiers."""
    for good in ("demo", "paper_1", "acct-42", "prod.book.v2"):
        r = _client.get(f"/pi/context/book?account_id={good}")
        assert r.status_code == 200, f"{good!r} rejected"


# ---------------------------------------------------------------------------
# #1640 — Default-layout pass (context bar wired into every tab)
# ---------------------------------------------------------------------------

_RESEARCH_TABS = (
    "overview",
    "financials",
    "technicals",
    "comparison",
    "ownership",
    "calendar",
    "estimates",
)
_PORTFOLIO_TABS = ("xray", "risk", "paper", "alerts")


def test_every_research_tab_starts_with_symbol_context() -> None:
    """F1..F7 tabs must include pi_symbol_context as the first slot (y == 0)."""
    tabs = _terminal().get("tabs", {})
    for tid in _RESEARCH_TABS:
        tab = tabs.get(tid, {})
        layout = tab.get("layout", [])
        assert layout, f"tab {tid!r} has empty layout"
        # First slot (top of tab) must be the symbol context bar.
        top = min(layout, key=lambda s: (s.get("y", 0), s.get("x", 0)))
        assert top["i"] == "pi_symbol_context", (
            f"tab {tid!r} missing symbol context bar as first slot;"
            f" got {top['i']!r}"
        )


def test_every_portfolio_tab_starts_with_book_context() -> None:
    """F8..F11 tabs must include pi_book_context as the first slot."""
    tabs = _terminal().get("tabs", {})
    for tid in _PORTFOLIO_TABS:
        tab = tabs.get(tid, {})
        layout = tab.get("layout", [])
        assert layout, f"tab {tid!r} has empty layout"
        top = min(layout, key=lambda s: (s.get("y", 0), s.get("x", 0)))
        assert top["i"] == "pi_book_context", (
            f"tab {tid!r} missing book context bar as first slot;" f" got {top['i']!r}"
        )


def test_no_layout_slot_overlap_within_a_tab() -> None:
    """Same (x, y, w, h) on two slots = they render on top of each other."""
    tabs = _terminal().get("tabs", {})
    for tid, tab in tabs.items():
        seen: set[tuple] = set()
        for slot in tab.get("layout", []):
            key = (slot["x"], slot["y"], slot["w"], slot["h"])
            assert (
                key not in seen
            ), f"tab {tid!r} has two slots at identical position {key}"
            seen.add(key)


# ---------------------------------------------------------------------------
# #1641 — Playwright-substitute layout smoke
# ---------------------------------------------------------------------------

_MIN_WIDGETS_PER_TAB = {
    "overview": 2,  # context + at least one profile widget
    "financials": 2,
    "technicals": 2,
    "comparison": 2,
    "ownership": 2,
    "calendar": 2,
    "estimates": 2,
    "xray": 2,
    "risk": 2,
    "paper": 2,
    "alerts": 2,
}


def test_terminal_app_has_all_expected_tabs() -> None:
    """Every research + portfolio tab id exists in the terminal app."""
    tabs = set(_terminal().get("tabs", {}).keys())
    expected = set(_RESEARCH_TABS) | set(_PORTFOLIO_TABS)
    missing = expected - tabs
    assert not missing, f"terminal app missing tabs: {missing!r}"


def test_each_tab_meets_minimum_widget_count() -> None:
    """Layout-smoke substitute: each tab has >= min expected widget count."""
    tabs = _terminal().get("tabs", {})
    for tid, tab in tabs.items():
        n = len(tab.get("layout", []))
        expected = _MIN_WIDGETS_PER_TAB.get(tid, 1)
        assert n >= expected, (
            f"tab {tid!r} has {n} widgets, expected >= {expected}"
            f" (Playwright-substitute smoke, see #1641)"
        )


def test_every_widget_ref_in_every_tab_resolves() -> None:
    """No unknown widget id in any layout slot (else Workspace renders blank)."""
    known = set(_widgets().keys())
    for tid, tab in _terminal().get("tabs", {}).items():
        for slot in tab.get("layout", []):
            assert slot["i"] in known, (
                f"tab {tid!r} references unknown widget id {slot['i']!r};"
                f" known: {sorted(known)}"
            )


def test_context_endpoints_are_registered_routes() -> None:
    """Manifest ↔ FastAPI route parity for the new context endpoints."""
    routes = {r.path for r in app.routes}
    assert "/pi/context/symbol" in routes
    assert "/pi/context/book" in routes
