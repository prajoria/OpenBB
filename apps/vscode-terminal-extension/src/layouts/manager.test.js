"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const fsp = require("node:fs/promises");

const compiled = path.join(__dirname, "..", "..", "out", "layouts", "manager.js");
if (!fs.existsSync(compiled)) {
  throw new Error(`compiled manager.js missing: ${compiled} (run npm run compile)`);
}

const Module = require("node:module");
const origResolve = Module._resolveFilename;
const fakeVscodePath = path.join(__dirname, "__vscode_stub_mgr.js");
fs.writeFileSync(
  fakeVscodePath,
  "module.exports = { Uri: { file: (p) => ({ fsPath: p, scheme: 'file' }) } };",
);
Module._resolveFilename = function (request, parent, ...rest) {
  if (request === "vscode") {
    return fakeVscodePath;
  }
  return origResolve.call(this, request, parent, ...rest);
};
const { LayoutManager, USER_LAYOUTS_KEY } = require(compiled);
Module._resolveFilename = origResolve;

function makeMemento() {
  const store = new Map();
  return {
    store,
    get(key, def) {
      return store.has(key) ? store.get(key) : def;
    },
    update(key, value) {
      store.set(key, value);
      return Promise.resolve();
    },
  };
}

function makeContext() {
  return { globalState: makeMemento() };
}

const BUILTIN = {
  id: "portfolio-overview",
  name: "Portfolio Overview",
  gridTemplate: "12-col",
  slots: [{ widgetId: "w1", col: 1, span: 4, row: 1 }],
};

function makeManager(opts = {}) {
  const ctx = makeContext();
  const workspaceRoot =
    opts.workspaceRoot ?? fs.mkdtempSync(path.join(os.tmpdir(), "obb-layouts-"));
  const mgr = new LayoutManager(ctx, {
    getBuiltinLayouts: async () => [BUILTIN],
    workspaceRoot,
  });
  return { mgr, ctx, workspaceRoot };
}

test("createLayout produces a fresh Layout with a unique id", async () => {
  const { mgr } = makeManager();
  const a = await mgr.createLayout("A");
  const b = await mgr.createLayout("B");
  assert.notEqual(a.id, b.id);
  assert.equal(a.name, "A");
  assert.equal(a.schemaVersion, 1);
});

test("renameLayout throws when target id missing", async () => {
  const { mgr } = makeManager();
  await assert.rejects(() => mgr.renameLayout("nope", "x"), /not found/);
});

test("duplicateLayout produces new id and name suffix '(copy)'", async () => {
  const { mgr } = makeManager();
  const orig = await mgr.createLayout("Alpha");
  const dup = await mgr.duplicateLayout(orig.id);
  assert.notEqual(dup.id, orig.id);
  assert.equal(dup.name, "Alpha (copy)");
});

test("deleteLayout on builtin throws", async () => {
  const { mgr } = makeManager();
  await assert.rejects(() => mgr.deleteLayout("portfolio-overview"), /built-in/);
});

test("deleteLayout on user removes from globalState", async () => {
  const { mgr, ctx } = makeManager();
  const l = await mgr.createLayout("Doomed");
  await mgr.deleteLayout(l.id);
  const map = ctx.globalState.get(USER_LAYOUTS_KEY, {});
  assert.equal(map[l.id], undefined);
});

test("listAll merges user + builtin + workspace with no duplicates", async () => {
  const { mgr, workspaceRoot } = makeManager();
  const wsDir = path.join(workspaceRoot, ".openbb", "layouts");
  await fsp.mkdir(wsDir, { recursive: true });
  const wsLayout = {
    schemaVersion: 1,
    id: "ws-only",
    name: "WS Only",
    gridTemplate: "12-col",
    slots: [{ widgetId: "w1", col: 1, span: 4, row: 1 }],
  };
  await fsp.writeFile(path.join(wsDir, "ws.json"), JSON.stringify(wsLayout));
  await mgr.createLayout("User A");
  const all = await mgr.listAll();
  const allIds = [
    ...all.builtins.map((l) => l.id),
    ...all.user.map((l) => l.id),
    ...all.workspace.map((l) => l.id),
  ];
  assert.equal(new Set(allIds).size, allIds.length, "no duplicate ids");
  assert.ok(all.workspace.some((l) => l.id === "ws-only"));
  assert.ok(all.builtins.some((l) => l.id === "portfolio-overview"));
  assert.equal(all.user.length, 1);
});

test("exportToWorkspace writes valid JSON to .openbb/layouts/", async () => {
  const { mgr } = makeManager();
  const l = await mgr.createLayout("Export Me");
  const uri = await mgr.exportToWorkspace(l.id);
  const written = JSON.parse(await fsp.readFile(uri.fsPath, "utf-8"));
  assert.equal(written.id, l.id);
  assert.equal(written.schemaVersion, 1);
  assert.ok(uri.fsPath.includes(path.join(".openbb", "layouts")));
});

test("importFromFile rejects invalid slot overflow", async () => {
  const { mgr, workspaceRoot } = makeManager();
  const bad = {
    schemaVersion: 1,
    id: "bad",
    name: "Bad",
    gridTemplate: "12-col",
    slots: [{ widgetId: "w1", col: 10, span: 8, row: 1 }],
  };
  const tmp = path.join(workspaceRoot, "bad.json");
  await fsp.writeFile(tmp, JSON.stringify(bad));
  const uri = { fsPath: tmp };
  await assert.rejects(() => mgr.importFromFile(uri), /invalid layout/);
});
