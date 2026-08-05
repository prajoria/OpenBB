"""Playwright workspace driver (B6, #1728).

Design spec: docs/superpowers/specs/2026-08-01-browser-test-harness-design.md §5.2

Two attach mechanisms (P0-1 fix from spec review):

- **persistent-context (default)** — ``chromium.launch_persistent_context`` against
  ``~/.openbb_browser_test_harness/chrome_profile/``. First-run opens a browser
  for the user to log in to pro.openbb.co; auth persists across runs via cookies.
- **cdp-attach** — user launches Chrome with ``--remote-debugging-port=9222``;
  driver calls ``chromium.connect_over_cdp("http://127.0.0.1:9222")``. Driver does
  not manage the browser lifecycle.

**Screenshot policy (P1-4):** ``page.screenshot()`` only — never OS-level capture.
Browser chrome (tab title, URL bar, taskbar) is outside the frame by construction.
Each screenshot's SHA-256 is recorded in ``StepResult.screenshot_sha256`` for
future baseline-diff (P2-10).

**Import guard:** Playwright is an optional dependency (extras=[workspace]). If
someone imports this module without playwright installed, they get a clear
``ImportError`` rather than a mysterious NameError at runtime.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..redact import assert_screenshot_clean
from ..selectors import WidgetSelector, selector_for_endpoint
from ..steps import ActionKind, Step, StepResult

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page, Playwright


class WorkspaceDriverError(RuntimeError):
    """Raised on setup or mode-selection failures."""


def _default_profile_dir() -> Path:
    """Chrome profile lives under ~/.openbb_browser_test_harness/chrome_profile/.

    Matches the ``portfolio_export`` chrome profile pattern from CLAUDE.md so
    users have a single conceptual location for browser state.
    """
    return Path.home() / ".openbb_browser_test_harness" / "chrome_profile"


def _pick_random_port() -> int:
    """Ask the kernel for a free ephemeral 127.0.0.1 port.

    Uses the classic ``bind((127.0.0.1, 0))`` trick so concurrent workspace
    runs never collide with each other, and never collide with a manual
    ``openbb.sh api`` session on the fixed port 8000. See #1789.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class WorkspaceDriver:
    """Playwright driver for the OpenBB Workspace UI at pro.openbb.co.

    Usage::

        driver = WorkspaceDriver(mode="persistent-context")
        await driver.setup()   # prompts user for first-run login if needed
        for step in story.steps:
            result = await driver.run_step(step)
        await driver.teardown()
    """

    mode: str = "persistent-context"  # or "cdp-attach"
    workspace_url: str = "https://pro.openbb.co"
    cdp_endpoint: str = "http://127.0.0.1:9222"
    profile_dir: Path = field(default_factory=_default_profile_dir)
    screenshots_dir: Path | None = None  # if None, screenshots aren't saved
    headless: bool = False  # persistent-context defaults to visible for login

    #: If None, spawn a fresh uvicorn on a random ephemeral 127.0.0.1 port
    #: (#1789). If set, attach to an existing backend.
    backend_url: str | None = None
    #: Timeout for the backend readiness probe (seconds).
    backend_readiness_timeout_s: float = 60.0
    #: Timeout for each step (currently informational, mirrors standalone).
    step_timeout_s: float = 10.0

    # Populated in setup()
    _playwright: Playwright | None = field(default=None, init=False, repr=False)
    _context: BrowserContext | None = field(default=None, init=False, repr=False)
    _page: Page | None = field(default=None, init=False, repr=False)
    _owns_context: bool = field(default=False, init=False, repr=False)
    #: True iff setup() spawned the backend (so teardown() must kill it).
    _spawn_backend: bool = field(default=False, init=False, repr=False)
    _backend_proc: asyncio.subprocess.Process | None = field(
        default=None, init=False, repr=False
    )
    _resolved_backend_url: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Record spawn-vs-attach mode at construction (#1789)."""
        self._spawn_backend = self.backend_url is None
        self._resolved_backend_url = self.backend_url

    async def _spawn_widget_backend(self) -> str:
        """Spawn uvicorn on a random ephemeral port; return the base URL.

        Polls ``/widgets.json`` for up to ``backend_readiness_timeout_s``.
        """
        import httpx  # local import: httpx is a runtime dep of the harness

        port = _pick_random_port()
        base_url = f"http://127.0.0.1:{port}"
        child_env = os.environ.copy()
        child_env.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")
        self._backend_proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "uvicorn",
            "openbb_portfolio_intel.widget_backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
            env=child_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        deadline = time.monotonic() + self.backend_readiness_timeout_s
        async with httpx.AsyncClient(base_url=base_url, timeout=2.0) as client:
            while time.monotonic() < deadline:
                if self._backend_proc.returncode is not None:
                    raise WorkspaceDriverError(
                        f"widget_backend exited with code "
                        f"{self._backend_proc.returncode} during setup."
                    )
                try:
                    resp = await client.get("/widgets.json")
                    if resp.status_code == 200:
                        return base_url
                except (httpx.ConnectError, httpx.RemoteProtocolError):
                    pass
                await asyncio.sleep(0.2)
        raise WorkspaceDriverError(
            f"widget_backend did not become ready in "
            f"{self.backend_readiness_timeout_s}s (port={port})"
        )

    async def setup(self) -> None:
        """Attach to Chromium via the chosen mechanism.

        For persistent-context mode: opens a browser window; on first run the
        user must log in to Workspace, then rerun. Cookies persist for future
        runs.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise WorkspaceDriverError(
                "Playwright not installed. Install harness with the workspace "
                "extra: `pip install -e "
                "openbb_platform/tools/browser_test_harness/[workspace]` "
                "and then `playwright install chromium`."
            ) from exc

        self._playwright = await async_playwright().start()

        # Resolve backend_url — spawn a fresh uvicorn on a random port if the
        # caller did not provide one (#1789). Attach mode otherwise.
        if self._spawn_backend:
            self._resolved_backend_url = await self._spawn_widget_backend()

        if self.mode == "persistent-context":
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
            )
            self._owns_context = True
        elif self.mode == "cdp-attach":
            browser = await self._playwright.chromium.connect_over_cdp(
                self.cdp_endpoint
            )
            if not browser.contexts:
                raise WorkspaceDriverError(
                    "CDP attach: no browser contexts found. Ensure Chrome is "
                    f"running with --remote-debugging-port at {self.cdp_endpoint}."
                )
            self._context = browser.contexts[0]
            self._owns_context = False
        else:
            raise WorkspaceDriverError(
                f"Unknown mode {self.mode!r} — use 'persistent-context' or 'cdp-attach'."
            )

        # Open a page and navigate to Workspace, appending backend_url so the
        # Workspace UI knows where to send widget requests (#1789).
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        target_url = self.workspace_url
        if self._resolved_backend_url:
            sep = "&" if "?" in target_url else "?"
            target_url = (
                f"{target_url}{sep}backend_url={self._resolved_backend_url}"
            )
        await self._page.goto(target_url, wait_until="load")
        # Wait for the widget grid selector, or fall through after 5s — the
        # grid may not exist on every route (e.g. login redirect page).
        import contextlib

        with contextlib.suppress(Exception):
            await self._page.wait_for_selector(
                '[data-testid="widget-grid"]', timeout=5000
            )

    async def teardown(self) -> None:
        """Close the page/context if we own them; otherwise leave them alive.

        In cdp-attach mode the user's browser keeps running.
        """
        if self._context is not None and self._owns_context:
            try:
                await self._context.close()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
        if self._playwright is not None:
            await self._playwright.stop()
        # Terminate the spawned uvicorn if we own it (#1789).
        if self._spawn_backend and self._backend_proc is not None:
            if self._backend_proc.returncode is None:
                try:
                    self._backend_proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(self._backend_proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._backend_proc.kill()
                    await self._backend_proc.wait()
        self._backend_proc = None
        self._context = None
        self._page = None
        self._playwright = None
        self._owns_context = False

    async def run_step(self, step: Step) -> StepResult:
        """Execute one step against the live Workspace UI.

        Screenshots the page, computes SHA-256, redacts the path, then
        (for steps with an endpoint) uses the selector graph (B10, #1735)
        to turn ``widget_visible`` and ``not_blank`` from ``"unverified"``
        sentinels into REAL UI assertions:

        - ``widget_visible``: container ``[data-widget-id="<id>"]`` is
          attached AND ``bounding_box().height > 0``.
        - ``not_blank``: at least one type-appropriate content selector
          resolves to a locator with non-empty ``innerText`` OR non-zero
          bounding-box area (charts/canvases are legitimately empty-text).

        Steps with no endpoint (NAVIGATE / SCREENSHOT chrome steps) fall
        back to page-level "did we load" observations.
        """
        if self._page is None:
            return StepResult(
                step_id=step.id,
                ok=False,
                duration_ms=0,
                screenshot_path=None,
                observations={},
                error="workspace_not_setup",
            )

        start = time.monotonic()

        # Screenshot capture — page.screenshot() only, no OS-level grab.
        screenshot_path: str | None = None
        screenshot_sha: str | None = None
        if self.screenshots_dir is not None:
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
            out = self.screenshots_dir / step.resolved_screenshot_name
            # PII guard on the OUTPUT PATH before we let Playwright write it.
            assert_screenshot_clean(out)
            png_bytes = await self._page.screenshot(
                path=str(out),
                type="png",
                full_page=False,  # viewport only per P1-4 (page-scoped)
            )
            screenshot_path = str(out)
            screenshot_sha = hashlib.sha256(png_bytes).hexdigest()
        else:
            # No output dir — capture bytes to compute SHA but don't save.
            png_bytes = await self._page.screenshot(
                type="png",
                full_page=False,
            )
            screenshot_sha = hashlib.sha256(png_bytes).hexdigest()

        # Selector-graph assertions (B10, #1735).
        widget_visible: object = "n/a"
        not_blank: object = "n/a"
        selector: WidgetSelector | None = None
        if step.endpoint:
            selector = selector_for_endpoint(step.endpoint)
        if selector is not None:
            widget_visible = await self._is_widget_visible(selector)
            if widget_visible is True:
                not_blank = await self._is_widget_not_blank(selector)

        duration_ms = int((time.monotonic() - start) * 1000)

        observations: dict[str, object] = {
            "widget_visible": widget_visible,
            "not_blank": not_blank,
            "screenshot_bytes": len(png_bytes),
        }
        if selector is not None:
            observations["container_selector"] = selector.container
            observations["widget_type"] = selector.widget_type
        if step.action == ActionKind.NAVIGATE:
            observations["current_url"] = self._page.url

        # An ASSERT-kind step in workspace mode gates ok on widget_visible.
        # OBSERVE / NAVIGATE / SCREENSHOT still record the observation but
        # don't fail on it (the standalone driver already gated the shape).
        ok = True
        error: str | None = None
        if step.action == ActionKind.ASSERT and selector is not None:
            if widget_visible is not True:
                ok = False
                error = f"widget_not_visible: selector={selector.container}"
            elif not_blank is not True:
                ok = False
                error = (
                    f"widget_blank: selector={selector.container} "
                    f"type={selector.widget_type}"
                )

        return StepResult(
            step_id=step.id,
            ok=ok,
            duration_ms=duration_ms,
            screenshot_path=screenshot_path,
            observations=observations,
            error=error,
            screenshot_sha256=screenshot_sha,
        )

    async def _is_widget_visible(self, selector: WidgetSelector) -> bool:
        """Container ``[data-widget-id="..."]`` is attached and has size.

        Uses ``locator.count()`` to survive missing containers without
        throwing (Playwright's ``bounding_box()`` on an absent locator
        raises). We return ``False`` (not None) so downstream logic is
        boolean-clean; the observation dict still carries the selector
        string for diagnosis.
        """
        assert self._page is not None
        loc = self._page.locator(selector.container).first
        try:
            n = await loc.count()
        except Exception:  # noqa: BLE001 — treat any playwright error as "not visible"
            return False
        if n == 0:
            return False
        try:
            box = await loc.bounding_box()
        except Exception:  # noqa: BLE001
            return False
        return bool(box and box.get("height", 0) > 0 and box.get("width", 0) > 0)

    async def _is_widget_not_blank(self, selector: WidgetSelector) -> bool:
        """Content non-blank per widget type.

        For each candidate content selector (rooted inside the container),
        we consider the widget non-blank if EITHER:
        - text mode: ``innerText.strip()`` is non-empty (tables / markdown /
          metrics), OR
        - visual mode: ``bounding_box().height > 0`` on a canvas / svg
          (charts legitimately have empty text but a visible frame).

        Returns True on the first candidate that satisfies either mode.
        """
        assert self._page is not None
        container = self._page.locator(selector.container).first
        for content_sel in selector.content_candidates:
            child = container.locator(content_sel).first
            try:
                if await child.count() == 0:
                    continue
            except Exception:  # noqa: BLE001
                continue
            # Text mode
            try:
                text = (await child.inner_text()).strip()
            except Exception:  # noqa: BLE001
                text = ""
            if text:
                return True
            # Visual mode
            try:
                box = await child.bounding_box()
            except Exception:  # noqa: BLE001
                box = None
            if box and box.get("height", 0) > 0:
                return True
        return False
