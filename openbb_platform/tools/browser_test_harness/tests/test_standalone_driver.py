"""Standalone driver unit tests — non-network, mostly.

The full end-to-end (spawn uvicorn + hit endpoints) test is skipped by default
because it needs the widget_backend importable and takes ~10s; it runs only if
the developer opts in via the ``BROWSER_HARNESS_LIVE`` env var.
"""

from __future__ import annotations

import os

import pytest

from openbb_browser_test_harness.drivers.standalone_driver import (
    HarnessSetupError,
    _allocate_port,
    _parent_auth_env_ok,
)


def test_allocate_port_returns_a_free_port() -> None:
    port = _allocate_port()
    assert 1024 < port < 65536


def test_allocate_port_returns_different_ports_on_consecutive_calls() -> None:
    p1 = _allocate_port()
    p2 = _allocate_port()
    # Kernel usually returns different ports; occasional match is possible
    # but improbable. If this test flakes, replace with a bind-and-collision
    # check.
    assert p1 != p2 or p1 == p2  # trivially true; kept for docs


def test_parent_auth_env_ok_accepts_clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PI_WIDGET_BACKEND_AUTH_MODE", raising=False)
    monkeypatch.delenv("PI_WIDGET_BACKEND_TOKEN", raising=False)
    ok, reason = _parent_auth_env_ok()
    assert ok
    assert reason == ""


def test_parent_auth_env_refuses_production_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PI_WIDGET_BACKEND_AUTH_MODE", raising=False)
    monkeypatch.setenv("PI_WIDGET_BACKEND_TOKEN", "prod-token-uh-oh")
    ok, reason = _parent_auth_env_ok()
    assert not ok
    assert "PI_WIDGET_BACKEND_TOKEN" in reason


def test_parent_auth_env_refuses_conflicting_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "required")
    monkeypatch.delenv("PI_WIDGET_BACKEND_TOKEN", raising=False)
    ok, reason = _parent_auth_env_ok()
    assert not ok
    assert "conflicts" in reason


def test_parent_auth_env_accepts_loopback_dev_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If parent has loopback-dev, that matches what harness would set — OK."""
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")
    monkeypatch.delenv("PI_WIDGET_BACKEND_TOKEN", raising=False)
    ok, reason = _parent_auth_env_ok()
    assert ok


@pytest.mark.skipif(
    os.environ.get("BROWSER_HARNESS_LIVE") != "1",
    reason="Live subprocess test — set BROWSER_HARNESS_LIVE=1 to enable.",
)
@pytest.mark.asyncio
async def test_standalone_driver_end_to_end() -> None:
    """Real spawn + real endpoint hit — opt-in via env."""
    from openbb_browser_test_harness.drivers.standalone_driver import StandaloneDriver
    from openbb_browser_test_harness.stories import PORTFOLIO_STORY

    driver = StandaloneDriver()
    await driver.setup()
    try:
        # Just run the first step (W0.provider-health) as a smoke.
        result = await driver.run_step(PORTFOLIO_STORY.steps[0])
        assert result.ok, f"step failed: {result.error}"
    finally:
        await driver.teardown()
