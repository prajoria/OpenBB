/**
 * Playwright config for the portfolio_app widget E2E suite.
 *
 * Bead: OpenBBTechnical-qy83.1.7 — Playwright E2E harness + widget scaffolds.
 *
 * Design notes:
 *   - `testDir` isolates suite files under `./tests`.
 *   - `baseURL` is env-driven so devs can point at a local uvicorn
 *     (`http://127.0.0.1:6903`, the portfolio_app default port), or at
 *     a preview deploy, without editing the config.
 *   - `webServer` is deliberately NOT wired at M0 — the suite currently
 *     ships one placeholder spec that validates harness plumbing without
 *     an app. P1 widget tests will opt-in by importing a helper that
 *     starts uvicorn on-demand.
 *   - `retries` are enabled on CI only; local runs stay deterministic.
 *   - `reporter` uses the HTML report + line output for readable CI logs.
 */

import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [["html", { open: "never" }], ["line"]],
  use: {
    baseURL: process.env.PORTFOLIO_APP_BASE_URL ?? "http://127.0.0.1:6903",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
