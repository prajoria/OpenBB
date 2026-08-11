"""Tests for #1961 — Provider Health strip renders Track A only.

The Portfolio Intelligence Terminal is verified against a single, unambiguous
data path. Every data widget already fetches via Track A (``with_chain`` /
``route_through_chain`` default to ``track="A"`` and no endpoint overrides to
``"B"``), so surfacing a second ``Track B (free)`` row in the health strip is
pure confusion during test/verification. This suite pins the strip to a single
Track A row.

Track B chain infrastructure (registry ``:B`` keys) stays in place as a dormant
no-credentials fallback — it is simply no longer rendered in the UX.

All hermetic: no network. Probers are injected fakes.
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from openbb_portfolio_intel.providers.probe import (  # noqa: E402
    register_prober,
    unregister_prober,
)
from openbb_portfolio_intel.providers.registry import (  # noqa: E402
    TRACK_A_DEFAULT,
    TRACK_B_DEFAULT,
)
from openbb_portfolio_intel.widget_backend import widgets_endpoints as we  # noqa: E402
from starlette.requests import Request  # noqa: E402

_ALL_TIERS = tuple(dict.fromkeys(TRACK_A_DEFAULT + TRACK_B_DEFAULT))


def _stub_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/pi/health/providers",
            "headers": [],
            "query_string": b"",
        }
    )


def _clear_cache() -> None:
    if hasattr(we, "_PROVIDER_HEALTH_CACHE"):
        we._PROVIDER_HEALTH_CACHE.clear()


def _render() -> str:
    _clear_cache()

    async def _ok() -> None:
        return None

    for t in _ALL_TIERS:
        register_prober(t, _ok)
    try:
        body = asyncio.run(we.provider_health(_stub_request()))
    finally:
        for t in _ALL_TIERS:
            unregister_prober(t)
        _clear_cache()
    return body


def _tiers(body: object) -> set:
    """Tier names present in the provider-health table rows (#1976)."""
    assert isinstance(body, list), f"expected table rows, got {type(body)}"
    return {row["tier"] for row in body}


def test_strip_names_track_a() -> None:
    """Every rendered row is a Track A tier."""
    assert _tiers(_render()) <= set(TRACK_A_DEFAULT)


def test_strip_omits_track_b() -> None:
    """Track B-exclusive tiers are gone — the reverse-verify of the two-row strip.

    Pre-fix the body carried a ``**Track B (free):**`` line; post-#1961/#1976 the
    table renders Track A rows only, so ``yfinance`` (Track B-exclusive) is absent.
    """
    assert "yfinance" not in _tiers(_render())


def test_strip_still_shows_all_track_a_tiers() -> None:
    """Dropping Track B must not drop any Track A tier."""
    tiers = _tiers(_render())
    for name in TRACK_A_DEFAULT:
        assert name in tiers, f"missing Track A tier {name!r} in health table"


def test_strip_probes_only_track_a_tiers() -> None:
    """Only Track A tiers are probed. ``yfinance`` (Track B-exclusive) must NOT
    be probed, proving the strip no longer touches the free track.
    """
    _clear_cache()
    calls: dict[str, int] = {}

    def _make(tier: str):
        async def _probe() -> None:
            calls[tier] = calls.get(tier, 0) + 1

        return _probe

    for t in _ALL_TIERS:
        register_prober(t, _make(t))
    try:
        asyncio.run(we.provider_health(_stub_request()))
    finally:
        for t in _ALL_TIERS:
            unregister_prober(t)
        _clear_cache()

    for t in TRACK_A_DEFAULT:
        assert calls.get(t) == 1, f"{t} probed {calls.get(t)}× (want 1)"
    # yfinance is Track B-exclusive (Track A uses yfinance-snapshot).
    b_only = set(TRACK_B_DEFAULT) - set(TRACK_A_DEFAULT)
    for t in b_only:
        assert calls.get(t, 0) == 0, f"Track-B-only tier {t} was probed"
