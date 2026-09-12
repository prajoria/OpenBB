# T5 Paper/Live Broker Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable, idempotent, explicitly confirmed T5 execution gateway supporting the existing paper engine and an injected live-broker client.

**Architecture:** A focused `broker_adapter.py` module owns execution DTOs, the adapter protocols, paper/live adapters, a SQLite audit journal, safety gates, and orchestration. Existing paper engines gain full UUID identifiers and batch idempotency. The widget endpoint delegates to the gateway and remains paper-safe by default.

**Tech Stack:** Python 3.12, dataclasses, typing protocols, sqlite3, UUID, FastAPI, pytest.

## Global Constraints

- Never contact a real brokerage or use credentials in tests or verification.
- Live execution fails closed unless mode, environment gate, account, injected client, verdict, and exact batch-bound confirmation all agree.
- No fallback from live to paper.
- `MysqlPaperEngine` access continues through `get_default_engine()` and its corrected #2059 pool contract.
- Every order and audit event has a full RFC 4122 UUID.
- The durable idempotency key is
  `(mode, broker_id, account_id, principal_id, plan_id, batch_sha256)`.

---

### Task 1: Paper-engine UUID and idempotency foundation

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/execution/paper_engine.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/execution/mysql_paper_engine.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_paper_engine.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_mysql_paper_engine.py`

**Interfaces:**
- Consumes: `OrderBatch.sha256()`, existing engine scope fields.
- Produces: idempotent `submit_batch(batch, plan_id="") -> list[str]` with IDs shaped as `ord_<canonical UUID>`.

- [ ] Add failing tests proving repeated same-batch submission returns the original IDs and creates no duplicate rows.
- [ ] Add failing tests parsing every `ord_` suffix with `uuid.UUID`.
- [ ] Run the four focused tests and confirm RED.
- [ ] Query existing rows by account/scope and full batch SHA before insertion; return IDs in stable insertion order.
- [ ] Change `_new_id` to retain a full canonical UUID.
- [ ] Run both paper-engine unit modules and confirm GREEN.

### Task 2: Broker adapters and durable execution journal

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/execution/broker_adapter.py`
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_broker_adapter.py`

**Interfaces:**
- Consumes: `OrderBatch`, `PaperEngine`, and injected `LiveBrokerClient`.
- Produces: `BrokerAdapter`, `PaperBrokerAdapter`, `LiveBrokerAdapter`,
  `SqliteExecutionAuditStore`, `ExecutionGateway`, `SubmissionReceipt`,
  `CancellationReceipt`, and typed execution errors.

- [ ] Write failing protocol and paper-adapter tests using a fake paper engine.
- [ ] Implement paper and live adapter boundaries; live calls
  `submit_order(ticket, client_order_id=<UUID>)` and never reads credentials.
- [ ] Write failing audit tests for durable replay, per-order UUIDs, and append-only events.
- [ ] Implement normalized SQLite schema and transactional reservation/update methods.
- [ ] Write failing gateway tests for PASS/batch gate, execute kill switch, exact confirmation, idempotent retry, and unknown-outcome refusal.
- [ ] Implement submission orchestration with deterministic per-order UUIDs and no cross-mode fallback.
- [ ] Write failing partial-failure and cancellation tests.
- [ ] Implement `FAILED`/`PARTIAL`, separately confirmed cancellation, idempotent cancellation, and `CANCEL_FAILED`.
- [ ] Run `test_broker_adapter.py` and confirm GREEN.

### Task 3: Safe factory and widget integration

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/execution/broker_adapter.py`
- Modify: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets_endpoints.py`
- Modify: `openbb_platform/extensions/portfolio_intel/tests/unit/test_tt_p4b_widget_frontend.py`

**Interfaces:**
- Consumes: `get_default_engine()`, `ExecutionGateway`.
- Produces: paper-default factory and `/tt/execute/write-batch` mode-aware response.

- [ ] Add failing tests that default paper construction calls
  `get_default_engine()` and live construction refuses a missing injected client.
- [ ] Implement the factory without directly constructing `SqlitePaperEngine`.
- [ ] Add endpoint tests for default-off execution, paper idempotent retry, live
  kill-switch rejection, exact live confirmation, and injected fake-live success.
- [ ] Delegate the endpoint to `ExecutionGateway`; preserve the existing paper
  `confirm=yes` compatibility by translating it to the gateway's exact
  batch-bound paper phrase.
- [ ] Run broker-adapter and widget endpoint tests and confirm GREEN.

### Task 4: Regression, harness, and review convergence

**Files:**
- Create: `.dev-cycle/verify-phase6.log`
- Create/update: `.dev-cycle/findings-pr<NN>-iter<N>.md`

**Interfaces:**
- Consumes: completed implementation.
- Produces: local evidence and a converged PR.

- [ ] Run targeted techtrade paper/MySQL/order-sink tests and portfolio widget tests.
- [ ] Run repository-configured ruff/type diagnostics on changed Python files.
- [ ] Drive a temporary SQLite paper engine and injected fake live client end to
  end; capture output in `.dev-cycle/verify-phase6.log`.
- [ ] Run local code, security, and simplification reviews; fix and re-run tests.
- [ ] Commit with `Refs #1719` and the Copilot trailer; push and open one PR to
  `portfolio` with `Closes #1719`.
- [ ] Iterate local/GitHub reviews until all findings are applied-and-verified or
  deferred with a Project #4 issue, all current threads are resolved, fresh code
  review is clean, and security review has no unaddressed high/critical finding.
- [ ] Merge when checks and policy permit; verify #1719 closes and clean the worktree.
