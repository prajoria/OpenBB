"""Tests for the price-history widget with line ↔ candlestick toggle (#1702).

Verifies:

- Backend endpoint ``/pi/equity/price-history`` accepts a ``chart_type``
  query param and returns different row shapes based on it.
- Default (``chart_type=line`` or omitted) returns ``{date, close}`` rows.
- ``chart_type=candle`` returns ``{date, open, high, low, close}`` OHLC rows.
- Invalid ``chart_type`` values are rejected with 400.
- The widget appears in ``widgets.json`` with a dropdown-typed
  ``chart_type`` param.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import pytest
from fastapi.testclient import TestClient
from openbb_portfolio_intel.providers.retrofit import _TIER_CALLS
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)


@pytest.fixture(autouse=True)
def _force_stub_path():
    """Keep these endpoint tests hermetic (network-free).

    Since #1898 wired an ``fmp_cached`` live tier for ``equity/price-history``,
    hitting the endpoint would otherwise dispatch a real ``obb`` call through
    the provider chain. These tests assert the endpoint's own shape/validation
    contract (which holds for both the live and stub paths), so we clear the
    dispatch table to force the chain to exhaust to the stub — matching the
    original "unit tests never touch the network" intent. Live-tier behavior
    is covered by ``test_tier_calls.py`` (shaping unit tests + integration).
    """
    saved = dict(_TIER_CALLS)
    _TIER_CALLS.clear()
    try:
        yield
    finally:
        _TIER_CALLS.clear()
        _TIER_CALLS.update(saved)


def _manifest() -> dict:
    return json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "openbb_portfolio_intel"
            / "widget_backend"
            / "widgets.json"
        ).read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# Endpoint shape tests
# ---------------------------------------------------------------------------


def test_price_history_default_is_line_shape() -> None:
    """Omitting ``chart_type`` returns line shape ``{date, close}``."""
    resp = _client.get("/pi/equity/price-history?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "line shape must return non-empty rows"
    assert all(
        set(r.keys()) == {"date", "close"} for r in rows
    ), f"expected exactly date+close keys, got {rows[0].keys()}"
    assert all(isinstance(r["close"], (int, float)) for r in rows)


def test_price_history_line_explicit() -> None:
    """Explicit ``chart_type=line`` returns the same shape as default."""
    resp = _client.get("/pi/equity/price-history?symbol=AAPL&chart_type=line")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows and all(set(r.keys()) == {"date", "close"} for r in rows)


def test_price_history_candle_returns_ohlc_shape() -> None:
    """``chart_type=candle`` returns ``{date, open, high, low, close}``."""
    resp = _client.get("/pi/equity/price-history?symbol=AAPL&chart_type=candle")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "candle shape must return non-empty rows"
    expected = {"date", "open", "high", "low", "close"}
    assert all(
        expected.issubset(set(r.keys())) for r in rows
    ), f"expected OHLC keys, got {rows[0].keys()}"
    # Sanity: high >= low, high >= open, high >= close (per-bar invariant).
    for r in rows:
        assert r["high"] >= r["low"], f"high < low on {r}"
        assert r["high"] >= r["open"], f"high < open on {r}"
        assert r["high"] >= r["close"], f"high < close on {r}"


def test_price_history_rejects_invalid_chart_type() -> None:
    """Unknown ``chart_type`` returns 400 with a discriminating error."""
    resp = _client.get("/pi/equity/price-history?symbol=AAPL&chart_type=heikinashi")
    assert resp.status_code == 400
    detail = resp.json().get("detail", "")
    assert "chart_type" in detail
    assert "line" in detail and "candle" in detail


def test_price_history_symbol_validation() -> None:
    """XSS-shaped symbol is rejected pre-fetch (shared _SYMBOL_RE)."""
    resp = _client.get("/pi/equity/price-history?symbol=<script>")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Time-range control (#1950) — the series must span a selectable range and
# read as a genuine trend, not a 3-week sine-wave stub.
# ---------------------------------------------------------------------------


def test_price_history_default_range_spans_months() -> None:
    """Default series is a multi-month window (6M ≈ 126 business days).

    Regression for the "no way to say time range / doesn't look like a trend"
    report: the old stub emitted only 20 rows over 3 weeks, which rendered as
    a short valley rather than a price trend.
    """
    rows = _client.get("/pi/equity/price-history?symbol=AAPL").json()
    assert len(rows) >= 100, f"default range should span months, got {len(rows)} rows"
    # Dates strictly ascending and unique (LWC requires ascending unique time).
    dates = [r["date"] for r in rows]
    assert dates == sorted(dates), "dates must be ascending"
    assert len(set(dates)) == len(dates), "dates must be unique"
    # First → last spans well over a single calendar month.
    from datetime import date as _date

    span = (_date.fromisoformat(dates[-1]) - _date.fromisoformat(dates[0])).days
    assert span > 120, f"6M window should span >120 calendar days, got {span}"


def test_price_history_range_controls_length() -> None:
    """1M < 3M < 1Y < 5Y in row count — the range param sizes the series."""

    def _n(rng: str) -> int:
        return len(
            _client.get(f"/pi/equity/price-history?symbol=AAPL&range={rng}").json()
        )

    n1m, n3m, n1y, n5y = _n("1M"), _n("3M"), _n("1Y"), _n("5Y")
    assert (
        n1m < n3m < n1y < n5y
    ), f"expected monotonic growth, got {n1m},{n3m},{n1y},{n5y}"
    assert 15 <= n1m <= 25, f"1M ≈ 21 business days, got {n1m}"
    assert 240 <= n1y <= 260, f"1Y ≈ 252 business days, got {n1y}"


def test_price_history_range_dates_are_business_days() -> None:
    """Every date is a weekday (Mon–Fri) — no weekend bars in the series."""
    from datetime import date as _date

    rows = _client.get("/pi/equity/price-history?symbol=AAPL&range=3M").json()
    for r in rows:
        wd = _date.fromisoformat(r["date"]).weekday()
        assert wd < 5, f"{r['date']} is a weekend (weekday={wd})"


def test_price_history_reads_as_upward_trend() -> None:
    """Net close change dominates local wiggle → a visible trend, not a sine.

    Asserts the last close is materially above the first (drift-dominant),
    which is the property that makes the line "look like a trend line".
    """
    rows = _client.get("/pi/equity/price-history?symbol=AAPL&range=1Y").json()
    closes = [r["close"] for r in rows]
    assert (
        closes[-1] > closes[0] * 1.10
    ), f"1Y series should trend up >10% (first={closes[0]}, last={closes[-1]})"


def test_price_history_rejects_invalid_range() -> None:
    """Unknown ``range`` returns 400 with a discriminating error."""
    resp = _client.get("/pi/equity/price-history?symbol=AAPL&range=10Y")
    assert resp.status_code == 400
    detail = resp.json().get("detail", "")
    assert "range" in detail.lower()


def test_price_history_candle_range_row_count_matches_line() -> None:
    """Candle and line honor the same range window (same row count)."""
    line = _client.get(
        "/pi/equity/price-history?symbol=AAPL&range=3M&chart_type=line"
    ).json()
    candle = _client.get(
        "/pi/equity/price-history?symbol=AAPL&range=3M&chart_type=candle"
    ).json()
    assert len(line) == len(candle), "line and candle must span the same range"


def test_price_history_candle_volume_varies_meaningfully() -> None:
    """Volume-bar HEIGHT must encode real day-to-day variation (#1952).

    The volume pane's only signal is bar height = shares traded. The old demo
    generator emitted a near-flat monotonic ramp (~1.7% spread), so every bar
    rendered the same height and the pane was meaningless. A realistic demo
    series must swing enough that bars are visibly different: assert the
    coefficient of variation (stdev/mean) is at least 15%.
    """
    import statistics

    rows = _client.get(
        "/pi/equity/price-history?symbol=AAPL&range=6M&chart_type=candle"
    ).json()
    vols = [r["volume"] for r in rows]
    assert len(vols) > 20
    mean = statistics.mean(vols)
    cov = statistics.pstdev(vols) / mean
    assert cov >= 0.15, (
        f"volume too flat to be meaningful: cov={cov:.3f} "
        f"(min={min(vols)}, max={max(vols)}, mean={mean:.0f})"
    )


def test_price_history_candle_volume_is_not_monotonic() -> None:
    """Real volume is spiky/mean-reverting, not a smooth ramp (#1952).

    The old generator's volume increased by a fixed step every day — a dead
    giveaway of a fake series. Assert the series both rises and falls (has
    interior local maxima AND minima), i.e. it is not monotonic.
    """
    rows = _client.get(
        "/pi/equity/price-history?symbol=MSFT&range=6M&chart_type=candle"
    ).json()
    vols = [r["volume"] for r in rows]
    ups = sum(1 for a, b in zip(vols, vols[1:]) if b > a)
    downs = sum(1 for a, b in zip(vols, vols[1:]) if b < a)
    assert (
        ups > 0 and downs > 0
    ), f"volume is monotonic (ups={ups}, downs={downs}) — looks fake"
    # And neither direction dominates to the point of a near-ramp.
    assert (
        min(ups, downs) >= len(vols) * 0.2
    ), f"volume barely reverses (ups={ups}, downs={downs}, n={len(vols)})"


def test_price_history_candle_body_sizes_vary() -> None:
    """Candle body HEIGHT (|open-close|) must vary — decisive vs quiet days.

    Uniform bodies teach the eye that every day had the same move. Assert the
    largest body is at least 3x the median non-trivial body, so the chart has
    both big candles and small ones.
    """
    import statistics

    rows = _client.get(
        "/pi/equity/price-history?symbol=NVDA&range=6M&chart_type=candle"
    ).json()
    bodies = [abs(r["close"] - r["open"]) for r in rows]
    nontrivial = sorted(b for b in bodies if b > 0)
    assert len(nontrivial) > 10
    med = statistics.median(nontrivial)
    assert (
        max(bodies) >= med * 3
    ), f"candle bodies too uniform: max={max(bodies):.3f}, median={med:.3f}"


# ---------------------------------------------------------------------------
# Widget-manifest tests — widgets.json must declare the toggle param
# ---------------------------------------------------------------------------


def test_manifest_registers_price_history_widget() -> None:
    """``pi_equity_price_history`` widget is declared in widgets.json."""
    m = _manifest()
    assert "pi_equity_price_history" in m, "widget missing from manifest"
    w = m["pi_equity_price_history"]
    assert w["type"] == "chart"
    assert w["endpoint"] == "pi/equity/price-history"


def test_manifest_price_history_has_chart_type_param() -> None:
    """The widget declares a ``chart_type`` param as a dropdown enum."""
    m = _manifest()
    w = m["pi_equity_price_history"]
    params = {p["paramName"]: p for p in w.get("params", [])}
    assert "chart_type" in params, "chart_type param missing from widget"
    p = params["chart_type"]
    # OpenBB Workspace uses type='endpoint' or 'text' for enums via
    # options list. Options must contain exactly the two supported modes.
    opts = p.get("options") or []
    values = {o.get("value") for o in opts}
    assert values == {"line", "candle"}, f"expected line+candle options, got {values}"
    assert p.get("value") == "line", "default should be line for backward compat"


def test_manifest_price_history_has_range_param() -> None:
    """The widget declares a ``range`` dropdown so users can pick a window."""
    m = _manifest()
    w = m["pi_equity_price_history"]
    params = {p["paramName"]: p for p in w.get("params", [])}
    assert "range" in params, "range param missing from widget (#1950)"
    p = params["range"]
    values = {o.get("value") for o in (p.get("options") or [])}
    assert values == {
        "1M",
        "3M",
        "6M",
        "YTD",
        "1Y",
        "5Y",
    }, f"expected standard range options, got {values}"
    assert p.get("value") == "6M", "default range should be 6M"
