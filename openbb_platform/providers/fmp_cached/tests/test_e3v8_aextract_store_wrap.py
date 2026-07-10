"""Unit tests for bd-e3v8 — D4 aextract_data cache-write wrap.

Six sibling ``aextract_data`` functions in ``openbb_fmp_cached/models/``
call ``_store_*(fresh_data)`` unconditionally after fetching from FMP:

    fresh_data = await FMPXFetcher.aextract_data(fetch_query, ...)
    if fresh_data:
        _store_X(fresh_data)          # can raise
        results.extend(fresh_data)    # NEVER RUNS if raise

If ``_store_X`` raises (MySQL down, network blip, disk full), the
``results.extend`` line is skipped and the exception propagates. The
user paid the FMP API cost, the data was fetched successfully, but
they receive an exception instead of the data.

Post-fix each of the 6 sites wraps ``_store_X(fresh_data)`` in
try/except: logger.warning matching the D4 pattern from
institutional_ownership and etf_holdings — cache write failure logs
a WARNING but the fresh_data is still returned to the caller.

Sites:
- balance_sheet
- cash_flow
- income_statement
- financial_ratios
- key_metrics
- equity_quote

The atomicity contract of ``_store_X`` itself (fail-fast, raise on
error — locked by PR #418 tests) is UNCHANGED. Only the caller wraps.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Site-level source-lint: every aextract_data MUST wrap _store_X in try/except
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_path, store_fn_name",
    [
        (
            "openbb_fmp_cached.models.balance_sheet",
            "_store_balance_sheets",
        ),
        (
            "openbb_fmp_cached.models.cash_flow",
            "_store_cash_flow_statements",
        ),
        (
            "openbb_fmp_cached.models.income_statement",
            "_store_income_statement",
        ),
        (
            "openbb_fmp_cached.models.financial_ratios",
            "_store_financial_ratios",
        ),
        (
            "openbb_fmp_cached.models.key_metrics",
            "_store_key_metrics",
        ),
        (
            "openbb_fmp_cached.models.equity_quote",
            "_store_quotes",
        ),
    ],
)
def test_aextract_data_wraps_store_call_in_try_except(
    module_path: str, store_fn_name: str
):
    """Source-level lint: aextract_data wraps _store_X in try/except.

    A regex-based lint that finds the ``if fresh_data:`` block and
    asserts the ``_store_X(fresh_data)`` call is inside a try/except
    that logs a warning. If a future refactor removes the wrap, this
    test fails at unit-test time rather than surfacing as a P2 hunter
    finding again.
    """
    import importlib

    mod = importlib.import_module(module_path)
    src = inspect.getsource(mod)

    # Locate the store call site.
    store_call = f"{store_fn_name}(fresh_data)"
    assert store_call in src, f"{module_path}: expected `{store_call}` in source"

    # Extract a window around the call to check for try/except.
    call_idx = src.find(store_call)
    window_start = max(0, call_idx - 400)
    window_end = min(len(src), call_idx + 200)
    window = src[window_start:window_end]

    assert "try:" in window, (
        f"{module_path}: `{store_call}` MUST be wrapped in try/except "
        f"(bd-e3v8 D4 — cache write failure MUST NOT discard fresh_data)"
    )
    assert "except Exception" in window, (
        f"{module_path}: try block MUST catch Exception (not just narrow types) "
        f"— cache is best-effort, ANY failure should log + fall through."
    )
    assert "logger.warning" in window, (
        f"{module_path}: cache write failure MUST log at WARNING (not DEBUG) "
        f"so operators see the fallback."
    )


# ---------------------------------------------------------------------------
# Behavioral verification: aextract_data returns data even if _store raises
# ---------------------------------------------------------------------------


# One representative behavioral test — balance_sheet stands in for all 6
# since the wrap pattern is identical. If the wrap regresses on one site,
# the source-level lint above catches it.


def test_aextract_data_returns_data_even_if_store_raises(caplog):
    """Behavioral: MSFT FMP returns data + _store raises → user gets MSFT data.

    Locks the bd-e3v8 contract end-to-end: fresh_data flows through to
    results even when the cache write blows up. Warning logged.
    """
    from openbb_fmp_cached.models import balance_sheet as mod

    # Skip if the module's upstream imports aren't fully wired in
    # the test env. Best-effort behavioral coverage.
    fetcher_cls = mod.FMPCachedBalanceSheetFetcher
    query = mod.FMPBalanceSheetQueryParams(symbol="MSFT")

    fresh_data = [
        {
            "symbol": "MSFT",
            "date": "2024-06-30",
            "period": "annual",
            "reportedCurrency": "USD",
            "totalAssets": 500_000_000,
        }
    ]

    with patch.object(mod, "init_database"), patch.object(
        mod, "create_balance_sheet_table"
    ), patch.object(mod, "_get_cached_balance_sheet", return_value=[]), patch.object(
        mod.FMPBalanceSheetFetcher,
        "aextract_data",
        new=AsyncMock(return_value=fresh_data),
    ), patch.object(
        mod, "_store_balance_sheets", side_effect=RuntimeError("mysql down")
    ), caplog.at_level(
        "WARNING", logger="openbb_fmp_cached.models.balance_sheet"
    ):
        result = asyncio.run(
            fetcher_cls.aextract_data(query, credentials={"fmp_api_key": "x"})
        )

    # Data MUST be returned to the user even though _store raised.
    assert result == fresh_data, (
        f"bd-e3v8: fresh_data MUST be returned to the caller even if the "
        f"cache write raises. Got: {result}. Pre-fix the exception would "
        f"propagate and the user would receive nothing despite paying the "
        f"FMP API cost."
    )
    # Warning logged so operators see the cache failure.
    assert any("cache write failed" in rec.message.lower() for rec in caplog.records), (
        f"Cache write failure MUST log at WARNING so operators see it. "
        f"Got: {[rec.message for rec in caplog.records]}"
    )
