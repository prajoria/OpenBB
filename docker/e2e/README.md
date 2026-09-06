# OpenBB `develop` end-to-end stability harness

A fully containerized harness that always starts from a **fresh clone of
`origin/develop`**, builds the whole stack bottom-up, runs an exhaustive
integration sweep against real providers + a real MySQL, and writes
local bug reports for manual review and issue filing.

Fills the gap that CI can't: no OpenAI keys, no FMP/FRED keys, no
database, no Analysis pipeline runs, no desktop bundle check.

## What it runs

```
mysql (healthy) → checkout (fresh develop)
                    ↓
             platform (dev_install -e)
                    ↓
             api (uvicorn up, healthy)
                    ↓
   ┌──────┬──────────┬──────────┬───────────┬──────────┐
   pytest analysis   doctor     api_smoke   desktop
   (unit +
   integration)
   ↓
   reporter  ──►  ./artifacts/<run-id>/summary.md
                  ./artifacts/<run-id>/bugs/*.md  (human reviews, then files)
```

## Prereqs

- Docker Desktop / Docker Engine ≥ 24 with Compose v2 (`docker compose`)
- `~/.openbb_platform/user_settings.json` with your provider keys
  (FMP, FRED, OpenAI, etc.). Bind-mounted read-only into every stage.
- Optionally `${REPO_ROOT}/.env` with `GH_TOKEN=...` for future
  automation. The harness currently writes local bug files only;
  a human reviews `artifacts/<run-id>/bugs/*.md` and files issues
  manually.

## Usage

```bash
cd docker/e2e
./run.sh                    # full sweep
./run.sh --skip-desktop     # skip the Tauri web-build stage
./run.sh --skip-integration # unit tests only (fast smoke)
./run.sh --keep-volumes     # dev-only: don't wipe the openbb_src volume
```

Every run gets a unique `RUN_ID` (`YYYYMMDDTHHMMSSZ-<hostname>`), and
all outputs land under `docker/e2e/artifacts/<RUN_ID>/`:

```
artifacts/<RUN_ID>/
├── summary.md              # top-level report
├── checkout/{status, stdout.log, stderr.log, develop_sha}
├── platform/{status, stdout.log, stderr.log}
├── pytest/{status, junit-unit.xml, junit-integration.xml, ...}
├── analysis/{status, summary.json, ...}
├── doctor/{status, summary.json, ...}
├── api_smoke/{status, summary.json, ...}
└── desktop/{status, stdout.log, stderr.log}
```

## Failure isolation & reporter contract

Every stage script writes exactly one thing the reporter cares about:

```
/artifacts/${RUN_ID}/<stage>/status  →  "pass" | "fail" | "skipped"
```

Runner stages never import from each other. The reporter reads only
this contract, so a runner crash can't take down the report path.

## Two-phase bug reporting (the harness NEVER files issues)

Failures go through a deliberate two-step flow — this is a policy
choice, not an oversight. See "Automated test-harness bug reporting"
in `~/.claude/CLAUDE.md` for the general rule.

**Phase 1 — harness writes local bug files.** When a stage is `fail`,
`report_and_file.sh` writes a structured bug file to
`artifacts/<RUN_ID>/bugs/<stage>.md` containing:

- Run ID + `develop` SHA + stage name + timestamp
- The stage's `summary.json` (if any)
- Junit failure/error markers (if any)
- First 6KB of stderr, last 4KB of stdout
- A reviewer checklist (repro / root-cause / dedupe / fix / impact)

That's it. The reporter does NOT call `gh`, does NOT touch Beads, does
NOT hit any tracker. It just dumps evidence to disk.

**Phase 2 — reviewer validates and files.** After a run, list the
pending bug files:

```bash
./docker/e2e/scripts/review_bugs.sh                # latest run
./docker/e2e/scripts/review_bugs.sh <run-id>       # specific run
./docker/e2e/scripts/review_bugs.sh --json         # machine-readable
```

For each bug, the reviewer (Claude or an engineer):

1. Reads the local bug file.
2. Cross-checks the claim against the current `develop` tree — opens
   the referenced files, confirms the symbol/import/line really is
   broken, not a stale log or environment fluke.
3. Searches the tracker for existing open issues on the same failure
   (`gh issue list ... --search`).
4. Drafts a concrete fix in the issue body (or explicitly marks it
   investigation-only).
5. Files the tracker issue by hand with the validated content.

Rationale: harnesses produce raw evidence but can't distinguish noise
from signal, can't propose fixes grounded in the current tree, and
can't dedupe intelligently. Direct-file harnesses either flood the
tracker or suppress real regressions via naive dedup.

## Design notes / non-goals

- **Fresh develop every run.** `checkout` wipes and re-clones. The
  host working copy is *never* mounted — this measures `origin/develop`,
  not your WIP.
- **Secrets bind-mounted read-only.** Never baked into images. See
  `.dockerignore` for the belt-and-suspenders exclusion list.
- **Reporter never files issues.** See two-phase rule above.
- **Nightly scheduling / watch-mode**: deliberately out of scope for
  the first cut. Design leaves hooks (RUN_ID, artifact layout) for a
  cron or GH Actions runner to invoke `./run.sh`.
- **Tauri binary build**: skipped. Only the web bundle is validated
  (needs xvfb + linux Tauri deps to do the full binary).

See `plans/luminous-petting-tome.md` for the full design.
