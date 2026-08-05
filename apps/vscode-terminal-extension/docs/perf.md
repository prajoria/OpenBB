# Performance NFR Gate & Harness (#1839)

This extension ships a small perf harness that measures runtime critical-path
latencies against the §17.1 NFR targets, so regressions surface at CI time
rather than after ship.

## The §17.1 NFR budgets

| Metric | Target | Ceiling (+10%) | Description |
| --- | ---: | ---: | --- |
| `activation` | 500 ms | 550 ms | Extension activation time excludes back-end start |
| `webview_first_paint_fixture` | 300 ms | 330 ms | Webview first-paint fixture mode |
| `webview_first_paint_live` | 1000 ms | 1100 ms | Webview first-paint live API after back-end healthy |
| `symbol_context_propagation` | 100 ms | 110 ms | Symbol context propagation end-to-end |
| `backend_start` | 30 000 ms | 33 000 ms | Back-end start time from cold |
| `widget_hot_reload` | 2000 ms | 2200 ms | Widget hot-reload dev mode after source change |

Each budget carries `allow_regression_pct: 10`, so a metric passes if it is
within +10% of its target.

## How the harness works

- `src/perf/budget.ts` defines the read-only `NFR_BUDGETS` registry plus
  `checkBudget(metric, actual_ms)` and the `loadPreviousMeasurements` /
  `saveMeasurements` helpers.
- `src/perf/harness.ts` exports `PerfHarness` with:
  - `mark(label)` — record a start time
  - `measure(label): number` — return elapsed ms and stash it in the report
  - `report(): Record<string, number>` — a copy of all recorded metrics
  - `persist()` — write the report to `reportPath` (if provided)
  - `checkAll()` — evaluate each NFR budget against the recorded metrics
- Time is injected via `timeSource` so tests are deterministic. `Date.now`
  is the default.
- `extension.ts` instantiates a harness at the top of `activate()`, marks
  and measures `activation`, and registers the `openbb.showPerfReport`
  command which dumps the report + `checkAll` result into the OpenBB
  Terminal output channel.

## Running the perf gate

```bash
cd apps/vscode-terminal-extension
npm run perf:check
```

The script (`scripts/perf-check.sh`) instantiates `PerfHarness`, records
synthetic under-budget measurements, prints a per-metric table, and exits
non-zero on any budget failure.

## Updating budgets

Budgets are the source of truth for the §17.1 NFR. To change one:

1. Edit `NFR_BUDGETS` in `src/perf/budget.ts`.
2. Update the table above and the CHANGELOG.
3. Reference the ADR / decision issue that authorizes the change in the
   PR body.

Do not tweak `allow_regression_pct` to make a red gate green — file a
follow-up issue instead.
