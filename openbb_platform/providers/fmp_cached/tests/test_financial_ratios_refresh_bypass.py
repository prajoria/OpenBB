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
