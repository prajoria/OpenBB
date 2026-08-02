# Playwright test harness — design spec

**Date:** 2026-08-01
**Author:** Session close-out
**Parent:** #1713 Real Playwright + Workspace-in-CI
**Repo path:** `openbb_platform/tools/browser_test_harness/`
**Package name (proposed):** `openbb_browser_test_harness`

---

## 0. Purpose

Build a **dual-mode browser test harness** for the Portfolio Intelligence Terminal
and Techtrade Trading-Desk apps. Same story, two drivers:

1. **Manual mode** — a plain-Markdown user's guide a human tester follows step-by-step
2. **Automated mode** — a Python-Playwright driver that walks the same steps and
   asserts the same invariants headlessly

**Narrative alignment:** the steps in both modes MUST follow the notebook arcs:

- `notebooks/portfolio/01-getting-started-and-providers.ipynb` → …NB08
- `notebooks/techtrade/01-foundations-techtrade-and-analysis.ipynb` → …NB06

A tester (human OR script) using this harness should feel like they're re-doing the
notebook workflow, but in the Workspace UI.

---

## 1. Constraints

1. **`.venv_portfolio` compatibility** — the automation must import cleanly under
   the existing project venv without disturbing the widget-backend surface.
2. **Local-only by default** — the harness runs the widget_backend on `127.0.0.1:6120`
   and drives a local browser. No credentials in code. No network beyond the backend
   under test.
3. **Two auth modes** — both must work:
   - **Standalone mode:** widget_backend in `loopback-dev`, no Workspace UI —
     harness hits endpoints directly + still validates the *response shapes* a
     tester would see. Zero external dependency. This is the CI-friendly mode.
   - **Workspace mode:** real `pro.openbb.co` running in a browser the human
     tester has logged into. Playwright drives THAT session, does not attempt
     to authenticate.
4. **Idempotent** — running the harness twice produces identical output. Any
   state changes are logged, timestamped, and rolled back.
5. **PII rules from CLAUDE.md apply** — no credentials, no real usernames, no
   home-directory paths in screenshots or logs. Redact automatically.
6. **Reuses the terminal's stub-first policy** — every step's expected state comes
   from the SHIPPED endpoint responses. If a widget currently returns demo values,
   the harness asserts those demo values. When real fetchers land, the harness's
   expected values update in the same PR.

---

## 2. Success criteria

- **Manual guide:** A user with no repo access can follow 100% of steps using only
  the guide + a running backend + Chrome. Every step names the exact click,
  input, or observation.
- **Automation:** A Python script under `.venv_portfolio` runs `python -m
  openbb_browser_test_harness.run --story portfolio` and produces:
  - `report.md` — pass/fail per step + screenshots
  - `report.json` — machine-readable for CI
  - exit code 0 on all-pass, non-zero on any fail
- **Parity gate:** A cross-check test asserts every step in the manual guide has
  a matching automation step ID and vice versa. Drift = CI failure.
- **Narrative fidelity:** The step IDs and story labels match the notebook arc
  (e.g., manual step W3 corresponds to `notebooks/portfolio/03-basket-xray-and-risk.ipynb`).

---

## 3. Structure

```
openbb_platform/tools/browser_test_harness/
├── README.md                        # Setup + how to run each mode
├── pyproject.toml                   # Independent poetry package, editable-installable
├── src/openbb_browser_test_harness/
│   ├── __init__.py
│   ├── run.py                       # CLI entrypoint: --story portfolio|techtrade|both --mode standalone|workspace
│   ├── stories/
│   │   ├── __init__.py
│   │   ├── portfolio.py             # Story steps for portfolio-intel terminal
│   │   └── techtrade.py             # Story steps for techtrade-desk
│   ├── drivers/
│   │   ├── __init__.py
│   │   ├── base.py                  # Driver Protocol — what each mode implements
│   │   ├── standalone_driver.py     # HTTP-only, no browser (fastest, CI-friendly)
│   │   └── workspace_driver.py      # Playwright Chromium against pro.openbb.co
│   ├── steps.py                     # Step dataclass, Assertion helpers, screenshot util
│   ├── redact.py                    # PII redaction for screenshots + logs
│   └── report.py                    # report.md + report.json emitters
├── guides/
│   ├── portfolio-manual-guide.md    # Human-tester walk-through for terminal
│   └── techtrade-manual-guide.md    # Human-tester walk-through for techtrade-desk
├── fixtures/
│   ├── expected_responses/          # JSON snapshots of every endpoint's stub response
│   │   ├── pi_xray_sector_demo.json
│   │   ├── tt_validation_verdict.json
│   │   └── ...                      # one per widget endpoint
│   └── expected_layouts/
│       ├── portfolio_terminal.json  # tab-by-tab widget-id set
│       └── techtrade_desk.json
└── tests/
    ├── test_parity.py               # manual guide ↔ automation step-ID parity
    ├── test_stories_load.py         # each story imports + step schema validates
    ├── test_standalone_driver.py    # unit tests with mocked httpx
    └── test_redaction.py            # PII removal invariants
```

---

## 4. The Story data model

The single source of truth is a **Story** — an ordered list of Steps that both
the manual guide generator AND the automation driver consume.

```python
# steps.py

from dataclasses import dataclass, field
from enum import Enum

class Persona(str, Enum):
    ANALYST = "analyst"
    PM = "pm"
    SYSTEMATIC_TRADER = "systematic_trader"

class ActionKind(str, Enum):
    NAVIGATE   = "navigate"      # go to a tab
    OBSERVE    = "observe"       # read a widget value
    INPUT      = "input"         # type into a param field
    SCREENSHOT = "screenshot"    # capture current state
    ASSERT     = "assert"        # check an invariant

@dataclass(frozen=True)
class Step:
    id: str                        # e.g. "W3.observe.xray-sector"
    story: str                     # "portfolio" or "techtrade"
    notebook_ref: str              # e.g. "notebooks/portfolio/03-basket-xray-and-risk.ipynb"
    persona: Persona
    tab_id: str                    # matches apps.json tab
    action: ActionKind
    #
    # Manual-mode fields (what a human reads)
    #
    human_title: str               # "Step W3 — Check the X-Ray sector breakdown"
    human_description: str         # 1-3 sentences of prose
    human_expected: str            # what the tester should see
    #
    # Automation-mode fields (what the driver executes)
    #
    endpoint: str | None = None    # e.g. "pi/xray/sector"
    params: dict[str, str] = field(default_factory=dict)
    expected_status: int = 200
    expected_shape_fixture: str | None = None   # path under fixtures/expected_responses/
    #
    # Cross-cutting
    #
    screenshot_name: str | None = None
    tags: tuple[str, ...] = ()
```

**Key property:** every field lets one code source emit both the manual
Markdown AND the Playwright script. No divergence possible.

---

## 5. The Driver Protocol

```python
# drivers/base.py

from typing import Protocol
from ..steps import Step

class Driver(Protocol):
    async def setup(self) -> None: ...
    async def teardown(self) -> None: ...

    async def run_step(self, step: Step) -> "StepResult": ...

@dataclass
class StepResult:
    step_id: str
    ok: bool
    duration_ms: int
    screenshot_path: str | None
    observations: dict[str, object]  # e.g. {"row_count": 6}
    error: str | None
```

Two implementations:

### 5.1 `standalone_driver.py` — HTTP-only

**Subprocess + port management (P0-2 fix):**

- **Dynamic port allocation:** bind to `127.0.0.1:0`, read the assigned port back
  before spawning uvicorn. Prevents port 6120 conflicts across concurrent CI shards
  and stale-run leaks.
- **Readiness gate:** poll `GET /widgets.json` with 100ms interval, 10s timeout.
  If the backend hasn't responded within 10s, teardown, raise, exit non-zero.
  Never proceed to step 1 with an unhealthy backend.
- **Subprocess lifecycle:** on Windows, spawn with
  `subprocess.Popen(..., creationflags=CREATE_NEW_PROCESS_GROUP)`; on POSIX,
  use `os.setpgrp` via `start_new_session=True`. On teardown, send SIGTERM
  (or CTRL_BREAK_EVENT on Windows) to the process group; if not exited within
  5s, escalate to SIGKILL. Guards against uvicorn worker orphans.
- **Crash-during-setup detection:** the readiness poll checks `Popen.poll()` on
  each tick; if the subprocess has exited (returncode is not None), raise
  immediately with the subprocess's stderr captured. Prevents the harness
  hanging on `httpx.get` when the backend never bound.
- **PID file + atexit:** write the subprocess PID to `<tmp>/pid` and register
  an `atexit` handler + signal handler (SIGINT/SIGTERM) that kills the group
  on abnormal harness exit. Prevents orphaned uvicorn across dev-shell
  Ctrl-C.

**Auth-mode env-var handling (P0-3 fix):**

- The child env is built via `env = os.environ.copy(); env["PI_WIDGET_BACKEND_AUTH_MODE"] = "loopback-dev"`.
  This mutation is **scoped to the subprocess env only** — the harness never
  writes to `os.environ` in the parent process.
- **Parent-env safety check:** if the parent process already has
  `PI_WIDGET_BACKEND_TOKEN` set OR `PI_WIDGET_BACKEND_AUTH_MODE` set to anything
  other than `loopback-dev`, the harness refuses to run with a loud error:
  *"Refusing to override parent's auth mode. Unset PI_WIDGET_BACKEND_* before
  running the harness."* Prevents silent auth disablement in a dev shell that
  happened to have production tokens loaded.
- **Bind-address guard:** the harness only ever binds to `127.0.0.1`. If a caller
  patches the port config to bind to `0.0.0.0`, the widget_backend's startup
  hook should refuse `loopback-dev` on non-loopback binds — file
  a follow-up ticket to add that server-side check as defense-in-depth (do
  NOT rely on the harness alone).

**Per-step behavior:**

- For each step: hits the endpoint with `httpx.AsyncClient`.
- Screenshots = rendered markdown of the response (or a JSON tree for table/chart).
- No browser required. Runs in CI today.

**Assertions marked N/A in standalone mode (P2-9 fix):**

The "widget visible" and "not blank" assertions (§8.3, §8.4) cannot be evaluated
without a browser. In standalone mode, `StepResult.observations["widget_visible"]`
and `StepResult.observations["not_blank"]` are set to the sentinel string `"n/a"`
— not `True`. The report renderer displays `n/a` explicitly to prevent false-green.

### 5.2 `workspace_driver.py` — Playwright Chromium

**Playwright mechanism (P0-1 fix):** Playwright cannot attach to a browser the user
opened manually with `open pro.openbb.co`. Two mechanisms actually work:

- **Preferred: persistent context** — `chromium.launch_persistent_context(user_data_dir=<path>)`
  points at a Chrome profile directory the user has pre-logged-into. Cookie/auth
  persists across runs. Path lives under
  `C:\Users\<user>\.openbb_browser_test_harness\chrome_profile\` (matches the
  `portfolio_export` chrome profile pattern from CLAUDE.md).
- **Alternate: CDP attach** — user launches Chrome manually with
  `chrome.exe --remote-debugging-port=9222`; harness calls
  `chromium.connect_over_cdp("http://127.0.0.1:9222")`. Useful when the user
  wants to use their normal Chrome profile with all extensions.

The prompt at run start becomes:

```
Playwright mode: persistent-context (default) | cdp-attach
  persistent-context: harness will launch its own Chromium against
    ~/.openbb_browser_test_harness/chrome_profile/. On first run, a browser
    opens; log in to pro.openbb.co and press Enter. Auth persists across
    subsequent runs via cookies in that profile directory.
  cdp-attach: launch your normal Chrome with
    chrome.exe --remote-debugging-port=9222 first. Harness attaches and does
    not manage the browser lifecycle.
```

- For each step: uses accessibility-tree locators to click tabs and read widgets.
- Screenshots via `page.screenshot()` — **NEVER** OS-level capture (P1-4 fix). Page
  content only; browser chrome (tab title, URL bar, taskbar) is not in the frame.
- URL / tab-title are redacted from the report metadata separately by `redact.py`.

**Both drivers must produce comparable `StepResult`s** — the story is agnostic
to which driver runs it.

---

## 6. Story catalogue

### 6.1 Portfolio story (8 acts, mirrors `notebooks/portfolio/01-08`)

| Step ID | Notebook | Tab | Action | What the tester sees |
|---|---|---|---|---|
| W0.provider-health | NB01 | overview | observe | Provider-health chrome shows Track A + B tier states |
| W1.symbol-header | NB02 | overview | input+observe | Enter AAPL; profile header shows exchange + sector |
| W1.key-stats | NB02 | overview | observe | Key Stats table shows Market Cap + P/E TTM + Forward P/E |
| W2.financials | NB02 | financials | observe | Financial Statements table with annual/quarterly toggle |
| W3.xray-sector | NB03 | xray | observe | Sector pie shows 6 sectors, Information Technology ~38% |
| W3.xray-country | NB03 | xray | observe | Country pie shows US ~72% |
| W3.concentration | NB03 | xray | observe | Concentration gauge shows HHI value |
| W4.risk-dashboard | NB03/05 | risk | observe | Vol / VaR / Beta numbers present |
| W4.brinson | NB05 | risk | observe | Brinson waterfall with allocation/selection/interaction rows |
| W5.calendar | NB04 | calendar | observe | Event Calendar shows AAPL earnings + ex-div |
| W5.alerts | NB04 | alerts | observe | Alerts panel + smart-money ribbon populated |
| W6.paper-kpis | NB05 | paper | observe | Paper Performance KPIs + performance chart |
| W7.whatif | NB05 | risk | input+observe | Set delta_shares=100; What-If card updates |
| W8.morning-review | NB06/07 | morning-review | observe | 5 REUSE widgets composed on one page |
| W9.basket-consensus | NB08 | estimates | input+observe | basket_id=demo returns 5 consensus rows |
| W9.basket-guard | NB08 | estimates | assert | basket_id=real_book returns 422 with #1714 pointer |

### 6.2 Techtrade story (6 acts, mirrors `notebooks/techtrade/01-06`)

| Step ID | Notebook | Tab | Action | What the tester sees |
|---|---|---|---|---|
| T1.morning-scan | NB01/02 | morning-scan | observe | Segment movers + scan table populated |
| T1.filter | NB02 | morning-scan | input+observe | segment=Technology filters to 3 rows |
| T2.signal-card | NB03 | position-workbench | input+observe | Signal card shows BREAKOUT for NVDA |
| T2.plan-card | NB03 | position-workbench | observe | Plan card shows Entry / Stop / Target |
| T2.order-legs | NB03 | position-workbench | observe | 3 order legs (ENTRY / STOP / TARGET) |
| T2.simulate | NB03 | position-workbench | observe | Simulated P&L trajectory chart |
| T3.verdict | NB04 | validation | observe | PBO/DSR/OOS-Sharpe rows + Verdict = PASS |
| T4.tuning | NB05 | tuning | observe | 4 tune proposals, per-param validate_gate |
| T5.engine-status | NB06 | engine-status | observe | Scheduler / signal / execution engine state |
| T5.execute-blocked | NB06 | engine-status | input+assert | verdict=FAIL → execute bridge shows BLOCKED |
| T5.execute-ready | NB06 | engine-status | input+assert | verdict=PASS → execute bridge shows READY |
| T6.audit | NB06 | audit | observe | Replay-vs-forward journal with deviation_bps |

**The load-bearing safety invariant** — T5.execute-blocked + T5.execute-ready — must
be tested in BOTH modes. This is the same "verdict gates execute" invariant
#1701's pytest substitute already proves; the browser harness makes it visible.

---

## 7. Manual guide format

Each `guides/*-manual-guide.md` is generated from the same story data. The
generator template:

```markdown
# Portfolio Terminal — Manual Test Guide

**Duration:** ~20 minutes
**Setup:** run `python -m openbb_browser_test_harness.serve` in a terminal, then
open http://127.0.0.1:6120/widgets.json in your browser to confirm the manifest.
Then open pro.openbb.co, log in, and register `http://127.0.0.1:6120` as a
Custom Backend.

## Act 0 — Provider Health (W0)

*Story anchor:* `notebooks/portfolio/01-getting-started-and-providers.ipynb`
*Persona:* analyst

### Step W0.provider-health

1. Click any tab in the Portfolio Intelligence Terminal
2. Look at the top row of the tab (chrome band)
3. **Expected:** you see two rows — "Track A (paid): fmp_cached ... yfinance-snap"
   and "Track B (free): cboe ... yfinance"
4. **If not:** the chrome placement broke; check widgets.json for pi_provider_health

_(screenshot goes here after the tester runs the automation)_

...
```

**Every human step corresponds 1:1 to a `Step` in the code.** The generator emits
identical numbering, identical prose (from `human_description` and `human_expected`).

---

## 8. Assertions per step

Both drivers evaluate the same assertion set per step:

1. **Endpoint OK** — HTTP status matches `expected_status`
2. **Shape** — response conforms to `expected_shape_fixture` (JSON diff, tolerant to numeric jitter)
3. **Widget visible** — (workspace mode only) widget appears in a screenshot
4. **Not blank** — (workspace mode) rendered widget has non-zero pixel content in
   the expected region
5. **Load-bearing invariants** — tagged assertions from the Step's `tags` field:
   e.g., `("safety", "verdict-gates-execute")` triggers the T5 check that the
   BLOCKED body does not also contain READY.

---

## 9. Test discipline

Following R7.1 / R7.7 / R7.11:

- **R7.1 realistic-shape fixtures** — the `fixtures/expected_responses/` snapshots are
  captured from the ACTUAL endpoint output at spec-freeze time, not hand-crafted.
- **Fixture staleness enforcement (P1-5 fix):** a `test_fixtures_are_current`
  pytest (in `tests/`) spawns the backend, re-hits every endpoint referenced by
  any step in any story, and diffs the response against the fixture. Drift =
  test failure with a `pytest --snapshot-update`-style message telling the
  developer how to re-record. Prevents R7.1's "mocks agree with themselves"
  antipattern — the fixtures rot exactly like unmaintained mocks otherwise.
- **R7.7 reverse-verify** — the parity test (`tests/test_parity.py`) fails if a
  manual step is removed but the automation still has it, or vice versa.
- **Parity gate hardening (P1-6 fix):** parity test asserts BOTH step-ID match
  AND a lock-file hash of `(human_expected, expected_shape_fixture path,
  fixture mtime)` per step. Editing a fixture without updating the prose (or
  vice versa) requires an explicit lock-file update commit — surfaces drift
  that pure step-ID matching would miss.
- **ASSERT-kind schema validation (P1-7 fix):** `test_stories_load` enforces
  that every `ActionKind.ASSERT` step has either a non-None
  `expected_shape_fixture` OR a `tags` entry pointing at a registered checker
  function. Steps that assert nothing are a schema violation, not a silent
  ceremonial pass.
- **R7.11 mutation catalogue** — per step:
  - `W0.provider-health`: mutate widgets.json to drop pi_provider_health → step
    fails with "widget missing from chrome"
  - `W9.basket-guard`: change endpoint to return 200 instead of 422 → assertion
    fails with "expected 422 on non-demo basket_id"
  - `T5.execute-blocked`: change endpoint to always return READY → assertion
    fails with "BLOCKED not in body but READY is"

---

## 10. Silent-failure guards

- If the widget_backend process dies mid-run, all subsequent steps report `error="backend_down"`
  and the report exits non-zero. **Mechanism:** each step's `driver.run_step()`
  checks `subprocess.Popen.poll()` before the httpx call; if the returncode is
  not None, the step short-circuits with `backend_down` and no further steps
  are attempted. Prevents silent-skip on backend crash.
- If a screenshot capture fails (browser closed, permissions), the step reports
  `error="screenshot_capture_failed"` — never records an empty file as success.
- **PII redaction is `page.screenshot()`-only.** No OS-level capture, no
  `pyautogui`, no desktop grab. Browser tab title, URL bar, taskbar, and OS
  context menus are outside the screenshot frame by construction. URL / tab
  title are redacted from `report.json` metadata separately.
- **PII deny-list unification (P1-4 continued):** `redact.py`'s deny-list of
  personal path fragments is imported from the same source as
  `openbb_platform/tests/test_notebooks_portfolio_smoke.py::test_no_pii_in_notebook_outputs`.
  Both regimes share one deny-list; drift between them is a CI test failure.
- **SHA screenshot for future baseline (P2-10 fix):** every screenshot's
  SHA-256 is recorded in `report.json` under `steps[].screenshot_sha256`.
  Enables a future visual-regression baseline job (currently deferred, §11)
  to diff without a design change.
- If PII redaction detects an unredacted personal path in a screenshot (e.g.,
  `C:\Users\daaji\...`), the harness raises immediately and does NOT save the file.
- Parity drift between manual guide and automation is a CI-visible failure, not
  a warning.

---

## 11. Follow-ups NOT covered here

**Explicitly deferred (file real tickets):**

- **Real Workspace-in-CI** — running `workspace_driver.py` in a headless CI job
  needs a Workspace deployment target. That's #1713's ultimate scope; this
  spec builds the harness locally-runnable now, but CI integration is
  incremental.
- **Screenshot-diff regression baseline** — visual regression testing (compare
  today's screenshots to yesterday's) is out of scope. Add later.
- **Cross-browser** — Firefox / WebKit support. Chromium only for v1.

---

## 12. Deliverables (implementation cycle)

- `openbb_platform/tools/browser_test_harness/` package (per structure above)
- **1 unit-test suite** (parity + story schema + redaction + standalone-driver)
- **2 generated manual guides** (portfolio + techtrade)
- **2 story files** with ~28 total steps (16 portfolio + 12 techtrade)
- **~30 expected-response fixtures** (one per widget stub)
- **README** with quickstart for both drivers
- **Follow-up ticket** filed for CI integration once Workspace target is chosen

---

## 13. Verification plan for the implementation PR

1. `pip install -e openbb_platform/tools/browser_test_harness/` succeeds in `.venv_portfolio`
2. `python -m openbb_browser_test_harness.run --story portfolio --mode standalone`
   → exit 0, generates report.md + report.json
3. `python -m openbb_browser_test_harness.run --story techtrade --mode standalone` → exit 0
4. `pytest openbb_platform/tools/browser_test_harness/tests/` → all green,
   including the 3 R7.11 mutations reverse-verified
5. Manual guides render cleanly in GitHub preview
6. Parity test surfaces intentional drift (mutation demo)

---

## 14. Judgment calls I made (open for override)

1. **Standalone mode ships first, Workspace mode second** — proves the shape
   contract independently of Workspace availability. If Workspace goes down or
   your login expires, the harness still validates the backend. Ships value on
   day 1 without any external dep.
2. **Chromium only for v1** — Firefox + WebKit later. Chromium's the
   authoritative Playwright target, and it's what OpenBB Workspace is
   optimized for.
3. **CLI, not pytest-plugin, for v1** — `python -m openbb_browser_test_harness.run`
   is friendlier for demo purposes than `pytest -k`. Pytest-plugin can wrap
   it later.
4. **Redact PII into `<user>` and `<home>` sentinels** — not `[REDACTED]` — so
   redacted screenshots remain human-readable. Matches how the notebooks handle
   the same class of PII (per `docs/MEMORIES.md`).
5. **No `Docker`, no `docker-compose` in v1** — the spec avoids introducing new
   infra dependencies. Just `.venv_portfolio` + `playwright install chromium`.
   CI-in-Docker is #1713's scope.

---

## 15. Review feedback (added 2026-08-01, GitHub Copilot CLI review)

Overall: strong spec. The single-source Story model (§4), the standalone-first
sequencing (§14.1), the false-green guards (§5.1 `n/a` sentinels), and the PII
screenshot-frame-by-construction argument (§10) are the standout ideas — they solve
the real problems and the P0/P1 fix annotations show the risky parts were already
pressure-tested. The items below are what I'd resolve before or during the
implementation cycle, ordered by severity. Section references are inline.

### Blocking (fix in the spec before implementation)

- **B1 — Parity lock-file keys on `fixture mtime` (§9, P1-6). This will false-fail on
  every fresh clone.** File mtimes are not stable across `git clone`, `git checkout`,
  CI cache restores, or different machines — git does not preserve mtime, so the
  lock-file hash will mismatch immediately after checkout and the parity test will fail
  for everyone who didn't record the lock file on their own disk. Hash the fixture
  **content** (SHA-256 of the bytes), not `(…, fixture mtime)`. Content hashing gives
  you exactly the drift detection you want (edit fixture without updating prose =
  hash change) and is reproducible everywhere. This is the one item most likely to
  brick CI on day one.

- **B2 — Dynamic port allocation has a TOCTOU race (§5.1).** "bind to `127.0.0.1:0`,
  read the assigned port back before spawning uvicorn" closes the socket, then uvicorn
  re-binds the same number — between close and re-bind another process (or a parallel
  CI shard, the very thing this fix targets) can take it, and uvicorn dies with
  `EADDRINUSE`. Prefer one of: (a) let uvicorn bind `:0` itself and read the actual
  port from its startup (via `Server.servers[0].sockets[0].getsockname()` or a
  lifespan hook that writes the port to the PID/port file the readiness gate already
  reads), or (b) pass the pre-bound socket to uvicorn by fd (`--fd`) so there is no
  close/re-bind gap. Either removes the window; the current wording keeps it.

- **B3 — No per-step timeout on the automation path (§5.1, §8).** A hung or
  slow-streaming endpoint will block `httpx`/Playwright indefinitely and there is no
  step-level deadline in the model. A single wedged step can hang the whole CI job past
  the outer job timeout with no useful report. Add an explicit `timeout_ms` to `Step`
  (or a global default on the driver), set `httpx.AsyncClient(timeout=…)` and
  Playwright's `page.set_default_timeout(...)`, and record a step failure
  `error="step_timeout"` so the report still emits. §10 guards backend *death* but not
  backend *hang* — they are different failure modes.

### Should-fix (resolve during implementation, or file a follow-up)

- **S1 — Constraint 4 "identical output" contradicts §10 and the `StepResult` model.**
  `report.json` carries `duration_ms` (§5) and `screenshot_sha256` (§10, P2-10);
  neither is byte-stable across runs (timing varies; screenshots vary with
  antialiasing/font hinting/render timing). As written, the idempotency claim is
  self-falsifying and a naive "diff two report.json" check would always fail. Reframe
  Constraint 4 as **verdict/observation idempotency**: same pass/fail per step + same
  logical `observations` (e.g. `row_count`, sector percentages) across runs, with
  timing and screenshot hashes explicitly excluded from the idempotency comparison.

- **S2 — Fixture "tolerant to numeric jitter" (§8.2) is in tension with the
  deterministic-stub premise (§9 R7.1 / Constraint 6).** If the expected values come
  from *shipped stub responses* that return fixed demo values, there is no jitter, and
  a tolerance band would silently mask real drift (a stub value changing from 38% to
  41% is exactly what you want to catch). Recommend: **exact match against stubs**, and
  reserve numeric tolerance only for the eventual real-fetcher mode — and when you do
  add tolerance, specify it (relative vs absolute, which JSON paths) rather than
  leaving it as an adjective.

- **S3 — Backend-death detection only checks `Popen.poll()` *before* the call (§10).**
  If the backend dies *during* the `httpx`/Playwright call, `poll()` was clean and the
  request raises a connection/reset error that the current wording would surface as a
  generic step failure, not `backend_down`. Also treat `httpx.ConnectError` /
  `ConnectResetError` (and Playwright's net errors) as `backend_down` so the
  short-circuit + non-zero exit fires on mid-call death too, not just pre-call.

- **S4 — Rollback machinery (Constraint 4: "state changes … rolled back") has no named
  writer in the spec.** Every catalogued step is `observe`/`assert`/`input` against
  stub endpoints; §6 W7 `delta_shares=100` and T5 `verdict=…` read like query params,
  not persisted mutations. If nothing actually writes server state, the
  logged/timestamped/rolled-back requirement is dead weight — drop it or mark it
  explicitly deferred. If something *does* mutate (e.g. What-If persists a scenario),
  name it and say what rollback does. Right now it is an unfulfilled obligation a
  reviewer of the implementation PR can't check.

- **S5 — Frozen `Step` with a mutable `dict` default (§4).** `@dataclass(frozen=True)`
  plus `params: dict = field(default_factory=dict)` gives immutable *rebinding* but a
  mutable `params` payload, and makes `Step` unhashable — fine unless any test or the
  parity lock-file wants to put Steps in a set / dict key. If you want true immutability
  and hashability, use a frozen mapping (e.g. store params as a sorted tuple of pairs,
  or wrap in `MappingProxyType`) so a Step is safely hashable and can key the lock file.

### Nits / clarifications (non-blocking)

- **N1 — `Persona` (§4) has no described consumer.** It's on every Step but no
  assertion, report grouping, or guide section references it. Either wire it into the
  report (group steps by persona) / guide headers, or note it's forward-looking
  metadata so an implementer doesn't treat the missing usage as an omission.

- **N2 — `tab_id` "matches apps.json tab" (§4) is asserted nowhere.** You already ship
  `fixtures/expected_layouts/*.json` as the tab-by-tab widget-id set (§3). Cheap win:
  have `test_stories_load` validate every Step's `tab_id` (and endpoint's widget) against
  that layout fixture, so a renamed tab fails a test instead of a silent 404 at runtime.

- **N3 — CDP-attach on `:9222` is unauthenticated (§5.2).** Any local process can drive
  that browser while it's open. Acceptable for local dev, but worth one sentence telling
  the tester to close the debug Chrome afterward, and note CDP mode is intentionally not
  a CI path.

- **N4 — Persistent-context profile path (§5.2) is a home-dir path
  (`C:\Users\<user>\…`).** It's config, not output, so it's out of the screenshot frame —
  but make sure it never lands in `report.json` metadata or logs unredacted, since it
  matches the exact deny-list pattern in §10. A one-line "profile path is redacted from
  all emitted artifacts" closes the loop.

- **N5 — §12 says "~28 total steps (16 portfolio + 12 techtrade)" but §6 lists 16
  portfolio + 12 techtrade = 28, while §6.2's prose says "6 acts" / T-steps count 12.**
  Numbers reconcile, but the "8 acts / 6 acts" act-counts vs the 16/12 step-counts are
  easy to misread; a one-line "acts != steps" note would help the implementer size the
  work.

**Net:** B1 and B2 are the two I'd insist on fixing in the spec text (both will bite on
first CI run); B3 close behind. S1-S5 are cheap to resolve and mostly about making
implicit contracts explicit so the implementation PR is actually reviewable against
this spec. Nothing here changes the architecture — the bones are good.
