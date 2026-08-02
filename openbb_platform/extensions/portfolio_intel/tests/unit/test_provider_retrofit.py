"""Retrofit helper tests (#1715 Phase 2A).

Covers:

- ``route_through_chain`` calls the stub_fallback when no tiers wired
- Records the tier used (or ``"stub"``) in the health ledger via callback
- Falls to stub cleanly when the chain exhausts
- Uses a registered tier call when available
- ``with_chain`` decorator preserves the wrapped function's return shape
  when nothing wired (byte-identical to today's stubs)
- Registered tier call short-circuits the stub
"""

from __future__ import annotations

import pytest
from openbb_portfolio_intel.providers.retrofit import (
    _TIER_CALLS,
    register_tier_call,
    route_through_chain,
    with_chain,
)


@pytest.fixture(autouse=True)
def _clear_dispatch() -> None:
    """Reset the module-level dispatch registry between tests."""
    _TIER_CALLS.clear()


def _stub() -> dict:
    return {"source": "stub", "rows": 3}


def test_route_falls_to_stub_when_no_tiers_wired() -> None:
    """R7.11 twin: remove the ``except ChainedFetcherAllTiersFailed`` branch
    -> the endpoint raises 500 instead of gracefully returning the stub.
    """
    calls: list[tuple[str, str]] = []

    def record(endpoint: str, tier: str) -> None:
        calls.append((endpoint, tier))

    result = route_through_chain(
        endpoint="pi/equity/header",
        family="equity/header",
        stub_fallback=_stub,
        record_tier_used=record,
        symbol="AAPL",
    )
    assert result == {"source": "stub", "rows": 3}
    assert calls == [("pi/equity/header", "stub")]


def test_route_calls_registered_tier() -> None:
    """A registered tier call short-circuits the stub."""

    def fmp_cached_call(symbol: str) -> dict:
        return {"source": "fmp_cached", "symbol": symbol}

    register_tier_call("equity/header", "fmp_cached", fmp_cached_call)

    calls: list[tuple[str, str]] = []

    def record(endpoint: str, tier: str) -> None:
        calls.append((endpoint, tier))

    result = route_through_chain(
        endpoint="pi/equity/header",
        family="equity/header",
        stub_fallback=_stub,
        record_tier_used=record,
        symbol="AAPL",
    )
    assert result == {"source": "fmp_cached", "symbol": "AAPL"}
    assert calls == [("pi/equity/header", "fmp_cached")]


def test_route_falls_through_first_tier_that_raises() -> None:
    """Tier 1 raises, tier 2 not registered — still falls to stub, but the
    ledger records ``"stub"`` (never a lie about which tier served)."""

    def broken_call(symbol: str) -> dict:
        raise RuntimeError("provider 500")

    register_tier_call("equity/header", "fmp_cached", broken_call)

    calls: list[tuple[str, str]] = []
    result = route_through_chain(
        endpoint="pi/equity/header",
        family="equity/header",
        stub_fallback=_stub,
        record_tier_used=lambda e, t: calls.append((e, t)),
        symbol="AAPL",
    )
    assert result == _stub()
    assert calls == [("pi/equity/header", "stub")]


def test_route_falls_through_to_next_registered_tier() -> None:
    """Tier 1 raises, tier 2 wired: tier 2 serves the request."""

    def raises(**_: object) -> dict:
        raise RuntimeError("cache miss")

    def fmp_backup(symbol: str) -> dict:
        return {"source": "fmp", "symbol": symbol}

    register_tier_call("equity/header", "fmp_cached", raises)
    register_tier_call("equity/header", "fmp", fmp_backup)

    calls: list[tuple[str, str]] = []
    result = route_through_chain(
        endpoint="pi/equity/header",
        family="equity/header",
        stub_fallback=_stub,
        record_tier_used=lambda e, t: calls.append((e, t)),
        symbol="AAPL",
    )
    assert result == {"source": "fmp", "symbol": "AAPL"}
    assert calls == [("pi/equity/header", "fmp")]


def test_route_falls_to_stub_for_unregistered_family() -> None:
    """Family not in TIER_REGISTRY at all — safe fallback still fires."""
    calls: list[tuple[str, str]] = []
    result = route_through_chain(
        endpoint="pi/never-registered",
        family="totally/fake",
        stub_fallback=lambda: "fine",
        record_tier_used=lambda e, t: calls.append((e, t)),
    )
    assert result == "fine"
    assert calls == [("pi/never-registered", "stub")]


# ---------------------------------------------------------------------------
# @with_chain decorator
# ---------------------------------------------------------------------------


def test_with_chain_preserves_stub_shape_when_no_tiers_wired() -> None:
    """The load-bearing invariant of the retrofit: existing stub
    responses stay byte-identical when nothing is wired."""

    calls: list[tuple[str, str]] = []

    @with_chain(
        endpoint="pi/equity/header",
        family="equity/header",
        record_tier_used=lambda e, t: calls.append((e, t)),
    )
    def equity_header(symbol: str = "AAPL") -> dict:
        return {"source": "stub", "symbol": symbol}

    assert equity_header(symbol="MSFT") == {"source": "stub", "symbol": "MSFT"}
    assert calls == [("pi/equity/header", "stub")]


def test_with_chain_routes_to_registered_tier() -> None:
    """A registered tier wins over the wrapped stub."""

    def fmp_cached_call(symbol: str) -> dict:
        return {"source": "fmp_cached", "symbol": symbol}

    register_tier_call("equity/header", "fmp_cached", fmp_cached_call)

    calls: list[tuple[str, str]] = []

    @with_chain(
        endpoint="pi/equity/header",
        family="equity/header",
        record_tier_used=lambda e, t: calls.append((e, t)),
    )
    def equity_header(symbol: str = "AAPL") -> dict:
        return {"source": "stub", "symbol": symbol}

    result = equity_header(symbol="AAPL")
    assert result["source"] == "fmp_cached"
    assert calls == [("pi/equity/header", "fmp_cached")]


def test_with_chain_kwargs_from_extracts_provider_kwargs() -> None:
    """Custom kwargs_from lets endpoints pass more than just symbol."""

    def news_call(symbol: str, horizon_days: int) -> list:
        return [{"symbol": symbol, "horizon": horizon_days}]

    register_tier_call("news", "fmp_cached", news_call)

    calls: list[tuple[str, str]] = []

    @with_chain(
        endpoint="pi/news",
        family="news",
        record_tier_used=lambda e, t: calls.append((e, t)),
        kwargs_from=lambda symbol="AAPL", horizon_days=7: {
            "symbol": symbol,
            "horizon_days": horizon_days,
        },
    )
    def news_endpoint(symbol: str = "AAPL", horizon_days: int = 7) -> list:
        return [{"source": "stub"}]

    result = news_endpoint(symbol="MSFT", horizon_days=30)
    assert result == [{"symbol": "MSFT", "horizon": 30}]
    assert calls == [("pi/news", "fmp_cached")]


def test_with_chain_falls_to_stub_when_registered_tier_raises() -> None:
    """R7.11 twin: R7.3 loud-fallback — the wrapped stub keeps the endpoint
    responsive even when a wired tier throws."""

    def broken(**_: object) -> dict:
        raise RuntimeError("provider down")

    register_tier_call("equity/header", "fmp_cached", broken)

    @with_chain(
        endpoint="pi/equity/header",
        family="equity/header",
        record_tier_used=lambda e, t: None,
    )
    def equity_header(symbol: str = "AAPL") -> dict:
        return {"source": "stub-recovered", "symbol": symbol}

    result = equity_header(symbol="AAPL")
    assert result == {"source": "stub-recovered", "symbol": "AAPL"}
