/**
 * Smoke test — proves the Playwright harness is wired.
 *
 * Bead: OpenBBTechnical-qy83.1.7.
 *
 * This test intentionally does NOT touch portfolio_app. It runs on a
 * data-URL page so devs can validate `npm run e2e` end-to-end before
 * spinning up the backend. Every real widget test in P1+ replaces
 * `page.goto("data:...")` with `page.goto("/widgets/xray")` etc.
 */

import { test, expect } from "@playwright/test";

test("smoke: playwright harness reaches a data-URL page", async ({ page }) => {
  const html = "<!doctype html><html><body><h1>portfolio-intel e2e OK</h1></body></html>";
  await page.goto("data:text/html;charset=utf-8," + encodeURIComponent(html));
  await expect(page.locator("h1")).toHaveText("portfolio-intel e2e OK");
});
