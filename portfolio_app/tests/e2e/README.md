# Portfolio App — Playwright E2E harness

Widget contract tests for `portfolio_app` (Portfolio Intelligence Engine).
Every widget shipped in P1/P2/P3 lands with a matching `.spec.ts` file here.

**Bead:** `OpenBBTechnical-qy83.1.7` — Playwright E2E harness + widget scaffolds.

## First-time setup

```bash
cd portfolio_app/tests/e2e
npm install
npx playwright install    # downloads the browser binaries (~200MB one-off)
```

## Run the suite

```bash
npm run e2e            # headless
npm run e2e:headed     # visible browser
npm run e2e:ui         # interactive Playwright UI
npm run e2e:report     # open the last HTML report
```

## Point at a different portfolio_app instance

```bash
PORTFOLIO_APP_BASE_URL=http://staging:6903 npm run e2e
```

Default base URL is `http://127.0.0.1:6903` (matches `portfolio_app`'s
`run_portfolio.py` default port).

## Adding a new widget test

1. Drop a file under `tests/<widget-name>.spec.ts`.
2. Boot `portfolio_app` (`python portfolio_app/run_portfolio.py`) in another shell.
3. `npm run e2e`.

Every new widget shipped in P1+ MUST include a matching `.spec.ts` per the
per-lane Definition of Done in the Execution Plan §10.

## What ships at M0 (this bead)

- `playwright.config.ts` — env-driven baseURL, HTML + line reporter, CI-only retries
- `package.json` — pins `@playwright/test ^1.48.0` + `e2e` npm scripts
- `tests/smoke.spec.ts` — one placeholder spec verifying the harness is wired
- `.gitignore` — excludes `node_modules/`, `test-results/`, `playwright-report/`
- Contract-guarded by `portfolio_app/tests/test_playwright_harness.py` (Python side)

## Deferred to follow-up beads

- **CI wiring** — this harness is currently **dev-machine only**. No GitHub
  Actions workflow invokes `npm run e2e`. That's intentional at M0 (the
  smoke spec runs without a backend but real widget specs need `portfolio_app`
  running, and we haven't decided per-suite-uvicorn vs shared-instance yet).
  Tracked as a follow-up bead once the first P1 widget lands.
- `webServer` block in `playwright.config.ts` to auto-start uvicorn — pending
  a decision on whether to spawn per-suite or share one instance
- Cross-browser (webkit / firefox) — chromium-only until we hit a rendering
  bug that requires it
- TypeScript-in-editor: `typescript` devDep was dropped in R2 (Playwright
  bundles its own TS transpile via esbuild, so `npm run e2e` doesn't need
  it). If an engineer wants editor tooling like `tsc --noEmit`, they can
  `npm i -D typescript` locally without checking it in.
