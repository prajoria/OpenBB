# OpenBB Terminal — Testing Strategy

Scaffolded in #1840, cross-referenced from PRD §17. Four tiers with
clearly-scoped triggers so contributors know which one to add a test to.

## Tier 1 — Unit tests (`src/**/*.test.js`)

- **Runner**: `npm test`
- **Runs**: every push, every PR, locally on save.
- **Scope**: pure functions and small modules. No `vscode` runtime.
- **Adding a test**: colocate `foo.test.js` next to `foo.ts` (compiled
  or `.js`), use `node:test` + `node:assert/strict`, keep it under ~50 ms.
- **Failure mode caught**: regressions in CSP builder, symbol validator,
  golden-layout loader, sparkline helpers, etc.

## Tier 2 — Snapshot tests (`tests/snapshots/`)

- **Runner**: `npm run test:snapshots`
- **Runs**: every push (unit-tier speed, no VS Code download).
- **Scope**: rendered webview HTML (terminal panel, preview panel).
  Nonce is stubbed for determinism.
- **Adding a test**: extend `snapshot.test.js`, then regenerate the
  fixture via `UPDATE_SNAPSHOTS=1 npm run test:snapshots`.
- **Failure mode caught**: silent template drift that would otherwise
  only surface in a live extension host — e.g. accidentally injecting
  `unsafe-inline` into `script-src`, dropping the API-base window
  global, changing widget-metadata escaping.

## Tier 3 — Fixture-harness tests (`tests/fixture-harness/`)

- **Runner**: `npm run test:fixture-harness`
- **Runs**: every push.
- **Scope**: JSON fixtures under `fixtures/` — shape validation and
  cross-reference integrity (every layout `widgetId` resolves against
  `widgets.sample.json`).
- **Adding a test**: extend `roundtrip.test.js` when a new fixture
  category ships.
- **Failure mode caught**: dangling widget references introduced by an
  ill-considered fixture edit, layout/widget schema drift.

## Tier 4 — Integration tests (`tests/integration/`)

- **Runner**: `RUN_INTEGRATION=1 npm run test:integration`
- **Runs**: nightly, not on every PR (downloads a stable VS Code build
  and launches an extension host, ~1 min per run).
- **Scope**: activation, command registration, settings visibility,
  end-to-end command wiring against a real `vscode` runtime.
- **Adding a test**: add a Mocha `*.test.js` under
  `tests/integration/`, reuse the existing `suite()` / `test()` style.
- **Failure mode caught**: activation-event misspellings, commands
  declared in `package.json` but not registered in `extension.ts`,
  configuration properties whose schema fails at load.

## Manual QA — `docs/qa-matrix.md`

- **Runs**: before every `v0.x` release tag.
- **Scope**: the human-visible cells that automated tests can't reach
  — theme flip, HC contrast, chart hover, paper-order round-trip.
- **Adding a row**: append when a new built-in layout ships.

## Which tier for which change?

- New helper function → Tier 1.
- Change to webview HTML template → Tier 2 (snapshot).
- New fixture / new widget or layout schema field → Tier 3.
- New command / new activation event / new setting → Tier 4 (+ Tier 1
  for any pure-function extraction).
- New rendered layout or visible theme change → QA matrix row.

## CI wiring

`npm run test:all` runs tiers 1–3 plus `verify:invariants` in one
shot. Tier 4 is gated on `RUN_INTEGRATION=1` and scheduled nightly so
PR authors are never blocked by the VS Code download.
