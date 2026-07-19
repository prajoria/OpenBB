"""
Helpers for use inside recording modules.

These are optional utilities recordings can import to:
  * save the current page as an HTML snapshot (crawler-style capture)
  * save a screenshot alongside it
  * detect a logged-out state and pause for manual MFA / re-login,
    then continue the deterministic replay
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, TimeoutError as PWTimeoutError


_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(text: str, fallback: str = "page") -> str:
    text = _SLUG_RE.sub("_", text).strip("_")
    return text[:80] if text else fallback


def _default_name(page: Page) -> str:
    """Derive a filename slug from the current URL."""
    u = urlparse(page.url)
    parts = [u.netloc, u.path.rstrip("/").replace("/", "_")]
    return _slug("_".join(p for p in parts if p), fallback=f"page_{int(time.time())}")


def save_page_html(
    page: Page,
    download_dir: str | Path,
    name: str | None = None,
) -> str:
    """
    Save `page.content()` to `<download_dir>/<name>.html`.

    Returns the absolute path (str) of the file written.
    """
    dl = Path(download_dir)
    dl.mkdir(parents=True, exist_ok=True)
    fname = f"{name or _default_name(page)}.html"
    path = dl / fname
    path.write_text(page.content(), encoding="utf-8")
    return str(path)


def save_page_snapshot(
    page: Page,
    download_dir: str | Path,
    name: str | None = None,
    include_screenshot: bool = True,
    full_page: bool = True,
) -> list[str]:
    """
    Save the page as HTML (+ optional PNG screenshot + URL sidecar).

    Returns a list of absolute paths to every file written.
    """
    dl = Path(download_dir)
    dl.mkdir(parents=True, exist_ok=True)
    stem = name or _default_name(page)
    written: list[str] = []

    html_path = dl / f"{stem}.html"
    html_path.write_text(page.content(), encoding="utf-8")
    written.append(str(html_path))

    url_path = dl / f"{stem}.url.txt"
    url_path.write_text(page.url, encoding="utf-8")
    written.append(str(url_path))

    if include_screenshot:
        png_path = dl / f"{stem}.png"
        page.screenshot(path=str(png_path), full_page=full_page)
        written.append(str(png_path))

    return written


def require_login(
    page: Page,
    logged_in_signal: str,
    *,
    is_selector: bool = False,
    timeout_ms: int = 15_000,
    pause_message: str = (
        "\n[require_login] Session appears logged out.\n"
        "  Log in manually in the browser (including MFA / 'trust this device'),\n"
        "  then close the Playwright Inspector to resume the replay.\n"
    ),
) -> None:
    """
    Assert the browser is logged in. If not, pause for manual intervention.

    Args:
      logged_in_signal:
        Either a URL substring (default) or a Playwright selector (when
        `is_selector=True`) that only appears when the user is logged in.
        Examples:
          logged_in_signal="/ftgw/digital/portfolio"       # URL substring
          logged_in_signal="text=Log Out", is_selector=True

    Behaviour:
      1. Wait up to `timeout_ms` for the signal to appear.
      2. If it doesn't, print `pause_message` and call `page.pause()` so the
         user can log in / do MFA. Resumes when the user closes the inspector.
      3. Re-check the signal; raise RuntimeError if still not present.
    """
    def _matches() -> bool:
        if is_selector:
            try:
                page.locator(logged_in_signal).first.wait_for(
                    state="visible", timeout=timeout_ms
                )
                return True
            except PWTimeoutError:
                return False
        # URL substring match
        deadline = time.monotonic() + (timeout_ms / 1000)
        while time.monotonic() < deadline:
            if logged_in_signal in page.url:
                return True
            page.wait_for_timeout(250)
        return logged_in_signal in page.url

    if _matches():
        return

    print(pause_message)
    page.pause()

    if not _matches():
        raise RuntimeError(
            f"require_login: signal {logged_in_signal!r} still not present after manual pause."
        )
