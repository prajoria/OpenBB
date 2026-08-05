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
    monkeypatch.setattr(tier_calls, "_fetch_price_history_rows", lambda symbol: [])
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


def test_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR #1899 review: the live tier must receive the SAME normalized ticker
    the stub body would use (``symbol.strip().upper()``).

    Forwarding the raw symbol would let ``" aapl "`` reach fmp_cached verbatim,
    return empty, and silently fall through the chain to the demo stub -
    fabricated data masquerading as live prices. This test captures the symbol
    the fetch actually receives and asserts it was normalized.
    """
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> list[dict]:
        seen["symbol"] = symbol
        return _fixture_rows()

    monkeypatch.setattr(tier_calls, "_fetch_price_history_rows", _capture)
    resp = _client.get("/pi/equity/price-history?symbol=+aapl+&chart_type=line")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", (
        "live tier must be queried with the normalized ticker, not the raw "
        f"input; got {seen['symbol']!r}"
    )


# ===========================================================================
# price-performance (#1900 — full-wiring of #1645)
# ===========================================================================


def _perf_row(**overrides: object) -> dict:
    """Return a realistic one-row fmp_cached price-performance dump (fractions)."""
    row = {
        "symbol": "AAPL",
        "one_day": -0.0013414,
        "wtd": None,
        "one_week": 0.0136314,
        "mtd": None,
        "one_month": -0.0118179,
        "qtd": None,
        "three_month": 0.0872158,
        "six_month": 0.201,
        "ytd": 0.1844,
        "one_year": 0.241,
        "two_year": None,
        "three_year": 0.8231,
        "four_year": None,
        "five_year": 2.456,
        "ten_year": None,
        "max": 12.3,
    }
    row.update(overrides)
    return row


def test_shape_price_performance_maps_and_percent_converts() -> None:
    """Horizons map to labels; fractions convert to percent (2 dp)."""
    out = tier_calls._shape_price_performance(_perf_row())
    by_period = {r["period"]: r["return_pct"] for r in out}
    assert by_period["1D"] == -0.13
    assert by_period["1W"] == 1.36
    assert by_period["3M"] == 8.72
    assert by_period["1Y"] == 24.1
    assert by_period["5Y"] == 245.6
    # Order + coverage: 9 horizons, in declared order.
    assert [r["period"] for r in out] == [
        "1D",
        "1W",
        "1M",
        "3M",
        "6M",
        "YTD",
        "1Y",
        "3Y",
        "5Y",
    ]


def test_shape_price_performance_omits_none_horizons() -> None:
    """A ``None`` source horizon is omitted, not emitted with a fake value."""
    out = tier_calls._shape_price_performance(_perf_row(six_month=None, one_year=None))
    periods = {r["period"] for r in out}
    assert "6M" not in periods and "1Y" not in periods
    assert "1D" in periods  # non-null horizons still present


def test_perf_tier_call_composes_fetch_and_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered tier call fetches then shapes into period rows."""
    monkeypatch.setattr(
        tier_calls, "_fetch_price_performance_row", lambda symbol: _perf_row()
    )
    call = _TIER_CALLS[("equity/price-performance", "fmp_cached")]
    rows = call(symbol="AAPL")
    assert {"period", "return_pct"} == set(rows[0])
    assert rows[0] == {"period": "1D", "return_pct": -0.13}


def test_perf_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """All-None row -> WARNING + ``[]`` (chain transitions to stub)."""
    empty = {k: None for k in _perf_row()}
    empty["symbol"] = "ZZZZ"
    monkeypatch.setattr(
        tier_calls, "_fetch_price_performance_row", lambda symbol: empty
    )
    call = _TIER_CALLS[("equity/price-performance", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger="openbb_portfolio_intel"):
        out = call(symbol="ZZZZ")
    assert out == []
    hits = [r for r in caplog.records if "0 rows" in r.getMessage()]
    assert len(hits) == 1, "loud-empty WARNING must fire exactly once"


def test_register_all_wires_price_performance() -> None:
    """The production registration wires the fmp_cached price-performance tier."""
    assert ("equity/price-performance", "fmp_cached") in _TIER_CALLS


def test_perf_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint returns the tier's shaped rows.

    The stub emits fixed values (1D=0.54); the fixture yields 1D=-0.13.
    Asserting the fixture-derived value proves the fmp_cached tier served.
    """
    monkeypatch.setattr(
        tier_calls, "_fetch_price_performance_row", lambda symbol: _perf_row()
    )
    resp = _client.get("/pi/equity/price-performance?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert {"period": "1D", "return_pct": -0.13} in rows
    assert not any(r["return_pct"] == 0.54 for r in rows), "served the stub!"


def test_perf_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> dict:
        seen["symbol"] = symbol
        return _perf_row()

    monkeypatch.setattr(tier_calls, "_fetch_price_performance_row", _capture)
    resp = _client.get("/pi/equity/price-performance?symbol=+aapl+")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen['symbol']!r}"


def test_perf_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(
        tier_calls, "_fetch_price_performance_row", lambda symbol: _perf_row()
    )
    resp = _client.get("/pi/equity/price-performance?symbol=<script>")
    assert resp.status_code == 400


@pytest.mark.integration
def test_price_performance_fmp_cached_live() -> None:
    """Live: fmp_cached returns real trailing returns the shaper can consume.

    Not ``plan_limited`` — ``equity.price.performance`` is covered by our
    current FMP key (verified during the #1900 feasibility gate).
    """
    row = tier_calls._fetch_price_performance_row("AAPL")
    assert row, "fmp_cached returned no AAPL price performance — wiring broken"
    shaped = tier_calls._shape_price_performance(row)
    assert shaped, "no non-null horizons — shaper produced empty"
    assert {"period", "return_pct"} == set(shaped[0])
    assert isinstance(shaped[0]["return_pct"], float)


# ---------------------------------------------------------------------------
# management-team (#1902 — full-wiring of #1648)
# ---------------------------------------------------------------------------


def _mgmt_rows() -> list[dict]:
    """Realistic-shape fmp_cached key-executive dump (extras the shaper drops).

    Real ``obb.equity.fundamental.management(provider="fmp_cached")`` rows
    carry ``name, title, pay, year_born, gender, currency_pay`` — no tenure.
    Includes a ``pay=None`` row and a nameless row so the shaper's None and
    skip branches are exercised.
    """
    return [
        {
            "name": "Jane Q. Public",
            "title": "Chief Executive Officer",
            "pay": 12_345_678,
            "year_born": 1968,
            "gender": "female",
            "currency_pay": "USD",
        },
        {
            "name": "John Roe",
            "title": "Chief Financial Officer",
            "pay": None,
            "year_born": 1975,
            "gender": "male",
            "currency_pay": "USD",
        },
        {
            "name": "",
            "title": "Unnamed Director",
            "pay": 999,
        },
    ]


def test_shape_management_maps_and_nulls_tenure() -> None:
    """Pay -> pay_usd; tenure_years always None; nameless row skipped."""
    out = tier_calls._shape_management(_mgmt_rows())
    assert out == [
        {
            "name": "Jane Q. Public",
            "title": "Chief Executive Officer",
            "pay_usd": 12_345_678,
            "tenure_years": None,
        },
        {
            "name": "John Roe",
            "title": "Chief Financial Officer",
            "pay_usd": None,
            "tenure_years": None,
        },
    ]


def test_mgmt_tier_call_composes_fetch_and_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered tier call composes fetch + shape into contract rows."""
    monkeypatch.setattr(
        tier_calls, "_fetch_management_rows", lambda symbol: _mgmt_rows()
    )
    call = _TIER_CALLS[("equity/management-team", "fmp_cached")]
    out = call(symbol="AAPL")
    assert out[0]["name"] == "Jane Q. Public"
    assert set(out[0]) == {"name", "title", "pay_usd", "tenure_years"}


def test_mgmt_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty fetch logs a WARNING (0 rows) and returns [] (chain moves on)."""
    monkeypatch.setattr(tier_calls, "_fetch_management_rows", lambda symbol: [])
    call = _TIER_CALLS[("equity/management-team", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="AAPL")
    assert out == []
    assert any("0 rows" in r.getMessage() for r in caplog.records)


def test_register_all_wires_management_team() -> None:
    """The production registration wires the fmp_cached management tier."""
    assert ("equity/management-team", "fmp_cached") in _TIER_CALLS


def test_mgmt_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint returns the tier's shaped rows.

    The stub emits Timothy D. Cook / CEO; the fixture yields Jane Q. Public.
    Asserting the fixture-derived name proves the fmp_cached tier served.
    """
    monkeypatch.setattr(
        tier_calls, "_fetch_management_rows", lambda symbol: _mgmt_rows()
    )
    resp = _client.get("/pi/equity/management-team?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows[0]["name"] == "Jane Q. Public"
    assert not any(r["name"] == "Timothy D. Cook" for r in rows), "served the stub!"


def test_mgmt_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> list[dict]:
        seen["symbol"] = symbol
        return _mgmt_rows()

    monkeypatch.setattr(tier_calls, "_fetch_management_rows", _capture)
    resp = _client.get("/pi/equity/management-team?symbol=+aapl+")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen['symbol']!r}"


def test_mgmt_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(
        tier_calls, "_fetch_management_rows", lambda symbol: _mgmt_rows()
    )
    resp = _client.get("/pi/equity/management-team?symbol=<script>")
    assert resp.status_code == 400


@pytest.mark.integration
def test_management_team_fmp_cached_live() -> None:
    """Live: fmp_cached returns real key executives the shaper can consume.

    Not ``plan_limited`` — ``equity.fundamental.management`` is covered by our
    current FMP key (verified during the #1902 feasibility probe).
    """
    rows = tier_calls._fetch_management_rows("AAPL")
    assert rows, "fmp_cached returned no AAPL management — wiring broken"
    shaped = tier_calls._shape_management(rows)
    assert shaped, "no named executives — shaper produced empty"
    assert set(shaped[0]) == {"name", "title", "pay_usd", "tenure_years"}
    assert shaped[0]["tenure_years"] is None


# ---------------------------------------------------------------------------
# revenue-geography (#1904 — full-wiring of #1649)
# ---------------------------------------------------------------------------


def _geo_rows() -> list[dict]:
    """Realistic fmp_cached revenue-by-geography dump spanning two periods.

    Real ``RevenueGeographicData`` rows carry ``period_ending, fiscal_period,
    fiscal_year, filing_date, region, revenue``. Two fiscal periods are
    present so the shaper's latest-period selection is exercised; the latest
    period (2026-09-30) also has a **split** Americas segment to exercise
    per-region aggregation, plus a null-revenue row to exercise the skip.
    """
    old = _dt.date(2025, 9, 30)
    new = _dt.date(2026, 9, 30)
    return [
        {"period_ending": old, "region": "Americas", "revenue": 100_000},
        {"period_ending": old, "region": "Europe", "revenue": 50_000},
        {"period_ending": new, "region": "Americas", "revenue": 120_000},
        {"period_ending": new, "region": "Americas", "revenue": 5_000},
        {"period_ending": new, "region": "Europe", "revenue": 60_000},
        {"period_ending": new, "region": "Greater China", "revenue": None},
    ]


def test_shape_revenue_geography_latest_period_and_aggregates() -> None:
    """Only the latest period; revenue summed per region; null revenue dropped."""
    out = tier_calls._shape_revenue_geography(_geo_rows())
    assert out == [
        {"region": "Americas", "revenue": 125_000},
        {"region": "Europe", "revenue": 60_000},
    ]


def test_shape_revenue_geography_empty_when_no_periods() -> None:
    """Rows lacking period_ending yield [] (nothing to anchor 'latest' on)."""
    assert tier_calls._shape_revenue_geography([{"region": "X", "revenue": 1}]) == []


def test_geo_tier_call_composes_fetch_and_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered tier call composes fetch + shape into contract rows."""
    monkeypatch.setattr(
        tier_calls, "_fetch_revenue_geography_rows", lambda symbol: _geo_rows()
    )
    call = _TIER_CALLS[("equity/revenue-geography", "fmp_cached")]
    out = call(symbol="AAPL")
    assert out == [
        {"region": "Americas", "revenue": 125_000},
        {"region": "Europe", "revenue": 60_000},
    ]


def test_geo_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty fetch logs a WARNING (0 rows) and returns [] (chain moves on)."""
    monkeypatch.setattr(tier_calls, "_fetch_revenue_geography_rows", lambda symbol: [])
    call = _TIER_CALLS[("equity/revenue-geography", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="AAPL")
    assert out == []
    assert any("0 rows" in r.getMessage() for r in caplog.records)


def test_register_all_wires_revenue_geography() -> None:
    """The production registration wires the fmp_cached revenue-geography tier."""
    assert ("equity/revenue-geography", "fmp_cached") in _TIER_CALLS


def test_geo_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint returns the tier's shaped rows.

    The stub emits Americas=162560; the fixture's latest period yields
    Americas=125000. Asserting the fixture value proves the tier served.
    """
    monkeypatch.setattr(
        tier_calls, "_fetch_revenue_geography_rows", lambda symbol: _geo_rows()
    )
    resp = _client.get("/pi/equity/revenue-geography?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert {"region": "Americas", "revenue": 125_000} in rows
    assert not any(r["revenue"] == 162560 for r in rows), "served the stub!"


def test_geo_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> list[dict]:
        seen["symbol"] = symbol
        return _geo_rows()

    monkeypatch.setattr(tier_calls, "_fetch_revenue_geography_rows", _capture)
    resp = _client.get("/pi/equity/revenue-geography?symbol=+aapl+")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen['symbol']!r}"


def test_geo_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(
        tier_calls, "_fetch_revenue_geography_rows", lambda symbol: _geo_rows()
    )
    resp = _client.get("/pi/equity/revenue-geography?symbol=<script>")
    assert resp.status_code == 400


@pytest.mark.integration
def test_revenue_geography_fmp_cached_live() -> None:
    """Live: fmp_cached returns real geographic revenue the shaper can consume.

    Not ``plan_limited`` — ``equity.fundamental.revenue_per_geography`` is
    covered by our current FMP key (verified during the #1904 probe).
    """
    rows = tier_calls._fetch_revenue_geography_rows("AAPL")
    assert rows, "fmp_cached returned no AAPL geo revenue — wiring broken"
    shaped = tier_calls._shape_revenue_geography(rows)
    assert shaped, "no regions in latest period — shaper produced empty"
    assert set(shaped[0]) == {"region", "revenue"}
    assert isinstance(shaped[0]["revenue"], (int, float))


# ---------------------------------------------------------------------------
# revenue-business-line (#1906 — full-wiring of #1650)
# ---------------------------------------------------------------------------


def _seg_rows() -> list[dict]:
    """Realistic fmp_cached revenue-by-segment dump spanning two periods.

    Real ``RevenueBusinessLineData`` rows carry ``period_ending, fiscal_period,
    fiscal_year, filing_date, business_line, revenue``. Two periods are present
    (latest-period selection); the latest period splits ``iPhone`` across two
    rows (per-segment aggregation) and includes a null-business_line row (skip).
    """
    old = _dt.date(2025, 9, 30)
    new = _dt.date(2026, 9, 30)
    return [
        {"period_ending": old, "business_line": "iPhone", "revenue": 190_000},
        {"period_ending": old, "business_line": "Services", "revenue": 80_000},
        {"period_ending": new, "business_line": "iPhone", "revenue": 200_000},
        {"period_ending": new, "business_line": "iPhone", "revenue": 3_000},
        {"period_ending": new, "business_line": "Services", "revenue": 96_000},
        {"period_ending": new, "business_line": None, "revenue": 1_000},
    ]


def test_shape_revenue_business_line_latest_period_renames_and_aggregates() -> None:
    """Latest period only; revenue summed per segment; business_line->segment."""
    out = tier_calls._shape_revenue_business_line(_seg_rows())
    assert out == [
        {"segment": "iPhone", "revenue": 203_000},
        {"segment": "Services", "revenue": 96_000},
    ]


def test_shape_revenue_business_line_empty_when_no_periods() -> None:
    """Rows lacking period_ending yield [] (nothing to anchor 'latest' on)."""
    assert (
        tier_calls._shape_revenue_business_line([{"business_line": "X", "revenue": 1}])
        == []
    )


def test_seg_tier_call_composes_fetch_and_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered tier call composes fetch + shape into contract rows."""
    monkeypatch.setattr(
        tier_calls, "_fetch_revenue_business_line_rows", lambda symbol: _seg_rows()
    )
    call = _TIER_CALLS[("equity/revenue-business-line", "fmp_cached")]
    out = call(symbol="AAPL")
    assert out == [
        {"segment": "iPhone", "revenue": 203_000},
        {"segment": "Services", "revenue": 96_000},
    ]


def test_seg_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty fetch logs a WARNING (0 rows) and returns [] (chain moves on)."""
    monkeypatch.setattr(
        tier_calls, "_fetch_revenue_business_line_rows", lambda symbol: []
    )
    call = _TIER_CALLS[("equity/revenue-business-line", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="AAPL")
    assert out == []
    assert any("0 rows" in r.getMessage() for r in caplog.records)


def test_register_all_wires_revenue_business_line() -> None:
    """The production registration wires the fmp_cached business-line tier."""
    assert ("equity/revenue-business-line", "fmp_cached") in _TIER_CALLS


def test_seg_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint returns the tier's shaped rows.

    The stub emits iPhone=200583; the fixture's latest period yields
    iPhone=203000. Asserting the fixture value proves the tier served.
    """
    monkeypatch.setattr(
        tier_calls, "_fetch_revenue_business_line_rows", lambda symbol: _seg_rows()
    )
    resp = _client.get("/pi/equity/revenue-business-line?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert {"segment": "iPhone", "revenue": 203_000} in rows
    assert not any(r["revenue"] == 200583 for r in rows), "served the stub!"


def test_seg_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> list[dict]:
        seen["symbol"] = symbol
        return _seg_rows()

    monkeypatch.setattr(tier_calls, "_fetch_revenue_business_line_rows", _capture)
    resp = _client.get("/pi/equity/revenue-business-line?symbol=+aapl+")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen['symbol']!r}"


def test_seg_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(
        tier_calls, "_fetch_revenue_business_line_rows", lambda symbol: _seg_rows()
    )
    resp = _client.get("/pi/equity/revenue-business-line?symbol=<script>")
    assert resp.status_code == 400


@pytest.mark.integration
def test_revenue_business_line_fmp_cached_live() -> None:
    """Live: fmp_cached returns real business-line revenue the shaper consumes.

    Not ``plan_limited`` — ``equity.fundamental.revenue_per_segment`` is
    covered by our current FMP key (verified during the #1906 probe).
    """
    rows = tier_calls._fetch_revenue_business_line_rows("AAPL")
    assert rows, "fmp_cached returned no AAPL segment revenue — wiring broken"
    shaped = tier_calls._shape_revenue_business_line(rows)
    assert shaped, "no segments in latest period — shaper produced empty"
    assert set(shaped[0]) == {"segment", "revenue"}
    assert isinstance(shaped[0]["revenue"], (int, float))
