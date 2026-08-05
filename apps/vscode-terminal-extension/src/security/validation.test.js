// Unit tests for workspace-trust settings validators (#1856).

const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");

const compiledPath = path.join(
  __dirname,
  "..",
  "..",
  "out",
  "security",
  "validation.js",
);

if (!fs.existsSync(compiledPath)) {
  test("validation.ts compiled output missing — run npm run compile", () => {
    assert.ok(fs.existsSync(compiledPath), `expected ${compiledPath}`);
  });
} else {
  const {
    isLoopbackHost,
    isSafeApiBaseUrl,
    isAbsolutePath,
    isSafePythonPath,
  } = require(compiledPath);

  test("isLoopbackHost accepts 127.0.0.1 / ::1 / localhost (any case)", () => {
    assert.equal(isLoopbackHost("127.0.0.1"), true);
    assert.equal(isLoopbackHost("::1"), true);
    assert.equal(isLoopbackHost("[::1]"), true);
    assert.equal(isLoopbackHost("localhost"), true);
    assert.equal(isLoopbackHost("LocalHost"), true);
  });

  test("isLoopbackHost rejects non-loopback hosts", () => {
    assert.equal(isLoopbackHost("evil.com"), false);
    assert.equal(isLoopbackHost("192.168.1.1"), false);
    assert.equal(isLoopbackHost("169.254.169.254"), false);
    assert.equal(isLoopbackHost(""), false);
  });

  test("isSafeApiBaseUrl accepts loopback http(s) URLs", () => {
    assert.equal(isSafeApiBaseUrl("http://127.0.0.1:6900").ok, true);
    assert.equal(isSafeApiBaseUrl("http://localhost:6900/").ok, true);
    assert.equal(isSafeApiBaseUrl("https://127.0.0.1:8443").ok, true);
    assert.equal(isSafeApiBaseUrl("http://[::1]:6900").ok, true);
  });

  test("isSafeApiBaseUrl rejects non-loopback host", () => {
    const r = isSafeApiBaseUrl("http://evil.com/");
    assert.equal(r.ok, false);
    assert.match(r.reason, /loopback/);
  });

  test("isSafeApiBaseUrl rejects non-http(s) protocol", () => {
    const r = isSafeApiBaseUrl("file:///etc/passwd");
    assert.equal(r.ok, false);
    assert.match(r.reason, /protocol/);
  });

  test("isSafeApiBaseUrl rejects malformed URL", () => {
    const r = isSafeApiBaseUrl("not-a-url");
    assert.equal(r.ok, false);
    assert.match(r.reason, /invalid/);
  });

  test("isSafePythonPath rejects empty", () => {
    const r = isSafePythonPath("");
    assert.equal(r.ok, false);
    assert.match(r.reason, /empty/);
  });

  test("isSafePythonPath rejects relative path", () => {
    const r = isSafePythonPath("python");
    assert.equal(r.ok, false);
    assert.match(r.reason, /absolute/);
  });

  test("isSafePythonPath rejects paths with shell metachars", () => {
    const abs = process.platform === "win32" ? "C:\\a;b\\python.exe" : "/a;b/python";
    const r = isSafePythonPath(abs);
    assert.equal(r.ok, false);
    assert.match(r.reason, /metachar/);
    const abs2 = process.platform === "win32" ? "C:\\bin\\py`x`.exe" : "/bin/py`x`";
    assert.equal(isSafePythonPath(abs2).ok, false);
  });

  test("isSafePythonPath accepts an absolute clean path", () => {
    const abs =
      process.platform === "win32"
        ? "C:\\Python312\\python.exe"
        : "/usr/bin/python3";
    assert.equal(isSafePythonPath(abs).ok, true);
  });

  test("isAbsolutePath matches path.isAbsolute semantics", () => {
    assert.equal(isAbsolutePath("relative/path"), false);
    const abs = process.platform === "win32" ? "C:\\x" : "/x";
    assert.equal(isAbsolutePath(abs), true);
  });
}
