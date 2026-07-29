# Create GH Project "Pine Script Support" — session prompt

**Purpose:** Reusable prompt to hand to a Claude Code session that has your
`prajoria/OpenBB` repo checked out. It creates a GitHub Project mirroring the
shape of Project #4 (Portfolio Intelligence Engine), tuned for Pine Script
support work, and seeds a root epic issue.

Paste the section below into a fresh session verbatim. It's self-contained —
no other files needed.

---

## Prompt to paste

> Create a new GitHub Project titled **"Pine Script Support"** under my
> `prajoria` GitHub account, mirroring the structural pattern of Project #4
> ("Portfolio Intelligence Engine") on the same account but tuned for Pine
> Script domain vocabulary. Follow the steps below in order and report each
> one as it completes. Use my `.venv_win` for any Python. Commit any scripts
> you create under `scripts/` — do not commit them until I authorize.
>
> ### Prerequisites (verify first, halt if any missing)
>
> - `gh auth status` must show scopes including `project` and `repo`. If not,
>   halt and print exactly: `gh auth refresh -h github.com -s project,read:project`
>   for me to run.
> - Target repo: `prajoria/OpenBB`. Verify with `gh repo view prajoria/OpenBB
>   --json name` before doing anything write-ish.
> - You will use `gh` CLI, `gh api graphql`, and the raw GitHub GraphQL API
>   (all authenticated via my existing `gh` token). No web-UI steps allowed
>   in your side of the work — surface any UI-only step at the end as
>   explicit manual instructions.
>
> ### Step 1 — Create the project
>
> Run `gh project create --owner prajoria --title "Pine Script Support"
> --format json`. Capture the project's `id` (e.g. `PVT_kw...`) and `number`
> (e.g. `5`). Save both to `scripts/pine_script_project.json` for resume
> safety.
>
> ### Step 2 — Link project to the repo
>
> Use `gh project link <number> --owner prajoria --repo prajoria/OpenBB` so
> issues from that repo can be added to the project via the "Add to project"
> button on issue pages.
>
> ### Step 3 — Create 5 custom fields (Pine-Script-tuned)
>
> Use `gh project field-create` for each. Save every returned field `id`
> AND every single-select option `id` to
> `scripts/pine_script_project.json` — you will need them in step 5.
>
> | Field name | Type | Single-select options |
> |---|---|---|
> | `Area` | `SINGLE_SELECT` | `Parser`, `Runtime`, `Types`, `StdLib`, `Docs`, `Examples`, `Tests`, `Tooling` |
> | `Priority` | `SINGLE_SELECT` | `P0`, `P1`, `P2`, `P3` |
> | `Type` | `SINGLE_SELECT` | `Epic`, `Feature`, `Task`, `Bug` |
> | `Start` | `DATE` | (no options) |
> | `End` | `DATE` | (no options) |
>
> Colour hints for labels (only if you also create matching GH labels — see
> step 4): Area=blues, Priority=reds→greens, Type=neutrals.
>
> ### Step 4 — Create matching labels on the repo
>
> Mirror the project's single-selects as issue labels so filtering works
> outside the project too. Use `gh label create <name> --color <hex>
> --description <desc> --force`. Suggested names + colors:
>
> - `pine-script` — `1d76db` — "Pine Script support program"
> - `pine-parser`, `pine-runtime`, `pine-types`, `pine-stdlib`, `pine-docs`,
>   `pine-examples`, `pine-tests`, `pine-tooling` — shades of blue
> - `priority-p0`, `priority-p1`, `priority-p2`, `priority-p3` — red→green
>
> Skip if the label already exists (use `--force` to make idempotent).
>
> ### Step 5 — Seed the root epic issue
>
> Create a single tracking issue on `prajoria/OpenBB` titled
> **"[EPIC] Pine Script Support"** with the body below (adapt only the
> `Docs` / `Contact` bullets — leave the rest verbatim):
>
> ```markdown
> ## Purpose
>
> Program-level tracking issue for Pine Script support in OpenBB. All
> Pine-Script-related work (parser, runtime, type system, standard library,
> docs, examples, tests, tooling) attaches here as a sub-issue.
>
> ## Goals
>
> - Provide a first-class Pine Script surface within OpenBB (or an adjacent
>   extension) that OpenBB users can consume alongside existing quant tools.
> - Parity with Pine Script v5/v6 language semantics where practical.
> - Coverage of the standard library, docs, and worked examples that the
>   TradingView user base expects.
>
> ## Non-goals
>
> - Bit-for-bit compatibility with TradingView's Pine execution engine
>   (their VM is proprietary; we target semantic equivalence, not identical
>   IEEE754 rounding).
> - Support for private/undocumented Pine features.
>
> ## How this is organized
>
> - This issue is the root. Every sub-topic (parser, runtime, docs, etc.)
>   gets its own child issue linked here via GitHub's native sub-issue
>   feature.
> - Every child is added to the "Pine Script Support" project so the Area /
>   Priority / Type / dates fields are populated.
> - PRs land against `develop` unless a program-branch is agreed on separately.
>
> ## Docs
>
> - Design spec: TBD
> - Contact: @prajoria
> ```
>
> Labels on the epic: `pine-script`, `type-epic` (create `type-epic` if
> missing — same color as portfolio-intel's).
>
> After creation, capture the issue number and node_id and add both to
> `scripts/pine_script_project.json`.
>
> ### Step 6 — Add the epic to the project + set fields
>
> Use the `addProjectV2ItemById` GraphQL mutation with the project ID and
> issue node_id. Then use `updateProjectV2ItemFieldValue` to set:
>
> - `Type` = `Epic`
> - `Area` = (leave blank — epic spans all)
> - `Priority` = `P1`
> - `Start` = today's date (ISO YYYY-MM-DD)
> - `End` = today + 90 days (initial guess; can be shifted later)
>
> ### Step 7 — Report the manual browser-only steps
>
> GitHub's public API does NOT support creating/renaming/configuring views.
> After you finish steps 1–6, print exactly these instructions for me to do
> in the browser:
>
> ```
> Manual steps (GitHub API doesn't expose view CRUD):
>
> 1. Open https://github.com/users/prajoria/projects/<NUMBER>
> 2. Delete the default "View 1" (▾ next to tab → Delete view).
> 3. Add 3 views:
>    a. "+ New view" → Board → Group by = Area → rename to "Board by Area"
>    b. "+ New view" → Table → Group by = Priority → rename to "Table by Priority"
>    c. "+ New view" → Roadmap → Start = Start, Target = End → rename to "Roadmap"
> 4. (Optional) On the Roadmap, zoom to Weeks or Months as you prefer.
> ```
>
> ### Step 8 — Final report
>
> Print a summary with:
> - Project URL (`https://github.com/users/prajoria/projects/<NUMBER>`)
> - Number of custom fields created (should be 5)
> - Number of labels created / already-existed
> - Root epic issue URL
> - Any errors encountered and how you handled them
> - Exact 4-line manual browser task list from step 7
>
> ### Guard-rails
>
> - Do NOT create any items other than the single root epic. Downstream
>   sub-issues are added by other devs.
> - Do NOT commit or push anything unless I say so — save scripts locally
>   under `scripts/pine_script_*.py` / `scripts/pine_script_project.json`
>   and report them at the end.
> - Do NOT modify `.beads/` or any existing bd state.
> - If you hit rate limits, sleep 15s and retry once; give up cleanly on
>   second failure with a resume instruction.

---

## Notes on the prompt design

- **Steps are numbered and self-verifying.** Each step reports done or halts
  cleanly. No implicit chaining.
- **Field / option IDs are captured to disk** so if the session dies you can
  resume by re-reading `scripts/pine_script_project.json` instead of
  re-doing steps 1–3.
- **Manual browser steps are surfaced at the end** exactly as they must be
  performed. GitHub's API gap on view CRUD is documented in-line so the
  next session doesn't try to work around it.
- **Guard-rails prevent scope creep.** Explicit "do not commit", "do not
  modify beads", "do not seed sub-issues" bounds.

## Reusing this prompt for other programs

Swap these substitutions to spin up another project with the same shape:

| Placeholder | Portfolio equivalent | Pine Script equivalent |
|---|---|---|
| Project title | `Portfolio Intelligence Engine` | `Pine Script Support` |
| Program label | `portfolio-intel` | `pine-script` |
| Field: domain grouping | `Phase` (M0..M4) | `Area` (Parser/Runtime/...) |
| Field: assignment | `Lane` (A-Data / ...) | `Priority` (P0..P3) |
| Type field | `Epic/Feature/Task/Bug` | same |
| Roadmap fields | `Start` / `End` | same |
| Root epic title | `[EPIC] Portfolio Intelligence Engine` | `[EPIC] Pine Script Support` |

For a third program (say "Documentation refresh"), copy this file, do the
substitutions once, and paste.
