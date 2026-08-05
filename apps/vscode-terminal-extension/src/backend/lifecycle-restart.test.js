// Node:test coverage for RestartController (#1838). No VS Code deps.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { RestartController } = require("../../out/backend/restart.js");

function makeController(overrides = {}) {
  const calls = { retry: [], giveUp: 0, sleeps: [] };
  const cfg = {
    maxAttempts: 3,
    backoffMs: [2000, 4000, 8000],
    onRetry: async (n) => { calls.retry.push(n); },
    onGiveUp: () => { calls.giveUp += 1; },
    sleep: async (ms) => { calls.sleeps.push(ms); },
    ...overrides,
  };
  return { rc: new RestartController(cfg), calls };
}

test("happy path: single failure invokes onRetry(1); reset zeros counter", async () => {
  const { rc, calls } = makeController();
  await rc.attemptRestart();
  assert.equal(rc.attemptCount, 1);
  assert.deepEqual(calls.retry, [1]);
  assert.equal(calls.giveUp, 0);
  rc.reset();
  assert.equal(rc.attemptCount, 0);
});

test("3 failures then 4th: onGiveUp fires; onRetry not called on 4th", async () => {
  const { rc, calls } = makeController();
  await rc.attemptRestart();
  await rc.attemptRestart();
  await rc.attemptRestart();
  assert.equal(rc.attemptCount, 3);
  assert.deepEqual(calls.retry, [1, 2, 3]);
  assert.equal(calls.giveUp, 0);
  await rc.attemptRestart();
  assert.equal(calls.giveUp, 1);
  assert.deepEqual(calls.retry, [1, 2, 3]);
});

test("custom backoff: sleeps recorded [2000,4000,8000] in order", async () => {
  const { rc, calls } = makeController();
  await rc.attemptRestart();
  await rc.attemptRestart();
  await rc.attemptRestart();
  assert.deepEqual(calls.sleeps, [2000, 4000, 8000]);
});
