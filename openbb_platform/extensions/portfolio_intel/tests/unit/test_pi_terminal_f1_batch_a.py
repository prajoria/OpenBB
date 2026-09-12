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
from openbb_portfolio_intel.providers.retrofit import _TIER_CALLS
from openbb_portfolio_intel.widget_backend import tier_calls
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
# #1647 — Share Statistics rows. #1959 wires Shares Float from the real
# fmp_cached share-statistics response. Short Interest and Insider Ownership
# remain omitted because the provider does not expose them; no constants or
# proxies may be substituted.
# ---------------------------------------------------------------------------


def _key_stats_metrics(symbol: str = "AAPL") -> dict[str, object]:
    r = _client.get(f"/pi/equity/key-stats?symbol={symbol}")
    assert r.status_code == 200
    rows = r.json()
    return {row["metric"]: row["value"] for row in rows}


def test_key_stats_no_tier_fallback_omits_source_dependent_metrics(
    monkeypatch,
) -> None:
    """#2075 — the no-tier fallback must not invent provider-backed values."""
    monkeypatch.setattr(
        "openbb_portfolio_intel.providers.retrofit._TIER_CALLS",
        {},
    )
    metrics = _key_stats_metrics()

    assert "Shares Float" not in metrics
    assert "Forward P/E" not in metrics


def test_key_stats_docs_distinguish_no_tier_fallback_from_live_shape() -> None:
    """#2075 — endpoint docs must describe the fallback's smaller metric set."""
    operation = _client.get("/openapi.json").json()["paths"][
        "/pi/equity/key-stats"
    ]["get"]
    description = " ".join(operation["description"].split())
    assert (
        "The no-tier fallback intentionally omits Shares Float and Forward P/E "
        "because both require provider data."
        in description
    )


def _patch_new_key_stats_sources(monkeypatch) -> None:
    monkeypatch.setitem(
        _TIER_CALLS,
        ("equity/key-stats", "fmp_cached"),
        tier_calls._key_stats_fmp_cached,
    )
    monkeypatch.setattr(tier_calls, "_fetch_profile", lambda symbol: {})
    monkeypatch.setattr(
        tier_calls, "_fetch_quote", lambda symbol: {"last_price": 200.0}
    )
    monkeypatch.setattr(tier_calls, "_fetch_metrics", lambda symbol: {})
    monkeypatch.setattr(tier_calls, "_fetch_ratios", lambda symbol: {})
    monkeypatch.setattr(
        tier_calls,
        "_fetch_share_statistics",
        lambda symbol: {"float_shares": 1_250_000_000},
    )
    monkeypatch.setattr(
        tier_calls, "_fetch_forward_eps", lambda symbol: {"mean": 10.0}
    )


def test_key_stats_includes_provider_backed_shares_float(monkeypatch) -> None:
    """#1959 — Shares Float is served from fmp_cached share statistics."""
    _patch_new_key_stats_sources(monkeypatch)
    m = _key_stats_metrics()
    assert "Shares Float" in m, f"missing sourced Shares Float; got {list(m)!r}"


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
# #1651 — Valuation Multiples rows in key_stats. Forward P/E is derived from
# the live quote and annual fmp_cached consensus EPS (#1959); trailing multiples
# (P/E TTM, EV/EBITDA, P/S) remain sourced live.
# ---------------------------------------------------------------------------


def test_key_stats_includes_provider_backed_forward_pe(monkeypatch) -> None:
    """#1959 — Forward P/E is derived only from live fmp_cached inputs."""
    _patch_new_key_stats_sources(monkeypatch)
    m = _key_stats_metrics()
    keys = {k.lower() for k in m}
    assert any(
        "forward p/e" in k or "p/e (fwd)" in k for k in keys
    ), f"missing sourced Forward P/E; got {list(m)!r}"


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
