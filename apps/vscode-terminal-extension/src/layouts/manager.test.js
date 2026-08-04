// Unit tests for LayoutManager CRUD + workspace export/import (#1831).
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
    assert.ok(false, `expected ${compiledPath} to exist`);
  });
} else {
  const files = new Map(); // fsPath -> Buffer
  const dirs = new Set(); // fsPath

  function makeUri(fsPath) {
    return {
      fsPath,
      toString() {
        return `file://${fsPath.replace(/\\/g, "/")}`;
      },
    };
  }

  const FileType = { Unknown: 0, File: 1, Directory: 2, SymbolicLink: 64 };

  const fakeVscode = {
    FileType,
    Uri: {
      file(fsPath) {
        return makeUri(fsPath);
      },
      joinPath(base, ...segs) {
        return makeUri(path.join(base.fsPath, ...segs));
      },
    },
    workspace: {
      fs: {
        async readDirectory(uri) {
          if (!dirs.has(uri.fsPath)) {
            const err = new Error("ENOENT");
            err.code = "FileNotFound";
            throw err;
          }
          const prefix = uri.fsPath + path.sep;
          const out = [];
          for (const f of files.keys()) {
            if (f.startsWith(prefix)) {
              const name = f.slice(prefix.length);
              if (!name.includes(path.sep)) {
                out.push([name, FileType.File]);
              }
            }
          }
          return out;
        },
        async readFile(uri) {
          const b = files.get(uri.fsPath);
          if (!b) {
            const err = new Error("not found");
            err.code = "FileNotFound";
            throw err;
          }
          return b;
        },
        async writeFile(uri, data) {
          dirs.add(path.dirname(uri.fsPath));
          files.set(uri.fsPath, Buffer.from(data));
        },
        async createDirectory(uri) {
          dirs.add(uri.fsPath);
        },
      },
    },
  };

  // Inject fake vscode via require.cache under a synthetic id.
  const fakeVscodePath = path.join(__dirname, "__vscode_manager_stub.js");
  fs.writeFileSync(fakeVscodePath, "module.exports = {};");
  const cached = require(fakeVscodePath);
  Object.assign(cached, fakeVscode);

  const origResolve = Module._resolveFilename;
  Module._resolveFilename = function (request, parent, ...rest) {
    if (request === "vscode") {
      return fakeVscodePath;
    }
    return origResolve.call(this, request, parent, ...rest);
  };
  const { LayoutManager } = require(compiledPath);
  Module._resolveFilename = origResolve;

  function makeContext() {
    const store = new Map();
    return {
      globalState: {
        get(key, def) {
          return store.has(key) ? store.get(key) : def;
        },
        async update(key, value) {
          store.set(key, value);
        },
      },
      subscriptions: [],
    };
  }

  const BUILTINS = [
    {
      id: "portfolio-overview",
      name: "Portfolio Overview",
      gridTemplate: "12-col",
      slots: [{ widgetId: "w1", col: 1, span: 6 }],
    },
  ];

  function makeManager(workspaceRoot) {
    const ctx = makeContext();
    const mgr = new LayoutManager(ctx, {
      getBuiltinLayouts: async () => BUILTINS,
      workspaceRoot,
    });
    return { mgr, ctx };
  }

  test("listAll returns three buckets", async () => {
    const { mgr } = makeManager();
    const b = await mgr.listAll();
    assert.equal(b.builtins.length, 1);
    assert.equal(b.user.length, 0);
    assert.equal(b.workspace.length, 0);
  });

  test("createLayout with no template yields empty slots", async () => {
    const { mgr } = makeManager();
    const l = await mgr.createLayout("My One");
    assert.equal(l.name, "My One");
    assert.equal(l.slots.length, 0);
    assert.equal(l.schemaVersion, 1);
    assert.equal(l.gridTemplate, "12-col");
    const b = await mgr.listAll();
    assert.equal(b.user.length, 1);
  });

  test("createLayout from template clones slots", async () => {
    const { mgr } = makeManager();
    const l = await mgr.createLayout("Cloned", "portfolio-overview");
    assert.equal(l.slots.length, 1);
    assert.notEqual(l.id, "portfolio-overview");
    assert.equal(l.slots[0].widgetId, "w1");
  });

  test("renameLayout updates name", async () => {
    const { mgr } = makeManager();
    const l = await mgr.createLayout("A");
    await mgr.renameLayout(l.id, "B");
    const b = await mgr.listAll();
    assert.equal(b.user[0].name, "B");
  });

  test("duplicateLayout copies with new id and (copy) suffix", async () => {
    const { mgr } = makeManager();
    const l = await mgr.createLayout("Src");
    const dup = await mgr.duplicateLayout(l.id);
    assert.notEqual(dup.id, l.id);
    assert.match(dup.name, / \(copy\)$/);
  });

  test("deleteLayout throws for built-in id", async () => {
    const { mgr } = makeManager();
    await assert.rejects(() => mgr.deleteLayout("portfolio-overview"), /built-in/);
  });

  test("exportToWorkspace writes JSON file", async () => {
    files.clear();
    dirs.clear();
    const root = path.join(__dirname, "__ws_root__");
    const { mgr } = makeManager(root);
    const l = await mgr.createLayout("Exportable");
    const uri = await mgr.exportToWorkspace(l.id);
    assert.match(uri.fsPath, /exportable\.json$/);
    const buf = files.get(uri.fsPath);
    assert.ok(buf, "file written");
    const parsed = JSON.parse(buf.toString("utf-8"));
    assert.equal(parsed.name, "Exportable");
  });

  test("importFromFile validates and persists", async () => {
    files.clear();
    dirs.clear();
    const { mgr } = makeManager();
    const valid = {
      id: "imp-1",
      name: "Imported",
      gridTemplate: "12-col",
      slots: [{ widgetId: "wX", col: 1, span: 4 }],
    };
    const uri = fakeVscode.Uri.file(
      path.join(__dirname, "__ws_root__", "imp.json"),
    );
    files.set(uri.fsPath, Buffer.from(JSON.stringify(valid)));
    const layout = await mgr.importFromFile(uri);
    assert.equal(layout.name, "Imported");
    assert.equal(layout.schemaVersion, 1);
    const b = await mgr.listAll();
    assert.equal(b.user.length, 1);

    const bad = { id: "", name: "", gridTemplate: "12-col", slots: [] };
    const badUri = fakeVscode.Uri.file(
      path.join(__dirname, "__ws_root__", "bad.json"),
    );
    files.set(badUri.fsPath, Buffer.from(JSON.stringify(bad)));
    await assert.rejects(() => mgr.importFromFile(badUri), /invalid layout/);
  });
}
