// Behavior tests for the Local Workspace Viewer's pure rendering helpers
// (#1805). These exercise the REAL functions embedded in index.html by
// extracting each named function's source (balanced-brace) and evaluating it
// in a clean sandbox — no DOM, no fetch, no bootstrap side effects. This
// keeps the viewer a single self-contained HTML file while still giving the
// chart/markdown/metric shaping logic genuine behavioral coverage.
//
// Run: node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/
//
// Fixtures below mirror the ACTUAL 6120 backend response shapes
// (widgets_endpoints.py): pie rows {sector,weight}, raw multi-series rows
// {date,vol_20d,vol_60d}, markdown strings, and metric dicts
// {value,label,note} / {vol_annualized,var_95_1d,beta_spy,note}.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const __dirname = dirname(fileURLToPath(import.meta.url));
const HTML = readFileSync(join(__dirname, "..", "index.html"), "utf-8");

// Extract the inline <script> body.
function scriptBody(html) {
  const m = /<script>([\s\S]*?)<\/script>/.exec(html);
  if (!m) throw new Error("no <script> block found in index.html");
  return m[1];
}

// Extract a single `function name(...) { ... }` declaration by brace-matching.
function extractFn(src, name) {
  const start = src.indexOf("function " + name + "(");
  if (start < 0) throw new Error(`function ${name} not found in index.html`);
  const open = src.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    const c = src[i];
    if (c === "{") depth++;
    else if (c === "}") {
      depth--;
      if (depth === 0) return src.slice(start, i + 1);
    }
  }
  throw new Error(`unbalanced braces extracting ${name}`);
}

// Build a sandbox with the pure helpers under test.
function loadHelpers() {
  const src = scriptBody(HTML);
  const names = ["escapeHtml", "mdToHtml", "inferChartModel", "svgForChart", "metricModel"];
  const code = names.map((n) => extractFn(src, n)).join("\n\n") +
    "\n;globalThis.__H = { " + names.join(", ") + " };";
  const ctx = {};
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return ctx.__H;
}

const H = loadHelpers();

// --------------------------------------------------------------------------
// escapeHtml (regression guard — must survive the #1805 edits)
// --------------------------------------------------------------------------
test("escapeHtml neutralizes angle brackets and quotes", () => {
  assert.equal(H.escapeHtml(`<script>"x"&'y'`), "&lt;script&gt;&quot;x&quot;&amp;&#39;y&#39;");
});

// --------------------------------------------------------------------------
// mdToHtml — safe markdown subset built on escapeHtml
// --------------------------------------------------------------------------
test("mdToHtml renders headings, bold, italic, inline code", () => {
  const h = H.mdToHtml("# Title\n\n**bold** and *italic* and `code`");
  assert.match(h, /<h1>Title<\/h1>/);
  assert.match(h, /<strong>bold<\/strong>/);
  assert.match(h, /<em>italic<\/em>/);
  assert.match(h, /<code>code<\/code>/);
});

test("mdToHtml renders unordered lists", () => {
  const h = H.mdToHtml("- one\n- two");
  assert.match(h, /<ul>/);
  assert.match(h, /<li>one<\/li>/);
  assert.match(h, /<li>two<\/li>/);
});

test("mdToHtml renders blockquotes", () => {
  const h = H.mdToHtml("> quoted line");
  assert.match(h, /<blockquote>[\s\S]*quoted line[\s\S]*<\/blockquote>/);
});

test("mdToHtml renders safe http links", () => {
  const h = H.mdToHtml("[OpenBB](https://openbb.co)");
  assert.match(h, /<a href="https:\/\/openbb\.co"[^>]*>OpenBB<\/a>/);
});

test("mdToHtml is XSS-safe: raw HTML is escaped, not passed through", () => {
  const h = H.mdToHtml('<img src=x onerror="alert(1)">');
  assert.doesNotMatch(h, /<img/i, "raw <img> tag must not survive");
  assert.match(h, /&lt;img/i, "angle brackets must be escaped to entities");
  // The chars 'onerror=' may remain as INERT escaped text; what must never
  // survive is a live tag carrying the handler.
  assert.doesNotMatch(h, /<[a-z][^>]*onerror/i, "no live tag may carry an event handler");
});

test("mdToHtml is XSS-safe: javascript: link hrefs are rejected", () => {
  const h = H.mdToHtml("[x](javascript:alert(1))");
  assert.doesNotMatch(h, /href="javascript:/i);
});

test("mdToHtml preserves link URLs containing _ and * (no emphasis corruption)", () => {
  // Emphasis passes must not rewrite chars inside a generated anchor's href.
  const h = H.mdToHtml("See [report](https://example.com/my_report_v2) now");
  assert.match(
    h,
    /href="https:\/\/example\.com\/my_report_v2"/,
    "underscores in the href must survive the *//_ emphasis passes"
  );
  assert.doesNotMatch(h, /href="[^"]*<em>/i, "no <em> injected into href");
  assert.doesNotMatch(h, /target="<em>/i, "no <em> injected into target attr");
});

test("mdToHtml loud-empty: empty input yields empty-ish output (no throw)", () => {
  assert.equal(typeof H.mdToHtml(""), "string");
});

// --------------------------------------------------------------------------
// inferChartModel — pie config vs. raw-row multi-series inference
// --------------------------------------------------------------------------
test("inferChartModel builds a pie model from labelColumn/valueColumn", () => {
  const rows = [
    { sector: "Technology", weight: 0.5 },
    { sector: "Financials", weight: 0.3 },
    { sector: "Energy", weight: 0.2 },
  ];
  const m = H.inferChartModel(rows, { type: "pie", labelColumn: "sector", valueColumn: "weight" });
  assert.equal(m.kind, "pie");
  assert.equal(m.slices.length, 3);
  assert.equal(m.slices[0].label, "Technology");
  assert.ok(Math.abs(m.total - 1.0) < 1e-9);
});

test("inferChartModel infers a multi-series line from raw rows", () => {
  const rows = [
    { date: "2026-06-01", vol_20d: 0.16, vol_60d: 0.18 },
    { date: "2026-06-02", vol_20d: 0.17, vol_60d: 0.19 },
    { date: "2026-06-03", vol_20d: 0.15, vol_60d: 0.17 },
  ];
  const m = H.inferChartModel(rows, undefined);
  assert.equal(m.kind, "line");
  assert.equal(m.xKey, "date");
  const keys = m.series.map((s) => s.key).sort();
  // Compare by value (join) — cross-realm arrays from the vm sandbox have a
  // different Array.prototype, which trips deepStrictEqual's prototype check.
  assert.equal(keys.join(","), "vol_20d,vol_60d");
  assert.equal(m.series[0].points.length, 3);
});

test("inferChartModel loud-empty: no rows -> empty (table fallback)", () => {
  assert.equal(H.inferChartModel([], undefined).kind, "empty");
});

test("inferChartModel loud-empty: no numeric columns -> empty (table fallback)", () => {
  const m = H.inferChartModel([{ a: "x", b: "y" }], undefined);
  assert.equal(m.kind, "empty");
});

// --------------------------------------------------------------------------
// svgForChart — inline SVG, no CDN
// --------------------------------------------------------------------------
test("svgForChart draws one slice per pie datum", () => {
  const model = H.inferChartModel(
    [{ s: "A", w: 0.6 }, { s: "B", w: 0.4 }],
    { type: "pie", labelColumn: "s", valueColumn: "w" },
  );
  const svg = H.svgForChart(model);
  assert.match(svg, /<svg/);
  assert.equal((svg.match(/<path/g) || []).length, 2);
});

test("svgForChart draws one polyline per line series", () => {
  const model = H.inferChartModel(
    [
      { date: "d1", a: 1, b: 2 },
      { date: "d2", a: 3, b: 4 },
    ],
    undefined,
  );
  const svg = H.svgForChart(model);
  assert.match(svg, /<svg/);
  assert.equal((svg.match(/<polyline/g) || []).length, 2);
});

// --------------------------------------------------------------------------
// metricModel — single big card vs. multi-key grid, sign coloring
// --------------------------------------------------------------------------
test("metricModel: {value,label,note} -> one card", () => {
  const m = H.metricModel({ value: 0.62, label: "Sentiment (-1..+1)", note: "demo" });
  assert.equal(m.cards.length, 1);
  assert.equal(m.cards[0].label, "Sentiment (-1..+1)");
  assert.equal(m.cards[0].value, 0.62);
  assert.equal(m.note, "demo");
});

test("metricModel: multi numeric keys -> grid, negatives flagged", () => {
  const m = H.metricModel({ vol_annualized: 0.184, var_95_1d: -0.021, beta_spy: 1.08, note: "demo book" });
  assert.equal(m.cards.length, 3);
  assert.equal(m.note, "demo book");
  const varCard = m.cards.find((c) => /var/i.test(c.label));
  assert.equal(varCard.cls, "neg");
});

test("metricModel loud-empty: {} -> no cards", () => {
  assert.equal(H.metricModel({}).cards.length, 0);
});
