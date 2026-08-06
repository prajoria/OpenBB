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
  const names = ["escapeHtml", "mdToHtml", "inferChartModel", "svgForChart", "metricModel", "inlineOptionsHtml",
    "sidebarAppsHtml", "pxToGridRect", "clampGridItem", "gridItemStyle", "mergeLayout", "widgetRefString"];
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

// --------------------------------------------------------------------------
// #1885 — candle mode must NOT crush OHLC onto a shared axis with volume
// --------------------------------------------------------------------------
test("inferChartModel detects OHLC candle shape (not a 5-line collapse)", () => {
  const rows = [
    { date: "2026-06-01", open: 188, high: 191, low: 187, close: 190, volume: 1_000_000 },
    { date: "2026-06-02", open: 190, high: 194, low: 189, close: 193, volume: 1_200_000 },
    { date: "2026-06-03", open: 193, high: 195, low: 190, close: 191, volume: 900_000 },
  ];
  const m = H.inferChartModel(rows, undefined);
  assert.equal(m.kind, "candle", "OHLCV rows must infer a candle model, not a line");
  assert.equal(m.candles.length, 3);
  assert.equal(m.candles[0].o, 188);
  assert.equal(m.candles[0].c, 190);
  // volume is carried separately so it never shares the price y-axis
  assert.ok(m.volume, "volume series must be separated from the price axis");
  assert.equal(m.volume.length, 3);
});

test("svgForChart candle: OHLC uses a PRICE-only y-axis (volume excluded)", () => {
  const rows = [
    { date: "d1", open: 188, high: 191, low: 187, close: 190, volume: 1_000_000 },
    { date: "d2", open: 190, high: 194, low: 189, close: 193, volume: 1_200_000 },
  ];
  const svg = H.svgForChart(H.inferChartModel(rows, undefined));
  assert.match(svg, /<svg/);
  // candlesticks render as <rect> bodies (one per candle) + <line> wicks
  assert.ok((svg.match(/<rect/g) || []).length >= 2, "expected candle body rects");
  // The price axis labels must reflect PRICE magnitude (~1e2), NOT volume (~1e6).
  // If volume shared the axis, the top label would be ~1,200,000.
  const labelMatch = [...svg.matchAll(/font-size="10">([^<]+)<\/text>/g)].map((x) => x[1]);
  assert.ok(labelMatch.length >= 2, "expected y-axis labels");
  assert.ok(
    labelMatch.every((t) => !/\d{7}/.test(t) && !/M$/.test(t)),
    `price axis labels must be price-scale, got ${JSON.stringify(labelMatch)}`,
  );
});

test("inferChartModel: numeric year column is the x-axis, not a plotted series (#1885)", () => {
  const rows = [
    { year: 2023, revenue: 383_000, net_income: 97_000 },
    { year: 2024, revenue: 391_000, net_income: 94_000 },
    { year: 2025, revenue: 400_000, net_income: 99_000 },
  ];
  const m = H.inferChartModel(rows, undefined);
  assert.equal(m.kind, "line");
  assert.equal(m.xKey, "year", "year must be treated as the x-axis");
  const keys = m.series.map((s) => s.key).sort().join(",");
  assert.equal(keys, "net_income,revenue", "year must not be a plotted series");
});

// --------------------------------------------------------------------------
// #1887 — y-axis labels must not clip past the left edge (compact big numbers)
// --------------------------------------------------------------------------
test("svgForChart compacts large y-axis labels so they do not overflow (#1887)", () => {
  const rows = [
    { date: "d1", pnl: 103_060 },
    { date: "d2", pnl: 118_500 },
  ];
  const svg = H.svgForChart(H.inferChartModel(rows, undefined));
  const labels = [...svg.matchAll(/font-size="10">([^<]+)<\/text>/g)].map((x) => x[1]);
  // large magnitudes must be compacted (k / M), never a raw 6+ digit run
  assert.ok(
    labels.some((t) => /[kMB]$/.test(t)),
    `expected compacted axis label (k/M/B), got ${JSON.stringify(labels)}`,
  );
  assert.ok(
    labels.every((t) => !/\d{6}/.test(t)),
    `no raw 6+ digit label may remain, got ${JSON.stringify(labels)}`,
  );
});

// --------------------------------------------------------------------------
// #1886 — params with an inline options array must build a <select> dropdown
// --------------------------------------------------------------------------
test("inlineOptionsHtml builds selectable <option>s from an inline array (#1886)", () => {
  const html = H.inlineOptionsHtml(
    [{ value: "line", label: "Line" }, { value: "candle", label: "Candlestick" }],
    "candle",
  );
  assert.match(html, /<option value="line">Line<\/option>/);
  assert.match(html, /<option value="candle" selected>Candlestick<\/option>/);
});

test("inlineOptionsHtml tolerates bare-string options and empty input (#1886)", () => {
  assert.match(H.inlineOptionsHtml(["PASS", "FAIL"], "FAIL"), /<option value="FAIL" selected>FAIL<\/option>/);
  assert.equal(H.inlineOptionsHtml(undefined, ""), "");
  assert.equal(H.inlineOptionsHtml([], ""), "");
});

// --------------------------------------------------------------------------
// #1890 — app switcher moves into a left sidebar (nav buttons, active marked)
// --------------------------------------------------------------------------
test("sidebarAppsHtml builds one nav button per app, marks the active one (#1890)", () => {
  const html = H.sidebarAppsHtml(
    [{ name: "Overview" }, { name: "Terminal" }, { name: "Techtrade" }],
    1,
  );
  assert.equal((html.match(/data-app=/g) || []).length, 3, "one nav entry per app");
  assert.match(html, /data-app="0"[^>]*>Overview</);
  // the active index (1) carries the active class
  assert.match(html, /class="[^"]*active[^"]*"[^>]*data-app="1"[^>]*>Terminal</);
  // non-active entries must NOT be marked active
  assert.doesNotMatch(html, /class="[^"]*active[^"]*"[^>]*data-app="0"/);
});

test("sidebarAppsHtml escapes app names and loud-empties on no apps (#1890)", () => {
  assert.match(H.sidebarAppsHtml([{ name: "<x>&\"" }], 0), /&lt;x&gt;&amp;&quot;/);
  assert.equal(H.sidebarAppsHtml([], 0), "");
  assert.equal(H.sidebarAppsHtml(undefined, 0), "");
});

// --------------------------------------------------------------------------
// #1893 / #1892 — floating grid math: px<->grid snap, clamp, style, merge
// --------------------------------------------------------------------------
test("pxToGridRect rounds pixel rect to grid units (#1893)", () => {
  const geom = { colW: 10, rowH: 30 };
  // left=98 -> 10, top=61 -> 2, width=201 -> 20, height=89 -> 3
  assert.deepEqual(
    { ...H.pxToGridRect({ left: 98, top: 61, width: 201, height: 89 }, geom) },
    { x: 10, y: 2, w: 20, h: 3 },
  );
});

// --------------------------------------------------------------------------
// #1894 — copyable widget reference string (click-to-copy header chip)
// --------------------------------------------------------------------------
test("widgetRefString builds a stable, paste-friendly @id reference (#1894)", () => {
  assert.equal(
    H.widgetRefString(
      "pi_equity_profile",
      "Portfolio Intelligence - Terminal",
      "F1 Overview",
      "Equity Profile",
    ),
    "@pi_equity_profile (app: Portfolio Intelligence - Terminal | tab: F1 Overview | widget: Equity Profile)",
  );
});

test("clampGridItem enforces min size, column bounds, and no negatives (#1892)", () => {
  const opts = { cols: 40, minW: 8, minH: 4 };
  // w below min -> minW; h below min -> minH; negative x -> 0
  assert.deepEqual({ ...H.clampGridItem({ x: -5, y: -3, w: 2, h: 1 }, opts) }, { x: 0, y: 0, w: 8, h: 4 });
  // x pushed so x+w would exceed cols -> x clamped to cols-w
  assert.deepEqual({ ...H.clampGridItem({ x: 39, y: 5, w: 20, h: 9 }, opts) }, { x: 20, y: 5, w: 20, h: 9 });
  // w wider than the grid -> clamped to cols, x -> 0
  assert.deepEqual({ ...H.clampGridItem({ x: 3, y: 0, w: 99, h: 9 }, opts) }, { x: 0, y: 0, w: 40, h: 9 });
});

test("gridItemStyle maps grid units to pixel box (#1893)", () => {
  const geom = { colW: 12, rowH: 30 };
  assert.deepEqual(
    { ...H.gridItemStyle({ x: 2, y: 3, w: 20, h: 9 }, geom) },
    { left: 24, top: 90, width: 240, height: 270 },
  );
});

test("mergeLayout applies saved per-id overrides over apps.json defaults (#1893)", () => {
  const def = [
    { i: "a", x: 0, y: 0, w: 20, h: 9 },
    { i: "b", x: 20, y: 0, w: 20, h: 9 },
  ];
  const merged = H.mergeLayout(def, { b: { x: 0, y: 9, w: 40, h: 12 } });
  const a = merged.find((m) => m.i === "a");
  const b = merged.find((m) => m.i === "b");
  assert.deepEqual({ x: a.x, y: a.y, w: a.w, h: a.h }, { x: 0, y: 0, w: 20, h: 9 }, "unoverridden default unchanged");
  assert.deepEqual({ x: b.x, y: b.y, w: b.w, h: b.h }, { x: 0, y: 9, w: 40, h: 12 }, "override applied");
  // must not mutate the input defaults
  assert.equal(def[1].x, 20, "mergeLayout must not mutate the default layout");
});

test("mergeLayout loud-empties gracefully on missing inputs (#1893)", () => {
  assert.equal(H.mergeLayout(undefined, undefined).length, 0);
  assert.equal(H.mergeLayout([{ i: "a", x: 1, y: 2, w: 3, h: 4 }], undefined).length, 1);
});

// --------------------------------------------------------------------------
// VS Code-style dual side-panel toggles — both the left "Apps" sidebar and
// the right "Copilot" panel must be collapsible, and Copilot defaults hidden.
// These are DOM/localStorage glue (not pure fns) so we guard the contract at
// the source level: a regression that drops a toggle or flips the default
// back to "Copilot visible" fails here rather than silently in the browser.
// --------------------------------------------------------------------------
test("both side panels expose a header toggle AND an in-panel hide button", () => {
  // Left "Apps" sidebar
  assert.match(HTML, /id="side-toggle"/, "left sidebar header toggle must exist");
  assert.match(HTML, /id="side-hide"/, "left sidebar in-panel hide (×) must exist");
  // Right "Copilot" panel
  assert.match(HTML, /id="chat-toggle"/, "Copilot header toggle must exist");
  assert.match(HTML, /id="chat-hide"/, "Copilot in-panel hide (×) must exist");
});

test("both side panels have a collapse CSS rule that zeroes their width", () => {
  assert.match(HTML, /body\.side-collapsed\s+\.sidebar\s*\{[^}]*width:\s*0/, "left collapse rule missing");
  assert.match(HTML, /body\.chat-collapsed\s+\.chat\s*\{[^}]*width:\s*0/, "Copilot collapse rule missing");
});

test("Copilot panel is HIDDEN BY DEFAULT (collapsed unless the user opted in)", () => {
  // The bootstrap must collapse chat whenever the stored pref is not exactly
  // "0" (the only value that means "user pinned it open"). A regression to
  // `=== "1"` (default open) would be caught here.
  assert.match(
    HTML,
    /applyChatCollapsed\(\s*localStorage\.getItem\("viewer:chatCollapsed"\)\s*!==\s*"0"\s*\)/,
    "Copilot must default to collapsed (getItem(...) !== \"0\")",
  );
  // The left sidebar keeps its original default-OPEN behavior (collapse only
  // when the stored pref is exactly "1").
  assert.match(
    HTML,
    /applySideCollapsed\(\s*localStorage\.getItem\("viewer:sideCollapsed"\)\s*===\s*"1"\s*\)/,
    "left sidebar must default to open (=== \"1\" to collapse)",
  );
});
