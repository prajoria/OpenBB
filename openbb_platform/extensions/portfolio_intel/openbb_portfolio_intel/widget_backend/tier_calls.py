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


def _price_history_fmp_cached(*, symbol: str, chart_type: str = "line") -> list[dict]:
    """Tier call: fetch live price history from fmp_cached and shape it.

    An empty result is loud (WARNING) and returned as ``[]`` so the chain
    transitions to the next tier / the endpoint stub instead of silently
    serving nothing.
    """
    rows = _fetch_price_history_rows(symbol)
    shaped = _shape_price_history(rows, chart_type)
    if not shaped:
        logger.warning(
            "price-history fmp_cached returned 0 rows for %s "
            "(chart_type=%s) — chain will transition to the next tier/stub",
            symbol,
            chart_type,
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


# Fire the registrations on import for the running backend (main.py imports
# this module for side effects).
from openbb_portfolio_intel.providers.retrofit import (  # noqa: E402
    register_tier_call as _register_tier_call,
)

register_all(_register_tier_call)
