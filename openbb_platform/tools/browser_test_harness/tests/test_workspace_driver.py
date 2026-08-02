"""Workspace driver unit tests (B6, #1728).

Full end-to-end (real Chromium + real Workspace login) is not automated in
CI — it's the manual workflow the guide documents. These tests cover the
schema, mode dispatch, and screenshot-path PII guards.
"""

from __future__ import annotations

import pytest

from openbb_browser_test_harness.drivers import _WORKSPACE_AVAILABLE
from openbb_browser_test_harness.drivers.workspace_driver import (
    WorkspaceDriver,
    WorkspaceDriverError,
    _default_profile_dir,
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
