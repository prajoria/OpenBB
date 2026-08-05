// Unit tests for guided API-key manager (#1836).

const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");

const compiledPath = path.join(
  __dirname,
  "..",
  "..",
  "out",
  "apikey",
  "manager.js",
);

if (!fs.existsSync(compiledPath)) {
  test("manager.ts compiled output missing — run npm run compile", () => {
    assert.ok(fs.existsSync(compiledPath), `expected ${compiledPath}`);
  });
} else {
  const { ApiKeyManager, KNOWN_KEYS } = require(compiledPath);

  function makeMemFs(initial = {}) {
    const store = new Map(Object.entries(initial));
    const chmods = [];
    return {
      store,
      chmods,
      async readFile(p) {
        if (!store.has(p)) {
          const err = new Error("ENOENT");
          err.code = "ENOENT";
          throw err;
        }
        return store.get(p);
      },
      async writeFile(p, content, _opts) {
        store.set(p, content);
      },
      async access(p) {
        if (!store.has(p)) {
          const err = new Error("ENOENT");
          err.code = "ENOENT";
          throw err;
        }
      },
      async rename(from, to) {
        if (!store.has(from)) {
          const err = new Error("ENOENT");
          err.code = "ENOENT";
          throw err;
        }
        store.set(to, store.get(from));
        store.delete(from);
      },
      async mkdir() {
        // no-op
      },
      async chmod(p, mode) {
        chmods.push({ path: p, mode });
      },
      async unlink(p) {
        store.delete(p);
      },
    };
  }

  test("KNOWN_KEYS contains fmp/fmp_cached/fred at minimum", () => {
    assert.ok(KNOWN_KEYS.includes("fmp_api_key"));
    assert.ok(KNOWN_KEYS.includes("fmp_cached_api_key"));
    assert.ok(KNOWN_KEYS.includes("fred_api_key"));
  });

  test("resolvePath returns config override when set", () => {
    const mgr = new ApiKeyManager({
      userSettingsPath: "C:/tmp/custom.json",
      fsPromises: makeMemFs(),
      homedir: () => "C:/Users/x",
    });
    assert.equal(mgr.resolvePath(), "C:/tmp/custom.json");
  });

  test("resolvePath falls back to homedir + .openbb_platform/user_settings.json", () => {
    const mgr = new ApiKeyManager({
      fsPromises: makeMemFs(),
      homedir: () => "/home/tester",
    });
    const p = mgr.resolvePath();
    assert.ok(p.includes(".openbb_platform"));
    assert.ok(p.endsWith("user_settings.json"));
  });

  test("readSettings returns empty parsed when file missing", async () => {
    const mgr = new ApiKeyManager({
      userSettingsPath: "/x/missing.json",
      fsPromises: makeMemFs(),
    });
    const result = await mgr.readSettings();
    assert.equal(result.content, "");
    assert.deepEqual(result.parsed, {});
    assert.equal(result.path, "/x/missing.json");
  });

  test("readSettings returns parsed JSON when file exists", async () => {
    const mgr = new ApiKeyManager({
      userSettingsPath: "/x/us.json",
      fsPromises: makeMemFs({
        "/x/us.json": JSON.stringify({ credentials: {} }),
      }),
    });
    const result = await mgr.readSettings();
    assert.ok(result.parsed);
    assert.ok(result.parsed.credentials);
  });

  test("writeSettings creates a .bak before overwrite when file exists (deleteBak=false preserves it)", async () => {
    const mem = makeMemFs({ "/x/us.json": '{"old":1}' });
    const mgr = new ApiKeyManager({
      userSettingsPath: "/x/us.json",
      fsPromises: mem,
      deleteBak: false,
    });
    await mgr.writeSettings('{"new":2}');
    assert.equal(mem.store.get("/x/us.json"), '{"new":2}');
    assert.equal(mem.store.get("/x/us.json.bak"), '{"old":1}');
  });

  test("writeSettings deletes .bak after successful write by default (#1856)", async () => {
    const mem = makeMemFs({ "/x/us.json": '{"old":1}' });
    const mgr = new ApiKeyManager({
      userSettingsPath: "/x/us.json",
      fsPromises: mem,
    });
    await mgr.writeSettings('{"new":2}');
    assert.equal(mem.store.get("/x/us.json"), '{"new":2}');
    assert.equal(
      mem.store.has("/x/us.json.bak"),
      false,
      ".bak should be removed after successful write",
    );
  });

  test("writeSettings chmods the target file 0600 (#1856)", async () => {
    const mem = makeMemFs();
    const mgr = new ApiKeyManager({
      userSettingsPath: "/x/us.json",
      fsPromises: mem,
    });
    await mgr.writeSettings('{"first":1}');
    const targetChmod = mem.chmods.find((c) => c.path === "/x/us.json");
    assert.ok(targetChmod, "expected chmod on target");
    assert.equal(targetChmod.mode, 0o600);
  });

  test("writeSettings chmods .bak 0600 before overwrite (#1856)", async () => {
    const mem = makeMemFs({ "/x/us.json": '{"old":1}' });
    const mgr = new ApiKeyManager({
      userSettingsPath: "/x/us.json",
      fsPromises: mem,
      deleteBak: false,
    });
    await mgr.writeSettings('{"new":2}');
    const bakChmod = mem.chmods.find((c) => c.path === "/x/us.json.bak");
    assert.ok(bakChmod, "expected chmod on .bak");
    assert.equal(bakChmod.mode, 0o600);
  });

  test("writeSettings does not create .bak if no prior file exists", async () => {
    const mem = makeMemFs();
    const mgr = new ApiKeyManager({
      userSettingsPath: "/x/us.json",
      fsPromises: mem,
    });
    await mgr.writeSettings('{"first":1}');
    assert.equal(mem.store.get("/x/us.json"), '{"first":1}');
    assert.equal(mem.store.has("/x/us.json.bak"), false);
  });
}
