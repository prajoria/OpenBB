# Design Spec — As-of EOD Snapshot Cache + techtrade/portfolio_intel Alignment

- **Status:** Ready for implementation hand-off (spec only — no code in this workflow)
- **Author / workflow:** Portfolio Intelligence Engine — validation/verification/recommendation session (2026-08-09)
- **Program:** Portfolio Intelligence Engine (GitHub Project #4)
- **Parent epic / blocker:** #1932 (architecture blocker: data-bearing techtrade widgets need a persisted scan-snapshot layer)
- **Implements issues:** #1963, #1964, #1965, #1966, #1967, #1968, #1969 (+ two new Phase-A foundation issues, see §9)
- **Design sources (scratch, gitignored):** `.dev-cycle/brainstorm-asof-snapshot-cache.md`, `.dev-cycle/plan-techtrade-portfolio-alignment.md`
- **Target branch for the implementing team:** feature branches off `portfolio`, PR **into `portfolio`** (`--repo prajoria/OpenBB`, never cross-fork, never `develop`)

> This document is the durable, checked-in specification. The two `.dev-cycle/*`
> docs are the brainstorming/analysis that produced it and are not part of the
> hand-off contract. Where they disagree with this spec, **this spec wins** (it
> already folds in the §12 architect/analyst review and the §12.7 EOD scoping
> constraint the user added).

---

## 0. TL;DR for the implementing team

Build a **persisted, as-of, end-of-day (EOD) snapshot cache** that lets slow
whole-universe techtrade compute (movers/scan/signals/… — 45 s to 45 min per
call) be pre-computed once per trading session by an offline job and served to
Terminal widgets as an **instant, compute-free, single-row read** with an
`as_of` provenance badge.

Five hard rules define correctness:

1. **stage → validate → atomic promote** — the LIVE view is never partially written.
2. **keep-last-good** — a worse run never displaces a better one.
3. **LIVE is an explicit promoted pointer, never a `MAX(as_of)` query.**
4. **read path is compute-free** — no snapshot ⇒ honest "pending", never a live scan.
5. **EOD-only** — the artifact is "as of the last completed session"; it is
   **never** valid for intraday/within-day trading and must say so on its face.

The store is **homed in `openbb_techtrade`** (the shared lower building block),
not in `openbb_portfolio_intel`, because the *writer* (techtrade compute job)
and the *reader* (portfolio_intel Terminal) must share it without a dependency
cycle — exactly the way both already share `techtrade.execution.paper_engine`.

---

## 1. Problem statement & scope

### 1.1 Two workload classes (only Class B needs this)

| Class | Widgets | Live cost | Needs snapshot cache? |
|---|---|---|---|
| **A. Per-symbol research** | F1/F2: price-history, header, key-stats, financials, dividends, filings, insider, peers, price-target | ~0.1–7 s (once openbb package is built) | **No.** `fmp_cached` already caches provider calls; the only real pain was cold-boot build, fixed in #1957/#1962. |
| **B. Whole-universe compute** | techtrade `movers`, `scan_segments`, `signals`, `plan`, `validate`, `tune`, `audit` | **45 s – 45 min** (fetches OHLCV for whole GICS segments every call) | **Yes.** 4+ min synchronous = guaranteed browser/HTTP timeout = broken widget. This is #1932. |

**Scope:** build the snapshot store for **Class B**. Class A stays on
read-through `fmp_cached` and is explicitly **out of scope** for the daily job
(putting price/technicals behind a once-daily job would be a *correctness
regression* — see §7). Optional Class-A "session pinning" for cross-tab
consistency is a future, non-blocking nicety (not specified here).

### 1.2 EOD-only scoping constraint (hard boundary)

**The system serves end-of-day planning only. It is never valid for, and must
never be used for, within-day / intraday trading decisions.** The snapshot is a
**prev-close-as-of planning artifact**: "here is what the names looked like as
of the last completed session, so I can plan tomorrow's actions."

Consequences (these *simplify* the build):

- **No intraday refresh.** Cadence is **once per trading day, after the close**
  (or a single pre-open run against the completed prior session) for *every*
  dataset. The "every 15–30 min during market hours" branch is **out of scope**.
- **Staleness is measured against the trading calendar, not wall-clock days**
  (review item #5): **green** = `as_of_session == last_completed_session` (so a
  Friday-close snapshot is green *all weekend* — it is the freshest possible
  artifact for Monday planning); **amber** = the job missed exactly one
  *completed* session; **red** = the job has missed ≥ 2 completed sessions (or
  hasn't run). "A weekend/holiday passed" is **not** staleness and must never
  show amber — that would cry wolf and train the user to ignore the badge.
- **Corporate actions / earnings are between-session events** the next post-close
  run naturally absorbs; they are a *display annotation* on the planning view,
  not an intraday cache-invalidation race.
- **A standing "EOD planning snapshot — not a live/intraday quote" disclaimer**
  is mandatory on every snapshot-backed widget (EOD analogue of the #1953
  live-vs-demo badge).

---

## 2. Where the store lives (architecture decision — blocks #1963)

**Do NOT merge the two extensions.** The current layering is correct; the seam
between them is merely implicit and half-wired. Fix the seam, keep the shape.

```
   openbb_techtrade    (LOWER — the building block; no upward deps)
   ├── engine/         movers, scan, signals, plan, screener, indicators
   ├── execution/      paper_engine (Sqlite/Mysql), order_sink, broker
   ├── snapshot/       *** NEW ***  SnapshotStore (as-of cache) — SHARED
   └── config/         *** NEW ***  PI_* env-seam single source of truth
               ▲                              ▲
               │ imports down (declared dep)  │ reads store (compute-free)
   openbb_portfolio_intel  (UPPER — composition / the Terminal)
   ├── widget_backend/ 11-tab single-symbol story + portfolio panels
   ├── analytics/      xray, risk, brinson, attribution
   ├── routers/        events, smart_money, risk, xray, paper_alerts
   └── paper/          FIFO cost-basis ledger  (see D3, §9)
```

**Decision:** `SnapshotStore` Protocol + `SqliteSnapshotStore` +
`MysqlSnapshotStore` + `get_default_snapshot_store()` live in
**`openbb_techtrade/snapshot/`**.

**Rationale:** the writer (techtrade compute job, #1968 is `area:techtrade`)
must write the store; the reader (Terminal, portfolio_intel) must read it. If
the store lived in portfolio_intel, techtrade would have to import *up* →
dependency cycle. Homing it in techtrade mirrors the established precedent: the
paper engine (also shared by both) already lives in
`techtrade/execution/paper_engine.py` and is imported downstream by the
Terminal. The snapshot store is the same shape of artifact → same home.

Data flow for a wired tab (e.g. segment movers):

```
techtrade job (post-close)
   → SnapshotStore.stage → validate → promote → LIVE pointer
portfolio_intel Terminal widget
   → SnapshotStore.get_live → as-of JSON + session-date badge   (never computes)
```

---

## 3. Data model / schema

Two design decisions from the §12 review are **binding** and must be in the
first schema, because every later phase depends on them:

- **12.2 #1 — LIVE is an explicit promoted pointer, not `MAX(as_of)`.** A
  `partial` run writes a *newer* row; a naive "latest row wins" query would
  serve the partial and silently violate keep-last-good. The read path must
  resolve LIVE through a state/pointer set **only on a clean promote**.
- **12.3 #8 — split the timestamp concepts; store native date/time types per
  dialect.** `as_of_session` = the **trading day the answer is about** (a `DATE`);
  `created_at` = wall-clock **UTC** of the write (`TIMESTAMP`/`DATETIME(6)`). The
  `SnapshotStore` Protocol always returns `datetime.date` / tz-aware
  `datetime.datetime` regardless of backend, so the storage representation is a
  per-dialect detail hidden behind the abstraction:
  - **SQLite** has no real date type — store both as **ISO-8601 strings**
    (`YYYY-MM-DD` and UTC ISO-8601) or the `... DESC` index misorders. This is a
    SQLite workaround, **not** a cross-dialect mandate.
  - **MySQL** stores them as native **`DATE`** + **`DATETIME(6)`** so sorting,
    validation, and index behavior are the engine's own — do **not** force the
    SQLite ISO-text representation onto MySQL (review item #2).

### 3.1 Core table (SQLite dialect shown; MySQL mirrors it)

```sql
CREATE TABLE pi_snapshot (
    dataset            TEXT NOT NULL,      -- 'techtrade.movers' | 'pi.equity.financials'
    entity_key         TEXT NOT NULL,      -- 'sector=Information Technology' | 'AAPL'
    as_of_session      TEXT NOT NULL,      -- ISO DATE (YYYY-MM-DD): trading day it is ABOUT
    created_at         TEXT NOT NULL,      -- ISO-8601 UTC: wall-clock of the write
    job_run_id         TEXT NOT NULL,      -- ties row to a job execution
    status             TEXT NOT NULL,      -- 'ok' | 'partial' | 'stale' | 'failed'
    state              TEXT NOT NULL,      -- 'staging' | 'live' | 'superseded'
    validated          INTEGER NOT NULL DEFAULT 0,
    validation_reason  TEXT NOT NULL DEFAULT '',
    payload_json       TEXT NOT NULL,      -- widget-ready result
    input_hash         TEXT,               -- hash(inputs + engine_version) — skip recompute
    row_count          INTEGER,            -- cheap sanity signal
    -- provenance (#1964)
    engine_version         TEXT,           -- code that produced the row (replay correctness)
    payload_schema_version TEXT,           -- decouples stored history from current UI schema
    PRIMARY KEY (dataset, entity_key, as_of_session, job_run_id)
);
CREATE INDEX ix_pi_snapshot_live   ON pi_snapshot(dataset, entity_key, state);
CREATE INDEX ix_pi_snapshot_latest ON pi_snapshot(dataset, entity_key, as_of_session DESC, created_at DESC);

-- Enforce "exactly one live row per key" at the DB level, not only in promote()
-- (review item #1). Dialect difference is REQUIRED — do not skip on MySQL:
--   SQLite (partial index — supported):
CREATE UNIQUE INDEX ux_pi_snapshot_live
    ON pi_snapshot(dataset, entity_key) WHERE state = 'live';
--   MySQL 8 (NO filtered unique indexes) — use a generated NULL-collapsing column:
--     ALTER TABLE pi_snapshot ADD COLUMN live_key VARCHAR(512)
--       GENERATED ALWAYS AS (IF(state='live', CONCAT(dataset,'\x1f',entity_key), NULL)) STORED,
--       ADD UNIQUE KEY ux_pi_snapshot_live (live_key);
--   (UNIQUE ignores NULLs in both engines, so only live rows are constrained.)
```

**LIVE resolution:** the single row with `state='live'` for a `(dataset,
entity_key)`. Exactly one LIVE row per key is enforced **at two layers**:
(1) `promote()` flips the prior LIVE → `superseded` and sets the new LIVE inside
one `_tx()` transaction; (2) the **partial/collapsing unique index above** makes
the invariant a hard DB constraint, so a crash between the two writes, or a
future second writer, **cannot** leave zero or two live rows — the second `live`
insert fails rather than corrupting the pointer. Readers never run `MAX()`.

### 3.2 Job bookkeeping tables (#1967)

```sql
CREATE TABLE snapshot_job (
    job_run_id   TEXT PRIMARY KEY,
    dataset      TEXT,
    started_at   TEXT,       -- ISO-8601 UTC
    finished_at  TEXT,
    state        TEXT,       -- 'running' | 'succeeded' | 'partial' | 'failed'
    n_ok         INTEGER,
    n_failed     INTEGER,
    error        TEXT
);

-- 12.3 #6 — per-symbol failure detail so a partial run re-pulls only the failures.
CREATE TABLE snapshot_job_error (
    job_run_id  TEXT NOT NULL,
    entity_key  TEXT NOT NULL,
    error       TEXT,
    PRIMARY KEY (job_run_id, entity_key)
);
```

`snapshot_job.state='running'` is the **single-flight** guard (§6). A new job
checks for a live `running` row and refuses, unless that row is stale (crashed
worker) — mirror the repo's 2-hour reclaim pattern.

### 3.3 Retention (12.3 #7)

"Keep history forever" is unbounded (~500 rows/dataset/session). Ship a
`RetentionPolicy(keep_sessions: int | None)` hook now (default `None` =
keep-all, the v1 behavior) so a real window+rollup policy can land later
**without a schema change**. LIVE rows are never pruned.

---

## 4. Public API contract (`openbb_techtrade/snapshot/store.py`)

The Terminal reader and the techtrade writer depend on the **Protocol**, not the
concrete class — mirroring the `PaperEngine` seam. Signatures are binding; the
implementing team owns the bodies.

### 4.1 Value types

```python
class SnapshotStatus(str, Enum):        # also the keep-last-good ranking key
    OK = "ok"; PARTIAL = "partial"; STALE = "stale"; FAILED = "failed"
# rank: OK(3) > PARTIAL(2) > STALE(1) > FAILED(0)

class SnapshotState(str, Enum):
    STAGING = "staging"; LIVE = "live"; SUPERSEDED = "superseded"

@dataclass(frozen=True)
class ValidationResult:  ok: bool; reason: str = ""

@dataclass(frozen=True)
class RetentionPolicy:   keep_sessions: int | None = None

@dataclass(frozen=True)
class SnapshotRow:
    dataset: str; entity_key: str
    as_of_session: datetime.date          # trading day it is ABOUT
    created_at: datetime.datetime          # tz-aware UTC of the write
    job_run_id: str
    status: SnapshotStatus
    state: str                             # staging | live | superseded
    payload: dict
    input_hash: str | None = None
    row_count: int | None = None
    validated: bool = False
    validation_reason: str = ""
    engine_version: str | None = None
    payload_schema_version: str | None = None
```

### 4.2 Key canonicalization (review item #4 — required for a shared store)

`dataset` and `entity_key` are free text. In a **shared** store, two writers
emitting `Information Technology` vs `Information_Technology` vs
`INFORMATION TECHNOLOGY` produce split-brain LIVE rows the reader can't
reconcile. A single canonicalizer, called by **both writer and reader** on every
`dataset`/`entity_key` before it touches the store, closes this gap:

```python
def canonical_key(raw: str) -> str:
    """Normalize a dataset or entity_key to a single canonical form.
    Both writer and reader MUST call this before any store operation.
    Rules: strip; collapse internal whitespace to single spaces; casefold the
    label half of 'field=Label' pairs (keep the field name verbatim); normalize
    separators. Deterministic and idempotent: canonical_key(canonical_key(x)) == canonical_key(x)."""
```

Every Protocol method treats its `dataset`/`entity_key` args as already-canonical
(the store may assert `canonical_key(x) == x` in debug builds). Canonicalization
is a contract obligation of the caller layer, applied once at the boundary.

### 4.3 Default validation gate

```python
def default_validator(row: SnapshotRow) -> ValidationResult:
    """Baseline sanity gate: reject empty payload; reject negative row_count.
    Callers pass a stricter validator= for dataset-specific bounds
    (row_count within X% of last run, no all-null columns, prices > 0, ...)."""
```

### 4.4 Protocol

```python
class SnapshotStore(Protocol):
    def stage(self, dataset, entity_key, as_of_session, job_run_id, payload, *,
              status=SnapshotStatus.OK, input_hash=None, row_count=None,
              engine_version=None, payload_schema_version=None) -> None: ...
        # write a run to STAGING; NEVER touches the LIVE view.

    def validate(self, dataset, entity_key, as_of_session, job_run_id,
                 validator=None) -> ValidationResult: ...
        # run gate on the staged row; persist validated flag + reason.

    def promote(self, dataset, entity_key, as_of_session, job_run_id) -> bool: ...
        # atomic: refuse if not validated; refuse if staged rank < live rank
        # (keep-last-good); else flip prior LIVE -> superseded and this -> LIVE.
        # returns True on success, False on any refusal (logs a WARNING).

    def get_live(self, dataset, entity_key) -> SnapshotRow | None: ...
        # compute-free single-row read of state='live'; None if absent.

    def get_as_of(self, dataset, entity_key, as_of_session) -> SnapshotRow | None: ...
        # promoted row for a specific session (replay/compare-to-yesterday).

    def list_history(self, dataset, entity_key, limit=50) -> list[SnapshotRow]: ...
        # newest first; retained for audit/replay/diffing.

    def should_skip(self, dataset, entity_key, input_hash) -> bool: ...
        # True iff LIVE row already carries this input_hash (idempotent rerun).
        # NOTE: a skip must NOT strand the staleness badge — see §4.6 + §6.

    def restamp_live(self, dataset, entity_key, as_of_session, job_run_id) -> bool: ...
        # cheap "re-stamp promote" (review item #3, option a): when should_skip is
        # True for a NEW session, advance the LIVE pointer's as_of_session to the
        # new session WITHOUT recomputing payload, so the badge reads green.
        # Writes a superseded history row for audit; returns True on success.

    def prune(self, policy: RetentionPolicy | None = None) -> int: ...
        # apply retention; return #rows removed (default policy -> 0, keep-all).

    def close(self) -> None: ...
```

### 4.5 `should_skip` must not strand the staleness badge (review item #3)

`input_hash` includes `engine_version` but **not** the session, so on a genuine
new session an illiquid entity whose inputs are byte-identical to yesterday's
would `should_skip → True`, the job would skip, and the LIVE row's
`as_of_session` would stay on the *older* session — making the
session-staleness badge (safeguard #4 / #1966) go amber/red even though the job
ran cleanly. This spec resolves the interaction **both** ways so implementers
have a clear default:

- **Primary (option a):** on a skip for a new session, the job calls
  `restamp_live(...)` to advance the LIVE pointer's `as_of_session` to the new
  completed session without recomputing the payload. The read stays green.
- **Backstop (option b):** the badge classifier (#1966) keys off the **last
  successful `snapshot_job` run for the dataset**, not the `as_of_session` of the
  LIVE row. Even if a re-stamp is missed, a clean job run keeps the badge green.

Implementers MUST wire option (a) as the primary path; option (b) is the
defense-in-depth so a missed re-stamp never silently cries "stale".

### 4.6 Backend selector (mirror `get_default_engine`)

```python
def get_default_snapshot_store() -> SnapshotStore:
    """PI_SNAPSHOT_ENGINE=mysql (default) -> shared-pool MysqlSnapshotStore;
    on ANY construction failure (module missing / pool unreachable) log a
    WARNING '... falling back to SQLite ...' and return SqliteSnapshotStore.
    Anything else -> SqliteSnapshotStore at PI_SNAPSHOT_DB or
    ~/.portfolio_intel/snapshot.db.  Keep a monkeypatchable `_make_mysql_store`
    seam so the fallback path is unit-testable without live MySQL."""
```

**Concurrency:** `SqliteSnapshotStore` opens the connection with
`check_same_thread=False`, `isolation_level=None`, `row_factory=Row`, runs
`executescript(_SCHEMA)`, and serializes all writes behind a module-level
`RLock` inside a `_tx()` BEGIN/COMMIT/ROLLBACK context manager — identical
discipline to `SqlitePaperEngine`. `MysqlSnapshotStore` acquires the shared pool
lazily via `openbb_fmp_cached.utils.database.get_connection_pool` (mirror
`MysqlPaperEngine`).

---

## 5. Correctness safeguards (the full checklist)

| # | Safeguard | Where enforced |
|---|---|---|
| 1 | stage → validate → **atomic** promote (never partial LIVE writes) | `promote()` inside `_tx()` |
| 2 | **keep-last-good** — worse status never displaces better | `promote()` rank guard |
| 3 | LIVE = promoted **pointer/state**, never `MAX(as_of)` | schema `state` col + `get_live` |
| 4 | mandatory `as_of` provenance + colour-coded session-staleness badge | payload + viewer (#1966) |
| 5 | **validation gate** (schema + sanity bounds + row-count delta) before promote | `validate()` + caller validator |
| 6 | per-row `status` so failures render "n/a", never silent drops | payload shape (#1968/#1969) |
| 7 | **input_hash includes `engine_version`** — changed code ⇒ recompute | job compute (#1967) + column |
| 8 | history retained for replay/audit (`job_run_id`, `get_as_of`) | schema + `list_history` |
| 9 | **read path compute-free** — no snapshot ⇒ honest "pending" | widget endpoints (#1968/#1969) |
| 10 | idempotent + `should_skip(input_hash)` for cheap reruns | `should_skip()` |
| 11 | **PII boundary** — account-scoped datasets never in the shared store | §8 (#1965) |
| 12 | single-flight job lock (`state='running'` + stale reclaim) | job runner (#1967) |
| 13 | `payload_schema_version` so replay survives UI-shape changes | provenance col (#1964) |

---

## 6. Job orchestration (#1967)

- **v1 runner = external scheduled process** (`python -m openbb_techtrade.snapshot.refresh`)
  triggered by OS Task Scheduler / cron, **post-close** once per trading day.
  An isolated process has its own main thread → sidesteps the `signal.signal`
  worker-thread bug that caused #1962. **Do not run the heavy compute inside the
  uvicorn request loop.**
- **Single-flight:** a new run refuses if `snapshot_job.state='running'` exists,
  unless that row is stale (crashed) — reclaim per the repo's 2-hour pattern.
- **Targeted retry:** a `partial` run records failures in `snapshot_job_error`;
  the next run re-pulls only those `entity_key`s instead of the whole universe,
  then promotes once the set is complete.
- **On-demand per-symbol trigger** (the user's "capability to trigger another
  cache snapshot per stock"): expose `refresh(dataset, entity_key)` that runs the
  same stage→validate→promote path for a single `entity_key`. The Terminal can
  call it to force a fresh snapshot for one name without waiting for the nightly
  job. **This still writes through the store — never a synchronous request-path
  compute.** UX is enqueue + poll job state.
- **Fetch layer hits `fmp_cached`** so the job's provider calls are themselves
  cached/cheap (Class A cache and Class B cache compose; they do not overlap).

---

## 7. Why a naive daily cache returns WRONG answers (and the defenses that stay)

Even under EOD-only scope, these remain real and the defenses are **in scope**:

- **Partial-failure poisoning (§5.4):** 500-symbol scan, 60 fail → overwriting
  LIVE silently drops 60 names. Defense: staging + validate + atomic promote +
  keep-last-good + per-row status. **(Core of #1963/#1968.)**
- **Provider drift / bad data (§5.5):** FMP returns null/garbage; a cache freezes
  it for a day. Defense: validation gate with sanity bounds before promote.
- **Stale-serve masquerading as fresh (§5.7):** job crashed N days ago, widget
  shows a confident number. Defense: mandatory session-date badge, red when the
  job hasn't run in ≥ 2 trading days.
- **Corporate actions / earnings (§5.3, 12.4 #10):** between-session events the
  next post-close run absorbs. Surface an **earnings annotation** on the planning
  view — but define it as **"reported since this snapshot's session close,"** not
  merely "reports before next open" (review item #6). The sharper trap is a name
  that reports **just after** the close the snapshot was computed on (e.g. 4:00pm
  close snapshot, 4:05pm earnings print): that snapshot is already stale on the
  single most important axis before the next session even opens, and the
  annotation must flag it loudly. Add delist/halt to the trigger set so a cached
  segment/peers set doesn't silently skew movers with an acquired/halted name.
- **Survivorship in validate/tune/audit (§5.6, 12.4 #11):** baking in *current*
  universe membership yields a tuned parameter set that backtests beautifully and
  fails live. **Do not ship validate/tune/audit snapshots until as-of universe
  membership exists, OR stamp them `in-sample · survivorship-uncorrected`** so no
  one mistakes them for a tradeable backtest. This gates part of #1969.

What EOD scope **removes:** intraday refresh, minutes-scale staleness ceilings,
within-session corporate-action invalidation races. What it does **not** relax:
the mandatory `as_of` badge and the standing "not a live quote" disclaimer.

---

## 8. PII boundary (#1965) — a gate, not a nitpick

Class B (universe compute) carries no PII. But any `pi.equity.*` /
account-scoped dataset can carry `account_id`, holdings, weights, dollar sizes.
Per the repo's hard PII rules:

- **Account-scoped datasets are NEVER written to the shared snapshot store.**
  Either they are excluded entirely, or written only to a **user-local,
  outside-repo** DB guarded by the same `_validate_outside_repo` check the
  portfolio importer uses (`download_dir`/`profile_dir` resolving inside the repo
  root raises `ConfigError`).
- The snapshot DB file itself defaults to `~/.portfolio_intel/snapshot.db`
  (outside the repo); `PI_SNAPSHOT_DB` overrides must also resolve outside the
  repo. `.gitignore` is defense-in-depth, not the primary guard.
- No holdings, weights, account numbers, or dollar sizes ever land in a
  committed/shared store or in any GH issue/PR/comment produced by this work.

---

## 9. Extension-alignment work (the seam fixes)

Four divergences between the two extensions were catalogued; two are HIGH and
directly gate this subsystem. The implementing team should file these as
Phase-A foundation issues under epic #1932 **before** the snapshot datasets
fan out.

| # | Divergence | Severity | Action |
|---|---|---|---|
| **D1** | **Undeclared dependency.** `portfolio_intel` imports `openbb_techtrade` at runtime but does not list it in `pyproject.toml` (all lazy imports). | **HIGH** | New issue: add `openbb-techtrade = "^0.1.0"` to `portfolio_intel/pyproject.toml`. Keep lazy imports for graceful-degrade, but make the install-time contract real. |
| **D2** | **Engine surfaces stubbed, not wired.** Terminal tabs for segments/scan/signals/plan/simulate/validate/tune/audit return literal "Stub" strings with `TODO(gh-…)`; the real impls exist in techtrade. This is the user-visible "everything says stub". | **HIGH** | Resolved by #1968 (movers) + #1969 (fan-out) reading the snapshot store. |
| **D3** | **Two paper systems.** `portfolio_intel/paper/` FIFO cost-basis ledger vs `techtrade/execution/paper_engine.py`. Terminal uses techtrade's; portfolio_intel/paper is only self-tested. | **MEDIUM** | New **investigation** issue — diff both lot/fill impls; likely outcome: portfolio_intel/paper becomes the cost-basis *library* the techtrade engine *uses*. **Do not delete either until the diff is done and tests cover the merge.** Not part of the snapshot build. |
| **D4** | **Ad-hoc `PI_*` config.** `PI_PAPER_ENGINE`, `PI_SNAPSHOT_ENGINE`, `PI_WIDGET_BACKEND_*`, etc. defined wherever first needed; no single owner. | **MEDIUM** | New issue: add `openbb_techtrade/config.py` (lower layer, both import it) with typed getters `snapshot_engine()`, `snapshot_db_path()`, `paper_engine()`, `paper_db()`… Migrate `os.environ.get("PI_*")` call-sites incrementally. |

**Not-divergences (do not "fix"):** the one-way import direction
(`portfolio_intel → techtrade`, never reverse); techtrade having no widget layer
(it is a headless engine); `PI_*` as the shared prefix (keep it — just
centralize ownership).

---

## 10. Phased plan → issue mapping & acceptance criteria

### Phase A — make the seam explicit & shared (foundation; 2 NEW issues)

- **A1 (new) — declare techtrade dep (D1).** DoD: `openbb-techtrade` in
  `portfolio_intel/pyproject.toml`; fresh `.venv_portfolio` install pulls it;
  lazy-import graceful-degrade paths unchanged; import smoke test green.
  **Note (review item #8):** for this intra-fork monorepo where both extensions
  are editable-installed into `.venv_portfolio`, prefer a **path / develop
  dependency** (e.g. Poetry `{ path = "../techtrade", develop = true }`) over a
  published version pin like `^0.1.0`, so the local techtrade is used rather than
  a wheel that may not exist on any index.
- **A2 (new) — centralize `PI_*` config (D4).** DoD: `openbb_techtrade/config.py`
  with typed getters; snapshot + paper selectors read from it; existing behavior
  preserved (same env vars, same defaults); unit tests for each getter's
  default + override.

### Phase B — snapshot infrastructure (#1963–#1967)

- **#1963 — store skeleton.** `SnapshotStore` Protocol + `SqliteSnapshotStore` +
  `MysqlSnapshotStore` + `get_default_snapshot_store()`; stage→validate→promote;
  keep-last-good; `as_of_session`/`created_at` split (native types per dialect,
  §3); `canonical_key` applied at the boundary; **DB-level single-live index**
  (partial unique on SQLite / generated-column unique on MySQL, §3);
  `should_skip` + `restamp_live`; retention hook. **DoD:** the RED-test contract
  in §11 passes (13 tests, each reverse-verified); `black --check` +
  `ruff check` clean; store homed in `openbb_techtrade/snapshot/`.
- **#1964 — LIVE-pointer reconciliation & provenance columns.** `state`-based
  LIVE pointer with instant rollback; `engine_version`, `payload_schema_version`,
  `snapshot_job_error` in schema; `input_hash` incorporates `engine_version`.
  **DoD:** promote/rollback tests; a stored row from an old `engine_version` is
  still replayable via `get_as_of`; reader selects renderer by
  `payload_schema_version`.
- **#1965 — PII boundary (§8).** `_validate_outside_repo`-style guard on the
  snapshot DB path; account-scoped datasets rejected from the shared store.
  **DoD:** a test proving an in-repo `PI_SNAPSHOT_DB` raises; a test proving an
  account-scoped dataset write is refused.
- **#1966 — EOD as-of semantics + staleness badge.** `as_of` = session date;
  **calendar-anchored** badge (review item #5): green =
  `as_of_session == last_completed_session` (green all weekend/holiday, since a
  Friday close is the freshest artifact for Monday), amber = missed exactly one
  *completed* session, red = missed ≥ 2; standing "EOD planning snapshot — not a
  live/intraday quote" disclaimer. **DoD:** badge classifier unit tests driven by
  a trading calendar (Friday-snapshot-viewed-Saturday→green, missed-one-completed-
  session→amber, missed-≥2→red); a weekend-passing test proving it does **not**
  go amber; disclaimer present on a snapshot-backed widget.
- **#1967 — job orchestration.** External post-close process; single-flight lock;
  `snapshot_job`/`snapshot_job_error` bookkeeping; targeted retry;
  `refresh(dataset, entity_key)` on-demand per-symbol trigger. **DoD:** a job run
  writes bookkeeping + promotes; a second concurrent run refuses (single-flight);
  a partial run re-pulls only failed keys on retry.

### Phase C — wire the stubs through the store (kills D2)

- **#1968 — techtrade movers EOD snapshot (unblocks #1692).** Job computes movers
  per segment → store; `tt_segment_movers` reads store compute-free + as-of badge;
  validation gate + partial-failure keep-last-good. **DoD:** one segment
  live-verified end-to-end (job writes, widget reads, badge shows session date);
  a simulated 1-symbol failure keeps yesterday's OK snapshot live (loud, not
  silent).
- **#1969 — fan-out (scan/signals/plan/validate/tune/audit).** Each dataset gets
  its own validation bounds; wires the remaining stub tabs
  (#1696/#1697/#1698/#1699) through the store; event-risk (earnings/delist/halt)
  annotation; **survivorship gate** on validate/tune/audit (do not ship, or stamp
  `in-sample · survivorship-uncorrected`). **DoD:** per-dataset validation tests;
  survivorship stamp present or dataset withheld; each wired tab serves from the
  store, never a synchronous scan.

### Phase E — single-stock → portfolio fan-out (north star, future)

Once one symbol's pipeline is proven, the portfolio job is a loop over the
holdings universe writing one snapshot per symbol per session. `entity_key`
already carries the symbol; no new store shape needed. (Not part of this
hand-off; noted so the store shape doesn't need rework later.)

---

## 11. Test contract for #1963 (the RED spec the store must satisfy)

The store skeleton must satisfy these 13 behaviors. Every load-bearing test must
be **reverse-verified**: revert the primitive it guards and confirm the test
FAILS (per the repo's R7 "fixtures must discriminate" rule). Tests drive the
real store with a **fake compute fn** — no live provider, no MySQL infra. Import
from `openbb_techtrade.snapshot.store`; `caplog` logger name
`openbb_techtrade.snapshot.store`.

**Safeguard coverage (review item #7):** these 13 tests cover 11 of the 13
safeguards in §5. The two **not** covered here are out of the skeleton's scope
and owned by later issues: safeguard #12 (single-flight job lock) belongs to the
**job runner (#1967)**, and the provenance-**replay** half of safeguard #13
(`payload_schema_version` renderer selection) belongs to **#1964**. The
skeleton does add the `payload_schema_version` column and the DB-level
single-live constraint, so those columns/indices exist before their behaviors
are exercised downstream.

1. `get_live` on a fresh store ⇒ `None` (compute-free; no live scan).
2. clean stage→validate→promote ⇒ row becomes LIVE with correct payload /
   job_run_id / `as_of_session`.
3. promote **without** validate first ⇒ `False`, LIVE stays `None`
   (reverse-verify: drop the `validated` check → flips to True).
4. empty-payload staged run fails `default_validator` ⇒ promote refused, no LIVE.
5. caller-supplied validator that rejects ⇒ promote refused.
6. **keep-last-good:** a validated `PARTIAL` run does NOT displace a live `OK`
   (reverse-verify: remove the rank guard → the partial clobbers the good LIVE).
7. a newer `OK` run promotes and supersedes the prior LIVE; history retains both;
   exactly one `state='live'` row for the key.
8. `as_of_session` is a `date`; `created_at` is tz-aware UTC (offset 0) — the two
   concepts are distinct.
9. `should_skip(input_hash)` ⇒ True for the LIVE row's hash, False otherwise;
   plus `restamp_live` on a new session advances the LIVE `as_of_session` without
   recomputing payload (reverse-verify: skip without re-stamp leaves the pointer
   on the old session).
10. `prune()` default policy keeps all (returns 0); `RetentionPolicy(keep_sessions=1)`
    is a configurable hook.
11. selector: `PI_SNAPSHOT_ENGINE=sqlite` ⇒ `SqliteSnapshotStore`;
    `=mysql` with `_make_mysql_store` monkeypatched to raise ⇒ WARNING
    "falling back to SQLite" + `SqliteSnapshotStore` (reverse-verify: the caplog
    WARNING fires only from the fallback branch).
12. **DB-level single-live constraint:** attempting to insert/flip a second
    `state='live'` row for the same `(dataset, entity_key)` (bypassing `promote()`)
    raises an integrity error — the partial/collapsing unique index holds even if
    `promote()`'s in-transaction flip is circumvented (reverse-verify: drop the
    unique index → the second live row inserts and the invariant breaks).
13. **canonicalization:** `stage`+`promote` under `entity_key='Information Technology'`
    then `get_live('Information_Technology')` (or a differently-cased variant)
    resolves the **same** LIVE row via `canonical_key`; `canonical_key` is
    idempotent (reverse-verify: bypass canonicalization → the reader misses the
    row / a split-brain second LIVE appears).

---

## 12. Non-goals / explicitly out of scope

- **Intraday refresh** of any dataset (hard EOD boundary, §1.2).
- **Class-A per-symbol widgets behind the daily job** — they stay on
  read-through `fmp_cached`; a daily price/technicals cache would be a
  correctness regression.
- **Physically merging** `openbb_techtrade` and `openbb_portfolio_intel`.
- **Deleting either paper system (D3)** — investigation only, gated on a diff.
- **Multi-exchange `as_of` labelling** — US-equity calendar for v1; note the ADR
  / dual-listed gap so the badge isn't quietly wrong for non-US names later.
  When Phase E fans out to a mixed holdings universe (review item #9), the badge
  copy for a non-US / ADR name must **not** imply a US-session date — either
  resolve its own exchange calendar or label the session neutrally until
  per-exchange calendars land.
- **Job queue (RQ/Celery) / in-backend APScheduler** — external scheduled
  process is the v1 runner; queue infra is future.

---

## 13. References

- Issues: #1932 (epic), #1963–#1969 (this subsystem), #1692/#1696/#1697/#1698/#1699
  (stub tabs unblocked by C), #1957/#1962 (cold-boot warmup — why Class A is
  already fast), #1953 (live-vs-demo provenance badge — badge lineage), #1790
  (`PI_PAPER_ENGINE` selector precedent).
- Repo precedents to mirror: `openbb_techtrade/execution/paper_engine.py`
  (`PaperEngine` Protocol, `SqlitePaperEngine`, `_SCHEMA`, `_tx()`,
  `get_default_engine()` selector), `mysql_paper_engine.py` (shared-pool
  acquisition), `openbb_fmp_cached.utils.database.get_connection_pool`.
- Design sources (scratch): `.dev-cycle/brainstorm-asof-snapshot-cache.md` (§1–§12,
  incl. the §12 architect/analyst review and §12.7 EOD constraint),
  `.dev-cycle/plan-techtrade-portfolio-alignment.md` (alignment analysis).
- Governing rules: `CLAUDE.md` (PII / sensitive-data rules, anti-mock testing
  rules R1–R11, provider policy `fmp_cached`-preferred, GH-issues tracker,
  fork-internal `portfolio` PRs only).
```

