// Sparkline SVG tests (#1825). Runs under `node --test` after compile.

const { test } = require("node:test");
const assert = require("node:assert/strict");

const { buildSparklineSvg } = require("../../out/hover/sparkline");

test("positive trend uses #4CAF50", () => {
  const svg = buildSparklineSvg([1, 2, 3, 4, 5]);
  assert.ok(svg.includes("#4CAF50"), "expected green stroke");
  assert.ok(svg.startsWith("<svg"));
  assert.ok(svg.endsWith("</svg>"));
});

test("negative trend uses #F44336", () => {
  const svg = buildSparklineSvg([5, 4, 3, 2, 1]);
  assert.ok(svg.includes("#F44336"), "expected red stroke");
  assert.ok(svg.startsWith("<svg"));
  assert.ok(svg.endsWith("</svg>"));
});

test("flat series (min === max) does not crash", () => {
  const svg = buildSparklineSvg([3, 3, 3, 3]);
  assert.ok(svg.startsWith("<svg"));
  assert.ok(svg.endsWith("</svg>"));
  assert.ok(svg.includes("<line") || svg.includes("<polyline"));
});

test("empty series returns valid empty svg", () => {
  const svg = buildSparklineSvg([]);
  assert.ok(svg.startsWith("<svg"));
  assert.ok(svg.endsWith("</svg>"));
});

test("single-element series does not crash", () => {
  const svg = buildSparklineSvg([42]);
  assert.ok(svg.startsWith("<svg"));
  assert.ok(svg.endsWith("</svg>"));
});
