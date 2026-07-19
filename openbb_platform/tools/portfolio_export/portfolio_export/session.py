"""
Chromium persistent-context factory. The user-data-dir is validated to live
outside the repo before use.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright

from portfolio_export.config import Config


@contextmanager
def persistent_context(
    cfg: Config,
    download_dir: Path,
    headless: bool | None = None,
) -> Iterator[BrowserContext]:
    """
    Yield a Chromium `BrowserContext` backed by the persistent profile.
    Downloads are accepted and routed to `download_dir`.
    """
    cfg.profile_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)

    effective_headless = cfg.headless if headless is None else headless

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(cfg.profile_dir),
            headless=effective_headless,
            accept_downloads=True,
            downloads_path=str(download_dir),
            viewport={"width": 1400, "height": 900},
        )
        try:
            yield context
        finally:
            context.close()
