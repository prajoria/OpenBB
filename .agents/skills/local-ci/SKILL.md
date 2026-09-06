---
name: local-ci
description: Run a project's local Docker-based CI stack via the deterministic `ci/local-ci` CLI. Detects the target project from CWD or an explicit arg, invokes `ci/local-ci <project> [tiers...] --json`, parses the `---LOCAL-CI-JSON---` machine-summary block, and reports pass/fail with a first-failure excerpt on any tier failure. **Zero hardcoded tier or project names** — discovers everything via `ci/local-ci --list --json` so adding a tier or project is a one-file YAML edit that this skill picks up automatically. Use when the user asks to "run local CI", "run CI locally", "run the CI for <project>", "run the mysql tier", or otherwise wants to reproduce the CI stack for a project inside Docker (including tiers GH-hosted CI cannot run, e.g. `requires_mysql` restored from `H:\DBBackup`). Do NOT use for GH Actions itself, desktop builds, or CodeQL — those stay on GH and the CLI will refuse them.
---

# local-ci — thin wrapper around `ci/local-ci`

The **deterministic CLI at `ci/local-ci`** is the source of truth for all
local CI execution. This skill's entire job is:

1. Discover projects + tiers by shelling out to `ci/local-ci --list --json`.
2. Detect the target project from CWD or an explicit user arg.
3. Invoke `ci/local-ci <project> [tiers...] --json` with flag passthrough.
4. Slice the trailing JSON block after the `---LOCAL-CI-JSON---` marker.
5. Render a compact pass/fail table + `first_failure_excerpt` on failure.
6. **On non-zero exit code, do NOT claim success** (verification-before-completion discipline).

## Contract with the CLI

- Config schema: `ci/local_ci/schema/local-ci.schema.json`
- Report schema: `ci/local_ci/schema/report.schema.json` (version tag `local-ci/v1`)
- Full CLI reference: `ci/local_ci/cli.py` (positional args, flags, exit codes)
- Formal spec: `docs/Specs/Local-CI-Skill-Spec.md`
- Boundary reference: `reference/cli-contract.md`
- Project inventory: `reference/project-map.md` (list snapshot; the live list is always `ci/local-ci --list --json`)

## Invocation flow

Every skill run follows the same 5 steps. Do not skip any of them.

### Step 1 — Discover

```bash
ci/local-ci --list --json
```

This returns the current inventory of projects and their tiers. **Never
assume** what tiers exist for a project — the YAML is the truth. If
`--list --json` returns `{"projects": []}`, no local-ci stacks exist yet
in the repo; tell the user which epic issue tracks adding them (#980 for
this repo) and stop.

### Step 2 — Resolve target

Resolution order:

1. **Explicit user arg** — "run local CI for openbb" → project=openbb.
2. **Tier + implicit project** — "run the mysql tier" with exactly one
   project having a `mysql` tier → resolve to that project. If multiple
   projects have the same tier name, ask the user.
3. **CWD-based detection** — if the user's active file is under
   `ci/<name>/` or the wider project directory that `local-ci.yml`
   points at, use that project.
4. **Ambiguous** — list the projects and ask.

For the tier list:

- User named tiers → pass them through as-is.
- No tiers named → let the CLI use `default_tiers` from the YAML (do not
  hardcode `[lint, unit]` here — the YAML owns that decision).

### Step 3 — Invoke

```bash
ci/local-ci <project> [tier1 tier2 ...] --json [flags...]
```

Flag passthrough rules:

| User says | Flag |
|---|---|
| "fresh", "re-restore", "clean sidecar volume" | `--fresh` |
| "keep it running", "leave the stack up" | `--keep-up` |
| "just show me what would run", "dry run" | `--dry-run` (skip JSON parsing step, print the plan) |
| "pull latest images", "freshen images" | `--pull` |
| "verbose", "stream everything" | `-v` |

Always pass `--json` unless the user asked for `--dry-run`. The JSON
block is how the skill knows what to report; without it, this skill
degrades to a raw pass-through and cannot produce the pass/fail table.

### Step 4 — Slice the JSON block

The CLI's stdout looks like:

```
local-ci: openbb — FAIL
  [PASS ] lint            42.10s  exit=0
  [FAIL ] unit           611.40s  exit=1
---LOCAL-CI-JSON---
{
  "schema": "local-ci/v1",
  "project": "openbb",
  "tiers": [...],
  "sidecars": [...],
  "overall_status": "fail",
  "overall_exit_code": 1
}
```

Split on the delimiter line `---LOCAL-CI-JSON---`. Everything after it
is a single JSON object. If the delimiter is missing (e.g. because the
process crashed before printing the JSON), the CLI exit code is still
the source of truth — treat as failure with "CLI aborted before emitting
JSON summary" and paste the stderr.

### Step 5 — Report

Render to chat:

- **One-line header**: `local-ci <project>: <overall_status.upper()>`.
- **Per-tier table**: name / status / duration / exit code.
- **On any failing tier**: paste the `first_failure_excerpt` in a code block.
- **Sidecar state**: only mention if `brought_up=true`.
- **On non-zero exit**: explicitly say "local CI did NOT pass" — do not
  soften. The user needs to know a failure survived the run.

## Discovery-first, always

There are **zero hardcoded tier names or project names** in this skill.
Every invocation starts with a fresh `--list --json`. This is deliberate:

- Adding a tier to a project's `local-ci.yml` is picked up on the next
  skill run with no code change here.
- Adding a whole new project (new `ci/<name>/local-ci.yml`) is picked up
  the same way.
- If a user asks for a tier that doesn't exist, the CLI returns exit 2
  with a list of available tiers — surface that message verbatim.

## Failure handling — respect the exit code

The CLI's exit codes are the primary signal:

| Exit | Meaning | Skill response |
|---|---|---|
| 0 | All tiers passed | Report success with the pass table |
| 1 | ≥1 tier failed | Report failure, paste `first_failure_excerpt` for each failed tier |
| 2 | CLI misuse (bad project/tier) | Show the CLI's stderr; do not retry with guessed args |
| 3 | Config error (YAML invalid) | Show the file+path from stderr; suggest running `--list --json` to see the schema |
| 4 | Docker error (daemon down, build failed, sidecar unhealthy) | Ask the user whether Docker Desktop is running; suggest `docker ps` |
| 5 | Init error (e.g. `DBBACKUP_DIR` missing) | Paste the CLI's error message verbatim — it names the missing file / env var |

**On any non-zero exit, do NOT paper over it** with "there were some
issues but…" — call it a failure and hand back the CLI's own error text.

## Red flags — do not do these

- ❌ Rewriting tier commands "for clarity" — the YAML is the contract; the CLI runs the YAML.
- ❌ Adding a tier name to this SKILL.md — go edit the project's `local-ci.yml` instead.
- ❌ Skipping `--json` because "I can parse the pretty output" — the delimited JSON is the machine contract; the pretty output is for humans.
- ❌ Reporting `overall_status: pass` when the CLI exited non-zero — the exit code is the truth.
- ❌ Suggesting the user run `docker compose ...` directly — the whole point is that the CLI is the invocation surface.
- ❌ Trying to run GH Actions workflows (desktop builds, CodeQL) — the CLI won't offer them; if the user asks, tell them to push and let GH run it.

## Scope boundaries

This skill is a wrapper. It does NOT:

- Modify `local-ci.yml`, `Dockerfile.ci`, or `docker-compose.ci.yml`.
- Manage the MySQL sidecar directly — the CLI's `mysql_restore` init
  handler does that.
- Substitute for GH Actions — it complements them by running the same
  commands locally, plus tiers GH cannot run (e.g. `requires_mysql`).
- Emulate Windows or macOS runners — Docker is Linux-only. Desktop
  builds and CodeQL stay on GH.

## Related

- `openbb-dev-cycle` — full 10-phase feature workflow; local-ci is what
  its Phase 6 (`/verify`) delegates to for the OpenBB stack.
- `simplify`, `code-review`, `security-review` — pre/post-CI review
  layers; orthogonal to what this skill does.
