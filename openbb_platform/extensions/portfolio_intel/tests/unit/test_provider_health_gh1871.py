"""Regression tests for #1871 — provider_health must be async.

Root cause (see #1871): ``provider_health`` was a **sync** ``def`` route that
called ``asyncio.run(asyncio.wait_for(asyncio.gather(_probe_track(...))))``.
Under uvicorn (a running event loop) ``asyncio.run`` raises ``RuntimeError``
*before* the gather runs, so:

- the two ``_probe_track(...)`` coroutines are created but never awaited
  (``RuntimeWarning: coroutine '_probe_track' was never awaited``), and
- the endpoint silently falls back to the cold-cache "unknown" strip on
  every call — the health widget is non-functional on the real server.

The bug was invisible to the existing suite because ``TestClient`` runs a sync
route in a threadpool worker that has *no* running loop, so ``asyncio.run``
works there ("mocks agree with themselves", CLAUDE.md R1/R2). These tests
exercise the endpoint the way uvicorn does — awaited on a running event loop —
so they fail on the pre-fix sync code and pass on the async fix.
"""

from __future__ import annotations

import asyncio
import inspect
import os

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import pytest  # noqa: E402
from openbb_portfolio_intel.providers.probe import (  # noqa: E402
    register_prober,
    unregister_prober,
)
from openbb_portfolio_intel.widget_backend import (  # noqa: E402
    widgets_endpoints as we,
)
from starlette.requests import Request  # noqa: E402


def _stub_request() -> Request:
    """Minimal GET Request. In loopback-dev auth mode the request body/headers
    are never inspected, so an empty scope is sufficient.
    """
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/pi/health/providers",
            "headers": [],
            "query_string": b"",
        }
    )


@pytest.fixture(autouse=True)
def _clear_state():
    we._PROVIDER_HEALTH_CACHE.clear()
    we._TIER_IN_USE.clear()
    yield
    we._PROVIDER_HEALTH_CACHE.clear()
    we._TIER_IN_USE.clear()


def test_provider_health_is_coroutine_function() -> None:
    """#1871 fix is structural: the endpoint MUST be an async coroutine so it
    awaits the probes on the running loop instead of calling asyncio.run()
    inside it. Fails on the pre-fix ``def`` route.
    """
    assert inspect.iscoroutinefunction(we.provider_health), (
        "provider_health must be `async def` (see #1871) — a sync def forces "
        "asyncio.run() inside uvicorn's running loop, which raises and leaks "
        "the _probe_track coroutines."
    )


def test_provider_health_awaited_on_running_loop_renders_registered_status() -> None:
    """Awaited on a running event loop (as uvicorn serves it), the endpoint must
    actually run the probes and render a registered tier's real status — not the
    cold-cache 'unknown' fallback.

    Reverse-verify: under the pre-fix sync ``def`` code ``provider_health(req)``
    returns a ``str`` and ``asyncio.run(<str>)`` raises ``ValueError: a
    coroutine was expected`` — this test errors. Under the async fix it returns
    the markdown with ``fmp_cached`` marked healthy (● badge).
    """

    async def _fast_ok() -> None:
        return None

    register_prober("fmp_cached", _fast_ok)
    try:
        body = asyncio.run(we.provider_health(_stub_request()))
    finally:
        unregister_prober("fmp_cached")

    assert isinstance(body, str)
    assert "● fmp_cached" in body, (
        "fmp_cached should render healthy (● badge) after its prober ran — "
        f"got cold-cache/unknown instead. Body:\n{body}"
    )
