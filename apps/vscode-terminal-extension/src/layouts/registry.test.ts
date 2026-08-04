import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import * as path from "node:path";
import { validateLayout, type Layout, type WidgetMeta, type WidgetSlot } from "./types";

const FIXTURES = path.join(__dirname, "..", "..", "fixtures");

async function loadJson<T>(rel: string): Promise<T> {
  const buf = await readFile(path.join(FIXTURES, rel), "utf-8");
  return JSON.parse(buf) as T;
}

async function loadWidgets(): Promise<WidgetMeta[]> {
  const parsed = await loadJson<{ widgets: WidgetMeta[] }>("widgets.sample.json");
  return parsed.widgets;
}

test("both layout JSON files parse and have required shape", async () => {
  for (const f of ["layouts/portfolio-overview.json", "layouts/equity-deep-dive.json"]) {
    const layout = await loadJson<Layout>(f);
    assert.ok(layout.id, `${f} missing id`);
    assert.ok(layout.name, `${f} missing name`);
    assert.ok(Array.isArray(layout.slots) && layout.slots.length > 0, `${f} slots invalid`);
    for (const slot of layout.slots) {
      assert.ok(slot.widgetId, "slot missing widgetId");
      assert.equal(typeof slot.col, "number");
      assert.equal(typeof slot.span, "number");
    }
  }
});

test("every layout widgetId exists in widgets.sample.json", async () => {
  const widgets = await loadWidgets();
  const ids = new Set(widgets.map((w) => w.id));
  for (const f of ["layouts/portfolio-overview.json", "layouts/equity-deep-dive.json"]) {
    const layout = await loadJson<Layout>(f);
    for (const slot of layout.slots) {
      assert.ok(ids.has(slot.widgetId), `unknown widgetId '${slot.widgetId}' in ${f}`);
    }
  }
});

test("no slot spans exceed 12 cols and no overlap within a row", async () => {
  const widgets = await loadWidgets();
  const ids = new Set(widgets.map((w) => w.id));
  for (const f of ["layouts/portfolio-overview.json", "layouts/equity-deep-dive.json"]) {
    const layout = await loadJson<Layout>(f);
    const errors = validateLayout(layout, ids);
    assert.deepEqual(errors, [], `validation errors in ${f}: ${errors.join("; ")}`);
  }
});

test("validateLayout detects overlaps and overflow", () => {
  const ids = new Set(["a", "b"]);
  const bad: Layout = {
    id: "bad",
    name: "bad",
    gridTemplate: "12-col",
    slots: [
      { widgetId: "a", col: 1, span: 6, row: 1 } as WidgetSlot,
      { widgetId: "b", col: 5, span: 6, row: 1 } as WidgetSlot,
    ],
  };
  const errs = validateLayout(bad, ids);
  assert.ok(errs.some((e) => e.includes("overlap")));

  const overflow: Layout = {
    id: "of",
    name: "of",
    gridTemplate: "12-col",
    slots: [{ widgetId: "a", col: 10, span: 6, row: 1 } as WidgetSlot],
  };
  const errs2 = validateLayout(overflow, ids);
  assert.ok(errs2.some((e) => e.includes("exceeds 12-col")));
});
