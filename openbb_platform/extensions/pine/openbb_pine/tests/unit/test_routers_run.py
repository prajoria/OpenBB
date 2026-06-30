"""Tests for :mod:`openbb_pine.routers.run_router` and ``strategies_router``
(P1 — bead 0e9.5.52).

Pin the two POST endpoints' M1 behavior:

* ``POST /pine/run`` returns HTTP 503 always (codegen C5 pending), but
  validates the request first — non-FMP providers raise PineProviderError
  BEFORE the 503 path so clients see the structured FMP-only message.
* ``POST /pine/strategies/run`` returns HTTP 501 always at M1 (strategies
  live at M2 per PRD §3.2).
* Both routes register their full request shape so the OpenAPI schema is
  correct for the M2 / C5 follow-ups.
"""

from __future__ import annotations

import asyncio

import pytest

from openbb_pine.errors import (
    PineProviderError,
    PineStrategyNotYetImplementedError,
)
from openbb_pine.routers._models import PineByoData


def _run_async(coro):
    """Helper — pytest-asyncio isn't strictly required for these tests."""
    return asyncio.run(coro)


_TRIVIAL_SRC = "//@version=6\nindicator(\"BB\")\nx = 1\n"


# ---------------------------------------------------------------------------
# /pine/run — 503 with structured error
# ---------------------------------------------------------------------------


def test_run_with_valid_provider_request_raises_503_error():
    """Valid FMP request -> structured PineCompilerNotYetAvailableError."""
    from openbb_pine.routers.run_router import (
        PineCompilerNotYetAvailableError,
        run,
    )

    with pytest.raises(PineCompilerNotYetAvailableError) as ei:
        _run_async(run(source=_TRIVIAL_SRC, provider="fmp", symbol="AAPL"))
    # Tracking URL + bead in the message so the client knows where to follow up.
    assert "0e9.5.5" in str(ei.value)
    assert "C5" in str(ei.value)


def test_run_error_has_structured_attributes():
    """The error class exposes ``code``, ``tracking_url``, ``bead``."""
    from openbb_pine.routers.run_router import (
        PineCompilerNotYetAvailableError,
        run,
    )

    with pytest.raises(PineCompilerNotYetAvailableError) as ei:
        _run_async(run(source=_TRIVIAL_SRC, provider="fmp", symbol="AAPL"))
    err = ei.value
    assert err.code == "PineCompilerNotYetAvailableError"
    assert err.tracking_url and "bead%3A0e9.5.5" in err.tracking_url
    assert err.bead == "0e9.5.5"


def test_run_with_byo_data_request_also_raises_503():
    """BYO mode hits the same 503 — both paths share the not-yet-runnable state."""
    from openbb_pine.routers.run_router import (
        PineCompilerNotYetAvailableError,
        run,
    )

    data = PineByoData(format="records", records=[{"close": 1.0}])
    with pytest.raises(PineCompilerNotYetAvailableError):
        _run_async(run(source=_TRIVIAL_SRC, data=data))


def test_run_non_fmp_provider_raises_pine_provider_error_first():
    """Non-FMP names MUST raise PineProviderError BEFORE the 503 path.

    Clients see the structured FMP-only message instead of a generic
    "compiler not yet ready" that masks a user mistake.
    """
    from openbb_pine.routers.run_router import run

    with pytest.raises(PineProviderError) as ei:
        _run_async(run(source=_TRIVIAL_SRC, provider="yahoo", symbol="AAPL"))
    msg = str(ei.value).lower()
    assert "fmp" in msg
    assert "yahoo" in msg


def test_run_without_provider_or_data_raises_validation_error():
    """At least one of provider+symbol or data must be set."""
    from openbb_pine.routers.run_router import run

    # The PineRunRequest validator runs first inside the command body.
    with pytest.raises((ValueError, Exception)) as ei:
        _run_async(run(source=_TRIVIAL_SRC))
    # Either the Pydantic ValidationError or the wrapped ValueError; the
    # body should NOT have reached the PineCompilerNotYetAvailableError.
    cls_name = type(ei.value).__name__
    assert cls_name in ("ValueError", "ValidationError")


def test_run_provider_without_symbol_raises_validation_error():
    from openbb_pine.routers.run_router import run

    with pytest.raises((ValueError, Exception)) as ei:
        _run_async(run(source=_TRIVIAL_SRC, provider="fmp"))
    cls_name = type(ei.value).__name__
    assert cls_name in ("ValueError", "ValidationError")


def test_run_accepts_fmp_cached_provider():
    """``fmp_cached`` is in the Literal set and must reach the 503 path."""
    from openbb_pine.routers.run_router import (
        PineCompilerNotYetAvailableError,
        run,
    )

    with pytest.raises(PineCompilerNotYetAvailableError):
        _run_async(run(source=_TRIVIAL_SRC, provider="fmp_cached", symbol="AAPL"))


# ---------------------------------------------------------------------------
# /pine/strategies/run — 501 always
# ---------------------------------------------------------------------------


def test_strategies_run_raises_501_always_m1():
    from openbb_pine.routers.strategies_router import run

    with pytest.raises(PineStrategyNotYetImplementedError) as ei:
        _run_async(run(source=_TRIVIAL_SRC, provider="fmp", symbol="AAPL"))
    assert "M2" in str(ei.value)
    assert "0e9.5.6" in str(ei.value)


def test_strategies_run_501_even_with_byo_data():
    from openbb_pine.routers.strategies_router import run

    data = PineByoData(format="records", records=[{"close": 1.0}])
    with pytest.raises(PineStrategyNotYetImplementedError):
        _run_async(run(source=_TRIVIAL_SRC, data=data))


def test_strategies_run_501_even_with_no_provider_or_data():
    """M1 strategies router does not validate input shape; always 501."""
    from openbb_pine.routers.strategies_router import run

    with pytest.raises(PineStrategyNotYetImplementedError):
        _run_async(run(source=_TRIVIAL_SRC))


def test_strategies_run_501_carries_strategy_params():
    """`strategy_params` accepted in OpenAPI schema; payload doesn't change M1 behavior."""
    from openbb_pine.routers.strategies_router import run

    with pytest.raises(PineStrategyNotYetImplementedError):
        _run_async(
            run(
                source=_TRIVIAL_SRC,
                provider="fmp",
                symbol="AAPL",
                strategy_params={"initial_capital": 100_000},
            )
        )


# ---------------------------------------------------------------------------
# Route registration — OpenAPI surface locks
# ---------------------------------------------------------------------------


def test_run_router_registers_run_route():
    from openbb_pine.routers.run_router import router

    paths = {r.path for r in router.api_router.routes}
    assert "/run" in paths


def test_strategies_router_registers_run_route_under_strategies():
    from openbb_pine.routers.strategies_router import router

    paths = {r.path for r in router.api_router.routes}
    assert "/strategies/run" in paths


def test_pine_compiler_not_yet_available_subclasses_pine_error():
    """Middleware-serializable — subclasses PineError (and so OpenBBError)."""
    from openbb_pine.errors import PineError
    from openbb_pine.routers.run_router import PineCompilerNotYetAvailableError

    assert issubclass(PineCompilerNotYetAvailableError, PineError)
