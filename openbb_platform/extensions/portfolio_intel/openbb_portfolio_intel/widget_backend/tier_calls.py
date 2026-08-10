"""Live ``fmp_cached`` tier-call registrations for widget-backend families.

Imported for side effects by :mod:`.main`. Each :func:`register_tier_call`
wires one ``(family, "fmp_cached")`` combination to a real ``obb`` provider
call so the provider-chain retrofit (:mod:`..providers.retrofit`) starts
serving **live** data instead of falling to the endpoint stub. On any
failure or empty result the chain transitions to the next tier and,
ultimately, the endpoint's own stub — never a silent empty.

``openbb`` is imported lazily (call time, not module load) because importing
it builds/loads every installed extension (minutes on a cold start) and
requires the platform installed. Deferring keeps backend startup fast and
offline-safe, and lets tests monkeypatch :func:`_fetch_price_history_rows`.

Wiring status
-------------
- ``equity/price-history`` -> ``fmp_cached`` (full-wiring of stub #1702, #1898)
- ``equity/price-performance`` -> ``fmp_cached`` (full-wiring of stub #1645, #1900)
- ``equity/management-team`` -> ``fmp_cached`` (full-wiring of stub #1648, #1902)
- ``equity/revenue-geography`` -> ``fmp_cached`` (full-wiring of stub #1649, #1904)
- ``equity/revenue-business-line`` -> ``fmp_cached`` (full-wiring of stub #1650, #1906)
- ``equity/dividend-payment`` -> ``fmp_cached`` (full-wiring of stub #1665, #1908)
- ``equity/insider-trading`` -> ``fmp_cached`` (full-wiring of stub #1661, #1910)
- ``equity/earnings-history`` -> ``fmp_cached`` (full-wiring of stub #1663, #1912)
- ``equity/company-filings`` -> ``fmp_cached`` (full-wiring of stub #1666, #1914)
- ``equity/stock-splits`` -> ``fmp_cached`` (full-wiring of stub #1664, #1916)
- ``charting`` -> ``fmp_cached`` (full-wiring of stub #1655, #1918)
- ``equity/statements`` -> ``fmp_cached`` (full-wiring of stub #1653, #1920)
- ``equity/peer-multiples`` -> ``fmp_cached`` (full-wiring of stub #1657, #1923)
- ``equity/price-target-history`` -> ``fmp_cached`` (full-wiring of stub #1669, #1926)
- ``equity/header`` -> ``fmp_cached`` (full-wiring of stub #1685, #1958)
- ``equity/key-stats`` -> ``fmp_cached`` (full-wiring of stub #1685, #1958)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# price-history (#1898 — full-wiring of #1702)
# ---------------------------------------------------------------------------


def _obb() -> Any:
    """Return the lazily-imported ``obb`` singleton.

    Isolated in one function so tests can monkeypatch the fetchers that call
    it without triggering the heavy ``from openbb import obb`` import.
    """
    from openbb import obb  # pylint: disable=import-outside-toplevel

    return obb


def _iso_date(value: Any) -> str | None:
    """Coerce a date-like value to an ISO ``YYYY-MM-DD`` string (or ``None``).

    ``model_dump`` yields ``datetime.date`` for date fields; some provider
    extras arrive as strings or ``None``. Returns ``None`` unchanged, calls
    ``.isoformat()`` when available, else falls back to ``str``.
    """
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _fetch_price_history_rows(symbol: str) -> list[dict]:
    """Fetch raw daily OHLCV rows for ``symbol`` from ``fmp_cached``.

    Returns a list of plain dicts (one per bar) as produced by the provider
    model's ``model_dump``. Network/quota errors propagate to the caller,
    which the chain classifies as a tier transition.
    """
    res = _obb().equity.price.historical(symbol=symbol, provider="fmp_cached")
    rows = getattr(res, "results", res)
    out: list[dict] = []
    for r in rows:
        if hasattr(r, "model_dump"):
            out.append(r.model_dump())
        elif isinstance(r, dict):
            out.append(r)
        else:  # pydantic v1 / namedtuple-ish fallback
            out.append(dict(r))
    return out


def _iso(value: Any) -> str:
    """Normalize a date-ish value to an ISO ``YYYY-MM-DD`` string."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _shape_price_history(rows: list[dict], chart_type: str) -> list[dict]:
    """Shape raw OHLCV rows to the widget contract.

    * ``line``  -> ``{date, close}``
    * ``candle`` -> ``{date, open, high, low, close, volume}``

    Extra provider columns (``vwap``, ``change`` ...) are dropped so the
    output is byte-identical in shape to the stub the widget already
    renders. Pure (no I/O) so it is trivially unit-tested.
    """
    out: list[dict] = []
    for r in rows:
        date_str = _iso(r.get("date"))
        if chart_type == "line":
            out.append({"date": date_str, "close": r.get("close")})
        else:  # candle
            out.append(
                {
                    "date": date_str,
                    "open": r.get("open"),
                    "high": r.get("high"),
                    "low": r.get("low"),
                    "close": r.get("close"),
                    "volume": r.get("volume"),
                }
            )
    return out


def _price_history_fmp_cached(
    *, symbol: str, chart_type: str = "line", range_: str = "6M"
) -> list[dict]:
    """Tier call: fetch live price history from fmp_cached, shape and slice it.

    ``range_`` slices the shaped series to the requested display window
    (anchored on the most recent bar) so the widget's Range dropdown is
    functional in live mode (#1950). The provider fetch itself is unchanged
    (``symbol`` only); slicing happens locally on the returned rows.

    An empty result is loud (WARNING) and returned as ``[]`` so the chain
    transitions to the next tier / the endpoint stub instead of silently
    serving nothing.
    """
    rows = _fetch_price_history_rows(symbol)
    shaped = _shape_price_history(rows, chart_type)
    shaped = _slice_rows_to_range(shaped, range_)
    if not shaped:
        logger.warning(
            "price-history fmp_cached returned 0 rows for %s "
            "(chart_type=%s range=%s) — chain will transition to the "
            "next tier/stub",
            symbol,
            chart_type,
            range_,
        )
    return shaped


# ---------------------------------------------------------------------------
# price-performance (#1900 — full-wiring of #1645)
# ---------------------------------------------------------------------------
#
# ``obb.equity.price.performance(provider="fmp_cached")`` returns ONE row of
# trailing returns as *fractions* (e.g. ``one_day=-0.00134`` == -0.134%). The
# widget's shipped stub contract is ``[{period, return_pct}]`` with the
# horizon labels below and ``return_pct`` in *percent*, so the shaper maps
# fields -> labels and multiplies by 100.

#: Widget horizon label -> provider field. Order defines row order.
_PRICE_PERF_PERIODS: tuple[tuple[str, str], ...] = (
    ("1D", "one_day"),
    ("1W", "one_week"),
    ("1M", "one_month"),
    ("3M", "three_month"),
    ("6M", "six_month"),
    ("YTD", "ytd"),
    ("1Y", "one_year"),
    ("3Y", "three_year"),
    ("5Y", "five_year"),
)


def _fetch_price_performance_row(symbol: str) -> dict:
    """Fetch the single trailing-returns row for ``symbol`` from ``fmp_cached``.

    Returns a plain dict (the provider model's ``model_dump``). An absent
    result yields ``{}`` so the shaper produces an empty list and the tier
    call transitions the chain. Network/quota errors propagate to the caller.
    """
    res = _obb().equity.price.performance(symbol=symbol, provider="fmp_cached")
    rows = getattr(res, "results", res)
    if not rows:
        return {}
    first = rows[0]
    if hasattr(first, "model_dump"):
        return first.model_dump()
    if isinstance(first, dict):
        return first
    return dict(first)


def _shape_price_performance(row: dict) -> list[dict]:
    """Shape one trailing-returns row to ``[{period, return_pct}]``.

    Fractions are converted to percent (``*100``, rounded to 2 dp). A period
    whose source value is ``None`` (provider has no data for that horizon) is
    **omitted** rather than emitted with a fabricated value — partial real
    data beats fake completeness. Pure (no I/O).
    """
    out: list[dict] = []
    for label, field in _PRICE_PERF_PERIODS:
        val = row.get(field)
        if val is None:
            continue
        out.append({"period": label, "return_pct": round(float(val) * 100.0, 2)})
    return out


def _price_performance_fmp_cached(*, symbol: str) -> list[dict]:
    """Tier call: fetch live trailing returns from fmp_cached and shape them.

    Empty output (no non-null horizons) is loud (WARNING) and returned as
    ``[]`` so the chain transitions to the next tier / the endpoint stub
    rather than silently serving nothing.
    """
    row = _fetch_price_performance_row(symbol)
    shaped = _shape_price_performance(row)
    if not shaped:
        logger.warning(
            "price-performance fmp_cached returned 0 rows for %s "
            "— chain will transition to the next tier/stub",
            symbol,
        )
    return shaped


# ---------------------------------------------------------------------------
# management-team (#1902 — full-wiring of #1648)
# ---------------------------------------------------------------------------
#
# ``obb.equity.fundamental.management(provider="fmp_cached")`` returns key
# executives with fields ``name, title, pay, year_born, gender, currency_pay``.
# The widget's shipped stub contract is ``[{name, title, pay_usd, tenure_years}]``.
# fmp_cached has no tenure field, so ``tenure_years`` is emitted as ``None``
# (the stub's tenure value was fabricated) — the key is kept so the table's
# columns stay stable across the live/stub paths.


def _fetch_management_rows(symbol: str) -> list[dict]:
    """Fetch key-executive rows for ``symbol`` from ``fmp_cached``.

    Returns a list of plain dicts (``model_dump`` per row). Network/quota
    errors propagate to the caller, which the chain classifies as a tier
    transition.
    """
    res = _obb().equity.fundamental.management(symbol=symbol, provider="fmp_cached")
    rows = getattr(res, "results", res)
    out: list[dict] = []
    for r in rows:
        if hasattr(r, "model_dump"):
            out.append(r.model_dump())
        elif isinstance(r, dict):
            out.append(r)
        else:
            out.append(dict(r))
    return out


def _shape_management(rows: list[dict]) -> list[dict]:
    """Shape key-executive rows to ``[{name, title, pay_usd, tenure_years}]``.

    ``pay`` -> ``pay_usd``; ``tenure_years`` is always ``None`` (no source
    field). A row with no ``name`` is skipped (can't render a nameless
    executive). Pure (no I/O).
    """
    out: list[dict] = []
    for r in rows:
        name = r.get("name")
        if not name:
            continue
        out.append(
            {
                "name": name,
                "title": r.get("title"),
                "pay_usd": r.get("pay"),
                "tenure_years": None,
            }
        )
    return out


def _management_team_fmp_cached(*, symbol: str) -> list[dict]:
    """Tier call: fetch live key executives from fmp_cached and shape them.

    Empty output is loud (WARNING) and returned as ``[]`` so the chain
    transitions to the next tier / the endpoint stub.
    """
    rows = _fetch_management_rows(symbol)
    shaped = _shape_management(rows)
    if not shaped:
        logger.warning(
            "management-team fmp_cached returned 0 rows for %s "
            "— chain will transition to the next tier/stub",
            symbol,
        )
    return shaped


# ---------------------------------------------------------------------------
# revenue-geography (#1904 — full-wiring of #1649)
# ---------------------------------------------------------------------------
#
# ``obb.equity.fundamental.revenue_per_geography(provider="fmp_cached")``
# returns ``RevenueGeographicData`` — one row per ``(period_ending, region)``
# across many fiscal periods. The widget is a pie chart with the contract
# ``[{region, revenue}]``, so we select the single latest ``period_ending``
# and aggregate revenue by region within it (guards against duplicate pie
# labels / split segments in one period).


def _fetch_revenue_geography_rows(symbol: str) -> list[dict]:
    """Fetch revenue-by-geography rows for ``symbol`` from ``fmp_cached``.

    Returns a list of plain dicts (``model_dump`` per row). Errors propagate
    to the caller, which the chain classifies as a tier transition.
    """
    res = _obb().equity.fundamental.revenue_per_geography(
        symbol=symbol, provider="fmp_cached"
    )
    rows = getattr(res, "results", res)
    out: list[dict] = []
    for r in rows:
        if hasattr(r, "model_dump"):
            out.append(r.model_dump())
        elif isinstance(r, dict):
            out.append(r)
        else:
            out.append(dict(r))
    return out


def _shape_revenue_geography(rows: list[dict]) -> list[dict]:
    """Shape geographic-revenue rows to the pie contract ``[{region, revenue}]``.

    Selects the single latest ``period_ending`` present, then aggregates
    ``revenue`` by ``region`` within that period. Rows with a null region or
    null revenue are ignored. Region insertion order (first seen in the
    latest period) is preserved. Pure (no I/O).
    """
    dated = [r for r in rows if r.get("period_ending") is not None]
    if not dated:
        return []
    latest = max(r["period_ending"] for r in dated)
    agg: dict[str, float] = {}
    for r in dated:
        if r["period_ending"] != latest:
            continue
        region = r.get("region")
        revenue = r.get("revenue")
        if not region or revenue is None:
            continue
        agg[region] = agg.get(region, 0) + revenue
    return [{"region": region, "revenue": revenue} for region, revenue in agg.items()]


def _revenue_geography_fmp_cached(*, symbol: str) -> list[dict]:
    """Tier call: fetch live geographic revenue from fmp_cached and shape it.

    Empty output is loud (WARNING) and returned as ``[]`` so the chain
    transitions to the next tier / the endpoint stub.
    """
    rows = _fetch_revenue_geography_rows(symbol)
    shaped = _shape_revenue_geography(rows)
    if not shaped:
        logger.warning(
            "revenue-geography fmp_cached returned 0 rows for %s "
            "— chain will transition to the next tier/stub",
            symbol,
        )
    return shaped


# ---------------------------------------------------------------------------
# revenue-business-line (#1906 — full-wiring of #1650)
# ---------------------------------------------------------------------------
#
# ``obb.equity.fundamental.revenue_per_segment(provider="fmp_cached")`` returns
# ``RevenueBusinessLineData`` — one row per ``(period_ending, business_line)``
# across many fiscal periods. The widget is a pie chart with the contract
# ``[{segment, revenue}]`` (note the ``business_line`` -> ``segment`` key
# rename), so we select the latest ``period_ending`` and aggregate revenue by
# business line within it.


def _fetch_revenue_business_line_rows(symbol: str) -> list[dict]:
    """Fetch revenue-by-segment rows for ``symbol`` from ``fmp_cached``.

    Returns a list of plain dicts (``model_dump`` per row). Errors propagate
    to the caller, which the chain classifies as a tier transition.
    """
    res = _obb().equity.fundamental.revenue_per_segment(
        symbol=symbol, provider="fmp_cached"
    )
    rows = getattr(res, "results", res)
    out: list[dict] = []
    for r in rows:
        if hasattr(r, "model_dump"):
            out.append(r.model_dump())
        elif isinstance(r, dict):
            out.append(r)
        else:
            out.append(dict(r))
    return out


def _shape_revenue_business_line(rows: list[dict]) -> list[dict]:
    """Shape business-line revenue rows to the pie contract ``[{segment, revenue}]``.

    Selects the single latest ``period_ending`` present, aggregates ``revenue``
    by ``business_line`` within that period, and renames ``business_line`` ->
    ``segment`` (the widget's contract key). Rows with a null business line or
    null revenue are ignored. Insertion order (first seen in the latest period)
    is preserved. Pure (no I/O).
    """
    dated = [r for r in rows if r.get("period_ending") is not None]
    if not dated:
        return []
    latest = max(r["period_ending"] for r in dated)
    agg: dict[str, float] = {}
    for r in dated:
        if r["period_ending"] != latest:
            continue
        segment = r.get("business_line")
        revenue = r.get("revenue")
        if not segment or revenue is None:
            continue
        agg[segment] = agg.get(segment, 0) + revenue
    return [
        {"segment": segment, "revenue": revenue} for segment, revenue in agg.items()
    ]


def _revenue_business_line_fmp_cached(*, symbol: str) -> list[dict]:
    """Tier call: fetch live business-line revenue from fmp_cached and shape it.

    Empty output is loud (WARNING) and returned as ``[]`` so the chain
    transitions to the next tier / the endpoint stub.
    """
    rows = _fetch_revenue_business_line_rows(symbol)
    shaped = _shape_revenue_business_line(rows)
    if not shaped:
        logger.warning(
            "revenue-business-line fmp_cached returned 0 rows for %s "
            "— chain will transition to the next tier/stub",
            symbol,
        )
    return shaped


# ---------------------------------------------------------------------------
# dividend-payment (#1908 — full-wiring of #1665)
# ---------------------------------------------------------------------------
#
# ``obb.equity.fundamental.dividends(provider="fmp_cached")`` returns
# ``HistoricalDividendsData`` (standard fields ``symbol, ex_dividend_date,
# amount``; ``payment_date`` is an FMP provider extra). The widget is a table
# with the contract ``[{ex_date, payment_date, amount}]`` showing recent
# dividends newest-first — so we sort by ex-date descending, cap to the latest
# 12, and ISO-stringify the date columns.

_DIVIDENDS_LIMIT = 12


def _fetch_dividend_rows(symbol: str) -> list[dict]:
    """Fetch historical dividend rows for ``symbol`` from ``fmp_cached``.

    Returns a list of plain dicts (``model_dump`` per row). Errors propagate
    to the caller, which the chain classifies as a tier transition.
    """
    res = _obb().equity.fundamental.dividends(symbol=symbol, provider="fmp_cached")
    rows = getattr(res, "results", res)
    out: list[dict] = []
    for r in rows:
        if hasattr(r, "model_dump"):
            out.append(r.model_dump())
        elif isinstance(r, dict):
            out.append(r)
        else:
            out.append(dict(r))
    return out


def _shape_dividends(rows: list[dict]) -> list[dict]:
    """Shape dividend rows to ``[{ex_date, payment_date, amount}]``, newest-first.

    Sorts by ``ex_dividend_date`` descending (rows with no ex-date sink to the
    end), caps to the latest ``_DIVIDENDS_LIMIT``, ISO-stringifies both date
    columns, and maps ``ex_dividend_date`` -> ``ex_date``. Rows with a null
    ``amount`` are skipped. Pure (no I/O).
    """
    kept = [r for r in rows if r.get("amount") is not None]
    kept.sort(key=lambda r: _iso_date(r.get("ex_dividend_date")) or "", reverse=True)
    out: list[dict] = []
    for r in kept[:_DIVIDENDS_LIMIT]:
        out.append(
            {
                "ex_date": _iso_date(r.get("ex_dividend_date")),
                "payment_date": _iso_date(r.get("payment_date")),
                "amount": r.get("amount"),
            }
        )
    return out


def _dividend_payment_fmp_cached(*, symbol: str) -> list[dict]:
    """Tier call: fetch live dividends from fmp_cached and shape them.

    Empty output is loud (WARNING) and returned as ``[]`` so the chain
    transitions to the next tier / the endpoint stub.
    """
    rows = _fetch_dividend_rows(symbol)
    shaped = _shape_dividends(rows)
    if not shaped:
        logger.warning(
            "dividend-payment fmp_cached returned 0 rows for %s "
            "— chain will transition to the next tier/stub",
            symbol,
        )
    return shaped


# ---------------------------------------------------------------------------
# insider-trading (#1910 — full-wiring of #1661)
# ---------------------------------------------------------------------------
#
# ``obb.equity.ownership.insider_trading(provider="fmp_cached")`` returns
# ``InsiderTradingData``. Relevant fields: ``owner_name, transaction_date,
# filing_date, securities_transacted (always POSITIVE), transaction_price,
# transaction_type, acquisition_or_disposition`` (``A``=acquire, ``D``=dispose).
# The widget contract is ``[{name, date, shares, transaction_type,
# price_usd}]``, newest-first. We sign ``shares`` from the A/D flag so a sale
# reads as a negative share count (matching the stub's convention).

_INSIDER_LIMIT = 25


def _fetch_insider_rows(symbol: str) -> list[dict]:
    """Fetch recent insider-trading rows for ``symbol`` from ``fmp_cached``.

    Returns a list of plain dicts (``model_dump`` per row). Errors propagate
    to the caller, which the chain classifies as a tier transition.
    """
    res = _obb().equity.ownership.insider_trading(
        symbol=symbol, provider="fmp_cached", limit=100
    )
    rows = getattr(res, "results", res)
    out: list[dict] = []
    for r in rows:
        if hasattr(r, "model_dump"):
            out.append(r.model_dump())
        elif isinstance(r, dict):
            out.append(r)
        else:
            out.append(dict(r))
    return out


def _shape_insider_trading(rows: list[dict]) -> list[dict]:
    """Shape insider rows to ``[{name, date, shares, transaction_type, price_usd}]``.

    ``shares`` = ``securities_transacted`` signed by
    ``acquisition_or_disposition`` (``D`` -> negative, anything else ->
    positive). ``date`` prefers ``transaction_date``, falling back to
    ``filing_date``, ISO-stringified. Rows with no owner name or no
    ``securities_transacted`` are skipped. Sorted newest-first, capped to
    ``_INSIDER_LIMIT``. Pure (no I/O).
    """
    kept: list[dict] = []
    for r in rows:
        name = r.get("owner_name")
        qty = r.get("securities_transacted")
        if not name or qty is None:
            continue
        shares = -abs(qty) if r.get("acquisition_or_disposition") == "D" else abs(qty)
        date = r.get("transaction_date") or r.get("filing_date")
        kept.append(
            {
                "name": name,
                "date": _iso_date(date),
                "shares": shares,
                "transaction_type": r.get("transaction_type"),
                "price_usd": r.get("transaction_price"),
                "_sort": _iso_date(date) or "",
            }
        )
    kept.sort(key=lambda r: r["_sort"], reverse=True)
    out: list[dict] = []
    for r in kept[:_INSIDER_LIMIT]:
        r.pop("_sort", None)
        out.append(r)
    return out


def _insider_trading_fmp_cached(*, symbol: str) -> list[dict]:
    """Tier call: fetch live insider trades from fmp_cached and shape them.

    Empty output is loud (WARNING) and returned as ``[]`` so the chain
    transitions to the next tier / the endpoint stub.
    """
    rows = _fetch_insider_rows(symbol)
    shaped = _shape_insider_trading(rows)
    if not shaped:
        logger.warning(
            "insider-trading fmp_cached returned 0 rows for %s "
            "— chain will transition to the next tier/stub",
            symbol,
        )
    return shaped


# ---------------------------------------------------------------------------
# earnings-history (#1912 — full-wiring of #1663)
# ---------------------------------------------------------------------------
#
# ``obb.equity.fundamental.historical_eps(provider="fmp_cached")`` returns
# ``HistoricalEps`` (``symbol, date, eps_actual, eps_estimated, ...``). The
# widget contract is ``[{quarter, eps_actual, eps_estimate, surprise_pct}]``,
# newest-first. The standard model carries NO fiscal-period label, so
# ``quarter`` is derived as the calendar quarter of the report ``date``
# (``"Q{n} {year}"``) — a deterministic, non-fabricated label documented as
# "quarter the results were reported in", not a fiscal period.

_EARNINGS_LIMIT = 8


def _fetch_earnings_rows(symbol: str) -> list[dict]:
    """Fetch historical EPS rows for ``symbol`` from ``fmp_cached``.

    Returns a list of plain dicts (``model_dump`` per row). Errors propagate
    to the caller, which the chain classifies as a tier transition.
    """
    res = _obb().equity.fundamental.historical_eps(symbol=symbol, provider="fmp_cached")
    rows = getattr(res, "results", res)
    out: list[dict] = []
    for r in rows:
        if hasattr(r, "model_dump"):
            out.append(r.model_dump())
        elif isinstance(r, dict):
            out.append(r)
        else:
            out.append(dict(r))
    return out


def _calendar_quarter_label(value: Any) -> str | None:
    """Return ``"Q{n} {year}"`` for a date-like value, else ``None``.

    ``n`` is the calendar quarter (1-4) of the value's month. Non-date values
    or ``None`` yield ``None``.
    """
    month = getattr(value, "month", None)
    year = getattr(value, "year", None)
    if month is None or year is None:
        return None
    return f"Q{(month - 1) // 3 + 1} {year}"


def _shape_earnings_history(rows: list[dict]) -> list[dict]:
    """Shape EPS rows to ``[{quarter, eps_actual, eps_estimate, surprise_pct}]``.

    Maps ``eps_estimated`` -> ``eps_estimate``; computes ``surprise_pct`` =
    ``(actual - estimate) / abs(estimate) * 100`` rounded to 2 decimals
    (``None`` when estimate is ``None`` or ``0``). ``quarter`` is the calendar
    quarter of the report ``date``. Rows with null ``eps_actual`` (future /
    unreported) or no derivable quarter are skipped. Sorted newest-first,
    capped to ``_EARNINGS_LIMIT``. Pure (no I/O).
    """
    kept: list[dict] = []
    for r in rows:
        actual = r.get("eps_actual")
        if actual is None:
            continue
        quarter = _calendar_quarter_label(r.get("date"))
        if quarter is None:
            continue
        estimate = r.get("eps_estimated")
        surprise = (
            None
            if estimate in (None, 0)
            else round((actual - estimate) / abs(estimate) * 100, 2)
        )
        kept.append(
            {
                "quarter": quarter,
                "eps_actual": actual,
                "eps_estimate": estimate,
                "surprise_pct": surprise,
                "_sort": _iso_date(r.get("date")) or "",
            }
        )
    kept.sort(key=lambda r: r["_sort"], reverse=True)
    out: list[dict] = []
    for r in kept[:_EARNINGS_LIMIT]:
        r.pop("_sort", None)
        out.append(r)
    return out


def _earnings_history_fmp_cached(*, symbol: str) -> list[dict]:
    """Tier call: fetch live historical EPS from fmp_cached and shape it.

    Empty output is loud (WARNING) and returned as ``[]`` so the chain
    transitions to the next tier / the endpoint stub.
    """
    rows = _fetch_earnings_rows(symbol)
    shaped = _shape_earnings_history(rows)
    if not shaped:
        logger.warning(
            "earnings-history fmp_cached returned 0 rows for %s "
            "— chain will transition to the next tier/stub",
            symbol,
        )
    return shaped


# ---------------------------------------------------------------------------
# company-filings (#1914 — full-wiring of #1666)
# ---------------------------------------------------------------------------


_FILINGS_LIMIT = 30


def _fetch_filings_rows(symbol: str) -> list[dict]:
    """Fetch recent SEC filing rows for ``symbol`` from ``fmp_cached``.

    Returns a list of plain dicts (``model_dump`` per row). Errors propagate
    to the caller, which the chain classifies as a tier transition.
    """
    res = _obb().equity.fundamental.filings(symbol=symbol, provider="fmp_cached")
    rows = getattr(res, "results", res)
    out: list[dict] = []
    for r in rows:
        if hasattr(r, "model_dump"):
            out.append(r.model_dump())
        elif isinstance(r, dict):
            out.append(r)
        else:
            out.append(dict(r))
    return out


def _shape_company_filings(rows: list[dict]) -> list[dict]:
    """Shape filing rows to ``[{filing_date, report_type, report_url, filing_url}]``.

    ``filing_date`` is ISO-stringified. Rows with no ``filing_date`` or no
    ``report_url`` (the report link is the whole point of the widget) are
    skipped. Sorted by filing date newest-first, capped to ``_FILINGS_LIMIT``.
    Pure (no I/O).
    """
    kept: list[dict] = []
    for r in rows:
        filing_date = _iso_date(r.get("filing_date"))
        report_url = r.get("report_url")
        if filing_date is None or not report_url:
            continue
        kept.append(
            {
                "filing_date": filing_date,
                "report_type": r.get("report_type"),
                "report_url": report_url,
                "filing_url": r.get("filing_url"),
            }
        )
    kept.sort(key=lambda r: r["filing_date"], reverse=True)
    return kept[:_FILINGS_LIMIT]


def _company_filings_fmp_cached(*, symbol: str) -> list[dict]:
    """Tier call: fetch live company filings from fmp_cached and shape them.

    Empty output is loud (WARNING) and returned as ``[]`` so the chain
    transitions to the next tier / the endpoint stub.
    """
    rows = _fetch_filings_rows(symbol)
    shaped = _shape_company_filings(rows)
    if not shaped:
        logger.warning(
            "company-filings fmp_cached returned 0 rows for %s "
            "— chain will transition to the next tier/stub",
            symbol,
        )
    return shaped


# ---------------------------------------------------------------------------
# stock-splits (#1916 — full-wiring of #1664)
# ---------------------------------------------------------------------------


_SPLITS_LIMIT = 20


def _fetch_splits_rows(symbol: str) -> list[dict]:
    """Fetch historical split rows for ``symbol`` from ``fmp_cached``.

    Returns a list of plain dicts (``model_dump`` per row). Errors propagate
    to the caller, which the chain classifies as a tier transition.
    """
    res = _obb().equity.fundamental.historical_splits(
        symbol=symbol, provider="fmp_cached"
    )
    rows = getattr(res, "results", res)
    out: list[dict] = []
    for r in rows:
        if hasattr(r, "model_dump"):
            out.append(r.model_dump())
        elif isinstance(r, dict):
            out.append(r)
        else:
            out.append(dict(r))
    return out


def _whole_number(value: Any) -> int | float:
    """Coerce a whole float (e.g. ``4.0``) to ``int``; leave others as-is."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _shape_stock_splits(rows: list[dict]) -> list[dict]:
    """Shape split rows to ``[{date, numerator, denominator, ratio}]``.

    ``date`` is ISO-stringified. ``numerator``/``denominator`` are coerced to
    ``int`` when whole (fmp yields floats like ``4.0``). ``ratio`` is derived
    as ``"{numerator}:{denominator}"`` (fmp's own ``split_ratio`` is null).
    Rows with no date or a null numerator/denominator are skipped. Sorted by
    date newest-first, capped to ``_SPLITS_LIMIT``. Pure (no I/O).
    """
    kept: list[dict] = []
    for r in rows:
        date = _iso_date(r.get("date"))
        numerator = r.get("numerator")
        denominator = r.get("denominator")
        if date is None or numerator is None or denominator is None:
            continue
        num = _whole_number(numerator)
        den = _whole_number(denominator)
        kept.append(
            {
                "date": date,
                "numerator": num,
                "denominator": den,
                "ratio": f"{num}:{den}",
            }
        )
    kept.sort(key=lambda r: r["date"], reverse=True)
    return kept[:_SPLITS_LIMIT]


def _stock_splits_fmp_cached(*, symbol: str) -> list[dict]:
    """Tier call: fetch live historical splits from fmp_cached and shape them.

    Empty output is loud (WARNING) and returned as ``[]`` so the chain
    transitions to the next tier / the endpoint stub.
    """
    rows = _fetch_splits_rows(symbol)
    shaped = _shape_stock_splits(rows)
    if not shaped:
        logger.warning(
            "stock-splits fmp_cached returned 0 rows for %s "
            "— chain will transition to the next tier/stub",
            symbol,
        )
    return shaped


# ---------------------------------------------------------------------------
# charting / technicals (#1918 — full-wiring of #1655)
# ---------------------------------------------------------------------------
#
# Reuses the proven price-history fetch (``equity.price.historical`` via
# ``fmp_cached``) and computes SMA20 / SMA50 / RSI14 locally over the *full*
# close series so the slower-moving averages have enough lookback, then slices
# the display to the requested ``window``. Indicators are ``None`` on bars that
# lack enough preceding history. Output shape matches the shipped stub:
# ``{date, open, high, low, close, sma20, sma50, rsi14}``.

import datetime as _dt  # noqa: E402

#: Trailing calendar-day span for each fixed window (YTD handled separately).
_CHART_WINDOW_DAYS: dict[str, int] = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365}


def _as_date(value: Any) -> _dt.date | None:
    """Coerce a date-ish value to a ``datetime.date`` (or ``None``)."""
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _sma(values: list[float], period: int) -> list[float | None]:
    """Return the simple moving average; ``None`` until ``period`` bars exist."""
    out: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        out[i] = round(sum(window) / period, 2)
    return out


def _rsi(values: list[float], period: int = 14) -> list[float | None]:
    """Relative Strength Index over ``period`` deltas (simple averaging).

    ``None`` until ``period + 1`` bars exist. A monotonic-up series yields
    ``100.0``; a monotonic-down series yields ``0.0``.
    """
    out: list[float | None] = [None] * len(values)
    for i in range(period, len(values)):
        gains = 0.0
        losses = 0.0
        for j in range(i - period + 1, i + 1):
            delta = values[j] - values[j - 1]
            if delta >= 0:
                gains += delta
            else:
                losses -= delta
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            out[i] = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            out[i] = round(100 - 100 / (1 + rs), 1)
    return out


def _window_cutoff(anchor: _dt.date, window: str) -> _dt.date:
    """Earliest display date for ``window`` anchored on the last bar's date."""
    if window == "YTD":
        return _dt.date(anchor.year, 1, 1)
    days = _CHART_WINDOW_DAYS.get(window, 91)
    return anchor - _dt.timedelta(days=days)


#: Trailing calendar-day span for each price-history range (YTD separate).
_RANGE_CAL_DAYS: dict[str, int] = {
    "1M": 30,
    "3M": 91,
    "6M": 182,
    "1Y": 365,
    "5Y": 1825,
}


def _slice_rows_to_range(rows: list[dict], range_: str) -> list[dict]:
    """Slice already-shaped price rows to ``range_``, anchored on the last bar.

    ``rows`` are ``{date, ...}`` dicts sorted ascending by date (as produced by
    the provider). Rows older than the range cutoff are dropped. Unknown /
    unparseable dates are kept (never silently discarded), and an all-unparseable
    input returns ``rows`` unchanged so a date-format drift degrades to "show
    everything" rather than "show nothing" (loud-empty avoidance, #1950).
    """
    if not rows:
        return rows
    dated = [(_as_date(r.get("date")), r) for r in rows]
    parseable = [d for d, _ in dated if d is not None]
    if not parseable:
        return rows
    anchor = max(parseable)
    if range_ == "YTD":
        cutoff = _dt.date(anchor.year, 1, 1)
    else:
        cutoff = anchor - _dt.timedelta(days=_RANGE_CAL_DAYS.get(range_, 182))
    return [r for d, r in dated if d is None or d >= cutoff]


def _shape_charting(rows: list[dict], window: str) -> list[dict]:
    """Shape raw OHLCV rows to ``{date, OHLC, sma20, sma50, rsi14}``.

    Indicators are computed over the full ascending series (so SMA50 has
    lookback) and the output is sliced to ``window``. Pure (no I/O).
    """
    parsed: list[tuple[_dt.date, dict]] = []
    for r in rows:
        d = _as_date(r.get("date"))
        if d is None or r.get("close") is None:
            continue
        parsed.append((d, r))
    parsed.sort(key=lambda t: t[0])
    if not parsed:
        return []
    closes = [float(r.get("close")) for _, r in parsed]
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    rsi14 = _rsi(closes, 14)
    cutoff = _window_cutoff(parsed[-1][0], window)
    out: list[dict] = []
    for idx, (d, r) in enumerate(parsed):
        if d < cutoff:
            continue
        out.append(
            {
                "date": d.isoformat(),
                "open": r.get("open"),
                "high": r.get("high"),
                "low": r.get("low"),
                "close": r.get("close"),
                "sma20": sma20[idx],
                "sma50": sma50[idx],
                "rsi14": rsi14[idx],
            }
        )
    return out


def _charting_fmp_cached(*, symbol: str, window: str = "3M") -> list[dict]:
    """Tier call: fetch live price history from fmp_cached, add indicators.

    Empty output is loud (WARNING) and returned as ``[]`` so the chain
    transitions to the next tier / the endpoint stub.
    """
    rows = _fetch_price_history_rows(symbol)
    shaped = _shape_charting(rows, window)
    if not shaped:
        logger.warning(
            "charting fmp_cached returned 0 rows for %s (window=%s) "
            "— chain will transition to the next tier/stub",
            symbol,
            window,
        )
    return shaped


# ---------------------------------------------------------------------------
# financials / statements (#1920 — full-wiring of #1653)
# ---------------------------------------------------------------------------
#
# A 2-period comparison table over three statements. Fetches income, balance,
# and cash statements (limit=2, latest-first) and maps nine canonical line
# items to ``{line_item, period_1 (latest), period_2 (prior)}``. Values are
# the provider's raw amounts (absolute currency units), ``None`` where a
# period or field is missing. The widget's ``period`` (annual/quarterly) maps
# to the provider's ``annual``/``quarter``.

#: Widget ``period`` value -> provider ``period`` argument.
_STATEMENT_PERIOD_MAP: dict[str, str] = {"annual": "annual", "quarterly": "quarter"}

#: (row label, statement source, provider field). Order defines row order and
#: mirrors the shipped stub so the widget renders identically.
_STATEMENT_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("Revenue", "income", "revenue"),
    ("Gross Profit", "income", "gross_profit"),
    ("Operating Income", "income", "total_operating_income"),
    ("Net Income", "income", "bottom_line_net_income"),
    ("Total Assets", "balance", "total_assets"),
    ("Total Debt", "balance", "total_debt"),
    ("Cash & Equivalents", "balance", "cash_and_cash_equivalents"),
    ("Operating Cash Flow", "cash", "operating_cash_flow"),
    ("Free Cash Flow", "cash", "free_cash_flow"),
)


def _fetch_statement(kind: str, symbol: str, period: str) -> list[dict]:
    """Fetch one statement (``income``/``balance``/``cash``) latest-first.

    Rows are normalized to plain dicts and sorted DESC by ``period_ending``
    so index 0 is the most recent fiscal period.
    """
    fetch = getattr(_obb().equity.fundamental, kind)
    res = fetch(symbol=symbol, provider="fmp_cached", period=period, limit=2)
    rows = getattr(res, "results", res)
    out: list[dict] = []
    for r in rows:
        if hasattr(r, "model_dump"):
            out.append(r.model_dump())
        elif isinstance(r, dict):
            out.append(r)
        else:
            out.append(dict(r))
    out.sort(key=lambda d: _iso(d.get("period_ending")), reverse=True)
    return out


def _fetch_statements_rows(
    symbol: str, period: str
) -> tuple[list[dict], list[dict], list[dict]]:
    """Fetch income, balance, and cash statements for ``symbol``/``period``."""
    provider_period = _STATEMENT_PERIOD_MAP.get(period, "annual")
    income = _fetch_statement("income", symbol, provider_period)
    balance = _fetch_statement("balance", symbol, provider_period)
    cash = _fetch_statement("cash", symbol, provider_period)
    return income, balance, cash


def _shape_statements(
    income: list[dict], balance: list[dict], cash: list[dict]
) -> list[dict]:
    """Map three statements to the 9-row ``{line_item, period_1, period_2}``.

    Pure (no I/O). Each source list is assumed latest-first; index 0 fills
    ``period_1`` and index 1 fills ``period_2`` (``None`` when absent).
    """
    src = {"income": income, "balance": balance, "cash": cash}

    def _value(source: str, field: str, idx: int) -> Any:
        rows = src[source]
        if idx < len(rows):
            return rows[idx].get(field)
        return None

    out: list[dict] = []
    for label, source, field in _STATEMENT_ITEMS:
        out.append(
            {
                "line_item": label,
                "period_1": _value(source, field, 0),
                "period_2": _value(source, field, 1),
            }
        )
    return out


def _statements_fmp_cached(*, symbol: str, period: str = "annual") -> list[dict]:
    """Tier call: fetch the three live statements from fmp_cached and shape them.

    Empty output (no statement returned any row) is loud (WARNING) and returned
    as ``[]`` so the chain transitions to the next tier / the endpoint stub.
    """
    income, balance, cash = _fetch_statements_rows(symbol, period)
    if not (income or balance or cash):
        logger.warning(
            "statements fmp_cached returned 0 rows for %s (period=%s) "
            "— chain will transition to the next tier/stub",
            symbol,
            period,
        )
        return []
    return _shape_statements(income, balance, cash)


# ---------------------------------------------------------------------------
# financials (F2 chart) — full-wiring of stub #1955
# ---------------------------------------------------------------------------
#
# The F2 Financials chart (pi_equity_financial_charts -> pi/equity/financials)
# renders 5 years of revenue / net income + net margin. Fetches annual income
# statements from fmp_cached and shapes each period to the widget contract
# ``{year, revenue_b, net_income_b, net_margin_pct}`` — matching the shipped
# stub so the chart renders identically. Amounts are scaled from absolute
# currency units to billions. Loud-empty falls to the endpoint stub.

#: Number of annual periods the financials chart shows.
_FINANCIALS_YEARS = 5


def _fetch_income_annual(symbol: str) -> list[dict]:
    """Fetch up to ``_FINANCIALS_YEARS`` annual income statements (fmp_cached).

    Rows are normalized to plain dicts. Order is not guaranteed here; the
    shaper sorts by fiscal year ascending.
    """
    res = _obb().equity.fundamental.income(
        symbol=symbol,
        provider="fmp_cached",
        period="annual",
        limit=_FINANCIALS_YEARS,
    )
    rows = getattr(res, "results", res)
    out: list[dict] = []
    for r in rows:
        if hasattr(r, "model_dump"):
            out.append(r.model_dump())
        elif isinstance(r, dict):
            out.append(r)
        else:
            out.append(dict(r))
    return out


def _year_of(period_ending: Any) -> int | None:
    """Extract the fiscal year from a date-ish ``period_ending`` (or None)."""
    if period_ending is None:
        return None
    if hasattr(period_ending, "year"):
        return int(period_ending.year)
    text = str(period_ending)
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def _shape_financials(rows: list[dict]) -> list[dict]:
    """Map raw annual income rows to the chart contract, oldest-first.

    Pure (no I/O). Each row -> ``{year, revenue_b, net_income_b,
    net_margin_pct}``. Amounts are scaled to billions. A row missing a fiscal
    year or a positive revenue is dropped (revenue anchors the year axis and
    the margin denominator). ``net_income_b`` / ``net_margin_pct`` are ``None``
    when net income is absent.
    """
    shaped: list[dict] = []
    for r in rows:
        year = _year_of(r.get("period_ending"))
        revenue = _as_float(r.get("revenue"))
        if year is None or not revenue:
            continue
        net_income = _as_float(r.get("bottom_line_net_income"))
        if net_income is None:
            net_income = _as_float(r.get("net_income"))
        net_income_b = None if net_income is None else round(net_income / 1e9, 3)
        revenue_b = round(revenue / 1e9, 3)
        net_margin_pct = (
            None if net_income is None else round(net_income / revenue * 100, 2)
        )
        shaped.append(
            {
                "year": year,
                "revenue_b": revenue_b,
                "net_income_b": net_income_b,
                "net_margin_pct": net_margin_pct,
            }
        )
    shaped.sort(key=lambda d: d["year"])
    return shaped


def _financials_fmp_cached(*, symbol: str) -> list[dict]:
    """Tier call: fetch live annual income from fmp_cached and shape it.

    Empty output is loud (WARNING) and returned as ``[]`` so the chain
    transitions to the next tier / the endpoint stub.
    """
    rows = _fetch_income_annual(symbol)
    shaped = _shape_financials(rows)
    if not shaped:
        logger.warning(
            "financials fmp_cached returned 0 rows for %s "
            "— chain will transition to the next tier/stub",
            symbol,
        )
    return shaped


# ---------------------------------------------------------------------------
# peer-multiples / competitors (#1923 — full-wiring of #1657)
# ---------------------------------------------------------------------------
#
# A valuation matrix over the ticker + its peers. Fetches the peer list
# (equity.compare.peers) and, per symbol, the latest valuation ratios/metrics,
# emitting {symbol, pe_ttm, pe_fwd, ev_ebitda, ps_ttm}. ``pe_fwd`` is None
# pending an fmp_cached forward-P/E source (gh #1922, area:fmp-cached-gap);
# the trailing multiples are live.

#: Max peers appended after the self symbol (bounds the fan-out cost).
_PEER_CAP = 4


def _as_float(value: Any) -> float | None:
    """Coerce a numeric-ish value to float, or None when absent/non-numeric."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_peer_symbols(symbol: str) -> list[str]:
    """Return ``[symbol, *peers]`` (deduped, self first, capped at _PEER_CAP)."""
    res = _obb().equity.compare.peers(symbol=symbol, provider="fmp_cached")
    rows = getattr(res, "results", res)
    peers: list[str] = []
    for r in rows:
        sym = getattr(r, "symbol", None)
        if sym is None and isinstance(r, dict):
            sym = r.get("symbol")
        if sym:
            peers.append(str(sym).upper())
    out: list[str] = [symbol]
    for p in peers:
        if p not in out:
            out.append(p)
        if len(out) >= _PEER_CAP + 1:
            break
    return out


def _fetch_valuation(sym: str) -> tuple[dict, dict]:
    """Fetch the latest ratios + metrics rows for ``sym`` as plain dicts.

    Each may be ``{}`` when the provider returns nothing for that symbol.
    """

    def _latest(kind: str) -> dict:
        fetch = getattr(_obb().equity.fundamental, kind)
        res = fetch(symbol=sym, provider="fmp_cached", limit=1)
        rows = getattr(res, "results", res)
        if not rows:
            return {}
        r = rows[0]
        if hasattr(r, "model_dump"):
            return r.model_dump()
        if isinstance(r, dict):
            return r
        return dict(r)

    return _latest("ratios"), _latest("metrics")


def _shape_peer_row(symbol: str, ratios: dict, metrics: dict) -> dict:
    """Map one symbol's ratios/metrics to the widget row (pure, no I/O).

    ``pe_fwd`` is always None until an fmp_cached forward-P/E source lands
    (gh #1922). The remaining multiples come from live provider fields.
    """
    return {
        "symbol": symbol,
        "pe_ttm": _as_float(ratios.get("price_to_earnings")),
        "pe_fwd": None,
        "ev_ebitda": _as_float(metrics.get("ev_to_ebitda")),
        "ps_ttm": _as_float(ratios.get("price_to_sales")),
    }


def _peer_multiples_fmp_cached(*, symbol: str) -> list[dict]:
    """Tier call: build the self+peers valuation matrix from fmp_cached.

    Empty output (no peer symbols resolved) is loud (WARNING) and returned as
    ``[]`` so the chain transitions to the next tier / the endpoint stub.
    """
    symbols = _fetch_peer_symbols(symbol)
    if not symbols:
        logger.warning(
            "peer-multiples fmp_cached returned 0 rows for %s "
            "— chain will transition to the next tier/stub",
            symbol,
        )
        return []
    out: list[dict] = []
    for sym in symbols:
        ratios, metrics = _fetch_valuation(sym)
        out.append(_shape_peer_row(sym, ratios, metrics))
    return out


# ---------------------------------------------------------------------------
# price-target-history (#1926 — full-wiring of #1669)
# ---------------------------------------------------------------------------
#
# Analyst price-target evolution vs. the stock price at posting time, as a
# {date, close, target} time series for the chart. Sourced from
# equity.estimates.price_target (fmp_cached), which returns dated per-analyst
# rows: published_date -> date, price_target -> target, price_when_posted ->
# close. Rows without a usable date or target are dropped; the most-recent
# _TARGET_CAP points are kept and emitted in chronological (ascending) order.

#: Max most-recent target points kept for the chart (bounds payload size).
_TARGET_CAP = 60


def _fetch_price_target_rows(symbol: str) -> list[dict]:
    """Fetch dated analyst price-target rows for ``symbol`` as plain dicts."""
    res = _obb().equity.estimates.price_target(symbol=symbol, provider="fmp_cached")
    rows = getattr(res, "results", res)
    out: list[dict] = []
    for r in rows:
        if hasattr(r, "model_dump"):
            out.append(r.model_dump())
        elif isinstance(r, dict):
            out.append(r)
        else:
            out.append(dict(r))
    return out


def _shape_target_history(rows: list[dict]) -> list[dict]:
    """Map raw analyst-target rows to ``{date, close, target}`` (pure, no I/O).

    Rows without a usable ``published_date`` or ``price_target`` are dropped.
    The most-recent :data:`_TARGET_CAP` rows are kept (sorted by date DESC)
    and returned in chronological (ascending) order so the chart reads
    left-to-right.
    """
    shaped: list[dict] = []
    for r in rows:
        date = _iso_date(r.get("published_date"))
        target = _as_float(r.get("price_target"))
        if date is None or target is None:
            continue
        shaped.append(
            {
                "date": date,
                "close": _as_float(r.get("price_when_posted")),
                "target": target,
            }
        )
    shaped.sort(key=lambda row: row["date"], reverse=True)
    kept = shaped[:_TARGET_CAP]
    kept.reverse()
    return kept


def _price_target_history_fmp_cached(*, symbol: str) -> list[dict]:
    """Tier call: build the price-target time series from fmp_cached.

    Empty output is loud (WARNING) and returned as ``[]`` so the chain
    transitions to the next tier / the endpoint stub.
    """
    rows = _fetch_price_target_rows(symbol)
    shaped = _shape_target_history(rows)
    if not shaped:
        logger.warning(
            "price-target-history fmp_cached returned 0 rows for %s "
            "— chain will transition to the next tier/stub",
            symbol,
        )
        return []
    return shaped


# ---------------------------------------------------------------------------
# equity/header + equity/key-stats (#1958 — full-wiring of #1685 profile stubs)
# ---------------------------------------------------------------------------
#
# equity/header renders a markdown profile card; equity/key-stats a
# {metric, value} grid. Both compose live fmp_cached ``equity.profile`` +
# ``equity.price.quote`` (key-stats also folds in ``fundamental.metrics`` and
# ``fundamental.ratios``). Provider conventions (verified live 2026-08-08):
#   * ``quote.change_percent`` is a FRACTION (0.00026 == 0.026%); the day-change
#     percent is computed from ``change / prev_close`` so it is agnostic to that
#     convention.
#   * ``ratios.dividend_yield`` is a FRACTION (0.00712 == 0.71%); shown ``*100``.
# header RAISES on an all-empty fetch — a non-empty ``str`` is NOT caught by the
# chain's ``_is_empty``, so returning ``""`` would be mis-read as a successful
# live serve (blank card). key-stats returns ``[]`` (loud-empty) so the chain
# transitions to the endpoint stub.


def _first_row_dump(res: Any) -> dict:
    """Return the first result row of an obb response as a plain dict ({} if none)."""
    rows = getattr(res, "results", res)
    if isinstance(rows, list):
        if not rows:
            return {}
        row = rows[0]
    else:
        row = rows
    if hasattr(row, "model_dump"):
        return row.model_dump()
    if isinstance(row, dict):
        return row
    return {}


def _safe_first_row(fetch: Callable[[], Any], *, label: str, symbol: str) -> dict:
    """Fetch + dump the first row; a provider failure degrades to ``{}``.

    Used for the *enrichment* sources (metrics/ratios) so a single endpoint
    hiccup (e.g. a plan-limited 402) never blanks the whole grid — the core
    profile/quote data still renders live.
    """
    try:
        return _first_row_dump(fetch())
    except Exception:  # noqa: BLE001 - enrichment source is best-effort
        logger.warning(
            "key-stats %s fetch failed for %s — omitting those fields",
            label,
            symbol,
        )
        return {}


def _human_usd(value: Any) -> str | None:
    """Format a USD magnitude as $X.XXT / $XXX.XB / $XXX.XM / $N (or None)."""
    n = _as_float(value)
    if n is None:
        return None
    a = abs(n)
    if a >= 1e12:
        return f"${n / 1e12:.2f}T"
    if a >= 1e9:
        return f"${n / 1e9:.1f}B"
    if a >= 1e6:
        return f"${n / 1e6:.1f}M"
    return f"${n:,.0f}"


def _human_int(value: Any) -> str | None:
    """Format a count as X.XB / X.XM / XXXK / N (or None)."""
    n = _as_float(value)
    if n is None:
        return None
    a = abs(n)
    if a >= 1e9:
        return f"{n / 1e9:.1f}B"
    if a >= 1e6:
        return f"{n / 1e6:.1f}M"
    if a >= 1e3:
        return f"{n / 1e3:.0f}K"
    return f"{n:,.0f}"


def _fetch_profile(symbol: str) -> dict:
    """Fetch the fmp_cached company profile row for ``symbol`` (or {})."""
    return _first_row_dump(_obb().equity.profile(symbol=symbol, provider="fmp_cached"))


def _fetch_quote(symbol: str) -> dict:
    """Fetch the fmp_cached live quote row for ``symbol`` (or {})."""
    return _first_row_dump(
        _obb().equity.price.quote(symbol=symbol, provider="fmp_cached")
    )


def _change_percent(quote: dict) -> float | None:
    """Compute day change % from ``change / prev_close`` (provider-agnostic)."""
    change = _as_float(quote.get("change"))
    prev_close = _as_float(quote.get("prev_close"))
    if change is None or not prev_close:
        return None
    return change / prev_close * 100


def _shape_header(symbol: str, profile: dict, quote: dict) -> str:
    """Compose the header markdown card from profile + quote (pure, no I/O)."""
    name = profile.get("name") or quote.get("name") or symbol
    exchange = quote.get("exchange") or profile.get("stock_exchange") or "—"
    sector = profile.get("sector") or "—"
    industry = profile.get("industry_group") or profile.get("industry_category") or "—"
    price = _as_float(quote.get("last_price"))
    if price is None:
        price = _as_float(profile.get("last_price"))
    change = _as_float(quote.get("change"))
    change_pct = _change_percent(quote)
    market_cap = _human_usd(profile.get("market_cap") or quote.get("market_cap"))
    year_high = _as_float(profile.get("year_high") or quote.get("year_high"))
    year_low = _as_float(profile.get("year_low") or quote.get("year_low"))

    price_line = "—" if price is None else f"${price:,.2f}"
    change_line = (
        "—"
        if change is None or change_pct is None
        else f"{change:+,.2f} ({change_pct:+.2f}%)"
    )
    range_line = (
        "—"
        if year_high is None or year_low is None
        else f"${year_low:,.2f} – ${year_high:,.2f}"
    )
    return "\n".join(
        [
            f"## {symbol} — {name}",
            "",
            f"- **Exchange:** {exchange}",
            f"- **Sector / Industry:** {sector} / {industry}",
            f"- **Price:** {price_line}",
            f"- **Day Change:** {change_line}",
            f"- **Market Cap:** {market_cap or '—'}",
            f"- **52-Week Range:** {range_line}",
        ]
    )


def _header_fmp_cached(*, symbol: str) -> str:
    """Tier call: live equity header markdown from fmp_cached profile + quote.

    Raises ``ValueError`` when BOTH sources are empty so the chain transitions
    to the endpoint stub (the chain's ``_is_empty`` does not treat a non-empty
    string as empty — returning ``""`` would be mis-read as a live serve).
    """
    profile = _fetch_profile(symbol)
    quote = _fetch_quote(symbol)
    if not profile and not quote:
        logger.warning(
            "header fmp_cached: empty profile+quote for %s — chain -> stub",
            symbol,
        )
        raise ValueError(f"no fmp_cached profile/quote for {symbol}")
    return _shape_header(symbol, profile, quote)


def _shape_key_stats(
    symbol: str, profile: dict, quote: dict, metrics: dict, ratios: dict
) -> list[dict]:
    """Compose the key-stats {metric, value} grid (pure, no I/O).

    Emits only fields fmp_cached sources live — never fabricates. The Symbol
    row is always appended but is NOT counted as a data row by the caller's
    loud-empty check. Fields with no fmp_cached source (forward P/E, short
    interest, insider ownership, shares float, next earnings) are dropped
    rather than faked (area:fmp-cached-gap follow-up).
    """
    out: list[dict] = []

    def add(metric: str, value: Any) -> None:
        if value is not None:
            out.append({"metric": metric, "value": value})

    add("Market Cap", _human_usd(profile.get("market_cap") or quote.get("market_cap")))
    pe = _as_float(ratios.get("price_to_earnings"))
    add("P/E (TTM)", None if pe is None else round(pe, 2))
    ev_ebitda = _as_float(metrics.get("ev_to_ebitda"))
    add("EV/EBITDA", None if ev_ebitda is None else round(ev_ebitda, 2))
    ps = _as_float(ratios.get("price_to_sales"))
    add("P/S (TTM)", None if ps is None else round(ps, 2))
    eps = _as_float(ratios.get("net_income_per_share"))
    add("EPS (TTM)", None if eps is None else round(eps, 2))
    beta = _as_float(profile.get("beta"))
    add("Beta", None if beta is None else round(beta, 2))
    div_yield = _as_float(ratios.get("dividend_yield"))
    add("Dividend Yield", None if div_yield is None else f"{div_yield * 100:.2f}%")
    add("Volume", _human_int(quote.get("volume")))
    yh = _as_float(profile.get("year_high") or quote.get("year_high"))
    add("52-Week High", None if yh is None else round(yh, 2))
    yl = _as_float(profile.get("year_low") or quote.get("year_low"))
    add("52-Week Low", None if yl is None else round(yl, 2))
    out.append({"metric": "Symbol", "value": symbol})
    return out


def _fetch_metrics(symbol: str) -> dict:
    """Fetch the latest fmp_cached key-metrics row for ``symbol`` (best-effort {})."""
    return _safe_first_row(
        lambda: _obb().equity.fundamental.metrics(symbol=symbol, provider="fmp_cached"),
        label="metrics",
        symbol=symbol,
    )


def _fetch_ratios(symbol: str) -> dict:
    """Fetch the latest fmp_cached ratios row for ``symbol`` (best-effort {})."""
    return _safe_first_row(
        lambda: _obb().equity.fundamental.ratios(
            symbol=symbol, provider="fmp_cached", limit=1
        ),
        label="ratios",
        symbol=symbol,
    )


def _key_stats_fmp_cached(*, symbol: str) -> list[dict]:
    """Tier call: live key-stats grid from fmp_cached profile/quote/metrics/ratios.

    Loud-empty: when no live data row (other than Symbol) can be built, returns
    ``[]`` so the chain transitions to the next tier / the endpoint stub.
    """
    profile = _fetch_profile(symbol)
    quote = _fetch_quote(symbol)
    metrics = _fetch_metrics(symbol)
    ratios = _fetch_ratios(symbol)
    shaped = _shape_key_stats(symbol, profile, quote, metrics, ratios)
    data_rows = [r for r in shaped if r["metric"] != "Symbol"]
    if not data_rows:
        logger.warning(
            "key-stats fmp_cached: no live metrics for %s — chain -> stub",
            symbol,
        )
        return []
    return shaped


# ---------------------------------------------------------------------------
# Registration entry point
# ---------------------------------------------------------------------------


def register_all(register: Callable[[str, str, Callable[..., Any]], None]) -> None:
    """Register every wired ``(family, "fmp_cached")`` tier call.

    Passed the ``register_tier_call`` hook explicitly (rather than importing
    it) so tests can drive registration deterministically after clearing the
    dispatch table.
    """
    register("equity/price-history", "fmp_cached", _price_history_fmp_cached)
    register("equity/price-performance", "fmp_cached", _price_performance_fmp_cached)
    register("equity/management-team", "fmp_cached", _management_team_fmp_cached)
    register("equity/revenue-geography", "fmp_cached", _revenue_geography_fmp_cached)
    register(
        "equity/revenue-business-line",
        "fmp_cached",
        _revenue_business_line_fmp_cached,
    )
    register("equity/dividend-payment", "fmp_cached", _dividend_payment_fmp_cached)
    register("equity/insider-trading", "fmp_cached", _insider_trading_fmp_cached)
    register("equity/earnings-history", "fmp_cached", _earnings_history_fmp_cached)
    register("equity/company-filings", "fmp_cached", _company_filings_fmp_cached)
    register("equity/stock-splits", "fmp_cached", _stock_splits_fmp_cached)
    register("charting", "fmp_cached", _charting_fmp_cached)
    register("equity/statements", "fmp_cached", _statements_fmp_cached)
    register("equity/financials", "fmp_cached", _financials_fmp_cached)
    register("equity/peer-multiples", "fmp_cached", _peer_multiples_fmp_cached)
    register(
        "equity/price-target-history",
        "fmp_cached",
        _price_target_history_fmp_cached,
    )
    register("equity/header", "fmp_cached", _header_fmp_cached)
    register("equity/key-stats", "fmp_cached", _key_stats_fmp_cached)


# Fire the registrations on import for the running backend (main.py imports
# this module for side effects).
from openbb_portfolio_intel.providers.retrofit import (  # noqa: E402
    register_tier_call as _register_tier_call,
)

register_all(_register_tier_call)
