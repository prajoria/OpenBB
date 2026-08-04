// node:test for perf budgets (#1839).
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  NFR_BUDGETS,
  checkBudget,
  loadPreviousMeasurements,
  saveMeasurements,
} = require("../../out/perf/budget.js");

test("NFR_BUDGETS has 6 entries with allow_regression_pct=10", () => {
  assert.equal(NFR_BUDGETS.length, 6);
  const metrics = NFR_BUDGETS.map((b) => b.metric).sort();
  assert.deepEqual(
    metrics,
    [
      "activation",
      "backend_start",
      "symbol_context_propagation",
      "webview_first_paint_fixture",
      "webview_first_paint_live",
      "widget_hot_reload",
    ],
  );
  for (const b of NFR_BUDGETS) {
    assert.equal(b.allow_regression_pct, 10);
    assert.ok(b.target_ms > 0);
    assert.ok(b.description.length > 0);
  }
});

test("checkBudget(activation, 400) passes", () => {
  const r = checkBudget("activation", 400);
  assert.equal(r.pass, true);
  assert.equal(r.budget.metric, "activation");
});

test("checkBudget(activation, 550) fails (exceeds 10% ceiling)", () => {
  const r = checkBudget("activation", 550);
  assert.equal(r.pass, false);
});

test("checkBudget(activation, 505) passes (within 10%)", () => {
  const r = checkBudget("activation", 505);
  assert.equal(r.pass, true);
});

test("checkBudget with unknown metric returns pass=false", () => {
  const r = checkBudget("nope", 1);
  assert.equal(r.pass, false);
  assert.equal(r.budget, null);
});

test("loadPreviousMeasurements returns {} when file missing", async () => {
  const fakeFs = {
    async readFile() {
      const err = new Error("ENOENT");
      err.code = "ENOENT";
      throw err;
    },
    async writeFile() {},
  };
  const out = await loadPreviousMeasurements("/nope.json", fakeFs);
  assert.deepEqual(out, {});
});

test("saveMeasurements writes JSON via injected fs", async () => {
  let written = null;
  const fakeFs = {
    async readFile() {
      return "{}";
    },
    async writeFile(path, data) {
      written = { path, data };
    },
    async mkdir() {},
  };
  await saveMeasurements("/tmp/x.json", { activation: 42 }, fakeFs);
  assert.equal(written.path, "/tmp/x.json");
  assert.deepEqual(JSON.parse(written.data), { activation: 42 });
});
