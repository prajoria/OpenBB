"""Techtrade T13.3-T13.7 tests — Validation Verdict + Tuning Report + Audit
Journal + Engine Status + Playwright cadence smoke substitute.

Closes out Techtrade EPIC #1691 alongside T13.1 (shipped as #1712) and
T13.2 (shipped as #1718).

- **#1697 T13.3** — tt_validation_verdict (metric widget with PBO/DSR/OOS-Sharpe)
- **#1698 T13.4** — tt_tuning_report (table over tuneta proposal + validate gate;
  'persist' behavior is stub-only, real state = follow-up)
- **#1699 T13.5** — tt_audit_journal (table with replay-vs-forward + deviation)
- **#1700 T13.6** — tt_engine_status (markdown) + T5 execute bridge widget
  (scaffold; real broker wiring is follow-up #1719); tab-group layout wiring
  all 6 techtrade tabs (T1..T6 spread across morning-scan + position-workbench
  + validation + tuning + audit + engine-status)
- **#1701 T13.7** — pytest substitute for the Playwright cadence smoke that
  steps T1 -> T6 and asserts verdict gates the execute bridge. Real
  Playwright + Workspace-in-CI is #1713.
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


def _techtrade_app() -> dict:
    for a in _apps():
        if a.get("id") == "techtrade-desk":
            return a
    return {}


# ===========================================================================
# T13.3 #1697 — tt_validation_verdict
# ===========================================================================


def test_validation_verdict_widget_declared() -> None:
    w = _widgets().get("tt_validation_verdict")
    assert w and w["type"] == "table"
    assert w["endpoint"] == "tt/validation/verdict"


def test_validation_verdict_returns_pbo_dsr_oos_sharpe() -> None:
    r = _client.get("/tt/validation/verdict?symbol=AAPL")
    assert r.status_code == 200
    rows = r.json()
    metrics = {row["metric"] for row in rows}
    assert "PBO" in metrics
    assert "DSR" in metrics
    assert any(
        "OOS" in m and "Sharpe" in m for m in metrics
    ), f"missing OOS Sharpe metric; got {metrics!r}"
    assert any(row.get("metric") == "Verdict" for row in rows)


def test_validation_verdict_gate_is_pass_or_fail() -> None:
    """The Verdict row must be a discrete gate: PASS or FAIL, never in-between."""
    rows = _client.get("/tt/validation/verdict?symbol=AAPL").json()
    verdict_row = [r for r in rows if r["metric"] == "Verdict"][0]
    assert verdict_row["value"] in (
        "PASS",
        "FAIL",
    ), f"Verdict must be PASS or FAIL; got {verdict_row['value']!r}"


# ===========================================================================
# T13.4 #1698 — tt_tuning_report
# ===========================================================================


def test_tuning_report_widget_declared() -> None:
    w = _widgets().get("tt_tuning_report")
    assert w and w["type"] == "table"
    assert w["endpoint"] == "tt/tuning/report"


def test_tuning_report_returns_param_rows() -> None:
    r = _client.get("/tt/tuning/report?symbol=AAPL")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        for f in ("param", "current", "proposed", "delta", "validate_gate"):
            assert f in row, f"missing {f} in {row!r}"


def test_tuning_report_validate_gate_is_pass_or_fail_per_param() -> None:
    """Each proposed param carries a validate_gate outcome (never silent)."""
    rows = _client.get("/tt/tuning/report?symbol=AAPL").json()
    for row in rows:
        assert row["validate_gate"] in (
            "PASS",
            "FAIL",
        ), f"validate_gate must be PASS/FAIL; got {row['validate_gate']!r}"


# ===========================================================================
# T13.5 #1699 — tt_audit_journal
# ===========================================================================


def test_audit_journal_widget_declared() -> None:
    w = _widgets().get("tt_audit_journal")
    assert w and w["type"] == "table"
    assert w["endpoint"] == "tt/audit/journal"


def test_audit_journal_returns_replay_vs_forward_rows() -> None:
    r = _client.get("/tt/audit/journal?symbol=AAPL")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        for f in ("bar_date", "replay_pnl", "forward_pnl", "deviation_bps"):
            assert f in row, f"missing {f} in {row!r}"


def test_audit_journal_deviation_is_numeric_bps() -> None:
    rows = _client.get("/tt/audit/journal?symbol=AAPL").json()
    for row in rows:
        assert isinstance(row["deviation_bps"], (int, float))


# ===========================================================================
# T13.6 #1700 — tt_engine_status + execute bridge (scaffold)
# ===========================================================================


def test_engine_status_widget_declared() -> None:
    w = _widgets().get("tt_engine_status")
    assert w and w["type"] == "markdown"
    assert w["endpoint"] == "tt/engine/status"


def test_engine_status_returns_observable_state() -> None:
    """#1931: honest status names the real operational surfaces.

    The engine has no scheduler (that was fabricated in the #1700 stub);
    the honest status names the capability matrix surfaces instead.
    """
    r = _client.get("/tt/engine/status")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, str)
    # Real operational surfaces present in the capability matrix.
    for surface in ("signals", "execution", "scan", "validation"):
        assert surface.lower() in body.lower(), f"missing {surface} in engine status"


def test_engine_status_reports_version_and_capability_count() -> None:
    """#1931: reports the real package version + an N/M capability count.

    Discriminating vs the #1700 stub, which had neither a version line nor a
    capability count — this test FAILS on the old fabricated stub.
    """
    body = _client.get("/tt/engine/status").json()
    assert "openbb_techtrade" in body
    assert "capabilities available" in body.lower()
    # "N/M engine capabilities available" — M is the fixed matrix size (9).
    import re as _re

    m = _re.search(r"(\d+)\s*/\s*(\d+)\s+engine capabilities", body, _re.IGNORECASE)
    assert m, f"no N/M capability count in body: {body[:200]!r}"
    n_avail, n_total = int(m.group(1)), int(m.group(2))
    assert n_total == 9, f"expected 9 total capabilities, got {n_total}"
    assert 0 <= n_avail <= n_total


def test_engine_status_has_no_fabricated_state() -> None:
    """#1931 (reverse-verification anchor): the fabricated tokens are GONE.

    The #1700 stub invented a running scheduler ("next tick in 47s"), a fake
    signal ("NVDA BREAKOUT at 09:32:14"), and a fake cache hit-rate ("98.2%").
    None of these are observable, so the honest wiring must not emit them.
    This test PASSES on the honest wiring and FAILS on the old stub.
    """
    body = _client.get("/tt/engine/status").json().lower()
    for fabricated in ("next tick", "nvda breakout", "98.2%", "hit-rate"):
        assert fabricated not in body, f"fabricated token still present: {fabricated!r}"


def test_engine_status_reports_preset_and_paper_state() -> None:
    """#1931: honest status surfaces the default preset weights + paper state."""
    body = _client.get("/tt/engine/status").json()
    assert "trend_follow" in body
    assert "trend=" in body  # confluence weight, from resolve_preset
    assert "Paper engine" in body


def test_execute_bridge_widget_declared() -> None:
    w = _widgets().get("tt_execute_bridge")
    assert w and w["type"] == "markdown"
    assert w["endpoint"] == "tt/execute/bridge"


def test_execute_bridge_blocked_when_verdict_fails() -> None:
    """The bridge gates on the verdict: FAIL -> BLOCKED, PASS -> READY."""
    r_fail = _client.get("/tt/execute/bridge?verdict=FAIL")
    assert r_fail.status_code == 200
    body_fail = r_fail.json()
    assert "BLOCKED" in body_fail
    r_pass = _client.get("/tt/execute/bridge?verdict=PASS")
    body_pass = r_pass.json()
    assert "READY" in body_pass


def test_execute_bridge_rejects_bad_verdict() -> None:
    r = _client.get("/tt/execute/bridge?verdict=SIDEWAYS")
    assert r.status_code == 400


# ===========================================================================
# T13.6 tab layout — 6 tabs across techtrade-desk
# ===========================================================================

_EXPECTED_TECHTRADE_TABS = {
    "morning-scan",
    "position-workbench",
    "validation",
    "tuning",
    "audit",
    "engine-status",
}


def test_techtrade_desk_has_all_6_tabs() -> None:
    tabs = _techtrade_app().get("tabs", {})
    missing = _EXPECTED_TECHTRADE_TABS - set(tabs.keys())
    assert not missing, f"techtrade-desk missing tabs: {missing!r}"


def test_validation_tab_has_verdict_widget() -> None:
    tabs = _techtrade_app().get("tabs", {})
    ids = {slot["i"] for slot in tabs["validation"]["layout"]}
    assert "tt_validation_verdict" in ids


def test_tuning_tab_has_report_widget() -> None:
    tabs = _techtrade_app().get("tabs", {})
    ids = {slot["i"] for slot in tabs["tuning"]["layout"]}
    assert "tt_tuning_report" in ids


def test_audit_tab_has_journal_widget() -> None:
    tabs = _techtrade_app().get("tabs", {})
    ids = {slot["i"] for slot in tabs["audit"]["layout"]}
    assert "tt_audit_journal" in ids


def test_engine_status_tab_has_status_and_execute_bridge() -> None:
    tabs = _techtrade_app().get("tabs", {})
    ids = {slot["i"] for slot in tabs["engine-status"]["layout"]}
    assert "tt_engine_status" in ids
    assert "tt_execute_bridge" in ids


# ===========================================================================
# T13.7 #1701 — Playwright cadence substitute
# ===========================================================================
#
# Steps T1 -> T6 headlessly (no browser). Verifies the tabs are ordered,
# each has non-blank layout, and the verdict output actually gates the
# execute bridge (the load-bearing safety invariant #1701 targets).

_T_ORDER = (
    ("T1", "morning-scan"),
    ("T2", "position-workbench"),
    ("T3", "validation"),
    ("T4", "tuning"),
    ("T5", "engine-status"),  # T5 = execute bridge lives on engine-status
    ("T6", "audit"),
)


def test_t1_through_t6_tabs_all_exist_and_nonblank() -> None:
    """Every T1..T6 tab exists and has non-empty layout."""
    tabs = _techtrade_app().get("tabs", {})
    for label, tab_id in _T_ORDER:
        assert tab_id in tabs, f"{label} tab {tab_id!r} missing"
        assert tabs[tab_id]["layout"], f"{label} tab {tab_id!r} has empty layout"


def test_verdict_pass_unblocks_execute_bridge_endpoint() -> None:
    """Load-bearing invariant: verdict=PASS -> execute bridge READY."""
    r = _client.get("/tt/execute/bridge?verdict=PASS")
    body = r.json()
    assert "READY" in body


def test_verdict_fail_blocks_execute_bridge_endpoint() -> None:
    """Load-bearing invariant: verdict=FAIL -> execute bridge BLOCKED."""
    r = _client.get("/tt/execute/bridge?verdict=FAIL")
    body = r.json()
    assert "BLOCKED" in body
    # And must NOT contain READY (belt + suspenders — prevents someone
    # accidentally emitting both states in the same body).
    assert "READY" not in body


# ===========================================================================
# Symbol allowlist + route parity
# ===========================================================================


def test_t13_endpoints_reject_bad_symbol() -> None:
    for path in ("/tt/validation/verdict", "/tt/tuning/report", "/tt/audit/journal"):
        r = _client.get(f"{path}?symbol=<script>")
        assert r.status_code == 400, f"{path} accepted bad symbol"


def test_all_t13_endpoints_registered() -> None:
    routes = {r.path for r in app.routes}
    for path in (
        "/tt/validation/verdict",
        "/tt/tuning/report",
        "/tt/audit/journal",
        "/tt/engine/status",
        "/tt/execute/bridge",
    ):
        assert path in routes, f"missing route {path}"
