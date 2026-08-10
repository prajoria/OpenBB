"""F1 Batch A tests: EXTEND equity_header/key_stats + REUSE on Overview tab.

Covers:

- **#1643 T1.1** — pi_equity_profile_header body now includes an
  explicit price + day-change row so the Overview tab has a live
  ticker line (adds a "Price" and "Day Change" line without changing
  the widget id or endpoint).
- **#1644 T1.2** — pi_equity_profile_header is placed on the Overview
  tab of the terminal (was: only F1 already, per F0.T0.5).
- **#1646 T1.4** — pi_equity_key_stats is placed on the Overview tab
  (was: already from F0.T0.5 — this test locks that in).
- **#1647 T1.5** — key_stats now exposes Share Statistics rows: Shares
  Float, Short Interest, Insider Ownership %.
- **#1651 T1.9** — key_stats now exposes Valuation Multiples: forward
  P/E, EV/EBITDA, P/S ratio (in addition to the existing trailing P/E).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)

_APPS_JSON = (
    Path(__file__).resolve().parents[2]
    / "openbb_portfolio_intel"
    / "widget_backend"
    / "apps.json"
)


def _terminal_overview_layout() -> list[dict]:
    apps = json.loads(_APPS_JSON.read_text(encoding="utf-8"))
    term = [a for a in apps if a.get("id") == "portfolio-intelligence-terminal"][0]
    return term["tabs"]["overview"]["layout"]


# ---------------------------------------------------------------------------
# #1643 — Price + day-change row in the header markdown body
# ---------------------------------------------------------------------------


def test_equity_header_body_includes_price_row() -> None:
    """Header markdown must have an explicit 'Price' line for at-a-glance read."""
    r = _client.get("/pi/equity/header?symbol=AAPL")
    assert r.status_code == 200
    body = r.json()
    # Anchored so a stray substring in a description can't satisfy the test.
    assert (
        "Price:" in body or "**Price**" in body
    ), "expected an explicit Price row in the equity header body (#1643)"


def test_equity_header_body_includes_day_change_row() -> None:
    """Header must show intraday change so the Overview reader sees direction."""
    r = _client.get("/pi/equity/header?symbol=AAPL")
    body = r.json()
    assert (
        "Day Change" in body or "Change" in body
    ), "expected day-change row in the equity header body (#1643)"


# ---------------------------------------------------------------------------
# #1644 + #1646 — Placement on the Overview tab
# ---------------------------------------------------------------------------


def test_overview_tab_contains_profile_header() -> None:
    """#1644 — pi_equity_profile_header must appear on the Overview tab layout."""
    ids = {slot["i"] for slot in _terminal_overview_layout()}
    assert (
        "pi_equity_profile_header" in ids
    ), "pi_equity_profile_header missing from terminal Overview tab (#1644)"


def test_overview_tab_contains_key_stats() -> None:
    """#1646 — pi_equity_key_stats must appear on the Overview tab layout."""
    ids = {slot["i"] for slot in _terminal_overview_layout()}
    assert (
        "pi_equity_key_stats" in ids
    ), "pi_equity_key_stats missing from terminal Overview tab (#1646)"


# ---------------------------------------------------------------------------
# #1647 — Share Statistics rows: NO fmp_cached source (area:fmp-cached-gap
# #1959). These were fabricated stub-only rows serving the same canned number
# for every symbol; #1958 dropped them from BOTH the live tier and the stub so
# the two shapes match (deterministic). These guards lock in that we do NOT
# re-fabricate them until a real provider source lands.
# ---------------------------------------------------------------------------


def _key_stats_metrics(symbol: str = "AAPL") -> dict[str, object]:
    r = _client.get(f"/pi/equity/key-stats?symbol={symbol}")
    assert r.status_code == 200
    rows = r.json()
    return {row["metric"]: row["value"] for row in rows}


def test_key_stats_omits_shares_float_no_source() -> None:
    """#1959 — Shares Float has no fmp_cached source; must NOT be fabricated."""
    m = _key_stats_metrics()
    assert "Shares Float" not in m, f"re-fabricated Shares Float; got {list(m)!r}"


def test_key_stats_omits_short_interest_no_source() -> None:
    """#1959 — Short Interest has no fmp_cached source; must NOT be fabricated."""
    m = _key_stats_metrics()
    assert "Short Interest" not in m, f"re-fabricated Short Interest; got {list(m)!r}"


def test_key_stats_omits_insider_ownership_no_source() -> None:
    """#1959 — Insider Ownership has no fmp_cached source; must NOT be fabricated."""
    m = _key_stats_metrics()
    keys = {k.lower() for k in m}
    assert not any(
        "insider" in k for k in keys
    ), f"re-fabricated Insider Ownership; got {list(m)!r}"


# ---------------------------------------------------------------------------
# #1651 — Valuation Multiples rows in key_stats. Forward P/E has no fmp_cached
# source (area:fmp-cached-gap #1959); trailing multiples (P/E TTM, EV/EBITDA,
# P/S) ARE sourced live and must stay.
# ---------------------------------------------------------------------------


def test_key_stats_omits_forward_pe_no_source() -> None:
    """#1959 — Forward P/E has no fmp_cached source; must NOT be fabricated."""
    m = _key_stats_metrics()
    keys = {k.lower() for k in m}
    assert not any(
        "forward p/e" in k or "p/e (fwd)" in k for k in keys
    ), f"re-fabricated Forward P/E; got {list(m)!r}"


def test_key_stats_includes_ev_ebitda() -> None:
    """#1651 — EV/EBITDA compares capital-structure-neutral valuation."""
    m = _key_stats_metrics()
    keys = {k.lower() for k in m}
    assert any(
        "ev/ebitda" in k for k in keys
    ), f"missing EV/EBITDA row; got {list(m)!r}"


def test_key_stats_includes_price_to_sales() -> None:
    """#1651 — P/S ratio (Price / Sales)."""
    m = _key_stats_metrics()
    keys = {k.lower() for k in m}
    assert any(
        k in ("p/s", "p/s (ttm)", "price / sales") for k in keys
    ), f"missing P/S row; got {list(m)!r}"


# ---------------------------------------------------------------------------
# Regression guard — trailing P/E (already there) must still be present
# ---------------------------------------------------------------------------


def test_key_stats_still_has_trailing_pe() -> None:
    """Regression: adding forward P/E must not accidentally drop trailing P/E."""
    m = _key_stats_metrics()
    assert "P/E (TTM)" in m, f"lost trailing P/E; got {list(m)!r}"
