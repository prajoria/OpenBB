// Node:test coverage for all five built-in layouts (#1821).
// Loads every fixture in fixtures/layouts/ and asserts shape, widget references,
// col-overflow, and per-row overlap. No VS Code dependency; the fs-based loader
// mirrors what getBuiltinLayouts() does via vscode.Uri.joinPath at runtime.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const FIXTURES = path.join(__dirname, "..", "..", "fixtures");
const LAYOUTS_DIR = path.join(FIXTURES, "layouts");

const EXPECTED_IDS = new Set([
  "portfolio-overview",
  "equity-deep-dive",
  "portfolio-risk",
  "trading-desk",
  "chart-focus",
]);

function loadJson(rel) {
  return JSON.parse(fs.readFileSync(path.join(FIXTURES, rel), "utf-8"));
}

function loadAllLayouts() {
  return fs
    .readdirSync(LAYOUTS_DIR)
    .filter((f) => f.endsWith(".json"))
    .map((f) => loadJson(path.join("layouts", f)));
}

function loadWidgetIds() {
  const m = loadJson("widgets.sample.json");
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
      errors.push(`slot ${slot.widgetId} exceeds 12-col grid in ${layout.id}`);
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

test("exactly five built-in layouts ship with the expected IDs", () => {
  const layouts = loadAllLayouts();
  assert.equal(layouts.length, 5, `expected 5 layouts, got ${layouts.length}`);
  const ids = new Set(layouts.map((l) => l.id));
  assert.deepEqual([...ids].sort(), [...EXPECTED_IDS].sort());
});

test("every layout validates: shape, widgetId known, no overflow, no overlap", () => {
  const knownIds = loadWidgetIds();
  const layouts = loadAllLayouts();
  for (const layout of layouts) {
    const errs = validate(layout, knownIds);
    assert.deepEqual(errs, [], `errors in ${layout.id}: ${errs.join("; ")}`);
  }
});

test("every widgetId referenced by any layout has a widgets.sample.json entry", () => {
  const knownIds = loadWidgetIds();
  const layouts = loadAllLayouts();
  for (const layout of layouts) {
    for (const slot of layout.slots) {
      assert.ok(
        knownIds.has(slot.widgetId),
        `layout ${layout.id} references unknown widget ${slot.widgetId}`
      );
    }
  }
});
