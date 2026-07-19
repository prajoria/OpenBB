"""Example (skeleton) Fidelity export + HTML capture flow.

This is a TEMPLATE. It will not run as-is — the selectors below are placeholders.
Record your real flow with `pe record fidelity_export --url https://digital.fidelity.com/`,
then paste the Playwright Inspector output into `run()`.

Guiding rules:
- Do NOT hard-code your password. Log in once during recording; the persistent
  Chromium profile keeps the session cookie so replay skips the login step.
- If the session expires, `require_login()` pauses for manual MFA and resumes.
- Wrap every download click in `page.expect_download()` and save via
  `dl.save_as(f"{download_dir}/...")`.
- For crawler-style HTML capture use `save_page_html` or `save_page_snapshot`.
"""

from playwright.sync_api import Page

from portfolio_export.helpers import (
    require_login,
    save_page_html,
    save_page_snapshot,
)

URL = "https://digital.fidelity.com/"


def run(page: Page, download_dir: str) -> list[str]:
    downloaded: list[str] = []

    page.goto(URL)

    # If the persistent profile's session has timed out, this pauses the
    # replay so you can complete MFA in the visible browser, then resumes.
    # Replace the URL fragment with something that only appears while logged in.
    require_login(page, "/ftgw/digital/portfolio")

    # --- Example only; replace with your recorded steps -----------------
    # page.get_by_role("link", name="Positions").click()
    #
    # # Capture the positions page as HTML + PNG + URL sidecar
    # downloaded += save_page_snapshot(page, download_dir, name="positions")
    #
    # # Real download (CSV export)
    # page.get_by_role("button", name="Download").click()
    # with page.expect_download() as dl_info:
    #     page.get_by_role("menuitem", name="CSV").click()
    # dl = dl_info.value
    # dest = f"{download_dir}/{dl.suggested_filename}"
    # dl.save_as(dest)
    # downloaded.append(dest)
    #
    # # Crawler pattern: iterate over tabs, snapshot each as HTML
    # for name in ["Balances", "History", "Activity"]:
    #     page.get_by_role("link", name=name).click()
    #     page.wait_for_load_state("networkidle")
    #     downloaded.append(save_page_html(page, download_dir, name=name.lower()))
    # -------------------------------------------------------------------

    return downloaded
