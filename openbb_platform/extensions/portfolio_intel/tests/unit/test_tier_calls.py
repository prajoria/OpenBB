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


# ---------------------------------------------------------------------------
# dividend-payment (#1908 — full-wiring of #1665)
# ---------------------------------------------------------------------------


def _div_rows() -> list[dict]:
    """Realistic fmp_cached dividend dump, deliberately out of order.

    Real ``HistoricalDividendsData`` carries ``symbol, ex_dividend_date,
    amount`` plus the FMP ``payment_date`` extra (both dates are
    ``datetime.date`` after model_dump). Includes an out-of-order sequence
    (to exercise newest-first sorting) and a null-amount row (skip).
    """
    return [
        {
            "symbol": "AAPL",
            "ex_dividend_date": _dt.date(2025, 11, 10),
            "payment_date": _dt.date(2025, 11, 16),
            "amount": 0.24,
        },
        {
            "symbol": "AAPL",
            "ex_dividend_date": _dt.date(2026, 5, 10),
            "payment_date": _dt.date(2026, 5, 16),
            "amount": 0.25,
        },
        {
            "symbol": "AAPL",
            "ex_dividend_date": _dt.date(2026, 2, 9),
            "payment_date": _dt.date(2026, 2, 15),
            "amount": 0.24,
        },
        {
            "symbol": "AAPL",
            "ex_dividend_date": _dt.date(2020, 1, 1),
            "payment_date": None,
            "amount": None,
        },
    ]


def test_shape_dividends_sorts_desc_and_iso_stringifies() -> None:
    """Newest-first; dates -> ISO strings; ex_dividend_date -> ex_date; null amount skipped."""
    out = tier_calls._shape_dividends(_div_rows())
    assert out == [
        {"ex_date": "2026-05-10", "payment_date": "2026-05-16", "amount": 0.25},
        {"ex_date": "2026-02-09", "payment_date": "2026-02-15", "amount": 0.24},
        {"ex_date": "2025-11-10", "payment_date": "2025-11-16", "amount": 0.24},
    ]


def test_shape_dividends_caps_to_limit() -> None:
    """No more than _DIVIDENDS_LIMIT rows are returned (newest kept)."""
    many = [
        {
            "ex_dividend_date": _dt.date(2000 + i // 4, (i % 4) * 3 + 1, 1),
            "payment_date": None,
            "amount": 0.1,
        }
        for i in range(40)
    ]
    out = tier_calls._shape_dividends(many)
    assert len(out) == tier_calls._DIVIDENDS_LIMIT
    # Newest row must be present; the very oldest must be dropped.
    dates = [r["ex_date"] for r in out]
    assert dates == sorted(dates, reverse=True)


def test_div_tier_call_composes_fetch_and_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered tier call composes fetch + shape into contract rows."""
    monkeypatch.setattr(tier_calls, "_fetch_dividend_rows", lambda symbol: _div_rows())
    call = _TIER_CALLS[("equity/dividend-payment", "fmp_cached")]
    out = call(symbol="AAPL")
    assert out[0] == {
        "ex_date": "2026-05-10",
        "payment_date": "2026-05-16",
        "amount": 0.25,
    }


def test_div_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty fetch logs a WARNING (0 rows) and returns [] (chain moves on)."""
    monkeypatch.setattr(tier_calls, "_fetch_dividend_rows", lambda symbol: [])
    call = _TIER_CALLS[("equity/dividend-payment", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="AAPL")
    assert out == []
    assert any("0 rows" in r.getMessage() for r in caplog.records)


def test_register_all_wires_dividend_payment() -> None:
    """The production registration wires the fmp_cached dividend tier."""
    assert ("equity/dividend-payment", "fmp_cached") in _TIER_CALLS


def test_div_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint returns the tier's shaped rows.

    The fixture yields exactly 3 rows; the stub yields 4 (it has an extra
    2025-08-11 row the fixture lacks). Assert both to prove the tier served.
    """
    monkeypatch.setattr(tier_calls, "_fetch_dividend_rows", lambda symbol: _div_rows())
    resp = _client.get("/pi/equity/dividend-payment?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 3, f"expected 3 fixture rows, got {len(rows)} (stub has 4)"
    assert not any(r["ex_date"] == "2025-08-11" for r in rows), "served the stub!"


def test_div_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> list[dict]:
        seen["symbol"] = symbol
        return _div_rows()

    monkeypatch.setattr(tier_calls, "_fetch_dividend_rows", _capture)
    resp = _client.get("/pi/equity/dividend-payment?symbol=+aapl+")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen['symbol']!r}"


def test_div_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(tier_calls, "_fetch_dividend_rows", lambda symbol: _div_rows())
    resp = _client.get("/pi/equity/dividend-payment?symbol=<script>")
    assert resp.status_code == 400


@pytest.mark.integration
def test_dividend_payment_fmp_cached_live() -> None:
    """Live: fmp_cached returns real dividends the shaper can consume.

    Not ``plan_limited`` — ``equity.fundamental.dividends`` is covered by our
    current FMP key (verified during the #1908 probe).
    """
    rows = tier_calls._fetch_dividend_rows("AAPL")
    assert rows, "fmp_cached returned no AAPL dividends — wiring broken"
    shaped = tier_calls._shape_dividends(rows)
    assert shaped, "shaper produced empty"
    assert set(shaped[0]) == {"ex_date", "payment_date", "amount"}
    assert isinstance(shaped[0]["amount"], (int, float))
    # Newest-first ordering holds on live data.
    ex_dates = [r["ex_date"] for r in shaped]
    assert ex_dates == sorted(ex_dates, reverse=True)


# ---------------------------------------------------------------------------
# insider-trading (#1910 — full-wiring of #1661)
# ---------------------------------------------------------------------------


def _insider_rows() -> list[dict]:
    """Realistic fmp_cached insider dump: positive qty + A/D sign flag.

    Deliberately out of order (to exercise sort), with a disposition (sell),
    an acquisition (buy), a null-owner row (skip), and a null-qty row (skip).
    ``securities_transacted`` is always positive; direction is the A/D flag.
    """
    return [
        {
            "owner_name": "COOK TIMOTHY",
            "transaction_date": _dt.date(2026, 5, 1),
            "filing_date": _dt.date(2026, 5, 3),
            "securities_transacted": 223986.0,
            "transaction_price": 173.45,
            "transaction_type": "S-Sale",
            "acquisition_or_disposition": "D",
        },
        {
            "owner_name": "LEVINSON ARTHUR",
            "transaction_date": _dt.date(2026, 6, 15),
            "filing_date": _dt.date(2026, 6, 17),
            "securities_transacted": 5000.0,
            "transaction_price": 311.02,
            "transaction_type": "P-Purchase",
            "acquisition_or_disposition": "A",
        },
        {
            "owner_name": None,
            "transaction_date": _dt.date(2026, 7, 1),
            "filing_date": _dt.date(2026, 7, 2),
            "securities_transacted": 999.0,
            "transaction_price": 1.0,
            "transaction_type": "S-Sale",
            "acquisition_or_disposition": "D",
        },
        {
            "owner_name": "GHOST NOQTY",
            "transaction_date": _dt.date(2026, 6, 20),
            "filing_date": _dt.date(2026, 6, 22),
            "securities_transacted": None,
            "transaction_price": 1.0,
            "transaction_type": "S-Sale",
            "acquisition_or_disposition": "D",
        },
    ]


def test_shape_insider_signs_shares_and_sorts_desc() -> None:
    """D->negative, A->positive shares; newest-first; null owner/qty skipped."""
    out = tier_calls._shape_insider_trading(_insider_rows())
    assert out == [
        {
            "name": "LEVINSON ARTHUR",
            "date": "2026-06-15",
            "shares": 5000.0,
            "transaction_type": "P-Purchase",
            "price_usd": 311.02,
        },
        {
            "name": "COOK TIMOTHY",
            "date": "2026-05-01",
            "shares": -223986.0,
            "transaction_type": "S-Sale",
            "price_usd": 173.45,
        },
    ]


def test_shape_insider_falls_back_to_filing_date() -> None:
    """When transaction_date is missing, filing_date is used for date/sort."""
    rows = [
        {
            "owner_name": "NO TXN DATE",
            "transaction_date": None,
            "filing_date": _dt.date(2026, 2, 2),
            "securities_transacted": 10.0,
            "transaction_price": 5.0,
            "transaction_type": "A-Award",
            "acquisition_or_disposition": "A",
        }
    ]
    out = tier_calls._shape_insider_trading(rows)
    assert out[0]["date"] == "2026-02-02"


def test_shape_insider_caps_to_limit() -> None:
    """No more than _INSIDER_LIMIT rows are returned (newest kept)."""
    many = [
        {
            "owner_name": f"OWNER {i}",
            "transaction_date": _dt.date(2000 + i // 12, (i % 12) + 1, 1),
            "filing_date": None,
            "securities_transacted": 1.0,
            "transaction_price": 1.0,
            "transaction_type": "S-Sale",
            "acquisition_or_disposition": "A",
        }
        for i in range(60)
    ]
    out = tier_calls._shape_insider_trading(many)
    assert len(out) == tier_calls._INSIDER_LIMIT
    dates = [r["date"] for r in out]
    assert dates == sorted(dates, reverse=True)


def test_insider_tier_call_composes_fetch_and_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered tier call composes fetch + shape into contract rows."""
    monkeypatch.setattr(
        tier_calls, "_fetch_insider_rows", lambda symbol: _insider_rows()
    )
    call = _TIER_CALLS[("equity/insider-trading", "fmp_cached")]
    out = call(symbol="AAPL")
    assert out[0]["name"] == "LEVINSON ARTHUR"
    assert out[0]["shares"] == 5000.0
    assert out[1]["shares"] == -223986.0


def test_insider_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty fetch logs a WARNING (0 rows) and returns [] (chain moves on)."""
    monkeypatch.setattr(tier_calls, "_fetch_insider_rows", lambda symbol: [])
    call = _TIER_CALLS[("equity/insider-trading", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="AAPL")
    assert out == []
    assert any("0 rows" in r.getMessage() for r in caplog.records)


def test_register_all_wires_insider_trading() -> None:
    """The production registration wires the fmp_cached insider tier."""
    assert ("equity/insider-trading", "fmp_cached") in _TIER_CALLS


def test_insider_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint returns the tier's shaped rows.

    The fixture yields 2 rows (LEVINSON, COOK); the stub yields 4 and
    contains 'Adams Katherine', which the fixture never does.
    """
    monkeypatch.setattr(
        tier_calls, "_fetch_insider_rows", lambda symbol: _insider_rows()
    )
    resp = _client.get("/pi/equity/insider-trading?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2, f"expected 2 fixture rows, got {len(rows)} (stub has 4)"
    assert not any(r["name"] == "Adams Katherine" for r in rows), "served the stub!"


def test_insider_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> list[dict]:
        seen["symbol"] = symbol
        return _insider_rows()

    monkeypatch.setattr(tier_calls, "_fetch_insider_rows", _capture)
    resp = _client.get("/pi/equity/insider-trading?symbol=+aapl+")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen['symbol']!r}"


def test_insider_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(
        tier_calls, "_fetch_insider_rows", lambda symbol: _insider_rows()
    )
    resp = _client.get("/pi/equity/insider-trading?symbol=<script>")
    assert resp.status_code == 400


@pytest.mark.integration
def test_insider_trading_fmp_cached_live() -> None:
    """Live: fmp_cached returns real insider trades the shaper can consume.

    Not ``plan_limited`` — ``equity.ownership.insider_trading`` is covered by
    our current FMP key (verified during the #1910 probe).
    """
    rows = tier_calls._fetch_insider_rows("AAPL")
    assert rows, "fmp_cached returned no AAPL insider trades — wiring broken"
    shaped = tier_calls._shape_insider_trading(rows)
    assert shaped, "shaper produced empty"
    assert set(shaped[0]) == {
        "name",
        "date",
        "shares",
        "transaction_type",
        "price_usd",
    }
    assert isinstance(shaped[0]["shares"], (int, float))
    dates = [r["date"] for r in shaped]
    assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# earnings-history (#1912 — full-wiring of #1663)
# ---------------------------------------------------------------------------


def _eps_rows() -> list[dict]:
    """Realistic fmp_cached historical-EPS dump, out of order, 2024 dates.

    Uses 2024 report dates (so derived quarters differ from the stub's
    2025/2026 labels). Includes an out-of-order sequence, a future/unreported
    row (null eps_actual -> skip), and a zero-estimate row (surprise -> None).
    """
    return [
        {
            "symbol": "AAPL",
            "date": _dt.date(2024, 5, 2),
            "eps_actual": 1.53,
            "eps_estimated": 1.50,
        },
        {
            "symbol": "AAPL",
            "date": _dt.date(2024, 8, 1),
            "eps_actual": 1.40,
            "eps_estimated": 1.35,
        },
        {
            "symbol": "AAPL",
            "date": _dt.date(2024, 2, 1),
            "eps_actual": 2.18,
            "eps_estimated": 0,
        },
        {
            "symbol": "AAPL",
            "date": _dt.date(2026, 11, 1),
            "eps_actual": None,
            "eps_estimated": 1.60,
        },
    ]


def test_shape_earnings_maps_computes_surprise_and_sorts() -> None:
    """eps_estimated->eps_estimate; surprise computed; quarter from date; sort DESC."""
    out = tier_calls._shape_earnings_history(_eps_rows())
    assert out == [
        {
            "quarter": "Q3 2024",
            "eps_actual": 1.40,
            "eps_estimate": 1.35,
            "surprise_pct": round((1.40 - 1.35) / 1.35 * 100, 2),
        },
        {
            "quarter": "Q2 2024",
            "eps_actual": 1.53,
            "eps_estimate": 1.50,
            "surprise_pct": 2.0,
        },
        {
            "quarter": "Q1 2024",
            "eps_actual": 2.18,
            "eps_estimate": 0,
            "surprise_pct": None,
        },
    ]


def test_calendar_quarter_label_boundaries() -> None:
    """Quarter label maps month ranges to Q1-Q4 correctly."""
    assert tier_calls._calendar_quarter_label(_dt.date(2024, 1, 15)) == "Q1 2024"
    assert tier_calls._calendar_quarter_label(_dt.date(2024, 3, 31)) == "Q1 2024"
    assert tier_calls._calendar_quarter_label(_dt.date(2024, 4, 1)) == "Q2 2024"
    assert tier_calls._calendar_quarter_label(_dt.date(2024, 12, 31)) == "Q4 2024"
    assert tier_calls._calendar_quarter_label(None) is None


def test_shape_earnings_caps_to_limit() -> None:
    """No more than _EARNINGS_LIMIT rows are returned (newest kept)."""
    many = [
        {
            "symbol": "AAPL",
            "date": _dt.date(2010 + i // 4, (i % 4) * 3 + 1, 1),
            "eps_actual": 1.0,
            "eps_estimated": 1.0,
        }
        for i in range(40)
    ]
    out = tier_calls._shape_earnings_history(many)
    assert len(out) == tier_calls._EARNINGS_LIMIT


def test_earnings_tier_call_composes_fetch_and_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered tier call composes fetch + shape into contract rows."""
    monkeypatch.setattr(tier_calls, "_fetch_earnings_rows", lambda symbol: _eps_rows())
    call = _TIER_CALLS[("equity/earnings-history", "fmp_cached")]
    out = call(symbol="AAPL")
    assert out[0]["quarter"] == "Q3 2024"
    assert out[0]["eps_estimate"] == 1.35


def test_earnings_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty fetch logs a WARNING (0 rows) and returns [] (chain moves on)."""
    monkeypatch.setattr(tier_calls, "_fetch_earnings_rows", lambda symbol: [])
    call = _TIER_CALLS[("equity/earnings-history", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="AAPL")
    assert out == []
    assert any("0 rows" in r.getMessage() for r in caplog.records)


def test_register_all_wires_earnings_history() -> None:
    """The production registration wires the fmp_cached earnings tier."""
    assert ("equity/earnings-history", "fmp_cached") in _TIER_CALLS


def test_earnings_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint returns the tier's shaped rows.

    Fixture uses 2024 dates -> quarters like 'Q3 2024' that the stub (2025/26
    labels) never contains, so their presence proves the tier served.
    """
    monkeypatch.setattr(tier_calls, "_fetch_earnings_rows", lambda symbol: _eps_rows())
    resp = _client.get("/pi/equity/earnings-history?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert any(r["quarter"] == "Q3 2024" for r in rows), "served the stub!"
    assert not any(r["quarter"] == "Q3 2026" for r in rows), "served the stub!"


def test_earnings_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> list[dict]:
        seen["symbol"] = symbol
        return _eps_rows()

    monkeypatch.setattr(tier_calls, "_fetch_earnings_rows", _capture)
    resp = _client.get("/pi/equity/earnings-history?symbol=+aapl+")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen['symbol']!r}"


def test_earnings_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(tier_calls, "_fetch_earnings_rows", lambda symbol: _eps_rows())
    resp = _client.get("/pi/equity/earnings-history?symbol=<script>")
    assert resp.status_code == 400


@pytest.mark.integration
def test_earnings_history_fmp_cached_live() -> None:
    """Live: fmp_cached returns real historical EPS the shaper can consume.

    Not ``plan_limited`` — ``equity.fundamental.historical_eps`` is covered by
    our current FMP key (verified during the #1912 probe).
    """
    rows = tier_calls._fetch_earnings_rows("AAPL")
    assert rows, "fmp_cached returned no AAPL historical EPS — wiring broken"
    shaped = tier_calls._shape_earnings_history(rows)
    assert shaped, "shaper produced empty"
    assert set(shaped[0]) == {
        "quarter",
        "eps_actual",
        "eps_estimate",
        "surprise_pct",
    }
    assert isinstance(shaped[0]["eps_actual"], (int, float))


# ---------------------------------------------------------------------------
# company-filings (#1914 — full-wiring of #1666)
# ---------------------------------------------------------------------------


def _filing_rows() -> list[dict]:
    """Realistic fmp_cached company-filings dump, out of order.

    Includes an out-of-order sequence, a row with null report_url (must be
    skipped — the report link is the whole point), and a null-filing_date
    row (also skipped).
    """
    return [
        {
            "filing_date": _dt.date(2024, 5, 2),
            "report_type": "10-Q",
            "report_url": "https://sec.gov/r/q2.htm",
            "filing_url": "https://sec.gov/i/q2-index.htm",
            "symbol": "AAPL",
            "cik": "0000320193",
        },
        {
            "filing_date": _dt.date(2024, 8, 1),
            "report_type": "8-K",
            "report_url": "https://sec.gov/r/8k.htm",
            "filing_url": "https://sec.gov/i/8k-index.htm",
            "symbol": "AAPL",
            "cik": "0000320193",
        },
        {
            "filing_date": _dt.date(2024, 2, 1),
            "report_type": "10-K",
            "report_url": None,
            "filing_url": "https://sec.gov/i/10k-index.htm",
            "symbol": "AAPL",
            "cik": "0000320193",
        },
        {
            "filing_date": None,
            "report_type": "4",
            "report_url": "https://sec.gov/r/form4.xml",
            "filing_url": "https://sec.gov/i/form4-index.htm",
            "symbol": "AAPL",
            "cik": "0000320193",
        },
    ]


def test_shape_company_filings_maps_iso_sorts_and_skips() -> None:
    """ISO dates; null report_url / null filing_date skipped; sorted DESC."""
    out = tier_calls._shape_company_filings(_filing_rows())
    assert out == [
        {
            "filing_date": "2024-08-01",
            "report_type": "8-K",
            "report_url": "https://sec.gov/r/8k.htm",
            "filing_url": "https://sec.gov/i/8k-index.htm",
        },
        {
            "filing_date": "2024-05-02",
            "report_type": "10-Q",
            "report_url": "https://sec.gov/r/q2.htm",
            "filing_url": "https://sec.gov/i/q2-index.htm",
        },
    ]


def test_shape_company_filings_caps_to_limit() -> None:
    """No more than _FILINGS_LIMIT rows are returned (newest kept)."""
    many = [
        {
            "filing_date": _dt.date(2010 + i // 12, (i % 12) + 1, 1),
            "report_type": "8-K",
            "report_url": f"https://sec.gov/r/{i}.htm",
            "filing_url": f"https://sec.gov/i/{i}.htm",
        }
        for i in range(80)
    ]
    out = tier_calls._shape_company_filings(many)
    assert len(out) == tier_calls._FILINGS_LIMIT


def test_company_filings_tier_call_composes_fetch_and_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered tier call composes fetch + shape into contract rows."""
    monkeypatch.setattr(
        tier_calls, "_fetch_filings_rows", lambda symbol: _filing_rows()
    )
    call = _TIER_CALLS[("equity/company-filings", "fmp_cached")]
    out = call(symbol="AAPL")
    assert out[0]["filing_date"] == "2024-08-01"
    assert out[0]["report_type"] == "8-K"


def test_company_filings_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty fetch logs a WARNING (0 rows) and returns [] (chain moves on)."""
    monkeypatch.setattr(tier_calls, "_fetch_filings_rows", lambda symbol: [])
    call = _TIER_CALLS[("equity/company-filings", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="AAPL")
    assert out == []
    assert any("0 rows" in r.getMessage() for r in caplog.records)


def test_register_all_wires_company_filings() -> None:
    """The production registration wires the fmp_cached company-filings tier."""
    assert ("equity/company-filings", "fmp_cached") in _TIER_CALLS


def test_company_filings_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint returns the tier's shaped rows.

    Fixture uses a ``report_url`` key the stub (``date/filing_type/description``)
    never contains, so its presence proves the tier served.
    """
    monkeypatch.setattr(
        tier_calls, "_fetch_filings_rows", lambda symbol: _filing_rows()
    )
    resp = _client.get("/pi/equity/company-filings?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert all("report_url" in r for r in rows), "served the stub!"
    assert not any("description" in r for r in rows), "served the stub!"


def test_company_filings_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> list[dict]:
        seen["symbol"] = symbol
        return _filing_rows()

    monkeypatch.setattr(tier_calls, "_fetch_filings_rows", _capture)
    resp = _client.get("/pi/equity/company-filings?symbol=+aapl+")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen['symbol']!r}"


def test_company_filings_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(
        tier_calls, "_fetch_filings_rows", lambda symbol: _filing_rows()
    )
    resp = _client.get("/pi/equity/company-filings?symbol=<script>")
    assert resp.status_code == 400


@pytest.mark.integration
def test_company_filings_fmp_cached_live() -> None:
    """Live: fmp_cached returns real SEC filings the shaper can consume.

    Not ``plan_limited`` — ``equity.fundamental.filings`` is covered by our
    current FMP key (verified during the #1914 probe).
    """
    rows = tier_calls._fetch_filings_rows("AAPL")
    assert rows, "fmp_cached returned no AAPL filings — wiring broken"
    shaped = tier_calls._shape_company_filings(rows)
    assert shaped, "shaper produced empty"
    assert set(shaped[0]) == {
        "filing_date",
        "report_type",
        "report_url",
        "filing_url",
    }
    assert shaped[0]["report_url"].startswith("http")


# ---------------------------------------------------------------------------
# stock-splits (#1916 — full-wiring of #1664)
# ---------------------------------------------------------------------------


def _split_rows() -> list[dict]:
    """Realistic fmp_cached historical-splits dump, out of order.

    fmp yields float numerator/denominator (e.g. 4.0) and a null
    ``split_ratio``. Includes an out-of-order sequence, a null-date row
    (must be skipped), and a null-denominator row (must be skipped).
    """
    return [
        {
            "date": _dt.date(2014, 6, 9),
            "numerator": 7.0,
            "denominator": 1.0,
            "split_ratio": None,
            "symbol": "AAPL",
            "splitType": "stock-split",
        },
        {
            "date": _dt.date(2020, 8, 31),
            "numerator": 4.0,
            "denominator": 1.0,
            "split_ratio": None,
            "symbol": "AAPL",
            "splitType": "stock-split",
        },
        {
            "date": None,
            "numerator": 2.0,
            "denominator": 1.0,
            "split_ratio": None,
            "symbol": "AAPL",
            "splitType": "stock-split",
        },
        {
            "date": _dt.date(2005, 2, 28),
            "numerator": 2.0,
            "denominator": None,
            "split_ratio": None,
            "symbol": "AAPL",
            "splitType": "stock-split",
        },
    ]


def test_shape_stock_splits_derives_ratio_coerces_and_sorts() -> None:
    """int-coerced num/den; ratio derived; null date/den skipped; sort DESC."""
    out = tier_calls._shape_stock_splits(_split_rows())
    assert out == [
        {"date": "2020-08-31", "numerator": 4, "denominator": 1, "ratio": "4:1"},
        {"date": "2014-06-09", "numerator": 7, "denominator": 1, "ratio": "7:1"},
    ]


def test_shape_stock_splits_caps_to_limit() -> None:
    """No more than _SPLITS_LIMIT rows are returned (newest kept)."""
    many = [
        {
            "date": _dt.date(1990 + i, 1, 1),
            "numerator": 2.0,
            "denominator": 1.0,
            "split_ratio": None,
        }
        for i in range(30)
    ]
    out = tier_calls._shape_stock_splits(many)
    assert len(out) == tier_calls._SPLITS_LIMIT


def test_stock_splits_tier_call_composes_fetch_and_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered tier call composes fetch + shape into contract rows."""
    monkeypatch.setattr(tier_calls, "_fetch_splits_rows", lambda symbol: _split_rows())
    call = _TIER_CALLS[("equity/stock-splits", "fmp_cached")]
    out = call(symbol="AAPL")
    assert out[0]["date"] == "2020-08-31"
    assert out[0]["ratio"] == "4:1"


def test_stock_splits_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty fetch logs a WARNING (0 rows) and returns [] (chain moves on)."""
    monkeypatch.setattr(tier_calls, "_fetch_splits_rows", lambda symbol: [])
    call = _TIER_CALLS[("equity/stock-splits", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="AAPL")
    assert out == []
    assert any("0 rows" in r.getMessage() for r in caplog.records)


def test_register_all_wires_stock_splits() -> None:
    """The production registration wires the fmp_cached stock-splits tier."""
    assert ("equity/stock-splits", "fmp_cached") in _TIER_CALLS


def test_stock_splits_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint returns the tier's shaped rows.

    The fixture's 2020 7:1-then-4:1 ordering and derived-ratio come from the
    shaper; the stub's oldest row is a 1987 2:1 that the fixture never yields,
    so its absence proves the tier served.
    """
    monkeypatch.setattr(tier_calls, "_fetch_splits_rows", lambda symbol: _split_rows())
    resp = _client.get("/pi/equity/stock-splits?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows[0]["date"] == "2020-08-31", "served the stub!"
    assert not any(r["date"] == "1987-06-16" for r in rows), "served the stub!"


def test_stock_splits_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> list[dict]:
        seen["symbol"] = symbol
        return _split_rows()

    monkeypatch.setattr(tier_calls, "_fetch_splits_rows", _capture)
    resp = _client.get("/pi/equity/stock-splits?symbol=+aapl+")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen['symbol']!r}"


def test_stock_splits_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(tier_calls, "_fetch_splits_rows", lambda symbol: _split_rows())
    resp = _client.get("/pi/equity/stock-splits?symbol=<script>")
    assert resp.status_code == 400


@pytest.mark.integration
def test_stock_splits_fmp_cached_live() -> None:
    """Live: fmp_cached returns real historical splits the shaper can consume.

    Not ``plan_limited`` — ``equity.fundamental.historical_splits`` is covered
    by our current FMP key (verified during the #1916 probe).
    """
    rows = tier_calls._fetch_splits_rows("AAPL")
    assert rows, "fmp_cached returned no AAPL splits — wiring broken"
    shaped = tier_calls._shape_stock_splits(rows)
    assert shaped, "shaper produced empty"
    assert set(shaped[0]) == {"date", "numerator", "denominator", "ratio"}
    assert ":" in shaped[0]["ratio"]
