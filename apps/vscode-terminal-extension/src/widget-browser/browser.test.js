// Widget Browser tree provider tests (#1830).
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
  "widget-browser",
  "browser.js",
);

if (!fs.existsSync(compiledPath)) {
  test("browser.ts compiled output missing — run npm run compile", () => {
    assert.ok(fs.existsSync(compiledPath), `expected ${compiledPath} to exist`);
  });
} else {
  // vscode stub — minimal API surface needed by browser.ts.
  const fakeVscodePath = path.join(__dirname, "__vscode_stub_browser.js");
  fs.writeFileSync(
    fakeVscodePath,
    `
    class EventEmitter {
      constructor() { this._listeners = []; }
      get event() {
        return (fn) => { this._listeners.push(fn); return { dispose: () => {} }; };
      }
      fire(v) { for (const fn of this._listeners) fn(v); }
    }
    class TreeItem {
      constructor(label, collapsibleState) {
        this.label = label;
        this.collapsibleState = collapsibleState;
      }
    }
    class ThemeIcon { constructor(id) { this.id = id; } }
    class DataTransferItem { constructor(value) { this.value = value; } }
    module.exports = {
      EventEmitter,
      TreeItem,
      TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 },
      ThemeIcon,
      DataTransferItem,
      window: {
        createTreeView(_id, _opts) {
          return { dispose() {} };
        },
      },
    };
    `,
  );
  const origResolve = Module._resolveFilename;
  Module._resolveFilename = function (r, p, ...rest) {
    if (r === "vscode") return fakeVscodePath;
    return origResolve.call(this, r, p, ...rest);
  };
  const { WidgetBrowserTreeProvider } = require(compiledPath);
  Module._resolveFilename = origResolve;

  const mkMeta = (id, type = "metric") => ({
    id,
    name: id.toUpperCase(),
    type,
    endpoint: `/${id}`,
    category: "test",
  });

  const mkProvider = (widgets) =>
    new WidgetBrowserTreeProvider({
      getManifest: async () => widgets,
    });

  test("root children ordered pi_, tt_, portfolio_, regime_, other", async () => {
    const p = mkProvider([
      mkMeta("regime_x"),
      mkMeta("other_z"),
      mkMeta("tt_a"),
      mkMeta("portfolio_b"),
      mkMeta("pi_c"),
    ]);
    const roots = await p.getChildren();
    const prefixes = roots.map((r) => r.prefix);
    assert.deepEqual(prefixes, ["pi_", "tt_", "portfolio_", "regime_", "other"]);
  });

  test("pi_ prefix count matches number of pi_ widgets", async () => {
    const p = mkProvider([
      mkMeta("pi_a"),
      mkMeta("pi_b"),
      mkMeta("pi_c"),
      mkMeta("tt_x"),
    ]);
    const roots = await p.getChildren();
    const piNode = roots.find((r) => r.prefix === "pi_");
    assert.equal(piNode.count, 3);
  });

  test("tt_ children sorted alpha by id", async () => {
    const p = mkProvider([
      mkMeta("tt_zebra"),
      mkMeta("tt_alpha"),
      mkMeta("tt_mango"),
    ]);
    const children = await p.getChildren({
      kind: "prefix",
      prefix: "tt_",
      count: 3,
    });
    assert.deepEqual(
      children.map((c) => c.meta.id),
      ["tt_alpha", "tt_mango", "tt_zebra"],
    );
  });

  test("unknown-prefix widget appears under 'other'", async () => {
    const p = mkProvider([mkMeta("weird_name"), mkMeta("pi_ok")]);
    const roots = await p.getChildren();
    const other = roots.find((r) => r.prefix === "other");
    assert.ok(other, "'other' group exists");
    assert.equal(other.count, 1);
    const kids = await p.getChildren(other);
    assert.equal(kids[0].meta.id, "weird_name");
  });

  test("empty manifest yields [] from root getChildren", async () => {
    const p = mkProvider([]);
    const roots = await p.getChildren();
    assert.deepEqual(roots, []);
  });

  test("refresh() fires onDidChangeTreeData event", () => {
    const p = mkProvider([mkMeta("pi_a")]);
    let fired = 0;
    p.onDidChangeTreeData(() => {
      fired += 1;
    });
    p.refresh();
    assert.equal(fired, 1);
  });
}
