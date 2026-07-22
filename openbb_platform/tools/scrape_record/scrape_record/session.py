"""Persistent Chrome context — optional login reuse.

Mirrors ``portfolio_export.session``: launches a persistent Playwright
Chromium context so the user's cookies + login state carry across runs
(useful for sites that rate-limit anonymous requests). Unlike
``portfolio_export``, login is OPTIONAL here — most public provider
pages work anonymously.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from scrape_record.config import Config


@contextmanager
def persistent_context(cfg: Config) -> Iterator:
    """Open a persistent Chromium context; yield it; close on exit.

    Uses ``cfg.profile_dir`` for cookie/session persistence and
    ``cfg.headless`` to control visibility. Playwright is imported
    lazily so the tool can be introspected without Playwright installed
    (helpful for CI containers that don't need browser bin).
    """
    # pylint: disable=import-outside-toplevel
    from playwright.sync_api import sync_playwright

    cfg.profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(cfg.profile_dir),
            headless=cfg.headless,
            accept_downloads=False,  # scrape-record captures DOM, not downloads
        )
        try:
            yield ctx
        finally:
            ctx.close()
