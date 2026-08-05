// Fixture round-trip test (#1840, tier 3).
//
// Reads every JSON fixture under fixtures/, validates the expected
// shape (layout: id/name/gridTemplate/slots[]; widgets: version +
// widgets[] each with id/name/type/endpoint/category), and confirms
// that every widgetId referenced by a layout slot resolves against
// widgets.sample.json.

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const FIXTURE_ROOT = path.resolve(__dirname, "..", "..", "fixtures");
const LAYOUTS_DIR = path.join(FIXTURE_ROOT, "layouts");
const WIDGETS_FILE = path.join(FIXTURE_ROOT, "widgets.sample.json");

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

test("widgets.sample.json has the documented shape", () => {
  const w = readJson(WIDGETS_FILE);
  assert.equal(typeof w.version, "string");
  assert.ok(Array.isArray(w.widgets), "widgets[] must be array");
  assert.ok(w.widgets.length > 0, "widgets[] must be non-empty");
  for (const widget of w.widgets) {
    for (const k of ["id", "name", "type", "endpoint", "category"]) {
      assert.equal(
        typeof widget[k],
        "string",
        `widget ${widget.id}: missing ${k}`,
      );
    }
  }
});

test("each layout fixture has the documented shape", () => {
  const files = fs
    .readdirSync(LAYOUTS_DIR)
    .filter((f) => f.endsWith(".json"));
  assert.ok(files.length > 0, "no layout fixtures found");
  for (const f of files) {
    const l = readJson(path.join(LAYOUTS_DIR, f));
    assert.equal(typeof l.id, "string", `${f}: id`);
    assert.equal(typeof l.name, "string", `${f}: name`);
    assert.equal(typeof l.gridTemplate, "string", `${f}: gridTemplate`);
    assert.ok(Array.isArray(l.slots), `${f}: slots[] must be array`);
    assert.ok(l.slots.length > 0, `${f}: slots[] must be non-empty`);
    for (const slot of l.slots) {
      assert.equal(typeof slot.widgetId, "string", `${f}: slot widgetId`);
      assert.equal(typeof slot.col, "number", `${f}: slot col`);
      assert.equal(typeof slot.span, "number", `${f}: slot span`);
      assert.equal(typeof slot.row, "number", `${f}: slot row`);
    }
  }
});

test("every layout widgetId resolves in widgets.sample.json", () => {
  const w = readJson(WIDGETS_FILE);
  const known = new Set(w.widgets.map((x) => x.id));
  const files = fs
    .readdirSync(LAYOUTS_DIR)
    .filter((f) => f.endsWith(".json"));
  const unresolved = [];
  for (const f of files) {
    const l = readJson(path.join(LAYOUTS_DIR, f));
    for (const slot of l.slots) {
      if (!known.has(slot.widgetId)) {
        unresolved.push(`${f}: ${slot.widgetId}`);
      }
    }
  }
  assert.deepEqual(
    unresolved,
    [],
    `unresolved widgetIds:\n  ${unresolved.join("\n  ")}`,
  );
});
