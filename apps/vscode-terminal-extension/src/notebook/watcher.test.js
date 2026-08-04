// Notebook symbol watcher tests (#1826).
const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const Module = require("node:module");

const compiledPath = path.join(__dirname, "..", "..", "out", "notebook", "watcher.js");

if (!fs.existsSync(compiledPath)) {
  test("watcher.ts compiled output missing — run npm run compile", () => {
    assert.ok(fs.existsSync(compiledPath), `expected ${compiledPath} to exist`);
  });
} else {
  const fakeVscodePath = path.join(__dirname, "__vscode_stub_watcher.js");
  fs.writeFileSync(fakeVscodePath, `module.exports = {
    workspace: {
      onDidOpenNotebookDocument(h) { global.__nbOpen = h; return { dispose() {} }; },
      onDidChangeNotebookDocument(h) { global.__nbChange = h; return { dispose() {} }; },
    },
  };`);
  const origResolve = Module._resolveFilename;
  Module._resolveFilename = function (r, p, ...rest) {
    if (r === "vscode") return fakeVscodePath;
    return origResolve.call(this, r, p, ...rest);
  };
  const { registerNotebookSymbolWatcher } = require(compiledPath);
  Module._resolveFilename = origResolve;

  const cell = (t) => ({ document: { getText: () => t } });
  const doc = (uri, cells) => ({ uri: { toString: () => uri }, getCells: () => cells });
  const symCtx = () => {
    const calls = [];
    return { calls, setSymbol: async (s, src) => { calls.push([s, src]); return { accepted: true }; } };
  };
  const fresh = () => {
    const sc = symCtx();
    registerNotebookSymbolWatcher({ subscriptions: [] }, sc);
    return { sc, open: global.__nbOpen, change: global.__nbChange };
  };

  test('symbol = "AAPL" -> one call', () => {
    const { sc, open } = fresh();
    open(doc("nb1", [cell('symbol = "AAPL"')]));
    assert.deepEqual(sc.calls, [["AAPL", "notebook"]]);
  });
  test("ticker = 'MSFT' -> one call", () => {
    const { sc, open } = fresh();
    open(doc("nb2", [cell("ticker = 'MSFT'")]));
    assert.deepEqual(sc.calls, [["MSFT", "notebook"]]);
  });
  test("x = 5 -> zero calls", () => {
    const { sc, open } = fresh();
    open(doc("nb3", [cell("x = 5")]));
    assert.equal(sc.calls.length, 0);
  });
  test('# symbol = "AAPL" (dumb parse) still matches', () => {
    const { sc, open } = fresh();
    open(doc("nb4", [cell('# symbol = "AAPL"')]));
    assert.deepEqual(sc.calls, [["AAPL", "notebook"]]);
  });
  test("2 rapid changes same symbol -> 1 call", () => {
    const { sc, change } = fresh();
    const c = cell('symbol = "AAPL"');
    const nb = { uri: { toString: () => "nb5" } };
    change({ notebook: nb, cellChanges: [{ cell: c }], contentChanges: [] });
    change({ notebook: nb, cellChanges: [{ cell: c }], contentChanges: [] });
    assert.equal(sc.calls.length, 1);
  });
  test("multi-cell different syms -> last wins", () => {
    const { sc, open } = fresh();
    open(doc("nb6", [cell('symbol = "AAPL"'), cell('ticker = "MSFT"'), cell('symbol = "GOOG"')]));
    assert.equal(sc.calls.length, 1);
    assert.deepEqual(sc.calls[0], ["GOOG", "notebook"]);
  });
}
