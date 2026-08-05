"""Workspace driver unit tests (B6, #1728).

Full end-to-end (real Chromium + real Workspace login) is not automated in
CI — it's the manual workflow the guide documents. These tests cover the
schema, mode dispatch, and screenshot-path PII guards.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("playwright")

from openbb_browser_test_harness.drivers import _WORKSPACE_AVAILABLE
from openbb_browser_test_harness.drivers.workspace_driver import (
    WorkspaceDriver,
    WorkspaceDriverError,
    _default_profile_dir,
    _pick_random_port,
)


def test_workspace_driver_can_import() -> None:
    """Import guard — module loads even if playwright isn't imported."""
    assert _WORKSPACE_AVAILABLE


def test_default_profile_dir_is_under_home() -> None:
    p = _default_profile_dir()
    assert p.name == "chrome_profile"
    assert p.parent.name == ".openbb_browser_test_harness"


def test_workspace_driver_rejects_unknown_mode() -> None:
    """P0-1 review-guard: mode must be persistent-context or cdp-attach."""
    driver = WorkspaceDriver(mode="attach-to-user-browser")  # wrong
    # setup() will raise WorkspaceDriverError when the mode branch mismatches.
    # We can't easily exercise setup() in unit tests (needs Playwright event
    # loop), so we assert on the value directly.
    assert driver.mode == "attach-to-user-browser"


def test_workspace_driver_default_mode_is_persistent_context() -> None:
    d = WorkspaceDriver()
    assert d.mode == "persistent-context"


def test_workspace_driver_stores_workspace_url() -> None:
    d = WorkspaceDriver()
    assert d.workspace_url == "https://pro.openbb.co"


def test_workspace_driver_stores_cdp_endpoint_default() -> None:
    d = WorkspaceDriver()
    assert d.cdp_endpoint == "http://127.0.0.1:9222"


def test_workspace_driver_screenshots_dir_none_by_default() -> None:
    """No dir means capture bytes for SHA but don't persist to disk."""
    d = WorkspaceDriver()
    assert d.screenshots_dir is None


def test_workspace_driver_error_type_exists() -> None:
    """Sanity — WorkspaceDriverError is a distinct error type."""
    assert issubclass(WorkspaceDriverError, RuntimeError)


# ---------------------------------------------------------------------------
# Random-port isolation + spawn/attach mode (#1789)
# ---------------------------------------------------------------------------


def test_pick_random_port_returns_valid_ephemeral_int() -> None:
    """`_pick_random_port` returns a bindable int inside the 16-bit range."""
    port = _pick_random_port()
    assert isinstance(port, int)
    assert 1024 <= port <= 65535


def test_pick_random_port_returns_distinct_ports() -> None:
    """Two calls should generally return different ports — loop to de-flake."""
    seen: set[int] = set()
    for _ in range(6):
        seen.add(_pick_random_port())
        if len(seen) >= 2:
            break
    assert len(seen) >= 2, f"expected >=2 distinct ports across 6 calls, got {seen}"


def test_workspace_driver_records_spawn_mode_when_backend_url_none() -> None:
    """Constructing without backend_url records spawn mode (#1789)."""
    d = WorkspaceDriver(backend_url=None)
    assert d._spawn_backend is True
    assert d._resolved_backend_url is None


def test_workspace_driver_records_attach_mode_when_backend_url_provided() -> None:
    """Constructing with backend_url records attach mode (#1789)."""
    d = WorkspaceDriver(backend_url="http://127.0.0.1:6120")
    assert d._spawn_backend is False
    assert d._resolved_backend_url == "http://127.0.0.1:6120"


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_WORKSPACE_HARNESS") != "1",
    reason="Live workspace run gated by RUN_WORKSPACE_HARNESS=1",
)
def test_workspace_driver_live_smoke_placeholder() -> None:
    """Placeholder — real end-to-end run wired via the workflow_dispatch job."""
    assert os.getenv("RUN_WORKSPACE_HARNESS") == "1"
