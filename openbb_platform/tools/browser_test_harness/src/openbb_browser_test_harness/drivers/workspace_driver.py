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

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..redact import assert_screenshot_clean
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

    # Populated in setup()
    _playwright: "Playwright | None" = field(default=None, init=False, repr=False)
    _context: "BrowserContext | None" = field(default=None, init=False, repr=False)
    _page: "Page | None" = field(default=None, init=False, repr=False)
    _owns_context: bool = field(default=False, init=False, repr=False)

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

        # Open a page and navigate to Workspace.
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        await self._page.goto(self.workspace_url, wait_until="load")

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
        self._context = None
        self._page = None
        self._playwright = None
        self._owns_context = False

    async def run_step(self, step: Step) -> StepResult:
        """Execute one step against the live Workspace UI.

        This is a MINIMAL first-pass implementation. It:
        - Screenshots the current page state
        - Records the SHA-256 of the screenshot bytes (P2-10)
        - Redacts the screenshot filesystem path (P1-4)
        - Reports widget_visible and not_blank observations honestly
          (currently as "unverified" pending selector work in a follow-up)

        Real tab-navigation + widget-selector logic requires a Workspace
        selector map that varies by Workspace version. Filed as a follow-up
        so the harness ships useful today (screenshots per step) even before
        the full selector graph exists.
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

        duration_ms = int((time.monotonic() - start) * 1000)

        # Observations — honest about what we can and can't verify.
        observations: dict[str, object] = {
            "widget_visible": "unverified",
            "not_blank": "unverified",
            "screenshot_bytes": len(png_bytes),
        }
        if step.action == ActionKind.NAVIGATE:
            observations["current_url"] = self._page.url

        # ok=True because we successfully captured the frame. Real
        # widget-presence assertion is follow-up work (Workspace selector map).
        return StepResult(
            step_id=step.id,
            ok=True,
            duration_ms=duration_ms,
            screenshot_path=screenshot_path,
            observations=observations,
            error=None,
            screenshot_sha256=screenshot_sha,
        )
