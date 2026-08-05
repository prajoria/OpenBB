// Unit tests for LayoutManager (#1831).

"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const Module = require("node:module");

const compiledPath = path.join(
  __dirname,
  "..",
  "..",
  "out",
  "layouts",
  "manager.js",
);

if (!fs.existsSync(compiledPath)) {
  test("manager.ts compiled output missing — run npm run compile", () => {
    assert.ok(fs.existsSync(compiledPath), `expected ${compiledPath} to exist`);
  });
} else {
  // Stub vscode module.
  const fakeVscodePath = path.join(__dirname, "__vscode_stub.js");
  fs.writeFileSync(
    fakeVscodePath,
    `
"use strict";
class Uri {
  constructor(fsPath) { this.fsPath = fsPath; this.path = fsPath; this.scheme = "file"; }
  static file(p) { return new Uri(p); }
  static joinPath(base, ...parts) { return new Uri([base.fsPath, ...parts].join("/")); }
  toString() { return "file://" + this.fsPath; }
}
const FileType = { Unknown: 0, File: 1, Directory: 2 };
module.exports = { Uri, FileType, workspace: { fs: {} } };
`,
  );
  const origResolve = Module._resolveFilename;
  Module._resolveFilename = function (req, parent, ...rest) {
    if (req === "vscode") return fakeVscodePath;
    return origResolve.call(this, req, parent, ...rest);
  };
  const { LayoutManager, toSlug } = require(compiledPath);
  Module._resolveFilename = origResolve;

  function makeMemento() {
    const store = new Map();
    return {
      get(k) {
        return store.get(k);
      },
      update(k, v) {
        if (v === undefined) store.delete(k);
        else store.set(k, v);
        return Promise.resolve();
      },
      _store: store,
    };
  }

  function makeContext() {
    return { globalState: makeMemento(), subscriptions: [] };
  }

  const BUILTIN_A = {
    id: "portfolio-overview",
    name: "Portfolio Overview",
    gridTemplate: "12-col",
    slots: [{ widgetId: "w1", col: 1, span: 6 }],
  };
  const BUILTIN_B = {
    id: "equity-deep-dive",
    name: "Equity Deep-Dive",
    gridTemplate: "12-col",
    slots: [{ widgetId: "w2", col: 1, span: 12 }],
  };
  const getBuiltins = async () => [BUILTIN_A, BUILTIN_B];

  function makeMemFs() {
    const files = new Map();
    const dirs = new Set();
    return {
      files,
      dirs,
      async readFile(uri) {
        if (!files.has(uri.fsPath)) throw new Error("ENOENT " + uri.fsPath);
        return files.get(uri.fsPath);
      },
      async writeFile(uri, bytes) {
        files.set(uri.fsPath, bytes);
      },
      async createDirectory(uri) {
        dirs.add(uri.fsPath);
      },
      async stat(uri) {
        if (dirs.has(uri.fsPath) || files.has(uri.fsPath)) return { type: 2 };
        throw new Error("ENOENT " + uri.fsPath);
      },
    };
  }

  test("createLayout produces schemaVersion:1 empty slots persisted", async () => {
    const ctx = makeContext();
    const fsx = makeMemFs();
    const mgr = new LayoutManager(ctx, { getBuiltinLayouts: getBuiltins, fs: fsx });
    const l = await mgr.createLayout("Alpha");
    assert.equal(l.schemaVersion, 1);
    assert.equal(l.name, "Alpha");
    assert.deepEqual(l.slots, []);
    const stored = ctx.globalState.get("openbb.userLayouts");
    assert.ok(stored[l.id]);
    assert.equal(stored[l.id].schemaVersion, 1);
  });

  test("createLayout with template copies slots", async () => {
    const ctx = makeContext();
    const mgr = new LayoutManager(ctx, { getBuiltinLayouts: getBuiltins, fs: makeMemFs() });
    const l = await mgr.createLayout("MyCopy", "portfolio-overview");
    assert.equal(l.slots.length, 1);
    assert.equal(l.slots[0].widgetId, "w1");
  });

  test("createLayout with unknown template throws", async () => {
    const ctx = makeContext();
    const mgr = new LayoutManager(ctx, { getBuiltinLayouts: getBuiltins, fs: makeMemFs() });
    await assert.rejects(() => mgr.createLayout("Zzz", "does-not-exist"));
  });

  test("renameLayout on missing id throws", async () => {
    const ctx = makeContext();
    const mgr = new LayoutManager(ctx, { getBuiltinLayouts: getBuiltins, fs: makeMemFs() });
    await assert.rejects(() => mgr.renameLayout("nope", "X"));
  });

  test("duplicateLayout adds ' (copy)'", async () => {
    const ctx = makeContext();
    const mgr = new LayoutManager(ctx, { getBuiltinLayouts: getBuiltins, fs: makeMemFs() });
    const orig = await mgr.createLayout("Beta");
    const dup = await mgr.duplicateLayout(orig.id);
    assert.match(dup.name, / \(copy\)$/);
    assert.notEqual(dup.id, orig.id);
  });

  test("deleteLayout of builtin throws", async () => {
    const ctx = makeContext();
    const mgr = new LayoutManager(ctx, { getBuiltinLayouts: getBuiltins, fs: makeMemFs() });
    await assert.rejects(() => mgr.deleteLayout("portfolio-overview"));
  });

  test("deleteLayout of user removes it", async () => {
    const ctx = makeContext();
    const mgr = new LayoutManager(ctx, { getBuiltinLayouts: getBuiltins, fs: makeMemFs() });
    const l = await mgr.createLayout("Gamma");
    await mgr.deleteLayout(l.id);
    const stored = ctx.globalState.get("openbb.userLayouts");
    assert.ok(!stored[l.id]);
  });

  test("listAll returns 3 buckets", async () => {
    const ctx = makeContext();
    const mgr = new LayoutManager(ctx, { getBuiltinLayouts: getBuiltins, fs: makeMemFs() });
    await mgr.createLayout("Delta");
    const all = await mgr.listAll();
    assert.equal(all.builtins.length, 2);
    assert.equal(all.user.length, 1);
    assert.equal(all.workspace.length, 0);
  });

  test("exportToWorkspace writes JSON at slug URI", async () => {
    const ctx = makeContext();
    const fsx = makeMemFs();
    const mgr = new LayoutManager(ctx, {
      getBuiltinLayouts: getBuiltins,
      workspaceRoot: "/tmp/ws",
      fs: fsx,
    });
    const l = await mgr.createLayout("Epsilon");
    const uri = await mgr.exportToWorkspace(l.id);
    assert.match(uri.fsPath, /\.openbb\/layouts\/.*\.json$/);
    assert.ok(fsx.files.has(uri.fsPath));
    const parsed = JSON.parse(Buffer.from(fsx.files.get(uri.fsPath)).toString("utf-8"));
    assert.equal(parsed.schemaVersion, 1);
    assert.equal(parsed.name, "Epsilon");
  });

  test("exportToWorkspace without workspaceRoot throws", async () => {
    const ctx = makeContext();
    const mgr = new LayoutManager(ctx, { getBuiltinLayouts: getBuiltins, fs: makeMemFs() });
    const l = await mgr.createLayout("Zeta");
    await assert.rejects(() => mgr.exportToWorkspace(l.id));
  });

  test("importFromFile with invalid layout (col overflow) throws", async () => {
    const ctx = makeContext();
    const fsx = makeMemFs();
    const bad = {
      id: "bad",
      name: "Bad",
      gridTemplate: "12-col",
      slots: [{ widgetId: "x", col: 8, span: 20 }],
    };
    const uri = { fsPath: "/tmp/bad.json" };
    fsx.files.set(uri.fsPath, Buffer.from(JSON.stringify(bad), "utf-8"));
    const mgr = new LayoutManager(ctx, { getBuiltinLayouts: getBuiltins, fs: fsx });
    await assert.rejects(() => mgr.importFromFile(uri), /invalid|overflow|exceeds/i);
  });

  test("toSlug('My Portfolio!') -> 'my-portfolio'", () => {
    assert.equal(toSlug("My Portfolio!"), "my-portfolio");
  });
}
