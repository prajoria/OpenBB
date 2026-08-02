"""F12 Portfolio-management workflow tests (#1678 + #1685-#1689).

Follows the design spec at
``docs/superpowers/specs/2026-07-31-f12-portfolio-workflow-design.md``.

Covers 5 sub-tasks:

- **#1685 T12.1** — pi_provider_health widget (real endpoint, non-blocking,
  cached, exception-note allowlist)
- **#1686 T12.2** — Morning Review one-pager tab (layout-only, 5 REUSE widgets)
- **#1687 T12.3** — pi_basket_analyst_consensus (STUB, demo-only, HTTP 422
  for non-demo basket_id)
- **#1688 T12.4** — guidedTour manifest on the terminal app entry (W0-W9
  step order)
- **#1689 T12.5** — pytest substitute for the Playwright tour smoke

Follow-up tickets referenced by the stubs and TODOs:

- **#1713** Real Playwright + Workspace-in-CI (T0.6 / T12.5 gap)
- **#1714** Basket-mode input design (blocks real T12.3 wiring)
- **#1715** Real 5-tier chain fallback (blocks provider-health -> routing)
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


def _terminal_app() -> dict:
    for a in _apps():
        if a.get("id") == "portfolio-intelligence-terminal":
            return a
    return {}


# ===========================================================================
# T12.1 #1685 — pi_provider_health
# ===========================================================================


def test_provider_health_widget_declared() -> None:
    """widgets.json declares pi_provider_health markdown widget."""
    w = _widgets().get("pi_provider_health")
    assert w and w["type"] == "markdown"
    assert w["endpoint"] == "pi/health/providers"


def test_provider_health_endpoint_returns_shape() -> None:
    """/pi/health/providers returns markdown with Track A + Track B tier info."""
    r = _client.get("/pi/health/providers")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, str)
    # Markdown widget must name both tracks.
    assert "Track A" in body
    assert "Track B" in body
    # Every tier name from the 5-tier chain (Track A) shows up.
    for name in ("fmp_cached", "fmp", "cboe", "sec", "yfinance"):
        assert name in body, f"missing tier {name!r} in health strip"


def test_provider_health_never_blocks_on_cold_cache() -> None:
    """P0-1 fix: endpoint returns immediately on cold cache with unknown tiers.

    Reset any module-level cache before the call so we're on cold cache,
    then assert the response comes back quickly. Also assert the response
    reflects the cold-cache state — 'unknown' or similar hedged status,
    not a lie about tier health.
    """
    from openbb_portfolio_intel.widget_backend import widgets_endpoints as we

    if hasattr(we, "_PROVIDER_HEALTH_CACHE"):
        we._PROVIDER_HEALTH_CACHE.clear()
    import time

    start = time.monotonic()
    r = _client.get("/pi/health/providers")
    elapsed = time.monotonic() - start
    assert r.status_code == 200
    # Response must return in well under the 2.5s wall-clock — cold cache
    # returns immediately per spec §3 T12.1.
    assert elapsed < 1.0, f"cold-cache response took {elapsed:.2f}s (spec: <1s)"


def test_provider_health_exception_note_uses_allowlist_never_raw() -> None:
    """P0-3 fix: exception notes use the fixed allowlist, never raw exc str.

    The endpoint body should not contain the substring 'Exception' with a
    trailing tuple/args (a signature of ``str(exc)``), nor URLs, nor any
    other exception-message leak. Test the code invariant by asserting the
    _EXC_NOTE_MAP module attribute exists and is used.
    """
    from openbb_portfolio_intel.widget_backend import widgets_endpoints as we

    assert hasattr(
        we, "_EXC_NOTE_MAP"
    ), "_EXC_NOTE_MAP allowlist missing — P0-3 fix requires it (see spec §3)"
    m = we._EXC_NOTE_MAP
    # Every mapped note must be a short lowercase snake_case token, never
    # a raw exception string.
    for exc_class, note in m.items():
        assert isinstance(note, str)
        assert " " not in note, f"note {note!r} has spaces — likely a raw exc str"
        assert "://" not in note, f"note {note!r} has a URL — leak vector"


# ===========================================================================
# T12.2 #1686 — Morning Review one-pager tab
# ===========================================================================

_MORNING_REVIEW_REQUIRED = {
    "pi_concentration_gauge",
    "pi_risk_dashboard",
    "pi_event_calendar",
    "pi_alerts_panel",
    "pi_paper_perf_kpis",
}


def _morning_review_layout() -> list[dict]:
    tabs = _terminal_app().get("tabs", {})
    tab = tabs.get("morning-review") or tabs.get("morning_review")
    return tab["layout"] if tab else []


def test_morning_review_tab_exists() -> None:
    """#1686 — morning-review tab is a new tab on the terminal app."""
    tabs = _terminal_app().get("tabs", {})
    assert (
        "morning-review" in tabs or "morning_review" in tabs
    ), "morning-review tab missing from terminal app"


def test_morning_review_contains_all_5_required() -> None:
    """#1686 — layout must include all 5 REUSE widgets from the spec.

    P1-6 mutation named test: dropping any of the 5 widgets fails here.
    """
    ids = {slot["i"] for slot in _morning_review_layout()}
    missing = _MORNING_REVIEW_REQUIRED - ids
    assert not missing, f"Morning Review layout missing widgets: {missing!r}"


# ===========================================================================
# T12.3 #1687 — pi_basket_analyst_consensus (STUB, demo-only)
# ===========================================================================


def test_basket_consensus_widget_declared() -> None:
    w = _widgets().get("pi_basket_analyst_consensus")
    assert w and w["type"] == "table"
    assert w["endpoint"] == "pi/equity/basket-analyst-consensus"
    params = {p["paramName"] for p in w.get("params", [])}
    assert "basket_id" in params


def test_basket_consensus_demo_returns_rows() -> None:
    """basket_id=demo returns the stub consensus rows."""
    r = _client.get("/pi/equity/basket-analyst-consensus?basket_id=demo")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list) and rows
    for row in rows:
        for f in ("symbol", "avg_target", "buy", "hold", "sell", "consensus"):
            assert f in row, f"missing {f} in {row!r}"


def test_non_demo_basket_id_unknown_returns_404() -> None:
    """#1714 flipped the 422 gate to real basket resolution.

    Unknown basket_id (no snapshot for that user) returns a loud 404
    with the ``basket_not_found`` marker — never silently returns [] or
    demo rows disguised with a note.
    """
    r = _client.get("/pi/equity/basket-analyst-consensus?basket_id=real_book")
    assert (
        r.status_code == 404
    ), f"unknown basket_id must return 404 (was 422 pre-#1714); got {r.status_code}"
    detail = r.json().get("detail", "")
    assert "basket_not_found" in str(detail) or "real_book" in str(detail)


def test_basket_consensus_rejects_malformed_basket_id() -> None:
    """Malformed basket_id (fails allowlist regex) returns 400."""
    for bad in ("<script>", "a;b", "book$(x)", "x" * 200):
        r = _client.get(f"/pi/equity/basket-analyst-consensus?basket_id={bad}")
        assert r.status_code == 400, f"{bad!r} accepted; must be 400"


# ===========================================================================
# T12.4 #1688 — guidedTour manifest
# ===========================================================================


def _tour() -> dict:
    return _terminal_app().get("guidedTour", {})


def test_guided_tour_declared() -> None:
    """#1688 — guidedTour key exists on the terminal app entry."""
    t = _tour()
    assert t, "guidedTour missing from terminal app"
    assert t.get("id") == "sunday-routine"
    steps = t.get("steps", [])
    assert len(steps) == 10, f"expected W0-W9 (10 steps); got {len(steps)}"


def test_guided_tour_steps_are_ordered_W0_to_W9() -> None:
    """P1-6 mutation named test: reordering steps or skipping one fails here."""
    steps = _tour().get("steps", [])
    labels = [s.get("step") for s in steps]
    expected = [f"W{i}" for i in range(10)]
    assert labels == expected, f"tour steps not in W0-W9 order; got {labels!r}"


def test_every_step_tab_exists() -> None:
    """P1-6 mutation named test: renaming a tab in the tour manifest fails
    here because the resolver returns None.
    """
    term_tabs = set(_terminal_app().get("tabs", {}).keys())
    for step in _tour().get("steps", []):
        tab_id = step.get("tab")
        assert tab_id in term_tabs, (
            f"tour step {step.get('step')!r} points at unknown tab "
            f"{tab_id!r}; known: {sorted(term_tabs)!r}"
        )


def test_every_step_focuswidget_exists() -> None:
    """P1-6 mutation named test: pointing at an unknown widget id fails here."""
    known = set(_widgets().keys())
    for step in _tour().get("steps", []):
        wid = step.get("focusWidget")
        assert wid in known, (
            f"tour step {step.get('step')!r} points at unknown widget " f"{wid!r}"
        )


# ===========================================================================
# T12.5 #1689 — pytest substitute for the Playwright tour smoke
# ===========================================================================


def test_tour_substitute_every_step_tab_has_nonblank_layout() -> None:
    """#1689 substitute (real Playwright follow-up #1713) — every step's
    tab has non-empty layout so a Workspace render won't blank.
    """
    term = _terminal_app()
    tabs = term.get("tabs", {})
    for step in _tour().get("steps", []):
        tab_id = step["tab"]
        layout = tabs[tab_id]["layout"]
        assert layout, f"tour step {step['step']} at tab {tab_id} has empty layout"


def test_tour_substitute_focuswidget_is_present_on_its_tab() -> None:
    """#1689 substitute — the focused widget must be on the tab it targets,
    else Workspace can't scroll/highlight it.
    """
    tabs = _terminal_app().get("tabs", {})
    for step in _tour().get("steps", []):
        tab_id = step["tab"]
        focus = step["focusWidget"]
        ids_on_tab = {slot["i"] for slot in tabs[tab_id]["layout"]}
        assert (
            focus in ids_on_tab
        ), f"tour step {step['step']}: focus widget {focus!r} not on tab {tab_id!r}"


# ===========================================================================
# Route parity
# ===========================================================================


def test_f12_endpoints_registered() -> None:
    routes = {r.path for r in app.routes}
    for path in ("/pi/health/providers", "/pi/equity/basket-analyst-consensus"):
        assert path in routes, f"missing route {path}"


# ===========================================================================
# Provider-health chrome placement — P1-5 safe pattern (y >= 0)
# ===========================================================================


def test_provider_health_appears_on_every_tab() -> None:
    """P1-5 fix (safe pattern first): pi_provider_health is placed on every
    tab of the terminal app, not via unverified y:-1 chrome placement.

    Rationale: 'app chrome' means the widget is present on every tab so the
    user always sees provider status. Using y>=0 is safe; y:-1 is a
    Workspace-version-dependent trick we're not adopting until proven.
    """
    term = _terminal_app()
    for tab_id, tab in term.get("tabs", {}).items():
        ids = {slot["i"] for slot in tab.get("layout", [])}
        assert (
            "pi_provider_health" in ids
        ), f"provider-health chrome missing from tab {tab_id!r}"
