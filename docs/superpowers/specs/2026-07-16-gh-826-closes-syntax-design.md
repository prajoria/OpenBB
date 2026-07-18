# Design: CI enforcement of `Closes #NN` syntax on `feat/pi-*` PRs

**GH Issue:** #826
**Author:** Claude (autopilot, per Daisy's blanket approval on 2026-07-16)
**Companion:** existing `.github/workflows/portfolio-intel-base-guard.yml` — same author-team pattern.

## Problem

The 2026-07-16 Project #4 tracker-sync audit found 6 shipped-but-open issues (#504, #506, #507, #509, #510, #511) because every merged `feat/pi-*` PR cited the retired `OpenBBTechnical-qy83.1.N` bd-id in its `Closes` clause. GitHub couldn't resolve those to real `#NN` references, so the issues stayed `Todo` on Project #4 even though the shipping PRs had merged into `portfolio`.

Root cause: **GitHub's auto-close only fires on the exact `Closes/Fixes/Resolves #NN | owner/repo#NN | full-URL` grammar**. Anything else (bd-ids, backtick-quoted identifiers, bare topic labels, prose references) is silently ignored. Prose-review by humans doesn't catch this at scale.

## Success criteria

1. Any PR targeting `portfolio` whose head-branch is `feat/pi-*` / `feature/pi-*` / `pi/*` (case-insensitive, matching the sibling base-guard's contract) must have at least ONE valid `Closes/Fixes/Resolves #NN` clause in the PR body — OR be explicitly marked `noissue` (docs-only, chore, dependency bump).
2. Any `Closes/Fixes/Resolves` clause present must reference `#NN` or `owner/repo#NN` (no bd-ids, no backticks, no URLs — URLs *would* actually work for GitHub's own auto-close, but we reject them for readability consistency with `portfolio-intel-base-guard`).
3. Fail loudly with an error message that (a) shows the offending line, (b) shows the correct grammar, (c) points at the CLAUDE.md Coordination section.
4. Green on this PR itself (which will cite `Closes #826`).

## Non-goals

- Do not validate that the `#NN` cited actually exists as an open issue. Rationale: cheap check first; if we want existence-checking later, that's a separate ticket. The retrospective audit is what catches non-existence — this workflow's job is *grammar* enforcement so retrospective audits never need to run again for the tracker-drift class.
- Do not scan commit messages. Only the PR body matters for GH's auto-close.
- Do not run on PRs that aren't from portfolio-intel branches. Portfolio-intel is the scope of Project #4; other work has its own rules.

## Approach

**Chosen:** single GitHub Actions workflow, bash-only (no Python or Node dependencies), triggered on the same `pull_request` events as the sibling base-guard, mirroring its structure exactly.

### Alternatives considered

- **Alt 1: A tightly-scoped Node action.** Rejected — bash grep suffices for grammar; a Node action adds a build step and a dependency for a task the shell handles in 20 lines.
- **Alt 2: A commit-message hook (pre-commit).** Rejected — misses squash-merge and edit-in-GH-UI paths, both of which shipped the drifted PRs we're fixing.
- **Alt 3: A GH App reading webhooks.** Rejected — infrastructure cost dwarfs benefit for a fork.

## Grammar spec

The check parses the PR body with a regex sensitive to line-start (avoids matching prose that happens to contain the word "closes").

```
GRAMMAR:  ^\s*(Closes|Fixes|Resolves)\s+(#\d+|[a-zA-Z][\w.-]*\/[\w.-]+#\d+)(\s*,\s*(#\d+|[a-zA-Z][\w.-]*\/[\w.-]+#\d+))*\s*\.?\s*$
```

Anchoring on start-of-line matches the community norm (both GitHub docs' examples and OpenBB-finance/openbb style). Bulleted lists (`- Closes #123`) match after stripping leading `- ` / `* `.

**Reject examples** (with error explaining why):
- `Closes \`OpenBBTechnical-qy83.1.4\`` (backticks + bd-id — the exact bug from PRs #466-#474)
- `Closes bd-qy83.1.4` (bd-id)
- `Closes https://github.com/prajoria/OpenBB/issues/826` (URL — works for GH auto-close, but rejected here for readability consistency)
- `This PR closes 826` (missing `#`)

**Accept examples:**
- `Closes #826`
- `Fixes #826, #827`
- `- Closes #826` (bulleted)
- `Resolves prajoria/OpenBB#826` (cross-repo shape — kept accepting since GH resolves it)

## Escape hatch: `noissue`

Some PRs legitimately don't close an issue: dependency bumps, pure docs, one-off chore branches. The escape hatch is a case-insensitive marker in the PR body:

```
noissue: <one-line reason>
```

When present, the workflow skips the "must have at least one Closes" check but still validates that any `Closes/Fixes/Resolves` clauses present are well-formed (grammar always enforced). This is cheaper than a `type:noissue` label because it lives in the PR author's action (edit the body) instead of requiring label-write permission.

## Implementation checklist

- [ ] `.github/workflows/portfolio-intel-closes-syntax.yml`
- [ ] Reuses `tj-actions/branch-names@5250492686b253f06fa55861556d1027b067aeb5` (same pin as base-guard)
- [ ] Reads `github.event.pull_request.body` via `${{ toJson(...) }}` piped through `jq -r` to preserve newlines
- [ ] Trigger: `pull_request` on `[opened, synchronize, reopened, edited]` targeting `portfolio` (edited = catches body-only edits)
- [ ] Concurrency group `${{ github.workflow }}-${{ github.ref }}` (matches base-guard)
- [ ] Skips gracefully if head-branch isn't portfolio-intel (defensive; the sibling base-guard handles the wrong-base case)
- [ ] Error message includes: offending line, correct grammar, link to `CLAUDE.md § Coordination — GitHub Issues only`
- [ ] TDD via a small `.dev-cycle/test-closes-syntax.sh` that exercises the regex against a fixture set BEFORE the workflow lands (RED first)

## Testing strategy

Since this is a bash-in-Actions rule, TDD is: **write a standalone bash function, exercise it against a fixture set locally, then embed it verbatim in the workflow.** That way the workflow itself is trivially small, the logic is testable outside Actions, and future edits regenerate green fixtures.

Fixture set:
1. `Closes #826` → PASS
2. `Fixes #826, #827` → PASS
3. `- Resolves #826` (bulleted) → PASS
4. `Resolves prajoria/OpenBB#826` → PASS
5. `Closes \`OpenBBTechnical-qy83.1.4\`` → FAIL (bd-id in backticks — historical bug)
6. `Closes bd-qy83.1.4` → FAIL (bd-id)
7. `Closes https://github.com/prajoria/OpenBB/issues/826` → FAIL (URL)
8. `Closes 826` → FAIL (missing #)
9. Body with no `Closes` at all, no `noissue:` → FAIL (missing-closes)
10. Body with no `Closes` and `noissue: docs-only cleanup` → PASS
11. Body with `closes #826` (lowercase) → PASS
12. Body with `Closes #826.` (trailing period) → PASS

## Rollout

1. Land this workflow on `portfolio` first (this PR).
2. Verify green on this PR's own body (which cites `Closes #826`).
3. Future `feat/pi-*` PRs auto-checked. Existing merged history is immune (workflow only runs on `pull_request` events).
4. Reviewer-discipline rule in `docs/superpowers/plans/2026-07-16-portfolio-intel-planning-approach.md` becomes mechanically enforced instead of requiring Mira judgment.
