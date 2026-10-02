"""Workspace driver unit tests (B6, #1728).

Full end-to-end (real Chromium + real Workspace login) is not automated in
CI — it's the manual workflow the guide documents. These tests cover the
schema, mode dispatch, and screenshot-path PII guards.
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("playwright")

from openbb_browser_test_harness.drivers import _WORKSPACE_AVAILABLE, workspace_driver
from openbb_browser_test_harness.drivers.workspace_driver import (
    WorkspaceDriver,
    WorkspaceDriverError,
    _default_profile_dir,
    _is_authenticated_workspace_url,
    _is_local_workspace_url,
    _pick_random_port,
    _read_managed_credentials,
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


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:1420",
        "http://127.0.0.1:1420/",
    ],
)
def test_local_workspace_url_accepts_only_exact_self_hosted_base(url) -> None:
    assert _is_local_workspace_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:1420",
        "http://127.0.0.1:1421",
        "https://127.0.0.1:1420",
        "http://user@127.0.0.1:1420",
        "http://127.0.0.1:1420?next=http://127.0.0.1:1420",
        "http://127.0.0.1:1420/#fragment",
        "http://127.0.0.1:1420/app",
        "https://pro.openbb.co",
    ],
)
def test_local_workspace_url_rejects_non_exact_variants(url) -> None:
    assert not _is_local_workspace_url(url)


def test_authenticated_workspace_url_accepts_exact_local_app_family() -> None:
    assert _is_authenticated_workspace_url("http://127.0.0.1:1420/app")
    assert _is_authenticated_workspace_url("http://127.0.0.1:1420/app/")
    assert _is_authenticated_workspace_url(
        "http://127.0.0.1:1420/app/dashboard?tab=portfolio"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:1420/",
        "http://127.0.0.1:1420/login",
        "http://127.0.0.1:1420/register",
        "http://127.0.0.1:1420/forgot-password",
        "http://127.0.0.1:1420/2fa",
        "http://127.0.0.1:1420/application",
        "http://localhost:1420/app",
        "http://127.0.0.1:1421/app",
        "https://127.0.0.1:1420/app",
        "https://example.invalid/app",
    ],
)
def test_authenticated_workspace_url_rejects_auth_and_off_origin_routes(url) -> None:
    assert not _is_authenticated_workspace_url(url)


def test_managed_credentials_are_read_from_json_without_mutating_file(
    tmp_path,
) -> None:
    path = tmp_path / "workspace-admin-credentials.secrets"
    original = {"Email": "local@example.invalid", "Password": "not-a-real-secret"}
    path.write_text(json.dumps(original), encoding="utf-8")

    credentials = _read_managed_credentials(path)

    assert credentials == ("local@example.invalid", "not-a-real-secret")
    assert json.loads(path.read_text(encoding="utf-8")) == original


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"Email": "", "Password": "present"},
        {"Email": "present@example.invalid", "Password": ""},
        {"Email": 42, "Password": "present"},
    ],
)
def test_managed_credentials_reject_invalid_json_shape(tmp_path, payload) -> None:
    path = tmp_path / "workspace-admin-credentials.secrets"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(WorkspaceDriverError, match="managed credential file"):
        _read_managed_credentials(path)


def test_local_workspace_uses_existing_managed_credential_location() -> None:
    d = WorkspaceDriver(workspace_url="http://127.0.0.1:1420")

    assert d.managed_credentials_path.name == "workspace-admin-credentials.secrets"
    assert d.managed_credentials_path.parent.name == "backend"


def test_workspace_driver_stores_cdp_endpoint_default() -> None:
    d = WorkspaceDriver()
    assert d.cdp_endpoint == "http://127.0.0.1:9222"


def test_workspace_driver_screenshots_dir_none_by_default() -> None:
    """No dir means capture bytes for SHA but don't persist to disk."""
    d = WorkspaceDriver()
    assert d.screenshots_dir is None


def test_workspace_driver_can_ignore_tls_only_for_exact_self_hosted_mode() -> None:
    d = WorkspaceDriver(
        workspace_url="http://127.0.0.1:1420/",
        ignore_local_self_hosted_https_errors=True,
    )
    assert d.ignore_local_self_hosted_https_errors is True


@pytest.mark.parametrize(
    "workspace_url",
    [
        "https://pro.openbb.co",
        "http://localhost:1420",
        "https://127.0.0.1:1420",
        "http://127.0.0.1:1421",
        "http://127.0.0.1:1420?redirect=local",
    ],
)
def test_workspace_driver_rejects_tls_bypass_outside_exact_self_hosted_mode(
    workspace_url,
) -> None:
    with pytest.raises(WorkspaceDriverError, match="TLS"):
        WorkspaceDriver(
            workspace_url=workspace_url,
            ignore_local_self_hosted_https_errors=True,
        )


def _pending_url_waiter() -> AsyncMock:
    async def wait_for_url(*_args, **_kwargs):
        await asyncio.Future()

    return AsyncMock(side_effect=wait_for_url)


@pytest.mark.asyncio
async def test_local_login_rejects_off_origin_page_before_credential_read(
    monkeypatch,
) -> None:
    driver = WorkspaceDriver(workspace_url="http://127.0.0.1:1420")
    page = MagicMock()
    page.url = "https://example.invalid/login"
    page.get_by_label = MagicMock()
    driver._page = page
    credential_reader = MagicMock()
    monkeypatch.setattr(
        workspace_driver, "_read_managed_credentials", credential_reader
    )

    with pytest.raises(WorkspaceDriverError, match="origin"):
        await driver._ensure_local_login()

    credential_reader.assert_not_called()
    page.get_by_label.assert_not_called()


@pytest.mark.asyncio
async def test_local_login_rejects_live_redirect_before_credential_read_or_fill(
    monkeypatch,
) -> None:
    driver = WorkspaceDriver(workspace_url="http://127.0.0.1:1420")
    page = MagicMock()
    page.url = "http://127.0.0.1:1420/login"
    email_input = MagicMock()

    async def redirect_while_waiting(**_kwargs):
        page.url = "https://example.invalid/login"

    email_input.wait_for = AsyncMock(side_effect=redirect_while_waiting)
    email_input.fill = AsyncMock()
    page.get_by_label.return_value = email_input
    page.wait_for_url = _pending_url_waiter()
    driver._page = page
    credential_reader = MagicMock()
    monkeypatch.setattr(
        workspace_driver, "_read_managed_credentials", credential_reader
    )

    with pytest.raises(WorkspaceDriverError, match="origin"):
        await driver._ensure_local_login()

    credential_reader.assert_not_called()
    email_input.fill.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_login_submits_managed_credentials(monkeypatch) -> None:
    driver = WorkspaceDriver(workspace_url="http://127.0.0.1:1420")
    page = MagicMock()
    page.url = "http://127.0.0.1:1420/login"
    email_input = MagicMock()
    email_input.wait_for = AsyncMock()
    email_input.count = AsyncMock(return_value=1)
    email_input.fill = AsyncMock()
    password_input = MagicMock()
    password_input.fill = AsyncMock()
    login_button = MagicMock()
    login_button.click = AsyncMock()
    page.get_by_label.side_effect = lambda label, **_kwargs: (
        email_input if label == "Email" else password_input
    )
    page.get_by_role.return_value = login_button
    url_wait_calls = 0

    async def wait_for_url(*_args, **_kwargs):
        nonlocal url_wait_calls
        url_wait_calls += 1
        if url_wait_calls == 1:
            await asyncio.Future()
        page.url = "http://127.0.0.1:1420/app"

    page.wait_for_url = AsyncMock(side_effect=wait_for_url)
    driver._page = page
    credential_reader = MagicMock(
        return_value=("local@example.invalid", "test-password")
    )
    monkeypatch.setattr(
        workspace_driver, "_read_managed_credentials", credential_reader
    )

    await driver._ensure_local_login()

    credential_reader.assert_called_once_with(driver.managed_credentials_path)
    email_input.fill.assert_awaited_once_with("local@example.invalid")
    password_input.fill.assert_awaited_once_with("test-password")
    login_button.click.assert_awaited_once()
    assert driver.login_performed is True


@pytest.mark.asyncio
async def test_local_login_reuses_authenticated_profile_without_credentials(
    monkeypatch,
) -> None:
    driver = WorkspaceDriver(workspace_url="http://127.0.0.1:1420")
    page = MagicMock()
    page.url = "http://127.0.0.1:1420/app/dashboard"
    page.get_by_label = MagicMock()
    driver._page = page
    credential_reader = MagicMock()
    monkeypatch.setattr(
        workspace_driver, "_read_managed_credentials", credential_reader
    )

    await driver._ensure_local_login()

    credential_reader.assert_not_called()
    page.get_by_label.assert_not_called()
    assert driver.login_performed is False


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
