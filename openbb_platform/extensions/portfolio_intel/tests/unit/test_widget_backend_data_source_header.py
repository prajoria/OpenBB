"""Data-provenance response header ``X-PI-Data-Source`` (#1953).

Every retrofitted ``@with_chain`` endpoint records which tier served the
request into the ``_TIER_IN_USE`` ledger. A small read-only ASGI middleware
mirrors that value onto an ``X-PI-Data-Source`` response header (keyed by
request path) so the local viewer can render a *live-vs-demo* badge and a
tester can tell real ``fmp_cached`` data from the offline stub at a glance.

These tests assert the header value tracks the serving tier:

- No live tier registered  -> chain exhausts to stub -> header ``stub``.
- A live tier registered    -> chain serves it        -> header ``fmp_cached``.
"""

from __future__ import annotations

import os

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import pytest
from fastapi.testclient import TestClient
from openbb_portfolio_intel.providers.retrofit import _TIER_CALLS
from openbb_portfolio_intel.widget_backend.main import app

_client = TestClient(app)

_URL = "/pi/equity/price-history?symbol=AAPL&chart_type=line&range=6M"


@pytest.fixture
def _clear_tiers():
    """Snapshot + restore the tier dispatch table around a test."""
    saved = dict(_TIER_CALLS)
    try:
        yield
    finally:
        _TIER_CALLS.clear()
        _TIER_CALLS.update(saved)


def test_data_source_header_is_stub_when_no_tier(_clear_tiers):
    """With no live tier, the chain exhausts to the stub -> header ``stub``."""
    _TIER_CALLS.clear()
    resp = _client.get(_URL)
    assert resp.status_code == 200
    assert resp.headers.get("X-PI-Data-Source") == "stub"


def test_data_source_header_is_tier_when_registered(_clear_tiers):
    """With a live tier that returns rows, the header names that tier."""

    def _fake_tier(*, symbol, chart_type="line", range_="6M"):  # noqa: ANN001
        # Non-empty -> the chain serves it (never reaches the stub).
        return [{"date": "2026-08-06", "close": 312.41}]

    _TIER_CALLS[("equity/price-history", "fmp_cached")] = _fake_tier
    resp = _client.get(_URL)
    assert resp.status_code == 200
    assert resp.headers.get("X-PI-Data-Source") == "fmp_cached"
