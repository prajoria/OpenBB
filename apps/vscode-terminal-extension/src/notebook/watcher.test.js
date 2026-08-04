// Notebook symbol watcher tests (#1826). Runs under `node --test`.
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
  fs.writeFileSync(
    fakeVscodePath,
    `module.exports = {
       workspace: {
         onDidOpenNotebookDocument(h) { global.__nbOpen = h; return { dispose() {} }; },
         onDidChangeNotebookDocument(h) { global.__nbChange = h; return { dispose() {} }; },
       },
     };`,
  );
  const origResolve = Module._resolveFilename;
  Module._resolveFilename = function (request, parent, ...rest) {
    if (request === "vscode") return fakeVscodePath;
    return origResolve.call(this, request, parent, ...rest);
  };
  const { registerNotebookSymbolWatcher } = require(compiledPath);
  Module._resolveFilename = origResolve;

  const makeCell = (t) => ({ document: { getText: () => t } });
  const makeDoc = (uri, cells) => ({ uri: { toString: () => uri }, getCells: () => cells });
  const makeSymCtx = () => {
    const calls = [];
    return { calls, setSymbol: async (sym, src) => { calls.push([sym, src]); return { accepted: true }; } };
  };
  const fresh = () => {
    const sc = makeSymCtx();
    registerNotebookSymbolWatcher({ subscriptions: [] }, sc);
    return { sc, open: global.__nbOpen, change: global.__nbChange };
  };

  test('symbol = "AAPL" triggers one setSymbol("AAPL","notebook")', () => {
    const { sc, open } = fresh();
    open(makeDoc("nb1", [makeCell('symbol = "AAPL"')]));
    assert.deepEqual(sc.calls, [["AAPL", "notebook"]]);
  });

  test("ticker = 'MSFT' triggers one setSymbol('MSFT','notebook')", () => {
    const { sc, open } = fresh();
    open(makeDoc("nb2", [makeCell("ticker = 'MSFT'")]));
    assert.deepEqual(sc.calls, [["MSFT", "notebook"]]);
  });

  test("x = 5 does not match", () => {
    const { sc, open } = fresh();
    open(makeDoc("nb3", [makeCell("x = 5")]));
    assert.equal(sc.calls.length, 0);
  });

  test('# symbol = "AAPL" still matches (dumb parsing)', () => {
    const { sc, open } = fresh();
    open(makeDoc("nb4", [makeCell('# symbol = "AAPL"')]));
    assert.deepEqual(sc.calls, [["AAPL", "notebook"]]);
  });

  test("two rapid changes same symbol within 300ms = one call", () => {
    const { sc, change } = fresh();
    const cell = makeCell('symbol = "AAPL"');
    const nb = { uri: { toString: () => "nb5" } };
    change({ notebook: nb, cellChanges: [{ cell }], contentChanges: [] });
    change({ notebook: nb, cellChanges: [{ cell }], contentChanges: [] });
    assert.equal(sc.calls.length, 1);
  });

  test("multiple cells different symbols -> last write wins", () => {
    const { sc, open } = fresh();
    open(makeDoc("nb6", [
      makeCell('symbol = "AAPL"'),
      makeCell('ticker = "MSFT"'),
      makeCell('symbol = "GOOG"'),
    ]));
    assert.equal(sc.calls.length, 1);
    assert.deepEqual(sc.calls[0], ["GOOG", "notebook"]);
  });
}
