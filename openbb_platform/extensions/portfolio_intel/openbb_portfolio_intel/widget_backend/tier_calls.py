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


# Fire the registrations on import for the running backend (main.py imports
# this module for side effects).
from openbb_portfolio_intel.providers.retrofit import (  # noqa: E402
    register_tier_call as _register_tier_call,
)

register_all(_register_tier_call)
