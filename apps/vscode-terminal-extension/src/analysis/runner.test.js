// Unit tests for AnalysisRunner (#1828).

const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const { EventEmitter } = require("node:events");
const Module = require("node:module");

const compiledPath = path.join(
  __dirname,
  "..",
  "..",
  "out",
  "analysis",
  "runner.js",
);

if (!fs.existsSync(compiledPath)) {
  test("runner.ts compiled output missing — run npm run compile", () => {
    assert.ok(fs.existsSync(compiledPath), `expected ${compiledPath}`);
  });
} else {
  const openNotebookCalls = [];
  const showNotebookCalls = [];
  const fakeVscode = {
    NotebookCellData: class {
      constructor(kind, value, language) {
        this.kind = kind;
        this.value = value;
        this.languageId = language;
      }
    },
    NotebookData: class {
      constructor(cells) {
        this.cells = cells;
        this.metadata = undefined;
      }
    },
    NotebookCellKind: { Markup: 1, Code: 2 },
    Uri: { parse: (s) => ({ toString: () => s, fsPath: s }) },
    workspace: {
      async openNotebookDocument(kind, data) {
        openNotebookCalls.push({ kind, data });
        return { uri: { fsPath: "untitled://analysis.ipynb" } };
      },
      workspaceFolders: undefined,
    },
    window: {
      async showNotebookDocument(doc) {
        showNotebookCalls.push(doc);
        return {};
      },
    },
  };
  const fakeVscodePath = path.join(__dirname, "__runner_vscode_stub.js");
  fs.writeFileSync(
    fakeVscodePath,
    `module.exports = require(${JSON.stringify(__filename)}).__fakeVscode;`,
  );
  module.exports.__fakeVscode = fakeVscode;

  const origResolve = Module._resolveFilename;
  Module._resolveFilename = function (request, parent, ...rest) {
    if (request === "vscode") return fakeVscodePath;
    return origResolve.call(this, request, parent, ...rest);
  };
  const { AnalysisRunner, SYMBOL_RE, buildAnalysisNotebookCells } = require(
    compiledPath,
  );
  Module._resolveFilename = origResolve;

  function makeChannel() {
    return { lines: [], appendLine(l) { this.lines.push(l); } };
  }

  function makeSpawn({ exitCode = 0, stdout = "ok\n", stderr = "", throwOn = false } = {}) {
    const calls = [];
    const impl = (cmd, args, opts) => {
      calls.push({ cmd, args, opts });
      if (throwOn) throw new Error("spawn failed");
      const child = new EventEmitter();
      child.stdout = new EventEmitter();
      child.stderr = new EventEmitter();
      child.kill = () => {};
      setImmediate(() => {
        if (stdout) child.stdout.emit("data", stdout);
        if (stderr) child.stderr.emit("data", stderr);
        child.emit("close", exitCode);
      });
      return child;
    };
    impl.calls = calls;
    return impl;
  }

  test("resolvePython returns setting value when set", () => {
    const r = new AnalysisRunner({
      pythonPath: "C:/x/python.exe",
      outputChannel: makeChannel(),
      spawnImpl: makeSpawn(),
    });
    assert.equal(r.resolvePython(), "C:/x/python.exe");
  });

  test("resolvePython falls back to 'python' when setting empty", () => {
    const r = new AnalysisRunner({
      pythonPath: "",
      outputChannel: makeChannel(),
      spawnImpl: makeSpawn(),
    });
    assert.equal(r.resolvePython(), "python");
  });

  test("resolvePython falls back when setting whitespace only", () => {
    const r = new AnalysisRunner({
      pythonPath: "   ",
      outputChannel: makeChannel(),
      spawnImpl: makeSpawn(),
    });
    assert.equal(r.resolvePython(), "python");
  });

  test("ensureAnalysisModule spawns python -c import stock_analysis", async () => {
    const spawnImpl = makeSpawn({ exitCode: 0, stdout: "ok\n" });
    const r = new AnalysisRunner({
      pythonPath: "python3",
      outputChannel: makeChannel(),
      spawnImpl,
    });
    const res = await r.ensureAnalysisModule();
    assert.equal(res.ok, true);
    assert.equal(spawnImpl.calls.length, 1);
    assert.equal(spawnImpl.calls[0].cmd, "python3");
    assert.deepEqual(spawnImpl.calls[0].args, [
      "-c",
      "import stock_analysis; print('ok')",
    ]);
  });

  test("ensureAnalysisModule returns friendly error on non-zero exit", async () => {
    const spawnImpl = makeSpawn({
      exitCode: 1,
      stdout: "",
      stderr: "ModuleNotFoundError",
    });
    const r = new AnalysisRunner({
      pythonPath: "python",
      outputChannel: makeChannel(),
      spawnImpl,
    });
    const res = await r.ensureAnalysisModule();
    assert.equal(res.ok, false);
    assert.match(res.message, /Analysis\/ module not found/);
  });

  test("symbol regex rejects invalid symbols", () => {
    assert.equal(SYMBOL_RE.test("aapl"), false);
    assert.equal(SYMBOL_RE.test("AAPLEX"), false);
    assert.equal(SYMBOL_RE.test(""), false);
    assert.equal(SYMBOL_RE.test("A B"), false);
    assert.equal(SYMBOL_RE.test("AAPL"), true);
    assert.equal(SYMBOL_RE.test("A"), true);
    assert.equal(SYMBOL_RE.test("AAPL:NASDAQ"), true);
  });

  test("buildAnalysisNotebookCells produces 3 cells with symbol interpolated", () => {
    const cells = buildAnalysisNotebookCells("MSFT");
    assert.equal(cells.length, 3);
    assert.equal(cells[0].kind, 1);
    assert.match(cells[0].value, /7-Phase Analysis — MSFT/);
    assert.equal(cells[1].kind, 2);
    assert.match(cells[1].value, /AnalysisConfig\(symbol="MSFT"\)/);
    assert.match(cells[1].value, /run_full_analysis/);
    assert.equal(cells[2].kind, 2);
    assert.match(cells[2].value, /Phase-by-phase results/);
  });

  test("runForSymbol rejects invalid symbol without spawning", async () => {
    const spawnImpl = makeSpawn();
    const r = new AnalysisRunner({
      pythonPath: "python",
      outputChannel: makeChannel(),
      spawnImpl,
    });
    const res = await r.runForSymbol("aapl");
    assert.equal(res.notebookUri, null);
    assert.match(res.error, /Invalid symbol/);
    assert.equal(spawnImpl.calls.length, 0);
  });

  test("runForSymbol opens notebook via openNotebookDocument on success", async () => {
    openNotebookCalls.length = 0;
    showNotebookCalls.length = 0;
    const spawnImpl = makeSpawn({ exitCode: 0, stdout: "ok\n" });
    const r = new AnalysisRunner({
      pythonPath: "python",
      outputChannel: makeChannel(),
      spawnImpl,
    });
    const res = await r.runForSymbol("MSFT");
    assert.equal(openNotebookCalls.length, 1);
    assert.equal(openNotebookCalls[0].kind, "jupyter-notebook");
    assert.equal(openNotebookCalls[0].data.cells.length, 3);
    assert.equal(showNotebookCalls.length, 1);
    assert.ok(res.notebookUri, "should return uri");
    assert.equal(res.error, undefined);
  });

  test("runForSymbol returns error when ensureAnalysisModule fails; no notebook opened", async () => {
    openNotebookCalls.length = 0;
    const spawnImpl = makeSpawn({ exitCode: 1, stderr: "no module" });
    const r = new AnalysisRunner({
      pythonPath: "python",
      outputChannel: makeChannel(),
      spawnImpl,
    });
    const res = await r.runForSymbol("MSFT");
    assert.equal(res.notebookUri, null);
    assert.match(res.error, /Analysis\/ module not found/);
    assert.equal(openNotebookCalls.length, 0);
  });
}
