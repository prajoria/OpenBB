// Node:test coverage for the backend reducer (#1819). No VS Code deps.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { transition, initialState } = require("../../out/backend/state.js");

test("SPAWN_REQUESTED moves stopped -> starting and clears error", () => {
  const s0 = { ...initialState(6900), status: "error", lastError: "prev" };
  const s1 = transition(s0, { type: "SPAWN_REQUESTED" });
  assert.equal(s1.status, "starting");
  assert.equal(s1.lastError, undefined);
});

test("SPAWN_SUCCEEDED moves starting -> running with pid + lastHealthAt", () => {
  const s0 = transition(initialState(6900), { type: "SPAWN_REQUESTED" });
  const s1 = transition(s0, { type: "SPAWN_SUCCEEDED", pid: 4242 });
  assert.equal(s1.status, "running");
  assert.equal(s1.pid, 4242);
  assert.ok(s1.lastHealthAt instanceof Date);
});

test("SPAWN_FAILED moves starting -> error with lastError set", () => {
  const s0 = transition(initialState(6900), { type: "SPAWN_REQUESTED" });
  const s1 = transition(s0, {
    type: "SPAWN_FAILED",
    error: "openbb-api not found",
  });
  assert.equal(s1.status, "error");
  assert.equal(s1.lastError, "openbb-api not found");
  assert.equal(s1.pid, undefined);
});

test("HEALTH_OK on running refreshes lastHealthAt and resets failure counter", () => {
  let s = transition(initialState(6900), { type: "SPAWN_REQUESTED" });
  s = transition(s, { type: "SPAWN_SUCCEEDED", pid: 1 });
  s = { ...s, consecutiveHealthFailures: 1, lastError: "prior" };
  const s1 = transition(s, { type: "HEALTH_OK" });
  assert.equal(s1.status, "running");
  assert.equal(s1.consecutiveHealthFailures, 0);
  assert.equal(s1.lastError, undefined);
  assert.ok(s1.lastHealthAt instanceof Date);
});

test("Two consecutive HEALTH_FAILED transitions running -> error", () => {
  let s = transition(initialState(6900), { type: "SPAWN_REQUESTED" });
  s = transition(s, { type: "SPAWN_SUCCEEDED", pid: 1 });
  s = transition(s, { type: "HEALTH_FAILED", error: "500" });
  assert.equal(s.status, "running");
  assert.equal(s.consecutiveHealthFailures, 1);
  s = transition(s, { type: "HEALTH_FAILED", error: "500 again" });
  assert.equal(s.status, "error");
  assert.equal(s.consecutiveHealthFailures, 2);
  assert.equal(s.lastError, "500 again");
});

test("STOP_REQUESTED then STOPPED settles at stopped, clears pid", () => {
  let s = transition(initialState(6900), { type: "SPAWN_REQUESTED" });
  s = transition(s, { type: "SPAWN_SUCCEEDED", pid: 99 });
  s = transition(s, { type: "STOP_REQUESTED" });
  assert.equal(s.status, "running");
  s = transition(s, { type: "STOPPED" });
  assert.equal(s.status, "stopped");
  assert.equal(s.pid, undefined);
});

test("Restart cycle: stopped -> running -> stopped -> running", () => {
  let s = initialState(6900);
  s = transition(s, { type: "SPAWN_REQUESTED" });
  s = transition(s, { type: "SPAWN_SUCCEEDED", pid: 1 });
  assert.equal(s.status, "running");
  s = transition(s, { type: "STOPPED" });
  assert.equal(s.status, "stopped");
  s = transition(s, { type: "SPAWN_REQUESTED" });
  s = transition(s, { type: "SPAWN_SUCCEEDED", pid: 2 });
  assert.equal(s.status, "running");
  assert.equal(s.pid, 2);
});
