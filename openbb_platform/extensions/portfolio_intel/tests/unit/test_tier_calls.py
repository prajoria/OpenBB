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


def _long_line_rows(n: int) -> list[dict]:
    """``n`` ascending daily ``{date, close}`` rows ending at a fixed anchor."""
    end = _dt.date(2026, 8, 1)
    out: list[dict] = []
    d = end - _dt.timedelta(days=n - 1)
    close = 100.0
    while d <= end:
        out.append({"date": d.isoformat(), "close": round(close, 2)})
        d += _dt.timedelta(days=1)
        close += 0.1
    return out


def test_slice_rows_to_range_narrows_shorter_window() -> None:
    """A shorter range keeps fewer trailing rows than a longer one."""
    rows = _long_line_rows(800)  # ~2.2 years of calendar days
    n1m = len(tier_calls._slice_rows_to_range(rows, "1M"))
    n6m = len(tier_calls._slice_rows_to_range(rows, "6M"))
    n1y = len(tier_calls._slice_rows_to_range(rows, "1Y"))
    assert n1m < n6m < n1y <= len(rows), f"{n1m},{n6m},{n1y},{len(rows)}"
    # 1M ≈ 30 calendar days (inclusive of anchor) -> ~31 rows.
    assert 28 <= n1m <= 33, f"1M ≈ 30 calendar days, got {n1m}"


def test_slice_rows_to_range_keeps_last_bar() -> None:
    """The most recent bar always survives any range slice (anchor kept)."""
    rows = _long_line_rows(400)
    for rng in ("1M", "3M", "6M", "YTD", "1Y", "5Y"):
        sliced = tier_calls._slice_rows_to_range(rows, rng)
        assert sliced[-1] == rows[-1], f"{rng} dropped the latest bar"


def test_slice_rows_to_range_passthrough_when_unparseable() -> None:
    """All-unparseable dates -> return unchanged (degrade to show-everything)."""
    rows = [{"date": "not-a-date", "close": 1.0}, {"date": None, "close": 2.0}]
    assert tier_calls._slice_rows_to_range(rows, "1M") == rows


def test_tier_call_honors_range(monkeypatch: pytest.MonkeyPatch) -> None:
    """The registered tier call slices live rows to the requested range."""
    monkeypatch.setattr(
        tier_calls, "_fetch_price_history_rows", lambda symbol: _long_line_rows(800)
    )
    call = _TIER_CALLS[("equity/price-history", "fmp_cached")]
    short = call(symbol="AAPL", chart_type="line", range_="1M")
    long = call(symbol="AAPL", chart_type="line", range_="1Y")
    assert len(short) < len(long), "range=1M must return fewer rows than range=1Y"


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

    The stub (``_demo_ohlc_series``) emits a multi-month business-day series
    (≈126 rows for the default 6M range, ending at the fixed demo anchor); the
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


# ---------------------------------------------------------------------------
# charting / technicals (#1918 — full-wiring of #1655)
# ---------------------------------------------------------------------------


def _charting_rows(
    n: int,
    *,
    anchor: _dt.date = _dt.date(2023, 6, 30),
    start: float = 100.0,
    step: float = 1.0,
) -> list[dict]:
    """Generate ``n`` daily OHLCV bars ending at ``anchor``, ascending by date.

    ``close`` moves by ``step`` per bar (monotonic-up for ``step>0``), so SMA
    and RSI are hand-verifiable. Dates are ``datetime.date`` (fmp_cached shape).
    """
    rows: list[dict] = []
    for i in range(n):
        d = anchor - _dt.timedelta(days=n - 1 - i)
        c = start + step * i
        rows.append(
            {
                "date": d,
                "open": c - 0.5,
                "high": c + 1.0,
                "low": c - 1.0,
                "close": c,
                "volume": 1000 + i,
            }
        )
    return rows


def test_shape_charting_computes_sma_over_full_series() -> None:
    """SMA20 = mean of the trailing 20 closes; SMA50 None with <50 bars."""
    out = tier_calls._shape_charting(_charting_rows(25), "3M")
    assert len(out) == 25
    # closes are 100..124; trailing-20 mean at the last bar = mean(105..124).
    assert out[-1]["sma20"] == 114.5
    assert out[-1]["sma50"] is None
    assert out[0]["sma20"] is None  # not enough lookback on the first bar


def test_shape_charting_rsi_direction() -> None:
    """RSI is 100 for a monotonic-up series and 0 for a monotonic-down one."""
    up = tier_calls._shape_charting(_charting_rows(40, step=1.0), "3M")
    down = tier_calls._shape_charting(_charting_rows(40, start=200.0, step=-1.0), "3M")
    assert up[-1]["rsi14"] == 100.0
    assert down[-1]["rsi14"] == 0.0


def test_shape_charting_slices_to_window() -> None:
    """The 1M window keeps only bars within 30 calendar days of the last bar."""
    out = tier_calls._shape_charting(_charting_rows(200), "1M")
    assert len(out) == 31  # anchor-30d .. anchor inclusive, 1 bar/day
    assert out[0]["date"] == "2023-05-31"
    assert out[-1]["date"] == "2023-06-30"


def test_shape_charting_ytd_window() -> None:
    """The YTD window cuts off at Jan 1 of the last bar's year."""
    out = tier_calls._shape_charting(_charting_rows(200), "YTD")
    assert all(row["date"] >= "2023-01-01" for row in out)
    assert out[0]["date"] == "2023-01-01"


def test_shape_charting_skips_null_close_and_date() -> None:
    """Rows lacking a usable date or close are dropped before indicators."""
    rows = _charting_rows(5)
    rows.append({"date": None, "close": 500.0})
    rows.append({"date": _dt.date(2023, 6, 29), "close": None})
    out = tier_calls._shape_charting(rows, "3M")
    assert len(out) == 5
    assert all(r["close"] is not None for r in out)


def test_charting_tier_call_composes_fetch_and_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered tier call composes the price fetch + charting shape."""
    monkeypatch.setattr(
        tier_calls, "_fetch_price_history_rows", lambda symbol: _charting_rows(60)
    )
    call = _TIER_CALLS[("charting", "fmp_cached")]
    out = call(symbol="AAPL", window="3M")
    assert out, "tier call returned empty"
    assert set(out[0]) >= {"date", "open", "high", "low", "close", "sma20", "rsi14"}


def test_charting_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty fetch logs a WARNING (0 rows) and returns [] (chain moves on)."""
    monkeypatch.setattr(tier_calls, "_fetch_price_history_rows", lambda symbol: [])
    call = _TIER_CALLS[("charting", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="AAPL", window="3M")
    assert out == []
    assert any("0 rows" in r.getMessage() for r in caplog.records)


def test_register_all_wires_charting() -> None:
    """The production registration wires the fmp_cached charting tier."""
    assert ("charting", "fmp_cached") in _TIER_CALLS


def test_charting_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint serves computed indicator rows.

    The stub's dates are 2026-04-01.., which the fixture never yields, so their
    absence (and the presence of an ``sma20`` key) proves the tier served.
    """
    monkeypatch.setattr(
        tier_calls, "_fetch_price_history_rows", lambda symbol: _charting_rows(60)
    )
    resp = _client.get("/pi/equity/charting?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "empty response"
    assert "sma20" in rows[0], "served the stub!"
    assert not any(r["date"].startswith("2026") for r in rows), "served the stub!"


def test_charting_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> list[dict]:
        seen["symbol"] = symbol
        return _charting_rows(60)

    monkeypatch.setattr(tier_calls, "_fetch_price_history_rows", _capture)
    resp = _client.get("/pi/equity/charting?symbol=+aapl+&window=6M")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen['symbol']!r}"


def test_charting_endpoint_rejects_bad_window_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Window validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(
        tier_calls, "_fetch_price_history_rows", lambda symbol: _charting_rows(60)
    )
    resp = _client.get("/pi/equity/charting?symbol=AAPL&window=2D")
    assert resp.status_code == 400


def test_charting_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(
        tier_calls, "_fetch_price_history_rows", lambda symbol: _charting_rows(60)
    )
    resp = _client.get("/pi/equity/charting?symbol=<script>")
    assert resp.status_code == 400


@pytest.mark.integration
def test_charting_fmp_cached_live() -> None:
    """Live: fmp_cached price history yields enough bars for real indicators.

    Reuses the price-history fetch (not plan_limited); with >50 daily bars the
    3M window still has SMA20 populated on its later bars.
    """
    rows = tier_calls._fetch_price_history_rows("AAPL")
    assert rows, "fmp_cached returned no AAPL price history — wiring broken"
    shaped = tier_calls._shape_charting(rows, "3M")
    assert shaped, "shaper produced empty"
    assert set(shaped[0]) == {
        "date",
        "open",
        "high",
        "low",
        "close",
        "sma20",
        "sma50",
        "rsi14",
    }
    assert any(r["sma20"] is not None for r in shaped), "no SMA20 computed"


# ---------------------------------------------------------------------------
# financials / statements (#1920 — full-wiring of #1653)
# ---------------------------------------------------------------------------


def _statement_fixtures() -> tuple[list[dict], list[dict], list[dict]]:
    """Two-period income/balance/cash fixtures, latest-first (FY2023, FY2022).

    Values differ per period so period_1/period_2 wiring is discriminable, and
    the fields are exactly those the shaper reads (see ``_STATEMENT_ITEMS``).
    """
    income = [
        {
            "period_ending": _dt.date(2023, 9, 30),
            "revenue": 383_285_000_000,
            "gross_profit": 169_148_000_000,
            "total_operating_income": 114_301_000_000,
            "bottom_line_net_income": 96_995_000_000,
        },
        {
            "period_ending": _dt.date(2022, 9, 24),
            "revenue": 394_328_000_000,
            "gross_profit": 170_782_000_000,
            "total_operating_income": 119_437_000_000,
            "bottom_line_net_income": 99_803_000_000,
        },
    ]
    balance = [
        {
            "period_ending": _dt.date(2023, 9, 30),
            "total_assets": 352_583_000_000,
            "total_debt": 111_088_000_000,
            "cash_and_cash_equivalents": 29_965_000_000,
        },
        {
            "period_ending": _dt.date(2022, 9, 24),
            "total_assets": 352_755_000_000,
            "total_debt": 120_069_000_000,
            "cash_and_cash_equivalents": 23_646_000_000,
        },
    ]
    cash = [
        {
            "period_ending": _dt.date(2023, 9, 30),
            "operating_cash_flow": 110_543_000_000,
            "free_cash_flow": 99_584_000_000,
        },
        {
            "period_ending": _dt.date(2022, 9, 24),
            "operating_cash_flow": 122_151_000_000,
            "free_cash_flow": 111_443_000_000,
        },
    ]
    return income, balance, cash


def test_shape_statements_maps_nine_line_items_in_order() -> None:
    """The shaper emits the 9 canonical line items in the fixed stub order."""
    income, balance, cash = _statement_fixtures()
    out = tier_calls._shape_statements(income, balance, cash)
    assert [r["line_item"] for r in out] == [
        "Revenue",
        "Gross Profit",
        "Operating Income",
        "Net Income",
        "Total Assets",
        "Total Debt",
        "Cash & Equivalents",
        "Operating Cash Flow",
        "Free Cash Flow",
    ]


def test_shape_statements_period_1_is_latest_period_2_is_prior() -> None:
    """Raw provider amounts are normalized to USD millions by period."""
    income, balance, cash = _statement_fixtures()
    out = tier_calls._shape_statements(income, balance, cash)
    by = {r["line_item"]: r for r in out}
    # Revenue from income[0]/income[1]
    assert by["Revenue"]["period_1"] == 383285
    assert by["Revenue"]["period_2"] == 394328
    # Total Assets from balance[0]/balance[1]
    assert by["Total Assets"]["period_1"] == 352583
    assert by["Total Assets"]["period_2"] == 352755
    # Free Cash Flow from cash[0]/cash[1]
    assert by["Free Cash Flow"]["period_1"] == 99584
    assert by["Free Cash Flow"]["period_2"] == 111443


def test_statements_live_and_fallback_values_use_usd_millions() -> None:
    """A raw live amount and the fallback both render as 391,000 USD millions."""
    raw_revenue = 391_000_000_000
    live = tier_calls._shape_statements(
        [{"period_ending": _dt.date(2024, 9, 28), "revenue": raw_revenue}],
        [],
        [],
    )
    assert live[0]["period_1"] == 391_000
    assert live[0]["period_1"] not in {391, raw_revenue}

    _TIER_CALLS.clear()
    try:
        response = _client.get("/pi/equity/statements?symbol=AAPL")
    finally:
        tier_calls.register_all(register_tier_call)

    assert response.status_code == 200
    fallback = {row["line_item"]: row for row in response.json()}
    assert fallback["Revenue"]["period_1"] == 391_000
    assert fallback["Revenue"]["period_1"] not in {391, raw_revenue}


def test_shape_statements_missing_prior_period_is_none() -> None:
    """A single available period fills period_1 and leaves period_2 None."""
    income, balance, cash = _statement_fixtures()
    out = tier_calls._shape_statements(income[:1], balance[:1], cash[:1])
    by = {r["line_item"]: r for r in out}
    assert by["Revenue"]["period_1"] == 383285
    assert by["Revenue"]["period_2"] is None


def test_shape_statements_missing_field_is_none() -> None:
    """A field absent from the provider row yields None (not a KeyError)."""
    out = tier_calls._shape_statements(
        [{"period_ending": _dt.date(2023, 9, 30)}], [], []
    )
    by = {r["line_item"]: r for r in out}
    assert by["Revenue"]["period_1"] is None
    assert by["Total Assets"]["period_1"] is None


def test_fetch_statement_sorts_period_ending_desc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fetch returns rows latest-first even if the provider is unsorted."""

    class _Row:
        def __init__(self, d: dict) -> None:
            self._d = d

        def model_dump(self) -> dict:
            return dict(self._d)

    class _Res:
        results = [
            _Row({"period_ending": _dt.date(2021, 9, 25), "revenue": 1}),
            _Row({"period_ending": _dt.date(2023, 9, 30), "revenue": 3}),
            _Row({"period_ending": _dt.date(2022, 9, 24), "revenue": 2}),
        ]

    class _Fundamental:
        def income(self, **_kwargs: object) -> _Res:
            return _Res()

    class _Equity:
        fundamental = _Fundamental()

    class _OBB:
        equity = _Equity()

    monkeypatch.setattr(tier_calls, "_obb", lambda: _OBB())
    rows = tier_calls._fetch_statement("income", "AAPL", "annual")
    assert [r["revenue"] for r in rows] == [3, 2, 1]  # sorted latest-first


def test_statements_tier_call_composes_fetch_and_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered tier call composes the 3-statement fetch + shape."""
    monkeypatch.setattr(
        tier_calls,
        "_fetch_statements_rows",
        lambda symbol, period: _statement_fixtures(),
    )
    call = _TIER_CALLS[("equity/statements", "fmp_cached")]
    out = call(symbol="AAPL", period="annual")
    assert len(out) == 9
    assert out[0]["line_item"] == "Revenue"


def test_statements_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When no statement returns a row, WARN (0 rows) and return []."""
    monkeypatch.setattr(
        tier_calls, "_fetch_statements_rows", lambda symbol, period: ([], [], [])
    )
    call = _TIER_CALLS[("equity/statements", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="AAPL", period="annual")
    assert out == []
    assert any("0 rows" in r.getMessage() for r in caplog.records)


def test_register_all_wires_statements() -> None:
    """The production registration wires the fmp_cached statements tier."""
    assert ("equity/statements", "fmp_cached") in _TIER_CALLS


def test_statements_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint serves live-shaped rows.

    The stub's Revenue period_1 is 391000; the fixture yields 383285, so its
    presence proves the tier served (not the demo stub).
    """
    monkeypatch.setattr(
        tier_calls,
        "_fetch_statements_rows",
        lambda symbol, period: _statement_fixtures(),
    )
    resp = _client.get("/pi/equity/statements?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "empty response"
    by = {r["line_item"]: r for r in rows}
    assert by["Revenue"]["period_1"] == 383285, "served the stub!"


def test_statements_endpoint_forwards_normalized_symbol_and_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker AND the period."""
    seen: dict[str, str] = {}

    def _capture(symbol: str, period: str) -> tuple[list, list, list]:
        seen["symbol"] = symbol
        seen["period"] = period
        return _statement_fixtures()

    monkeypatch.setattr(tier_calls, "_fetch_statements_rows", _capture)
    resp = _client.get("/pi/equity/statements?symbol=+aapl+&period=quarterly")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen['symbol']!r}"
    assert seen["period"] == "quarterly"


def test_statements_endpoint_rejects_bad_period_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Period validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(
        tier_calls,
        "_fetch_statements_rows",
        lambda symbol, period: _statement_fixtures(),
    )
    resp = _client.get("/pi/equity/statements?symbol=AAPL&period=monthly")
    assert resp.status_code == 400


def test_statements_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(
        tier_calls,
        "_fetch_statements_rows",
        lambda symbol, period: _statement_fixtures(),
    )
    resp = _client.get("/pi/equity/statements?symbol=<script>")
    assert resp.status_code == 400


def test_statements_period_map_translates_quarterly() -> None:
    """The widget's 'quarterly' maps to the provider's 'quarter'."""
    assert tier_calls._STATEMENT_PERIOD_MAP["quarterly"] == "quarter"
    assert tier_calls._STATEMENT_PERIOD_MAP["annual"] == "annual"


@pytest.mark.integration
def test_statements_fmp_cached_live() -> None:
    """Live: fmp_cached returns real income/balance/cash statements for AAPL."""
    income, balance, cash = tier_calls._fetch_statements_rows("AAPL", "annual")
    assert (
        income or balance or cash
    ), "fmp_cached returned no statements — wiring broken"
    shaped = tier_calls._shape_statements(income, balance, cash)
    assert len(shaped) == 9
    assert [r["line_item"] for r in shaped][0] == "Revenue"
    # At least the latest revenue should be a real number.
    by = {r["line_item"]: r for r in shaped}
    assert by["Revenue"]["period_1"] is not None, "no live revenue"


# ---------------------------------------------------------------------------
# financials (F2 chart) — full-wiring of stub #1955
# ---------------------------------------------------------------------------
#
# The F2 Financials chart (pi_equity_financial_charts -> pi/equity/financials)
# had no live tier registered, so every symbol fell to the demo stub's
# hardcoded AAPL numbers. These tests drive the live fmp_cached income wiring.


def _income_fixtures() -> list[dict]:
    """Realistic-shape fmp_cached annual income rows (unsorted on purpose).

    Keys mirror the provider (``revenue``, ``bottom_line_net_income``,
    ``period_ending`` as a ``datetime.date``) plus extras the shaper ignores.
    """
    return [
        {
            "period_ending": _dt.date(2023, 9, 30),
            "revenue": 383_285_000_000,
            "bottom_line_net_income": 96_995_000_000,
            "gross_profit": 169_148_000_000,
        },
        {
            "period_ending": _dt.date(2025, 9, 27),
            "revenue": 416_161_000_000,
            "bottom_line_net_income": 112_010_000_000,
            "gross_profit": 190_000_000_000,
        },
        {
            "period_ending": _dt.date(2024, 9, 28),
            "revenue": 391_035_000_000,
            "bottom_line_net_income": 93_736_000_000,
            "gross_profit": 180_683_000_000,
        },
    ]


def test_shape_financials_sorts_year_ascending_and_scales_to_billions() -> None:
    """Rows come out oldest-first with revenue/net income in billions."""
    out = tier_calls._shape_financials(_income_fixtures())
    assert [r["year"] for r in out] == [2023, 2024, 2025]
    first = out[0]
    assert first["revenue_b"] == pytest.approx(383.285, abs=1e-3)
    assert first["net_income_b"] == pytest.approx(96.995, abs=1e-3)


def test_shape_financials_computes_net_margin_pct() -> None:
    """net_margin_pct = net_income / revenue * 100, rounded to 2dp."""
    out = tier_calls._shape_financials(_income_fixtures())
    by = {r["year"]: r for r in out}
    assert by[2025]["net_margin_pct"] == pytest.approx(26.92, abs=0.01)


def test_shape_financials_skips_rows_missing_revenue_or_date() -> None:
    """A row with no revenue or no period_ending is dropped (not 0-division)."""
    rows = [
        {"period_ending": _dt.date(2024, 9, 28), "revenue": None},
        {"period_ending": None, "revenue": 100_000_000_000},
        {
            "period_ending": _dt.date(2025, 9, 27),
            "revenue": 400_000_000_000,
            "bottom_line_net_income": 100_000_000_000,
        },
    ]
    out = tier_calls._shape_financials(rows)
    assert [r["year"] for r in out] == [2025]


def test_shape_financials_net_margin_none_when_net_income_missing() -> None:
    """Missing net income yields net_income_b=None and net_margin_pct=None."""
    rows = [
        {
            "period_ending": _dt.date(2025, 9, 27),
            "revenue": 400_000_000_000,
            "bottom_line_net_income": None,
        }
    ]
    out = tier_calls._shape_financials(rows)
    assert out[0]["net_income_b"] is None
    assert out[0]["net_margin_pct"] is None


def test_financials_tier_call_composes_fetch_and_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered tier call composes the income fetch + shape."""
    monkeypatch.setattr(
        tier_calls, "_fetch_income_annual", lambda symbol: _income_fixtures()
    )
    call = _TIER_CALLS[("equity/financials", "fmp_cached")]
    out = call(symbol="AAPL")
    assert [r["year"] for r in out] == [2023, 2024, 2025]


def test_financials_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When the fetch returns nothing, WARN (0 rows) and return []."""
    monkeypatch.setattr(tier_calls, "_fetch_income_annual", lambda symbol: [])
    call = _TIER_CALLS[("equity/financials", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="AAPL")
    assert out == []
    assert any("0 rows" in r.getMessage() for r in caplog.records)


def test_register_all_wires_financials() -> None:
    """The production registration wires the fmp_cached financials tier."""
    assert ("equity/financials", "fmp_cached") in _TIER_CALLS


def test_financials_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint serves live-shaped rows.

    The stub's first row is year 2021 revenue_b 365.8; the fixture's oldest
    year is 2023, so the absence of 2021 proves the tier served (not the stub).
    """
    monkeypatch.setattr(
        tier_calls, "_fetch_income_annual", lambda symbol: _income_fixtures()
    )
    resp = _client.get("/pi/equity/financials?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "empty response"
    years = [r["year"] for r in rows]
    assert 2021 not in years, "served the stub!"
    assert years == [2023, 2024, 2025]


def test_financials_endpoint_forwards_normalized_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (strip + upper)."""
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> list[dict]:
        seen["symbol"] = symbol
        return _income_fixtures()

    monkeypatch.setattr(tier_calls, "_fetch_income_annual", _capture)
    resp = _client.get("/pi/equity/financials?symbol=+aapl+")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen.get('symbol')!r}"


def test_financials_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(
        tier_calls, "_fetch_income_annual", lambda symbol: _income_fixtures()
    )
    resp = _client.get("/pi/equity/financials?symbol=<script>")
    assert resp.status_code == 400


@pytest.mark.integration
def test_financials_fmp_cached_live() -> None:
    """Live: fmp_cached returns real annual income for AAPL (5 years)."""
    rows = tier_calls._fetch_income_annual("AAPL")
    assert rows, "fmp_cached returned no income statements — wiring broken"
    shaped = tier_calls._shape_financials(rows)
    assert shaped, "shaper dropped every live row"
    assert all(r["revenue_b"] and r["revenue_b"] > 0 for r in shaped)
    # Years must be strictly ascending.
    yrs = [r["year"] for r in shaped]
    assert yrs == sorted(yrs)


# ---------------------------------------------------------------------------
# peer-multiples / competitors (#1923 — full-wiring of #1657)
# ---------------------------------------------------------------------------


def test_shape_peer_row_maps_ratios_and_metrics() -> None:
    """pe_ttm/ps_ttm come from ratios, ev_ebitda from metrics; pe_fwd is None."""
    ratios = {"price_to_earnings": 32.1, "price_to_sales": 8.7}
    metrics = {"ev_to_ebitda": 24.8}
    row = tier_calls._shape_peer_row("AAPL", ratios, metrics)
    assert row == {
        "symbol": "AAPL",
        "pe_ttm": 32.1,
        "pe_fwd": None,
        "ev_ebitda": 24.8,
        "ps_ttm": 8.7,
    }


def test_shape_peer_row_missing_fields_are_none() -> None:
    """Absent provider fields yield None (no KeyError), pe_fwd always None."""
    row = tier_calls._shape_peer_row("XYZ", {}, {})
    assert row["symbol"] == "XYZ"
    assert row["pe_ttm"] is None
    assert row["pe_fwd"] is None
    assert row["ev_ebitda"] is None
    assert row["ps_ttm"] is None


def test_shape_peer_row_coerces_numeric_strings() -> None:
    """Numeric-ish strings are coerced to float; junk becomes None."""
    row = tier_calls._shape_peer_row(
        "AAPL", {"price_to_earnings": "15.5", "price_to_sales": "n/a"}, {}
    )
    assert row["pe_ttm"] == 15.5
    assert row["ps_ttm"] is None


def test_fetch_peer_symbols_caps_and_dedupes_self_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Self is first; peers deduped; total capped at _PEER_CAP + 1."""

    class _Peer:
        def __init__(self, s: str) -> None:
            self.symbol = s

    class _Res:
        results = [_Peer(s) for s in ["MSFT", "GOOGL", "META", "NVDA", "TSM", "AMD"]]

    class _Compare:
        def peers(self, **_kwargs: object) -> _Res:
            return _Res()

    class _Equity:
        compare = _Compare()

    class _OBB:
        equity = _Equity()

    monkeypatch.setattr(tier_calls, "_obb", lambda: _OBB())
    out = tier_calls._fetch_peer_symbols("AAPL")
    assert out[0] == "AAPL"
    assert len(out) == tier_calls._PEER_CAP + 1
    assert len(out) == len(set(out)), "duplicates present"


def test_peer_multiples_tier_call_composes_symbols_and_valuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tier call fans out over symbols and shapes each valuation row."""
    monkeypatch.setattr(
        tier_calls, "_fetch_peer_symbols", lambda symbol: ["AAPL", "MSFT"]
    )
    monkeypatch.setattr(
        tier_calls,
        "_fetch_valuation",
        lambda sym: (
            {"price_to_earnings": 30.0, "price_to_sales": 8.0},
            {"ev_to_ebitda": 20.0},
        ),
    )
    call = _TIER_CALLS[("equity/peer-multiples", "fmp_cached")]
    out = call(symbol="AAPL")
    assert [r["symbol"] for r in out] == ["AAPL", "MSFT"]
    assert out[0]["pe_ttm"] == 30.0
    assert out[0]["pe_fwd"] is None


def test_peer_multiples_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When no peer symbols resolve, WARN (0 rows) and return []."""
    monkeypatch.setattr(tier_calls, "_fetch_peer_symbols", lambda symbol: [])
    call = _TIER_CALLS[("equity/peer-multiples", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="AAPL")
    assert out == []
    assert any("0 rows" in r.getMessage() for r in caplog.records)


def test_register_all_wires_peer_multiples() -> None:
    """The production registration wires the fmp_cached peer-multiples tier."""
    assert ("equity/peer-multiples", "fmp_cached") in _TIER_CALLS


def test_peer_multiples_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint serves live-shaped rows.

    The stub's second row is MSFT with pe_ttm 34.9; the fixture yields a
    single self row with pe_fwd None and a distinct pe_ttm, proving the tier
    served (not the demo stub).
    """
    monkeypatch.setattr(tier_calls, "_fetch_peer_symbols", lambda symbol: ["AAPL"])
    monkeypatch.setattr(
        tier_calls,
        "_fetch_valuation",
        lambda sym: ({"price_to_earnings": 11.1, "price_to_sales": 2.2}, {}),
    )
    resp = _client.get("/pi/equity/peer-multiples?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "empty response"
    assert rows[0]["pe_fwd"] is None, "served the stub!"
    assert rows[0]["pe_ttm"] == 11.1, "served the stub!"


def test_peer_multiples_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> list[str]:
        seen["symbol"] = symbol
        return [symbol]

    monkeypatch.setattr(tier_calls, "_fetch_peer_symbols", _capture)
    monkeypatch.setattr(tier_calls, "_fetch_valuation", lambda sym: ({}, {}))
    resp = _client.get("/pi/equity/peer-multiples?symbol=+aapl+")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen['symbol']!r}"


def test_peer_multiples_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(tier_calls, "_fetch_peer_symbols", lambda symbol: [symbol])
    monkeypatch.setattr(tier_calls, "_fetch_valuation", lambda sym: ({}, {}))
    resp = _client.get("/pi/equity/peer-multiples?symbol=<script>")
    assert resp.status_code == 400


@pytest.mark.integration
def test_peer_multiples_fmp_cached_live() -> None:
    """Live: fmp_cached resolves AAPL peers + real trailing multiples."""
    symbols = tier_calls._fetch_peer_symbols("AAPL")
    assert symbols and symbols[0] == "AAPL", "peers not resolved — wiring broken"
    ratios, metrics = tier_calls._fetch_valuation("AAPL")
    row = tier_calls._shape_peer_row("AAPL", ratios, metrics)
    assert set(row) == {"symbol", "pe_ttm", "pe_fwd", "ev_ebitda", "ps_ttm"}
    assert row["pe_fwd"] is None
    # At least one trailing multiple should be live.
    assert (
        row["pe_ttm"] is not None
        or row["ps_ttm"] is not None
        or row["ev_ebitda"] is not None
    ), "no live valuation multiple"


# ---------------------------------------------------------------------------
# price-target-history (#1926 — full-wiring of #1669)
# ---------------------------------------------------------------------------


def _target_rows() -> list[dict]:
    """Unsorted analyst price-target rows (as ``model_dump`` would yield)."""
    return [
        {
            "published_date": "2026-02-01",
            "price_target": 190.0,
            "price_when_posted": 172.10,
        },
        {
            "published_date": "2026-05-01",
            "price_target": 200.0,
            "price_when_posted": 173.45,
        },
        {
            "published_date": "2025-11-01",
            "price_target": 175.0,
            "price_when_posted": 152.20,
        },
    ]


def test_shape_target_history_maps_and_sorts_ascending() -> None:
    """Rows map to {date, close, target} and emit chronological ascending."""
    out = tier_calls._shape_target_history(_target_rows())
    assert [r["date"] for r in out] == ["2025-11-01", "2026-02-01", "2026-05-01"]
    assert out[-1]["target"] == 200.0
    assert out[-1]["close"] == 173.45
    assert set(out[0]) == {"date", "close", "target"}


def test_shape_target_history_skips_null_date_or_target() -> None:
    """Rows without a usable date or target are dropped."""
    rows = [
        {"published_date": None, "price_target": 100.0, "price_when_posted": 90.0},
        {
            "published_date": "2026-01-01",
            "price_target": None,
            "price_when_posted": 90.0,
        },
        {
            "published_date": "2026-02-01",
            "price_target": 120.0,
            "price_when_posted": None,
        },
    ]
    out = tier_calls._shape_target_history(rows)
    assert len(out) == 1
    assert out[0]["date"] == "2026-02-01"
    assert out[0]["target"] == 120.0
    assert out[0]["close"] is None


def test_shape_target_history_coerces_numeric_strings() -> None:
    """Numeric-string target/close are coerced to float."""
    rows = [
        {
            "published_date": "2026-03-01",
            "price_target": "195.5",
            "price_when_posted": "170.25",
        }
    ]
    out = tier_calls._shape_target_history(rows)
    assert out[0]["target"] == 195.5
    assert out[0]["close"] == 170.25


def test_shape_target_history_caps_most_recent() -> None:
    """Only the most-recent _TARGET_CAP points are kept, in ascending order."""
    rows = [
        {"published_date": f"2{i:03d}-01-01", "price_target": float(i)}
        for i in range(70)
    ]
    out = tier_calls._shape_target_history(rows)
    assert len(out) == tier_calls._TARGET_CAP
    # Most-recent 60 of 70 (i=10..69), returned ascending -> first is i=10.
    assert out[0]["date"] == "2010-01-01"
    assert out[0]["target"] == 10.0
    assert out[-1]["date"] == "2069-01-01"


def test_price_target_history_tier_call_composes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tier call fetches rows then shapes them to the chart series."""
    monkeypatch.setattr(
        tier_calls, "_fetch_price_target_rows", lambda symbol: _target_rows()
    )
    call = _TIER_CALLS[("equity/price-target-history", "fmp_cached")]
    out = call(symbol="AAPL")
    assert [r["date"] for r in out] == ["2025-11-01", "2026-02-01", "2026-05-01"]
    assert out[-1]["target"] == 200.0


def test_price_target_history_tier_call_loud_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When no usable rows resolve, WARN (0 rows) and return []."""
    monkeypatch.setattr(tier_calls, "_fetch_price_target_rows", lambda symbol: [])
    call = _TIER_CALLS[("equity/price-target-history", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="AAPL")
    assert out == []
    assert any("0 rows" in r.getMessage() for r in caplog.records)


def test_register_all_wires_price_target_history() -> None:
    """The production registration wires the fmp_cached price-target tier."""
    assert ("equity/price-target-history", "fmp_cached") in _TIER_CALLS


def test_price_target_history_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint serves live-shaped rows.

    The stub's rows start at date 2025-11-01/target 175.0; the fixture yields
    a single distinct row (2099-01-01/target 999.0), proving the tier served.
    """
    monkeypatch.setattr(
        tier_calls,
        "_fetch_price_target_rows",
        lambda symbol: [
            {
                "published_date": "2099-01-01",
                "price_target": 999.0,
                "price_when_posted": 111.0,
            }
        ],
    )
    resp = _client.get("/pi/equity/price-target-history?symbol=AAPL")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "empty response"
    assert rows[0]["date"] == "2099-01-01", "served the stub!"
    assert rows[0]["target"] == 999.0, "served the stub!"


def test_price_target_history_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture(symbol: str) -> list[dict]:
        seen["symbol"] = symbol
        return [{"published_date": "2026-01-01", "price_target": 1.0}]

    monkeypatch.setattr(tier_calls, "_fetch_price_target_rows", _capture)
    resp = _client.get("/pi/equity/price-target-history?symbol=+aapl+")
    assert resp.status_code == 200
    assert seen["symbol"] == "AAPL", f"raw symbol leaked: {seen['symbol']!r}"


def test_price_target_history_endpoint_rejects_bad_symbol_with_tier_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol validation runs pre-dispatch (not bypassed by the live tier)."""
    monkeypatch.setattr(tier_calls, "_fetch_price_target_rows", lambda symbol: [])
    resp = _client.get("/pi/equity/price-target-history?symbol=<script>")
    assert resp.status_code == 400


@pytest.mark.integration
def test_price_target_history_fmp_cached_live() -> None:
    """Live: fmp_cached resolves AAPL analyst price targets as a time series."""
    rows = tier_calls._fetch_price_target_rows("AAPL")
    assert rows, "no analyst targets returned — wiring broken"
    out = tier_calls._shape_target_history(rows)
    assert out, "shaped series empty on live data"
    assert set(out[0]) == {"date", "close", "target"}
    # Chronological ascending: dates non-decreasing.
    dates = [r["date"] for r in out]
    assert dates == sorted(dates), "series not chronological"
    assert any(r["target"] is not None for r in out), "no live target value"


# ---------------------------------------------------------------------------
# equity/header + equity/key-stats (#1958 — full-wiring of profile stubs #1685)
# ---------------------------------------------------------------------------


def _header_profile() -> dict:
    """Realistic fmp_cached profile row (subset the shaper reads)."""
    return {
        "symbol": "MSFT",
        "name": "Microsoft Corporation",
        "stock_exchange": "NASDAQ",
        "sector": "Technology",
        "industry_group": None,
        "industry_category": "Software - Infrastructure",
        "market_cap": 3_715_000_000_000.0,
        "last_price": 499.99,
        "year_high": 553.72,
        "year_low": 349.2,
        "beta": 1.13,
    }


def _header_quote() -> dict:
    """Realistic fmp_cached quote row. ``change_percent`` is deliberately a
    bogus 999.0 to prove the shaper computes the percent from change/prev_close
    rather than trusting the provider's field."""
    return {
        "exchange": "NASDAQ",
        "last_price": 499.99,
        "change": 2.28,
        "change_percent": 999.0,
        "prev_close": 497.71,
        "volume": 24_137_816,
        "market_cap": 3_715_000_000_000.0,
        "year_high": 553.72,
        "year_low": 349.2,
    }


def test_shape_header_composes_live_card() -> None:
    """Header markdown carries name/exchange/sector/price/cap — no stub markers."""
    out = tier_calls._shape_header("MSFT", _header_profile(), _header_quote())
    assert "Microsoft Corporation" in out
    assert "NASDAQ" in out
    assert "Technology" in out
    # industry_group is None -> falls back to industry_category.
    assert "Software - Infrastructure" in out
    assert "$499.99" in out
    assert "$3.71T" in out  # market cap humanized
    assert "$349.20 – $553.72" in out
    assert "(stub)" not in out


def test_shape_header_change_percent_from_prev_close_not_provider_field() -> None:
    """Day-change % is computed from change/prev_close (provider-agnostic).

    2.28 / 497.71 * 100 == 0.46%. The provider ``change_percent`` field is a
    bogus 999.0; if the shaper trusted it the output would read +999. This is
    the reverse-verified guard against the 100x fraction-vs-percent bug.
    """
    out = tier_calls._shape_header("MSFT", _header_profile(), _header_quote())
    assert "+2.28 (+0.46%)" in out
    assert "999" not in out


def test_shape_header_missing_price_and_change_dash() -> None:
    """Empty quote -> price/change/range degrade to em-dash, never crash."""
    out = tier_calls._shape_header("MSFT", {}, {})
    assert "**Price:** —" in out
    assert "**Day Change:** —" in out
    assert "**Market Cap:** —" in out


def test_header_tier_call_composes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tier call fetches profile+quote then shapes them to markdown."""
    monkeypatch.setattr(tier_calls, "_fetch_profile", lambda s: _header_profile())
    monkeypatch.setattr(tier_calls, "_fetch_quote", lambda s: _header_quote())
    call = _TIER_CALLS[("equity/header", "fmp_cached")]
    out = call(symbol="MSFT")
    assert "Microsoft Corporation" in out
    assert "(stub)" not in out


def test_header_tier_call_raises_on_all_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Both sources empty -> WARN + raise (NOT return "").

    A non-empty string is not treated as empty by the chain's ``_is_empty``,
    so returning ``""`` would be mis-read as a successful serve (blank card).
    The tier must raise so the chain transitions to the stub. Reverse-verified:
    changing the raise to ``return ""`` makes this test fail.
    """
    monkeypatch.setattr(tier_calls, "_fetch_profile", lambda s: {})
    monkeypatch.setattr(tier_calls, "_fetch_quote", lambda s: {})
    call = _TIER_CALLS[("equity/header", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        with pytest.raises(ValueError):
            call(symbol="MSFT")
    assert any("empty profile+quote" in r.getMessage() for r in caplog.records)


def test_register_all_wires_header() -> None:
    """The production registration wires the fmp_cached header tier."""
    assert ("equity/header", "fmp_cached") in _TIER_CALLS


def test_header_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint serves the live card, not stub.

    The stub body contains ``(stub)`` markers; the live card never does.
    """
    monkeypatch.setattr(tier_calls, "_fetch_profile", lambda s: _header_profile())
    monkeypatch.setattr(tier_calls, "_fetch_quote", lambda s: _header_quote())
    resp = _client.get("/pi/equity/header?symbol=MSFT")
    assert resp.status_code == 200
    body = resp.json()
    assert "(stub)" not in body, "served the stub!"
    assert "Microsoft Corporation" in body


def test_header_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture_profile(symbol: str) -> dict:
        seen["symbol"] = symbol
        return _header_profile()

    monkeypatch.setattr(tier_calls, "_fetch_profile", _capture_profile)
    monkeypatch.setattr(tier_calls, "_fetch_quote", lambda s: _header_quote())
    resp = _client.get("/pi/equity/header?symbol=+msft+")
    assert resp.status_code == 200
    assert seen["symbol"] == "MSFT", f"raw symbol leaked: {seen['symbol']!r}"


def _ks_ratios() -> dict:
    """Realistic fmp_cached ratios row (dividend_yield is a FRACTION)."""
    return {
        "price_to_earnings": 27.77,
        "price_to_sales": 11.18,
        "net_income_per_share": 18.0,
        "dividend_yield": 0.00712,
    }


def _ks_metrics() -> dict:
    """Realistic fmp_cached key-metrics row."""
    return {"ev_to_ebitda": 18.41}


def test_shape_key_stats_only_sourced_fields() -> None:
    """Only fields with a live source are emitted; unsourced ones dropped."""
    rows = tier_calls._shape_key_stats(
        "MSFT", _header_profile(), _header_quote(), _ks_metrics(), _ks_ratios()
    )
    metrics = {r["metric"] for r in rows}
    assert {"Market Cap", "P/E (TTM)", "EV/EBITDA", "Beta", "Symbol"} <= metrics
    # Fabricated stub-only fields must NOT appear (no fmp_cached source).
    assert "Forward P/E" not in metrics
    assert "Short Interest" not in metrics
    assert "Insider Ownership" not in metrics


def test_shape_key_stats_dividend_yield_is_fraction_times_100() -> None:
    """dividend_yield 0.00712 (fraction) renders as 0.71% (reverse-verified).

    Dropping the ``*100`` would render 0.01% — this test discriminates.
    """
    rows = tier_calls._shape_key_stats(
        "MSFT", _header_profile(), _header_quote(), _ks_metrics(), _ks_ratios()
    )
    dy = next(r["value"] for r in rows if r["metric"] == "Dividend Yield")
    assert dy == "0.71%"


def test_shape_key_stats_symbol_row_not_counted_as_data() -> None:
    """An all-empty fetch yields ONLY the Symbol row (used by loud-empty guard)."""
    rows = tier_calls._shape_key_stats("MSFT", {}, {}, {}, {})
    assert rows == [{"metric": "Symbol", "value": "MSFT"}]


def test_key_stats_tier_call_composes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tier call folds profile+quote+metrics+ratios into the grid."""
    monkeypatch.setattr(tier_calls, "_fetch_profile", lambda s: _header_profile())
    monkeypatch.setattr(tier_calls, "_fetch_quote", lambda s: _header_quote())
    monkeypatch.setattr(tier_calls, "_fetch_metrics", lambda s: _ks_metrics())
    monkeypatch.setattr(tier_calls, "_fetch_ratios", lambda s: _ks_ratios())
    call = _TIER_CALLS[("equity/key-stats", "fmp_cached")]
    rows = call(symbol="MSFT")
    metrics = {r["metric"] for r in rows}
    assert "EV/EBITDA" in metrics
    assert "Dividend Yield" in metrics


def test_key_stats_tier_call_loud_empty_returns_list(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """No live data (only the Symbol row) -> WARN + return [] (chain -> stub)."""
    monkeypatch.setattr(tier_calls, "_fetch_profile", lambda s: {})
    monkeypatch.setattr(tier_calls, "_fetch_quote", lambda s: {})
    monkeypatch.setattr(tier_calls, "_fetch_metrics", lambda s: {})
    monkeypatch.setattr(tier_calls, "_fetch_ratios", lambda s: {})
    call = _TIER_CALLS[("equity/key-stats", "fmp_cached")]
    with caplog.at_level(logging.WARNING, logger=tier_calls.logger.name):
        out = call(symbol="MSFT")
    assert out == []
    assert any("no live metrics" in r.getMessage() for r in caplog.records)


def test_key_stats_enrichment_failure_degrades_not_blanks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A metrics/ratios fetch raising must NOT blank the grid — core still serves."""

    def _boom(symbol: str) -> dict:
        raise RuntimeError("simulated 402")

    monkeypatch.setattr(tier_calls, "_fetch_profile", lambda s: _header_profile())
    monkeypatch.setattr(tier_calls, "_fetch_quote", lambda s: _header_quote())
    # Use the real _safe_first_row via _fetch_metrics/_fetch_ratios by
    # making the underlying obb call raise.
    monkeypatch.setattr(
        tier_calls,
        "_obb",
        lambda: (_ for _ in ()).throw(RuntimeError("simulated 402")),
    )
    call = _TIER_CALLS[("equity/key-stats", "fmp_cached")]
    rows = call(symbol="MSFT")
    metrics = {r["metric"] for r in rows}
    # Core profile/quote fields survive; enrichment fields simply absent.
    assert "Market Cap" in metrics
    assert "Beta" in metrics


def test_register_all_wires_key_stats() -> None:
    """The production registration wires the fmp_cached key-stats tier."""
    assert ("equity/key-stats", "fmp_cached") in _TIER_CALLS


def test_key_stats_endpoint_serves_from_tier_not_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the tier registered, the endpoint serves the live grid, not stub.

    The stub grid contains the fabricated ``Forward P/E`` row and ``$3.47T``
    market cap; the live grid has neither.
    """
    monkeypatch.setattr(tier_calls, "_fetch_profile", lambda s: _header_profile())
    monkeypatch.setattr(tier_calls, "_fetch_quote", lambda s: _header_quote())
    monkeypatch.setattr(tier_calls, "_fetch_metrics", lambda s: _ks_metrics())
    monkeypatch.setattr(tier_calls, "_fetch_ratios", lambda s: _ks_ratios())
    resp = _client.get("/pi/equity/key-stats?symbol=MSFT")
    assert resp.status_code == 200
    rows = resp.json()
    metrics = {r["metric"] for r in rows}
    assert "Forward P/E" not in metrics, "served the stub!"
    mc = next(r["value"] for r in rows if r["metric"] == "Market Cap")
    assert mc != "$3.47T", "served the stub!"


def test_key_stats_endpoint_forwards_normalized_symbol_to_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tier must receive the normalized ticker (PR #1899 pattern)."""
    seen: dict[str, str] = {}

    def _capture_profile(symbol: str) -> dict:
        seen["symbol"] = symbol
        return _header_profile()

    monkeypatch.setattr(tier_calls, "_fetch_profile", _capture_profile)
    monkeypatch.setattr(tier_calls, "_fetch_quote", lambda s: _header_quote())
    monkeypatch.setattr(tier_calls, "_fetch_metrics", lambda s: _ks_metrics())
    monkeypatch.setattr(tier_calls, "_fetch_ratios", lambda s: _ks_ratios())
    resp = _client.get("/pi/equity/key-stats?symbol=+msft+")
    assert resp.status_code == 200
    assert seen["symbol"] == "MSFT", f"raw symbol leaked: {seen['symbol']!r}"


@pytest.mark.integration
def test_header_fmp_cached_live() -> None:
    """Live: fmp_cached profile+quote compose a real header card for MSFT."""
    out = tier_calls._header_fmp_cached(symbol="MSFT")
    assert "(stub)" not in out
    assert "MSFT" in out
    assert "$" in out  # a real price/cap rendered


@pytest.mark.integration
def test_key_stats_fmp_cached_live() -> None:
    """Live: fmp_cached composes a real key-stats grid for MSFT."""
    rows = tier_calls._key_stats_fmp_cached(symbol="MSFT")
    assert rows, "empty live grid — wiring broken"
    metrics = {r["metric"] for r in rows}
    assert "Market Cap" in metrics
    assert "Forward P/E" not in metrics  # no fmp_cached source
    assert {"metric", "value"} == set(rows[0])
