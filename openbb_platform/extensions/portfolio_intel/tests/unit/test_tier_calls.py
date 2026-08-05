"""Live fmp_cached tier-call registration tests (#1898).

Covers the price-history wiring (full-wiring of stub #1702):

- ``_shape_price_history`` produces the widget contract for line + candle.
- The registered tier call composes fetch + shape and returns live rows.
- Loud-empty: an empty fetch logs a WARNING and returns ``[]`` so the
  provider chain transitions to the next tier / stub (never silent).
- ``register_all`` wires ``("equity/price-history", "fmp_cached")``.

Fixtures are realistic-shape snapshots of ``obb.equity.price.historical(
provider="fmp_cached")`` output (keys incl. the extras the shaper must
ignore: ``vwap``, ``change`` ...), so the shaper is tested against the
provider's real row shape rather than a hand-crafted minimal dict.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import pytest
from fastapi.testclient import TestClient
from openbb_portfolio_intel.providers.retrofit import _TIER_CALLS, register_tier_call
from openbb_portfolio_intel.widget_backend import tier_calls
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_and_reregister() -> None:
    """Reset the dispatch table, then re-run production registrations."""
    _TIER_CALLS.clear()
    tier_calls.register_all(register_tier_call)


def _fixture_rows() -> list[dict]:
    """Two realistic fmp_cached daily bars (date is a ``datetime.date``)."""
    return [
        {
            "date": _dt.date(2026, 6, 1),
            "open": 190.12,
            "high": 193.44,
            "low": 189.55,
            "close": 192.01,
            "volume": 51_234_000,
            "vwap": 191.7,
            "change": 1.89,
            "change_percent": 0.0099,
            "dividend": 0.0,
        },
        {
            "date": _dt.date(2026, 6, 2),
            "open": 192.5,
            "high": 195.0,
            "low": 191.8,
            "close": 194.3,
            "volume": 48_900_000,
            "vwap": 193.6,
            "change": 2.29,
            "change_percent": 0.0119,
            "dividend": 0.0,
        },
    ]


def test_shape_price_history_line() -> None:
    """Line mode -> ``{date, close}`` only, date normalized to ISO string."""
    out = tier_calls._shape_price_history(_fixture_rows(), "line")
    assert out == [
        {"date": "2026-06-01", "close": 192.01},
        {"date": "2026-06-02", "close": 194.3},
    ]
    assert all(isinstance(r["date"], str) for r in out)


def test_shape_price_history_candle() -> None:
    """Candle mode -> full OHLCV, extras (vwap/change) dropped."""
    out = tier_calls._shape_price_history(_fixture_rows(), "candle")
    assert out[0] == {
        "date": "2026-06-01",
        "open": 190.12,
        "high": 193.44,
        "low": 189.55,
        "close": 192.01,
        "volume": 51_234_000,
    }
    assert "vwap" not in out[0] and "change" not in out[0]


def test_tier_call_composes_fetch_and_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """Registered tier call returns shaped live rows for both chart types."""
    monkeypatch.setattr(
        tier_calls, "_fetch_price_history_rows", lambda symbol: _fixture_rows()
    )
    call = _TIER_CALLS[("equity/price-history", "fmp_cached")]

    line = call(symbol="AAPL", chart_type="line")
    assert line[0] == {"date": "2026-06-01", "close": 192.01}

    candle = call(symbol="AAPL", chart_type="candle")
    assert set(candle[0]) == {"date", "open", "high", "low", "close", "volume"}


def test_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Empty fetch -> WARNING logged + ``[]`` returned (chain transitions)."""
    monkeypatch.setattr(
        tier_calls, "_fetch_price_history_rows", lambda symbol: []
    )
    call = _TIER_CALLS[("equity/price-history", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger="openbb_portfolio_intel"):
        out = call(symbol="ZZZZ", chart_type="line")
    assert out == []
    hits = [r for r in caplog.records if "0 rows" in r.getMessage()]
    assert len(hits) == 1, "loud-empty WARNING must fire exactly once"


def test_register_all_wires_price_history() -> None:
    """The production registration wires the fmp_cached price-history tier."""
    assert ("equity/price-history", "fmp_cached") in _TIER_CALLS


@pytest.mark.integration
def test_price_history_fmp_cached_live() -> None:
    """Live: fmp_cached returns real OHLCV rows the shaper can consume.

    Not ``plan_limited`` — ``equity.price.historical`` is covered by our
    current FMP key (verified during the #1898 feasibility gate). If this
    ever starts 402-ing, register the endpoint in ``plan_limited.py`` and add
    the ``plan_limited`` marker per the CLAUDE.md FMP-tier rule.
    """
    rows = tier_calls._fetch_price_history_rows("AAPL")
    assert rows, "fmp_cached returned no AAPL price history — live wiring broken"

    line = tier_calls._shape_price_history(rows, "line")
    assert line and set(line[0]) == {"date", "close"}
    assert isinstance(line[0]["date"], str) and line[0]["close"] is not None

    candle = tier_calls._shape_price_history(rows, "candle")
    assert set(candle[0]) == {"date", "open", "high", "low", "close", "volume"}


# ---------------------------------------------------------------------------
# Endpoint-through-chain tests: the live tier is registered (autouse), so
# these exercise the wired path — NOT the stub. Fetch is monkeypatched so no
# network. Guards the #1898 validation-bypass regression.
# ---------------------------------------------------------------------------


def test_endpoint_serves_from_tier_not_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the tier registered, the endpoint returns the tier's rows.

    The stub (``_demo_ohlc_series``) emits 20 rows dated ``2026-06-DD``; the
    fixture has 2 rows dated ``2026-06-01/02``. Asserting the 2-row fixture
    comes back proves the fmp_cached tier served, not the stub fallback.
    """
    monkeypatch.setattr(
        tier_calls, "_fetch_price_history_rows", lambda symbol: _fixture_rows()
    )
    resp = _client.get("/pi/equity/price-history?symbol=AAPL&chart_type=line")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows == [
        {"date": "2026-06-01", "close": 192.01},
        {"date": "2026-06-02", "close": 194.3},
    ], "endpoint must serve fmp_cached tier rows, not the 20-row stub"


def test_endpoint_rejects_invalid_chart_type_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1898 regression: invalid chart_type must 400 even on the live path.

    The chart_type 400-guard originally lived only in the stub body, which
    the chain bypasses once a tier serves — so ``chart_type=heikin`` slipped
    through as candle rows. The guard now runs in the pre-dispatch
    ``validate_kwargs`` hook; this test fails if it regresses back into the
    stub body.
    """
    monkeypatch.setattr(
        tier_calls, "_fetch_price_history_rows", lambda symbol: _fixture_rows()
    )
    resp = _client.get("/pi/equity/price-history?symbol=AAPL&chart_type=heikin")
    assert resp.status_code == 400
    detail = resp.json().get("detail", "")
    assert "chart_type" in detail and "line" in detail and "candle" in detail


def test_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation also runs pre-dispatch (not bypassed by the tier)."""
    monkeypatch.setattr(
        tier_calls, "_fetch_price_history_rows", lambda symbol: _fixture_rows()
    )
    resp = _client.get("/pi/equity/price-history?symbol=<script>")
    assert resp.status_code == 400
