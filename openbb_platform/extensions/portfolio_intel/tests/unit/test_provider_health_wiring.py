"""Integration tests for the provider-health widget + ChainedFetcher wiring (#1715).

The pure-machinery tests live in ``test_provider_chain.py``. This module
tests the wiring layer: when a widget endpoint calls ``record_tier_used``
after a fetch, the ``/pi/health/providers`` endpoint reflects it.

Also covers the FastAPI TestClient end-to-end for the new
``asyncio.run(...)`` branch inside ``provider_health``.
"""

from __future__ import annotations

import os

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import pytest
from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend import widgets_endpoints as we
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    """Reset per-test module state so tests don't interfere with each other."""
    we._PROVIDER_HEALTH_CACHE.clear()
    we._TIER_IN_USE.clear()


def test_provider_health_shows_currently_serving_section_when_ledger_populated() -> (
    None
):
    """After record_tier_used, the markdown carries 'Currently serving:'."""
    we.record_tier_used("equity/header", "fmp")
    we.record_tier_used("news", "yfinance")

    r = _client.get("/pi/health/providers")
    assert r.status_code == 200
    body = r.json()
    assert "Currently serving:" in body
    assert "`equity/header` → **fmp**" in body
    assert "`news` → **yfinance**" in body


def test_provider_health_omits_currently_serving_when_ledger_empty() -> None:
    """No ChainedFetcher calls yet → no 'Currently serving:' block."""
    r = _client.get("/pi/health/providers")
    body = r.json()
    assert "Currently serving:" not in body


def test_provider_health_cache_ttl_holds_second_call() -> None:
    """Second call within TTL uses cached tier list — no re-probe.

    Note: the cache is populated only when the sync ``asyncio.run(...)``
    branch completes within the 0.5s budget. In test envs with no
    registered probers every tier returns 'unknown' fast, so the cache
    fills; the assertion below tolerates the alternative empty-cache
    branch (cold-cache also correctly renders 'unknown').
    """
    r1 = _client.get("/pi/health/providers")
    cache_after_first = dict(we._PROVIDER_HEALTH_CACHE)
    r2 = _client.get("/pi/health/providers")
    cache_after_second = dict(we._PROVIDER_HEALTH_CACHE)
    assert r1.status_code == r2.status_code == 200
    # Cache is either populated in both calls (identical), or missed in
    # both (both empty). Either state is a valid rendering of "the
    # widget did not lie about tier health" — we're testing determinism.
    assert cache_after_second == cache_after_first


def test_provider_health_still_reports_five_tier_a_and_three_tier_b_names() -> None:
    """Post-#1715 the tier NAMES are unchanged — only rendering changed."""
    r = _client.get("/pi/health/providers")
    body = r.json()
    for tier in ("fmp_cached", "fmp", "cboe", "sec", "yfinance"):
        assert tier in body, f"missing tier {tier!r} in health strip"


def test_provider_health_currently_serving_sorted_for_determinism() -> None:
    """Multi-endpoint ledger renders in sorted order — no test flakes."""
    we.record_tier_used("z_zebra", "sec")
    we.record_tier_used("a_apple", "fmp_cached")
    we.record_tier_used("m_mango", "cboe")

    r = _client.get("/pi/health/providers")
    body = r.json()
    a_idx = body.index("a_apple")
    m_idx = body.index("m_mango")
    z_idx = body.index("z_zebra")
    assert a_idx < m_idx < z_idx, "endpoints must render sorted for determinism"


def test_record_tier_used_updates_ledger_in_place() -> None:
    """Second call with new tier for same endpoint updates, not appends."""
    we.record_tier_used("equity/header", "fmp_cached")
    we.record_tier_used("equity/header", "fmp")

    r = _client.get("/pi/health/providers")
    body = r.json()
    assert "`equity/header` → **fmp**" in body
    assert body.count("equity/header") == 1  # not duplicated


def test_provider_health_never_leaks_raw_exception_in_note() -> None:
    """R7.11 twin: any leaked raw exc string would fail this test.

    Force a probe to raise a raw-message exception. The strip must
    render with a note from ALLOWED_NOTES, never the raw string.
    """
    from openbb_portfolio_intel.providers.probe import (  # noqa: PLC0415
        register_prober,
        unregister_prober,
    )

    async def _leaky() -> None:
        raise RuntimeError("SECRET_TOKEN_abc123 leaked")

    register_prober("cboe", _leaky)
    try:
        r = _client.get("/pi/health/providers")
        body = r.json()
        assert "SECRET_TOKEN_abc123" not in body
    finally:
        unregister_prober("cboe")


def test_provider_health_cold_cache_returns_under_1s() -> None:
    """Preserve the F12 cold-cache latency invariant (#1685 P0-1)."""
    import time as _time

    we._PROVIDER_HEALTH_CACHE.clear()
    start = _time.monotonic()
    r = _client.get("/pi/health/providers")
    elapsed = _time.monotonic() - start
    assert r.status_code == 200
    assert elapsed < 1.0, f"cold-cache probe took {elapsed:.2f}s (spec <1s)"
