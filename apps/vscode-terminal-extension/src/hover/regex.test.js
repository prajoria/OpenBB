// Hover regex tests (#1825). Runs under `node --test` after compile.
// Uses the pure `findTickerInLine(text, col)` so the vscode module isn't
// required at test time.

const { test } = require("node:test");
const assert = require("node:assert/strict");

const { findTickerInLine } = require("../../out/hover/regex");

function hitFor(line) {
  for (let c = 0; c <= line.length; c++) {
    const h = findTickerInLine(line, c);
    if (h) return h;
  }
  return null;
}

test("accepts assignment: symbol = \"AAPL\"", () => {
  const h = hitFor(`symbol = "AAPL"`);
  assert.ok(h);
  assert.equal(h.symbol, "AAPL");
});

test("accepts assignment: ticker='MSFT'", () => {
  const h = hitFor(`ticker='MSFT'`);
  assert.ok(h);
  assert.equal(h.symbol, "MSFT");
});

test("accepts quoted literal in comment: # \"NVDA\"", () => {
  const h = hitFor(`# note about "NVDA" here`);
  assert.ok(h);
  assert.equal(h.symbol, "NVDA");
});

test("rejects bare identifiers: API, URL, MAX, SQL, DDL", () => {
  for (const bad of ["API", "URL", "MAX", "SQL", "DDL"]) {
    const line = `x = ${bad} + 1`;
    assert.equal(hitFor(line), null, `unexpected match on bare ${bad}`);
  }
});

test("rejects single-letter quoted: \"A\"", () => {
  assert.equal(hitFor(`x = "A"`), null);
});

test("rejects >=6-char quoted: \"GOOGLE\"", () => {
  assert.equal(hitFor(`x = "GOOGLE"`), null);
});

test("rejects lowercase: \"aapl\"", () => {
  assert.equal(hitFor(`x = "aapl"`), null);
});

test("rejects mixed-case: \"Aapl\"", () => {
  assert.equal(hitFor(`x = "Aapl"`), null);
});

test("cursor outside ticker returns null", () => {
  const line = `symbol = "AAPL"`;
  assert.equal(findTickerInLine(line, 0), null);
});

test("assignment takes priority over bare quoted literal", () => {
  const line = `symbol = "AAPL"  # also see "MSFT"`;
  const first = hitFor(line);
  assert.equal(first.symbol, "AAPL");
});
