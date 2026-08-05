#!/usr/bin/env bash
# Perf gate check (#1839).
#
# Instantiates the PerfHarness against synthetic under-budget
# measurements to prove the gate wires end-to-end. Exits non-zero on
# any failure and prints a per-metric table.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

cd "$ROOT"

if [ ! -d "out/perf" ]; then
  echo "[perf-check] compiling TypeScript..."
  npx --no-install tsc -p . >/dev/null
fi

node --input-type=commonjs -e '
const { PerfHarness } = require("./out/perf/harness.js");
const { NFR_BUDGETS, checkBudget } = require("./out/perf/budget.js");

// Synthetic under-budget measurements: each metric at 50% of its target.
const synthetic = Object.fromEntries(
  NFR_BUDGETS.map((b) => [b.metric, Math.round(b.target_ms * 0.5)]),
);

const h = new PerfHarness({ timeSource: (() => {
  let n = 0;
  return () => n++;
})() });
for (const [metric, ms] of Object.entries(synthetic)) {
  h.record(metric, ms);
}

(async () => {
  const results = await h.checkAll();
  const rows = [];
  let failed = 0;
  for (const r of results) {
    const metric = r.budget ? r.budget.metric : "(unknown)";
    const target = r.budget ? r.budget.target_ms : "n/a";
    const actual = synthetic[metric] ?? "-";
    const status = r.pass ? "PASS" : "FAIL";
    if (!r.pass) failed++;
    rows.push({ metric, target, actual, status });
  }
  const w1 = Math.max(6, ...rows.map((r) => r.metric.length));
  console.log(
    "metric".padEnd(w1) + "  target_ms  actual_ms  status",
  );
  console.log("-".repeat(w1 + 30));
  for (const r of rows) {
    console.log(
      r.metric.padEnd(w1) +
        "  " +
        String(r.target).padStart(9) +
        "  " +
        String(r.actual).padStart(9) +
        "  " +
        r.status,
    );
  }
  // Spot-check checkBudget directly.
  const spot = checkBudget("activation", 400);
  if (!spot.pass) {
    console.error("[perf-check] spot check FAIL: activation 400ms should pass");
    process.exit(2);
  }
  if (failed > 0) {
    console.error("[perf-check] " + failed + " metric(s) failed budget");
    process.exit(1);
  }
  console.log("[perf-check] all metrics within budget");
})();
'
