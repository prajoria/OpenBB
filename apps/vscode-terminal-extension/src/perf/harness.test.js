// node:test for PerfHarness (#1839).
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { PerfHarness } = require("../../out/perf/harness.js");

function fakeClock(sequence) {
  let i = 0;
  return () => sequence[Math.min(i++, sequence.length - 1)];
}

test("mark + measure returns injected elapsed", () => {
  const h = new PerfHarness({ timeSource: fakeClock([1000, 1250]) });
  h.mark("activation");
  const elapsed = h.measure("activation");
  assert.equal(elapsed, 250);
  assert.deepEqual(h.report(), { activation: 250 });
});

test("measure without mark throws", () => {
  const h = new PerfHarness({ timeSource: () => 0 });
  assert.throws(() => h.measure("nope"), /no matching mark/);
});

test("checkAll returns one result per NFR metric", async () => {
  const h = new PerfHarness({ timeSource: fakeClock([0, 100]) });
  h.mark("symbol_context_propagation");
  h.measure("symbol_context_propagation");
  const results = await h.checkAll();
  assert.equal(results.length, 6);
  const propagation = results.find(
    (r) => r.budget && r.budget.metric === "symbol_context_propagation",
  );
  assert.equal(propagation.pass, true);
});

test("persist writes JSON via injected fs", async () => {
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
  const h = new PerfHarness({
    reportPath: "/tmp/report.json",
    timeSource: fakeClock([0, 42]),
    fsPromises: fakeFs,
  });
  h.mark("activation");
  h.measure("activation");
  await h.persist();
  assert.equal(written.path, "/tmp/report.json");
  assert.deepEqual(JSON.parse(written.data), { activation: 42 });
});

test("persist with no reportPath is a no-op", async () => {
  const h = new PerfHarness({ timeSource: () => 0 });
  await h.persist(); // should not throw
});
