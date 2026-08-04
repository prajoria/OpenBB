// node:test coverage for DataModeController (#1820).
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { DataModeController } = require("../../out/data/mode.js");

function makeController() {
  const changes = [];
  const c = new DataModeController({ onModeChange: (m) => changes.push(m) });
  return { c, changes };
}

test("initial mode is fixture", () => {
  const { c } = makeController();
  assert.equal(c.mode, "fixture");
});

test("transition to running -> live and fires onModeChange", () => {
  const { c, changes } = makeController();
  c.updateFromBackendState({ status: "running", port: 6900 });
  assert.equal(c.mode, "live");
  assert.deepEqual(changes, ["live"]);
});

test("back to stopped -> fixture", () => {
  const { c, changes } = makeController();
  c.updateFromBackendState({ status: "running", port: 6900 });
  c.updateFromBackendState({ status: "stopped", port: 6900 });
  assert.equal(c.mode, "fixture");
  assert.deepEqual(changes, ["live", "fixture"]);
});

test("no duplicate fires when state stays running", () => {
  const { c, changes } = makeController();
  c.updateFromBackendState({ status: "running", port: 6900 });
  c.updateFromBackendState({ status: "running", port: 6900 });
  c.updateFromBackendState({ status: "running", port: 6900 });
  assert.deepEqual(changes, ["live"]);
});

test("registerPanel immediately posts current mode", () => {
  const { c } = makeController();
  const posted = [];
  const panel = { webview: { postMessage: (m) => { posted.push(m); return true; } } };
  c.registerPanel(panel);
  assert.deepEqual(posted, [{ type: "dataModeChange", mode: "fixture" }]);
  c.updateFromBackendState({ status: "running", port: 6900 });
  assert.deepEqual(posted[1], { type: "dataModeChange", mode: "live" });
});

test("unregisterPanel stops future broadcasts", () => {
  const { c } = makeController();
  const posted = [];
  const panel = { webview: { postMessage: (m) => { posted.push(m); return true; } } };
  c.registerPanel(panel);
  c.unregisterPanel(panel);
  c.updateFromBackendState({ status: "running", port: 6900 });
  assert.equal(posted.length, 1); // only the initial register post
});
