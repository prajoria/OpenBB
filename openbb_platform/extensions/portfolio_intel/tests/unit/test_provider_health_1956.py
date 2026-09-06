"""Tests for #1956 — Provider Health strip never populated (all tiers '?').

Root cause: :func:`register_prober` was only ever called from tests, so on the
running server the prober registry was empty and every tier fell to
``probe_tier``'s ``prober is None`` branch → an instant
``probe_failed_cold_cache`` 'unknown'. The strip therefore never showed real
liveness — and this was NOT a too-tight-timeout problem (with no prober there
is nothing to time out).

Fix under test:
  * :mod:`openbb_portfolio_intel.providers.health_probers` supplies cheap,
    quota-free HTTP-``HEAD`` reachability probers, one per tier.
  * ``_app._register_health_probers`` registers them from the FastAPI lifespan
    (real server only — bare ``TestClient(app)`` does not run lifespan, so unit
    tests stay hermetic).
  * ``provider_health``'s inline cold-cache probe budget was widened
    (0.4s/0.5s → 2.5s/3.0s) so real HEADs can complete and populate the cache.

Every test here is hermetic: reachability probers are exercised with an
injected fake httpx client, so no test touches the network.
"""

from __future__ import annotations

import asyncio
import inspect
import os

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import httpx  # noqa: E402
import pytest  # noqa: E402
from openbb_portfolio_intel.providers import (
    health_probers as hp,  # noqa: E402
    probe as probe_mod,  # noqa: E402
)
from openbb_portfolio_intel.providers.probe import (  # noqa: E402
    probe_tier,
    register_prober,
    unregister_prober,
)
from openbb_portfolio_intel.widget_backend import (  # noqa: E402
    _app as app_mod,  # noqa: E402
    widgets_endpoints as we,
)
from starlette.requests import Request  # noqa: E402

# ---------------------------------------------------------------------------
# Fakes / helpers (no network)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.request = httpx.Request("HEAD", "https://probe.test")


class _FakeClient:
    """Async-context httpx stand-in whose ``head`` is deterministic."""

    def __init__(self, *, status_code: int | None = None, exc: Exception | None = None):
        self._status = status_code
        self._exc = exc

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_a: object) -> bool:
        return False

    async def head(self, _url: str) -> _FakeResp:
        if self._exc is not None:
            raise self._exc
        assert self._status is not None
        return _FakeResp(self._status)


def _factory(*, status_code: int | None = None, exc: Exception | None = None):
    def _make() -> _FakeClient:
        return _FakeClient(status_code=status_code, exc=exc)

    return _make


def _stub_request() -> Request:
    """Minimal GET request; loopback-dev auth ignores headers/body."""
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
def _clean_state():
    """Keep the prober registry + health cache clean so a leaked real-network
    prober can never bleed into (or slow down) another test file.
    """
    for t in list(hp.BASE_URL_FOR_TIER):
        unregister_prober(t)
    we._PROVIDER_HEALTH_CACHE.clear()
    yield
    for t in list(hp.BASE_URL_FOR_TIER):
        unregister_prober(t)
    we._PROVIDER_HEALTH_CACHE.clear()


# ---------------------------------------------------------------------------
# Prober map / registration
# ---------------------------------------------------------------------------


def test_base_url_map_covers_all_track_tiers() -> None:
    """Drift guard: every tier in either fallback track has a probe URL.

    Reverse-verify: delete any key from BASE_URL_FOR_TIER and this fails,
    proving the assertion discriminates a real gap.
    """
    missing = hp.all_probeable_tiers() - set(hp.BASE_URL_FOR_TIER)
    assert not missing, f"tiers with no reachability probe URL: {sorted(missing)}"


def test_register_default_probers_registers_every_mapped_tier() -> None:
    """register_default_probers wires one async prober per mapped tier."""
    captured: dict[str, object] = {}
    returned = hp.register_default_probers(
        register=lambda tier, prober: captured.__setitem__(tier, prober)
    )
    assert set(returned) == set(hp.BASE_URL_FOR_TIER)
    assert set(captured) == set(hp.BASE_URL_FOR_TIER)
    for prober in captured.values():
        assert inspect.iscoroutinefunction(prober), "prober must be an async callable"


# ---------------------------------------------------------------------------
# Reachability prober semantics (via probe_tier, fake client — no network)
# ---------------------------------------------------------------------------


def _probe_with(status_code=None, exc=None):
    prober = hp.make_reachability_prober(
        "https://probe.test", client_factory=_factory(status_code=status_code, exc=exc)
    )
    register_prober("probe_tier_under_test", prober)
    try:
        return asyncio.run(probe_tier("probe_tier_under_test"))
    finally:
        unregister_prober("probe_tier_under_test")


def test_reachability_prober_healthy_on_2xx() -> None:
    h = _probe_with(status_code=200)
    assert h.status == "healthy", h


def test_reachability_prober_healthy_on_4xx_reachable() -> None:
    """A 4xx means the host answered → reachable → healthy (liveness, not
    authz). Reverse-verify: if the prober raised on any non-2xx, this would be
    'down' — so this test discriminates the 'any response = reachable' rule.
    """
    h = _probe_with(status_code=403)
    assert h.status == "healthy", h


def test_reachability_prober_down_http_5xx_on_5xx() -> None:
    h = _probe_with(status_code=503)
    assert h.status == "down", h
    assert h.note == "http_5xx", h


def test_reachability_prober_down_on_connect_error() -> None:
    h = _probe_with(exc=httpx.ConnectError("connection refused"))
    assert h.status == "down", h
    # classified from the allowlist, never a raw string
    assert h.note in {"network", "unknown_error", "timeout"}, h


# ---------------------------------------------------------------------------
# Lifespan wiring + hermeticity guard
# ---------------------------------------------------------------------------


def test_register_health_probers_populates_the_real_registry() -> None:
    """The lifespan helper registers a real prober for every mapped tier.

    Reverse-verify: stub register_default_probers to a no-op and this fails,
    proving the helper (not some ambient state) does the wiring.
    """
    for t in list(hp.BASE_URL_FOR_TIER):
        unregister_prober(t)
    app_mod._register_health_probers()
    for t in hp.BASE_URL_FOR_TIER:
        assert t in probe_mod._PROBER_REGISTRY, f"{t} prober not registered"


def test_bare_testclient_does_not_register_probers() -> None:
    """Hermeticity guard (#1956): importing the app + using a bare
    ``TestClient(app)`` must NOT auto-register real network probers, because
    lifespan only runs under uvicorn / ``with TestClient(app)``. If a future
    change moves prober registration to import time, this fails — and the whole
    unit suite would start hitting the network.
    """
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from openbb_portfolio_intel.widget_backend.main import app  # noqa: PLC0415

    for t in list(hp.BASE_URL_FOR_TIER):
        unregister_prober(t)
    client = TestClient(app)  # bare — no `with`, so lifespan does not run
    resp = client.get("/pi/health/providers")
    assert resp.status_code == 200
    leaked = set(hp.BASE_URL_FOR_TIER) & set(probe_mod._PROBER_REGISTRY)
    assert not leaked, f"probers auto-registered without lifespan: {sorted(leaked)}"


# ---------------------------------------------------------------------------
# Endpoint renders real status once probers exist
# ---------------------------------------------------------------------------


def test_provider_health_renders_healthy_when_probers_registered() -> None:
    """With reachability probers registered (fake-fast client), the endpoint
    renders a live ● status instead of the '?' cold-cache strip.

    This is the load-bearing #1956 assertion: it FAILS on the pre-fix state
    (empty registry → every tier '?'), and PASSES once probers are registered
    and the endpoint probes them inline within the widened budget.
    """
    we._PROVIDER_HEALTH_CACHE.clear()
    for tier in hp.BASE_URL_FOR_TIER:
        register_prober(
            tier,
            hp.make_reachability_prober(
                "https://probe.test", client_factory=_factory(status_code=200)
            ),
        )
    try:
        body = asyncio.run(we.provider_health(_stub_request()))
    finally:
        for tier in hp.BASE_URL_FOR_TIER:
            unregister_prober(tier)
        we._PROVIDER_HEALTH_CACHE.clear()

    assert isinstance(body, list)
    row = next(r for r in body if r["tier"] == "fmp_cached")
    assert "healthy" in row["status"], f"expected fmp_cached healthy; got:\n{row}"
    assert "probe_failed_cold_cache" not in row["note"], "still rendering cold-cache"


def test_provider_health_5xx_tier_renders_down_not_unknown() -> None:
    """A tier whose host returns 5xx renders ✕ (down) — distinct from the '?'
    unknown state — proving the strip reflects real probe outcomes, not just
    'registered vs not'.
    """
    we._PROVIDER_HEALTH_CACHE.clear()
    for tier in hp.BASE_URL_FOR_TIER:
        register_prober(
            tier,
            hp.make_reachability_prober(
                "https://probe.test", client_factory=_factory(status_code=503)
            ),
        )
    try:
        body = asyncio.run(we.provider_health(_stub_request()))
    finally:
        for tier in hp.BASE_URL_FOR_TIER:
            unregister_prober(tier)
        we._PROVIDER_HEALTH_CACHE.clear()

    row = next(r for r in body if r["tier"] == "fmp_cached")
    assert "down" in row["status"], f"expected fmp_cached down; got:\n{row}"
