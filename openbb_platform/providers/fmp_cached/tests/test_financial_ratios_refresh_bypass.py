"""Unit tests for financial_ratios ``refresh=True`` cache bypass — bd-ygoh.

Pre-fix (bd-ygoh) the ``FMPCachedFinancialRatiosFetcher.aextract_data``
cache-read path was gated purely on ``cached_at`` (via the 1-day TTL),
with no mechanism to force-refresh rows whose ``filing_date`` had
advanced. Restatements of historical ratios (methodology fix, amended
filing) would silently disagree with the source until the whole
symbol was evicted from the cache.

The fix (bd-ygoh, option B): add a ``refresh=True`` kwarg on
``aextract_data`` that BYPASSES the cache-read step and refetches
every requested symbol from FMP. The write path
(``_store_financial_ratios``) already DELETE-then-INSERTs per symbol,
so the refetch cleanly overwrites the stale rows. Callers who suspect
a restatement can force a refresh; the default behavior remains
unchanged.

Option A (per-row `filing_date` versioning) is deferred to a Tier-3
refactor with its own schema migration; ``refresh=True`` is the
tactical fix that unblocks the caller today.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from openbb_fmp.models.financial_ratios import FMPFinancialRatiosQueryParams
from openbb_fmp_cached.models import financial_ratios


def _run(coro):
    """Sync wrapper — sidesteps pytest-asyncio inspect.getsource issue."""
    return asyncio.run(coro)


def _stale_cached_row(symbol: str = "AAPL") -> dict:
    """Return a plausible cached financial_ratios record."""
    return {
        "symbol": symbol,
        "date": "2025-06-30",
        "period": "annual",
        "reportedCurrency": "USD",
        "priceToEarningsRatio": 25.0,  # stale (would be different post-restatement)
    }


def _fresh_upstream_row(symbol: str = "AAPL") -> dict:
    """Return a plausible fresh FMP record with a DIFFERENT PE (simulating restatement)."""
    return {
        "symbol": symbol,
        "date": "2025-06-30",
        "period": "annual",
        "reportedCurrency": "USD",
        "priceToEarningsRatio": 22.5,  # restated value
    }


# ---------------------------------------------------------------------------
# Contract 1 — default behavior (refresh=False) is UNCHANGED (regression lock).
# ---------------------------------------------------------------------------


def test_aextract_data_default_serves_cache_when_available():
    """Regression lock: without refresh=True, cache serves the stale row (bd-ygoh)."""
    query = FMPFinancialRatiosQueryParams(symbol="AAPL")
    stale = _stale_cached_row("AAPL")

    with patch.object(
        financial_ratios,
        "init_database",
        return_value=None,
    ), patch.object(
        financial_ratios,
        "create_financial_ratios_table",
        return_value=None,
    ), patch.object(
        financial_ratios,
        "_get_cached_financial_ratios",
        return_value=[stale],
    ), patch.object(
        financial_ratios.FMPFinancialRatiosFetcher,
        "aextract_data",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_upstream:
        result = _run(
            financial_ratios.FMPCachedFinancialRatiosFetcher.aextract_data(
                query, {"fmp_api_key": "fake"}
            )
        )

    # Default path: cache hit → no upstream call.
    assert mock_upstream.call_count == 0, (
        f"upstream was called {mock_upstream.call_count} times — default "
        f"path should serve from cache when available (regression)."
    )
    assert len(result) == 1
    assert result[0]["priceToEarningsRatio"] == 25.0  # stale value


# ---------------------------------------------------------------------------
# Contract 2 — refresh=True BYPASSES the cache-read path (bd-ygoh core).
# ---------------------------------------------------------------------------


def test_aextract_data_refresh_true_bypasses_cache():
    """refresh=True must ignore any cached rows and refetch from FMP (bd-ygoh)."""
    query = FMPFinancialRatiosQueryParams(symbol="AAPL")
    stale = _stale_cached_row("AAPL")
    fresh = _fresh_upstream_row("AAPL")

    with patch.object(
        financial_ratios,
        "init_database",
        return_value=None,
    ), patch.object(
        financial_ratios,
        "create_financial_ratios_table",
        return_value=None,
    ), patch.object(
        financial_ratios,
        "_get_cached_financial_ratios",
        return_value=[stale],
    ) as mock_cache_read, patch.object(
        financial_ratios,
        "_store_financial_ratios",
        return_value=None,
    ), patch.object(
        financial_ratios.FMPFinancialRatiosFetcher,
        "aextract_data",
        new_callable=AsyncMock,
        return_value=[fresh],
    ) as mock_upstream:
        result = _run(
            financial_ratios.FMPCachedFinancialRatiosFetcher.aextract_data(
                query, {"fmp_api_key": "fake"}, refresh=True
            )
        )

    # bd-ygoh core: cache-read helper must NOT be called under refresh=True.
    # (An alternative implementation might call it and then discard the
    # result, but the cleaner fix — and the one that gives operators
    # observable "no cache read happened" behavior — is to skip the call.)
    assert mock_cache_read.call_count == 0, (
        f"_get_cached_financial_ratios was called {mock_cache_read.call_count} "
        f"times under refresh=True — the whole point of refresh is to bypass "
        f"the cache-read step (bd-ygoh)."
    )
    # And upstream MUST have been called.
    assert mock_upstream.call_count == 1, (
        f"upstream aextract_data was called {mock_upstream.call_count} times "
        f"— refresh=True must force a fresh fetch (bd-ygoh)."
    )
    # Result is the fresh value, not the stale one.
    assert len(result) == 1
    assert result[0]["priceToEarningsRatio"] == 22.5, (
        f"refresh=True returned the stale cached value {result[0]!r} — the "
        f"fresh upstream row should have overwritten it."
    )


# ---------------------------------------------------------------------------
# Contract 3 — refresh=True does NOT leak to the upstream FMP call kwargs.
# ---------------------------------------------------------------------------


def test_aextract_data_refresh_kwarg_stripped_before_upstream_call():
    """The refresh kwarg is a cache-layer flag; it MUST NOT reach FMP's fetcher (bd-ygoh).

    Upstream ``FMPFinancialRatiosFetcher.aextract_data`` doesn't accept
    ``refresh`` — leaking it via ``**kwargs`` would raise TypeError. The
    cached wrapper must pop it before delegating.
    """
    query = FMPFinancialRatiosQueryParams(symbol="AAPL")

    captured_kwargs: dict = {}

    async def _capture_upstream(*args, **kwargs):
        # Capture whatever kwargs land here so we can assert refresh
        # was stripped.
        captured_kwargs.update(kwargs)
        return []

    with patch.object(
        financial_ratios,
        "init_database",
        return_value=None,
    ), patch.object(
        financial_ratios,
        "create_financial_ratios_table",
        return_value=None,
    ), patch.object(
        financial_ratios,
        "_get_cached_financial_ratios",
        return_value=[],
    ), patch.object(
        financial_ratios,
        "_store_financial_ratios",
        return_value=None,
    ), patch.object(
        financial_ratios.FMPFinancialRatiosFetcher,
        "aextract_data",
        side_effect=_capture_upstream,
    ):
        _run(
            financial_ratios.FMPCachedFinancialRatiosFetcher.aextract_data(
                query, {"fmp_api_key": "fake"}, refresh=True
            )
        )

    assert "refresh" not in captured_kwargs, (
        f"refresh kwarg leaked to upstream FMP fetcher: {captured_kwargs!r} "
        f"— must be popped from **kwargs before delegating (bd-ygoh)."
    )


# ---------------------------------------------------------------------------
# Contract 4 — refresh=False (explicit) matches default behavior.
# ---------------------------------------------------------------------------


def test_aextract_data_refresh_false_matches_default():
    """Explicit refresh=False behaves identically to omitting the kwarg."""
    query = FMPFinancialRatiosQueryParams(symbol="AAPL")
    stale = _stale_cached_row("AAPL")

    with patch.object(
        financial_ratios,
        "init_database",
        return_value=None,
    ), patch.object(
        financial_ratios,
        "create_financial_ratios_table",
        return_value=None,
    ), patch.object(
        financial_ratios,
        "_get_cached_financial_ratios",
        return_value=[stale],
    ) as mock_cache_read, patch.object(
        financial_ratios.FMPFinancialRatiosFetcher,
        "aextract_data",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_upstream:
        _run(
            financial_ratios.FMPCachedFinancialRatiosFetcher.aextract_data(
                query, {"fmp_api_key": "fake"}, refresh=False
            )
        )

    # refresh=False → cache IS consulted → no upstream call.
    assert mock_cache_read.call_count == 1
    assert mock_upstream.call_count == 0


# ---------------------------------------------------------------------------
# Contract 5 — PR #355 review P1: refresh=True with empty upstream response
#              MUST still evict stale cache rows (bd-ygoh).
# ---------------------------------------------------------------------------


def test_aextract_data_refresh_true_evicts_stale_when_upstream_empty():
    """refresh=True with empty upstream response MUST still evict stale rows (bd-ygoh).

    Pre-review-fix the write path's ``if fresh_data:`` guard skipped
    ``_store_financial_ratios`` when upstream returned ``[]`` (delisting,
    methodology drop, transient failure). Under refresh=True this defeated
    the whole point — user asked for source-over-cache, got kept-cache.
    Post-review-fix (PR #355 code-reviewer P1) the eviction is now
    UNCONDITIONAL via the new ``_evict_symbols_from_cache`` helper
    called BEFORE the fetch.
    """
    query = FMPFinancialRatiosQueryParams(symbol="AAPL,MSFT")

    with patch.object(
        financial_ratios,
        "init_database",
        return_value=None,
    ), patch.object(
        financial_ratios,
        "create_financial_ratios_table",
        return_value=None,
    ), patch.object(
        financial_ratios,
        "_evict_symbols_from_cache",
    ) as mock_evict, patch.object(
        financial_ratios,
        "_store_financial_ratios",
        return_value=None,
    ) as mock_store, patch.object(
        financial_ratios.FMPFinancialRatiosFetcher,
        "aextract_data",
        new_callable=AsyncMock,
        return_value=[],  # empty upstream response
    ):
        _run(
            financial_ratios.FMPCachedFinancialRatiosFetcher.aextract_data(
                query, {"fmp_api_key": "fake"}, refresh=True
            )
        )

    # bd-ygoh core (PR #355 review P1): eviction MUST fire under
    # refresh=True, even though the upstream returned nothing.
    assert mock_evict.call_count == 1, (
        f"_evict_symbols_from_cache was called {mock_evict.call_count} times "
        f"under refresh=True — must fire unconditionally so stale rows don't "
        f"survive an empty upstream response (PR #355 hunter/code-reviewer P1)."
    )
    # And the symbols passed to evict are the full requested set.
    evicted_symbols = mock_evict.call_args[0][0]
    assert set(evicted_symbols) == {"AAPL", "MSFT"}, (
        f"_evict_symbols_from_cache was called with {evicted_symbols!r} "
        f"instead of the full requested symbol set."
    )
    # _store_financial_ratios must NOT be called on empty response
    # (that's the existing write-path guard, unchanged).
    assert mock_store.call_count == 0


def test_aextract_data_refresh_true_does_not_evict_on_default_path():
    """Regression lock: refresh=False (default) must NOT touch _evict_symbols_from_cache."""
    query = FMPFinancialRatiosQueryParams(symbol="AAPL")

    with patch.object(
        financial_ratios,
        "init_database",
        return_value=None,
    ), patch.object(
        financial_ratios,
        "create_financial_ratios_table",
        return_value=None,
    ), patch.object(
        financial_ratios,
        "_get_cached_financial_ratios",
        return_value=[_stale_cached_row("AAPL")],
    ), patch.object(
        financial_ratios,
        "_evict_symbols_from_cache",
    ) as mock_evict:
        _run(
            financial_ratios.FMPCachedFinancialRatiosFetcher.aextract_data(
                query, {"fmp_api_key": "fake"}
            )
        )

    assert mock_evict.call_count == 0, (
        f"_evict_symbols_from_cache was called {mock_evict.call_count} times "
        f"on the default path — eviction must ONLY fire under refresh=True."
    )


def test_aextract_data_db_init_failure_delegates_upstream_regardless_of_refresh():
    """PR #355 review P2: DB-init-fail branch must not accidentally leak refresh (bd-ygoh).

    If ``init_database()`` fails, the code delegates directly to upstream
    without honoring the cache. The ``refresh`` flag is a cache-layer
    kwarg — upstream ``FMPFinancialRatiosFetcher.aextract_data`` doesn't
    accept it and would raise TypeError. Since ``refresh`` is now a
    keyword-only argument (not in ``**kwargs``), it CAN'T leak — this
    test locks that in.
    """
    query = FMPFinancialRatiosQueryParams(symbol="AAPL")

    captured_kwargs: dict = {}

    async def _capture_upstream(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return []

    with patch.object(
        financial_ratios,
        "init_database",
        side_effect=RuntimeError("simulated DB init failure"),
    ), patch.object(
        financial_ratios.FMPFinancialRatiosFetcher,
        "aextract_data",
        side_effect=_capture_upstream,
    ):
        _run(
            financial_ratios.FMPCachedFinancialRatiosFetcher.aextract_data(
                query, {"fmp_api_key": "fake"}, refresh=True
            )
        )

    # Upstream MUST have been called (DB init failed, fell through to
    # direct FMP).
    assert "refresh" not in captured_kwargs, (
        f"refresh leaked to upstream FMP fetcher on the DB-init-fail path: "
        f"{captured_kwargs!r} — keyword-only slot must isolate it (PR #355 "
        f"review P2 defense-in-depth)."
    )
