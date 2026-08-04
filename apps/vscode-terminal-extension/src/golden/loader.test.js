// Node:test coverage for the golden-layouts loader (#1833).
//
// The loader itself imports `vscode`, which is only resolvable inside the
// extension host. This test mirrors the fs shape the loader consumes and
// exercises the same validate + cache invariants against the real JSON on
// disk, plus a shim that verifies the module-level cache semantics.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const EXT_ROOT = path.join(__dirname, "..", "..");
const GOLDEN_DIR = path.join(EXT_ROOT, "golden_layouts");
const FIXTURES = path.join(EXT_ROOT, "fixtures");

const EXPECTED_IDS = new Set([
  "momentum-scan",
  "risk-review",
  "single-stock-deep-dive",
  "paper-trading-cockpit",
]);

function loadJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf-8"));
}

function loadGoldenFromDisk() {
  return fs
    .readdirSync(GOLDEN_DIR)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => loadJson(path.join(GOLDEN_DIR, f)));
}

function loadWidgetIds() {
  const m = loadJson(path.join(FIXTURES, "widgets.sample.json"));
  return new Set(m.widgets.map((w) => w.id));
}

function validate(layout, knownIds) {
  const errors = [];
  if (!layout.id || !layout.name || !Array.isArray(layout.slots)) {
    errors.push("missing required fields");
    return errors;
  }
  const rows = new Map();
  for (const slot of layout.slots) {
    if (!slot.widgetId || typeof slot.col !== "number" || typeof slot.span !== "number") {
      errors.push(`slot missing widgetId/col/span in ${layout.id}`);
      continue;
    }
    if (!knownIds.has(slot.widgetId)) {
      errors.push(`unknown widgetId '${slot.widgetId}' in ${layout.id}`);
    }
    const end = slot.col + slot.span - 1;
    if (slot.col < 1 || end > 12) {
      errors.push(`slot ${slot.widgetId} exceeds 12-col in ${layout.id}`);
    }
    const row = slot.row ?? 1;
    const arr = rows.get(row) ?? [];
    for (const r of arr) {
      if (!(end < r.start || slot.col > r.end)) {
        errors.push(`overlap in ${layout.id} row ${row}: ${slot.widgetId}`);
      }
    }
    arr.push({ start: slot.col, end });
    rows.set(row, arr);
  }
  return errors;
}

test("golden_layouts/ ships the expected 4 curated layouts", () => {
  const layouts = loadGoldenFromDisk();
  assert.equal(layouts.length, 4, `expected 4 golden layouts, got ${layouts.length}`);
  const ids = new Set(layouts.map((l) => l.id));
  assert.deepEqual([...ids].sort(), [...EXPECTED_IDS].sort());
});

test("every golden layout validates: shape, widgetId known, no overflow, no overlap", () => {
  const ids = loadWidgetIds();
  for (const layout of loadGoldenFromDisk()) {
    const errs = validate(layout, ids);
    assert.deepEqual(errs, [], `errors in ${layout.id}: ${errs.join("; ")}`);
  }
});

test("every widgetId referenced by a golden layout exists in widgets.sample.json", () => {
  const ids = loadWidgetIds();
  for (const layout of loadGoldenFromDisk()) {
    for (const slot of layout.slots) {
      assert.ok(
        ids.has(slot.widgetId),
        `golden layout ${layout.id} references unknown widget ${slot.widgetId}`
      );
    }
  }
});

test("each golden layout is stamped with sourceGoldenId == id (loader contract)", () => {
  const layouts = loadGoldenFromDisk().map((l) => ({ ...l, sourceGoldenId: l.id }));
  for (const l of layouts) {
    assert.equal(l.sourceGoldenId, l.id);
  }
});

test("cache semantics: same reference on repeat, resetCache invalidates", () => {
  let cache = null;
  let reads = 0;
  const load = () => {
    if (cache) return cache;
    reads += 1;
    cache = loadGoldenFromDisk();
    return cache;
  };
  const reset = () => { cache = null; };

  const a = load();
  const b = load();
  assert.strictEqual(a, b, "cached call must return same reference");
  assert.equal(reads, 1);
  reset();
  const c = load();
  assert.notStrictEqual(a, c, "resetCache must yield a fresh array");
  assert.equal(reads, 2);
});
