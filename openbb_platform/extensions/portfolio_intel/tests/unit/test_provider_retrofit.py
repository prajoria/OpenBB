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


# ---------------------------------------------------------------------------
# Security review (#1715 review — HIGH: auth-bypass, input-validation-bypass)
# ---------------------------------------------------------------------------


def test_with_chain_require_auth_runs_before_chain_dispatch() -> None:
    """R7.11 twin: without ``require_auth`` firing in the wrapper, a
    registered live tier would serve unauthenticated requests because
    the ``_require_auth(request)`` inside the stub body is bypassed on
    chain success.

    Load-bearing: replace ``if require_auth is not None: require_auth(...)``
    with ``pass`` in retrofit.py and this test fails.
    """

    tier_called = []

    def live_tier(**kw: object) -> dict:
        tier_called.append(kw)
        return {"served_by": "fmp_cached", **kw}

    register_tier_call("equity/header", "fmp_cached", live_tier)

    class _Denied(RuntimeError):
        pass

    def deny_auth(*_a: object, **_kw: object) -> None:
        raise _Denied("unauthenticated")

    @with_chain(
        endpoint="pi/equity/header",
        family="equity/header",
        record_tier_used=lambda e, t: None,
        require_auth=deny_auth,
    )
    def equity_header(symbol: str = "AAPL") -> dict:
        # Would run if the wrapper let us past auth — must not.
        return {"never": True}

    with pytest.raises(_Denied):
        equity_header(symbol="AAPL")
    assert tier_called == [], "tier called despite auth denial — auth bypass!"


def test_with_chain_validate_kwargs_runs_before_chain_dispatch() -> None:
    """R7.11 twin: without ``validate_kwargs`` firing in the wrapper, a
    registered tier receives un-sanitized user input.

    Load-bearing: replace the ``validate_kwargs(...)`` call with ``pass``
    in retrofit.py and this test fails.
    """

    tier_called = []

    def live_tier(**kw: object) -> dict:
        tier_called.append(kw)
        return {"served_by": "fmp_cached", **kw}

    register_tier_call("equity/header", "fmp_cached", live_tier)

    class _Invalid(RuntimeError):
        pass

    def reject_xss(*_a: object, symbol: str = "AAPL", **_kw: object) -> None:
        if "<" in symbol or ">" in symbol:
            raise _Invalid(f"invalid symbol {symbol!r}")

    @with_chain(
        endpoint="pi/equity/header",
        family="equity/header",
        record_tier_used=lambda e, t: None,
        validate_kwargs=reject_xss,
    )
    def equity_header(symbol: str = "AAPL") -> dict:
        return {"stub": True, "symbol": symbol}

    with pytest.raises(_Invalid):
        equity_header(symbol="<script>alert(1)</script>")
    assert tier_called == [], "tier called with un-sanitized input — validation bypass!"


def test_with_chain_auth_runs_even_when_chain_falls_to_stub() -> None:
    """Auth must run for BOTH the wired-tier and stub-fallback paths."""
    auth_calls: list = []

    @with_chain(
        endpoint="pi/equity/header",
        family="equity/header",
        record_tier_used=lambda e, t: None,
        require_auth=lambda *a, **kw: auth_calls.append(1),
    )
    def equity_header(symbol: str = "AAPL") -> dict:
        return {"stub": True}

    # No tiers wired — chain exhausts → stub runs.
    equity_header(symbol="AAPL")
    assert auth_calls == [1], "auth must fire even on stub fallback path"
