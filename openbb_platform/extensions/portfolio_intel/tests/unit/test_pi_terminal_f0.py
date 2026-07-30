"""F0 shell / prereq-defect tests (#1632, #1633, plus F0 shell scaffolding).

Covers:

- **#1632** — every JSON response from the widget backend MUST advertise
  ``charset=utf-8`` in its ``Content-Type`` header so Workspace decodes
  em-dashes and other UTF-8 bytes correctly (no more ``â€"`` mojibake in
  widget/app titles).
- **#1633** — the two X-Ray pie widgets (``pi_xray_sector`` and
  ``pi_xray_country``) either return a Plotly figure dict OR carry a
  ``data.chart`` mapping in the widget spec that tells Workspace how to
  render the raw records as a pie. Empty-pane bug is fixed either way;
  this test enforces one of the two contracts is in place.
- **F0 shell (#1635-#1637)** — the ``portfolio-intelligence-terminal``
  eleven-tab app entry is declared in ``apps.json`` with both a symbol
  and a book context, and a top-level chrome test asserts every one of
  the eleven tabs is present.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)


def _read(name: str) -> dict:
    return json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "openbb_portfolio_intel"
            / "widget_backend"
            / name
        ).read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# #1632 — charset=utf-8 on every JSON response
# ---------------------------------------------------------------------------


def test_widgets_manifest_advertises_utf8() -> None:
    """``GET /widgets.json`` must serve ``Content-Type: application/json; charset=utf-8``."""
    r = _client.get("/widgets.json")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "").lower()
    assert "application/json" in ct and "charset=utf-8" in ct, (
        f"charset missing — got {ct!r}. Workspace will decode em-dashes as"
        f" mojibake without it. See #1632."
    )


def test_apps_manifest_advertises_utf8() -> None:
    """``GET /apps.json`` must serve UTF-8-tagged JSON (see #1632)."""
    r = _client.get("/apps.json")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "").lower()
    assert "charset=utf-8" in ct, f"charset missing on apps.json — got {ct!r}"


# ---------------------------------------------------------------------------
# #1633 — X-Ray pies render (either Plotly-fig OR data.chart mapping)
# ---------------------------------------------------------------------------


def _has_pie_chart_hint(widget_spec: dict) -> bool:
    """One of two acceptable contracts must be present.

    Contract A: widget declares a ``data.chart`` mapping with a pie shape.
    Contract B: widget's endpoint returns a Plotly figure dict (assertable
    at request time — see ``test_xray_endpoints_return_pie_hint`` below).
    """
    data = widget_spec.get("data") or {}
    chart = data.get("chart") or widget_spec.get("chart") or {}
    if not chart:
        return False
    ctype = (chart.get("type") or chart.get("chartType") or "").lower()
    if ctype != "pie":
        return False
    # Must name both the label column and the value column so Workspace
    # can wire the axes without guessing.
    label = chart.get("labelColumn") or chart.get("label")
    value = chart.get("valueColumn") or chart.get("value")
    return bool(label and value)


def test_xray_sector_declares_pie_chart_mapping() -> None:
    """#1633 — pi_xray_sector widget carries a pie chart mapping."""
    m = _read("widgets.json")
    spec = m.get("pi_xray_sector", {})
    assert _has_pie_chart_hint(spec), (
        "pi_xray_sector must carry chart.type=pie with labelColumn+valueColumn"
        " so Workspace knows how to render the raw sector/weight rows. See #1633."
    )


def test_xray_country_declares_pie_chart_mapping() -> None:
    """#1633 — pi_xray_country widget carries a pie chart mapping."""
    m = _read("widgets.json")
    spec = m.get("pi_xray_country", {})
    assert _has_pie_chart_hint(spec), (
        "pi_xray_country must carry chart.type=pie with labelColumn+valueColumn."
        " See #1633."
    )


# ---------------------------------------------------------------------------
# F0 shell — eleven-tab app entry in apps.json (#1635, #1636)
# ---------------------------------------------------------------------------


_TERMINAL_APP_ID = "portfolio-intelligence-terminal"

# Tab labels are the ones named in the EPIC #1634 body and F1..F11 issue
# titles. We match on substrings so cosmetic renaming (e.g. adding an
# emoji) does not break the test.
_EXPECTED_TAB_SUBSTRINGS = (
    "Overview",
    "Financials",
    "Technical",
    "Comparison",
    "Ownership",
    "Calendar",
    "Estimates",
    "X-Ray",
    "Risk",
    "Paper",
    "Alerts",
)


def test_terminal_app_declared() -> None:
    """#1636 — the ``portfolio-intelligence-terminal`` app is in apps.json."""
    apps = _read("apps.json")
    # apps.json is either a list-of-app-dicts or an object keyed by id.
    if isinstance(apps, dict) and "apps" in apps:
        entries = apps["apps"]
    elif isinstance(apps, list):
        entries = apps
    elif isinstance(apps, dict):
        # dict keyed by id -> use values
        entries = list(apps.values())
    else:
        entries = []
    ids = {
        (a.get("id") or a.get("appId") or "").lower()
        for a in entries
        if isinstance(a, dict)
    }
    assert (
        _TERMINAL_APP_ID in ids
    ), f"Portfolio Intelligence Terminal app entry missing. Got ids: {ids!r}."


def _terminal_entry() -> dict:
    apps = _read("apps.json")
    if isinstance(apps, dict) and "apps" in apps:
        entries = apps["apps"]
    elif isinstance(apps, list):
        entries = apps
    else:
        entries = list(apps.values()) if isinstance(apps, dict) else []
    for a in entries:
        if (
            isinstance(a, dict)
            and (a.get("id") or a.get("appId") or "").lower() == _TERMINAL_APP_ID
        ):
            return a
    return {}


def _tabs_of(entry: dict) -> list:
    """Normalize tabs to a list of dicts regardless of dict-vs-list shape."""
    tabs = entry.get("tabs")
    if isinstance(tabs, list):
        return tabs
    if isinstance(tabs, dict):
        return list(tabs.values())
    return []


def test_terminal_app_has_eleven_tabs() -> None:
    """#1635 — the app declares exactly eleven tabs, one per F1..F11."""
    e = _terminal_entry()
    tabs = _tabs_of(e)
    assert len(tabs) == 11, f"Terminal app must have 11 tabs (F1..F11); got {len(tabs)}"


def test_terminal_app_tab_labels_present() -> None:
    """#1635 — every expected tab label from the F1..F11 spec is present."""
    e = _terminal_entry()
    tabs = _tabs_of(e)
    tab_labels = " ".join(
        (t.get("name") or t.get("label") or t.get("title") or "") for t in tabs
    )
    for sub in _EXPECTED_TAB_SUBSTRINGS:
        assert (
            sub in tab_labels
        ), f"tab label {sub!r} missing from terminal app; got: {tab_labels!r}"


def test_terminal_app_declares_symbol_and_book_contexts() -> None:
    """#1636 — the terminal app declares both a ``symbol`` and ``book`` param context.

    Tabs 1-7 are symbol-scoped (research). Tabs 8-11 are book-scoped
    (portfolio). The app-level params carry both defaults so Workspace
    can share them across the shell.
    """
    e = _terminal_entry()
    params = e.get("params") or {}
    # Support both shapes: dict-of-defaults or list-of-param-specs.
    if isinstance(params, list):
        names = {p.get("paramName") for p in params if isinstance(p, dict)}
    else:
        names = set(params.keys()) if isinstance(params, dict) else set()
    assert (
        "symbol" in names
    ), f"Terminal app must declare a top-level ``symbol`` param context; got {names!r}"
    assert "account_id" in names or "book" in names, (
        f"Terminal app must declare a top-level book context (``account_id`` or"
        f" ``book``); got {names!r}"
    )
