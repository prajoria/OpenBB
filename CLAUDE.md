# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Communication Conventions

**Always pair an issue number with its title/description — never cite a bare number.**
When referencing any GitHub Issue (`#NN`) in a question, status update, summary,
commit message, or PR body, write it as `#NN (short description)` so it is
understandable without a lookup.

- Good: `#65 (Scaffold techtrade extension + entry point + green build)`
- Bad: `#65`

If you don't already know the title, look it up first (`gh issue view NN`)
before mentioning it.

## Coordination — GitHub Issues only

**GitHub Issues are the sole source of truth for all work tracking in this
repository, across every branch.** The prior beads (`bd`) system has been
retired. Do NOT use `bd` commands, do NOT create `.beads/` state, and do NOT
cite `bd-XX` identifiers in new work.

**Workflow:**

1. Every unit of work has a GitHub Issue. Find work with `gh issue list`.
2. Claim by self-assigning: `gh issue edit <NN> --add-assignee @me`.
3. Branch names embed the issue number: `feat/topic-gh-<NN>`,
   `fix/topic-gh-<NN>`, `docs/topic-gh-<NN>`.
4. Every commit body cites its issue: `Refs #NN` (or `Closes #NN` on the
   final commit / PR body for auto-close on merge).
5. PR title cites the issue: `<type>(<scope>): <what> (#NN)`.

**Cross-session memory:** durable knowledge lives in `docs/MEMORIES.md`
(a plain checked-in markdown file). Append new entries; do NOT create
scratch `MEMORY.md` files in random locations.

**Legacy references:** any `bd-XX` identifier in old commit history, old
comments, or old docs is historical only — treat it as a permanent
identifier of past work, but never file new `bd-XX` items.

## Claim + heartbeat protocol (Project #5)

When executing the `openbb-dev-cycle` skill (or otherwise working
through Project #5 issues autonomously), every agent MUST follow the
claim + heartbeat discipline below. This is the Pine-program equivalent
of the Portfolio program's `pi_claim.py` — the goal is identical: no
two agents race on the same issue, and abandoned claims can be safely
reclaimed by a fresh agent after 2 hours of heartbeat silence.

### Session-start (BEFORE Phase 1 of openbb-dev-cycle)

```bash
# What issues do I already own from prior sessions?
gh issue list --repo prajoria/OpenBB --assignee @me --state open --limit 20

# What open Pine PRs do I own?
gh pr list --repo prajoria/OpenBB --author @me --state open \
  --base openbb_pine_support

# What issues on Project #5 are In Progress (potentially stale)?
gh project item-list 5 --owner prajoria --format json --limit 200 \
  | jq '.items[] | select(.status=="In Progress") | {n:.content.number,t:.content.title}'
```

Release any assignee claim on an issue you are NOT resuming this session:

```bash
gh issue edit <NN> --remove-assignee @me --repo prajoria/OpenBB
gh issue comment <NN> --repo prajoria/OpenBB \
  --body "Releasing claim — not resuming this session."
```

Reclaim a stale In-Progress issue (no heartbeat comment from its
assignee in the last 2h) only after posting an audit comment naming
the prior owner and reason.

### Claim protocol (Phase 3 of openbb-dev-cycle)

1. **Self-assign the issue** — this is the durable claim signal:
   ```bash
   gh issue edit <NN> --add-assignee @me --repo prajoria/OpenBB
   ```
2. **Move to In Progress on the project board.** Requires the project
   item ID + status field IDs (cached in `scripts/pine_script_project.json`).
   Use the helper below (define once, reuse):
   ```bash
   python scripts/pine_claim.py <NN> in-progress
   ```
   Until `scripts/pine_claim.py` is authored (tracked as a follow-up
   issue), fall back to a `gh issue comment` claim marker naming the
   branch:
   ```bash
   gh issue comment <NN> --repo prajoria/OpenBB \
     --body "🚧 Claimed for work on branch \`<branch-name>\` — heartbeat every ≤10 min until PR merged or claim released."
   ```
3. **Post the initial heartbeat immediately** — this makes
   `--list-stale` see you from minute 1:
   ```bash
   gh issue comment <NN> --repo prajoria/OpenBB --body "💓 heartbeat"
   ```

### Heartbeat rule (Phases 4–9 of openbb-dev-cycle)

While ANY Project #5 issue is `In Progress` under this cycle, you MUST
post a heartbeat comment at least every **10 minutes** until the issue
closes (via PR merge) or you release the claim.

- **Heartbeat at natural pause points**: after every test run, after
  every commit, after every review-tool invocation, before + after
  `/verify`, before + after opening the PR. Rough target: never let
  >10 min pass without one.
- **A heartbeat is not a status update.** It's an "I'm still alive"
  signal — a one-line `💓 heartbeat` comment is enough. If real progress
  is worth documenting, add a second sentence, but the minimum viable
  heartbeat is the emoji + word.
- **Faked heartbeats are worse than missed ones.** An empty ping every
  10 min for 2h reads as real progress to every other agent but wastes
  2h before anyone else can pick up the work. If you're actually
  blocked, post a comment explaining what's blocked, then release the
  claim and pick a different task.
- **Long-running steps (test suites, `/verify` end-to-end, CI waits):**
  set a `ScheduleWakeup delaySeconds=540 reason="heartbeat #NN"`
  reminder BEFORE starting the step so a 9-minute wakeup fires before
  the 10-minute threshold expires.
- **Stale = 2h without heartbeat.** Any other agent may reclaim your
  issue after 2h of comment silence. Don't treat reclaim as adversarial
  — it's the design.

### Release protocol (any time you stop working on an issue mid-cycle)

```bash
gh issue edit <NN> --remove-assignee @me --repo prajoria/OpenBB
gh issue comment <NN> --repo prajoria/OpenBB \
  --body "🔓 Releasing claim — <one-sentence reason>. Next agent is free to reclaim."
```

Then also comment on the project item if it had been moved to
In Progress on the board, or leave a note that the next claimant should
flip the board status themselves.

### Auto-close via PR merge (Phase 8/9)

The self-assignment is durable through PR merge — GitHub keeps the
assignee even after `Closes #NN` auto-closes the issue. There is no
"unclaim on merge" step; a closed issue is the terminal state.

## Pine Support Branch Workflow (long-running feature branch)

**`openbb_pine_support` is a LONG-RUNNING integration branch for all Pine
Script support work.** Treat it the way you would treat `develop` for the
scope of the Pine project: it accumulates completed feature work over
many sessions, and only gets promoted to `develop` via a single PR when
the user explicitly says so.

**Hard rules (do NOT violate without explicit user instruction):**

1. **Never open a PR from `openbb_pine_support` → `develop`** until the
   user says, in their own words, something equivalent to
   *"let's finally generate a PR to develop"* / *"open the develop PR now"*.
   Until then, this branch stays open and keeps accumulating merges from
   feature side-branches. Merging `develop` INTO `openbb_pine_support` to
   stay current is fine and encouraged; the forbidden direction is the
   outgoing PR.
2. **All Pine-related development happens on side-branches cut from
   `openbb_pine_support`, not from `develop`.** Naming:
   `feat/pine-<topic>-gh-<NN>`, `fix/pine-<topic>-gh-<NN>`,
   `docs/pine-<topic>-gh-<NN>`. Side-branches PR back into
   `openbb_pine_support` (NOT into `develop`) via
   `gh pr create --base openbb_pine_support`.
3. **Every Pine issue lives on GitHub Project #5 (Pine Script Support)**:
   <https://github.com/users/prajoria/projects/5/views/2>. When filing a
   new issue for Pine work, add it to that project:

   ```bash
   gh issue create --title "<title>" --body "<body>" \
     --project "Pine Script Support"
   # or for an existing issue:
   gh project item-add 5 --owner prajoria --url <issue-url>
   ```

   If unsure whether a piece of work is "Pine-related," ask before
   filing; do not silently attach unrelated work to Project #5.
4. **PR titles for side-branches** follow the standard convention plus a
   `pine:` scope tag so they're greppable:
   `<type>(pine/<area>): <what> (#NN)` — e.g.
   `feat(pine/parser): tokenize plot() calls (#217)`.
5. **The eventual `openbb_pine_support` → `develop` PR** (when the user
   asks) should summarize the accumulated Pine work, list the closed
   Project #5 items, and note any migrations / breaking changes. Do not
   pre-draft this PR body speculatively — wait for the go-ahead.

**Session-start check for this branch:** if the current branch is
`openbb_pine_support`, print a one-line reminder that it is a
long-running integration branch and that new work should be done on a
side-branch cut from HEAD, not committed directly. Direct commits to
`openbb_pine_support` are allowed only for (a) merge commits from side
branches, (b) merges pulling `develop` in, and (c) trivial doc/regen
cleanups the user has explicitly authorized this session.

**Python environment isolation** — Pine work MUST use
`.venv_pine_support` (`H:\masterswork\git\OpenBB-Pine\.venv_pine_support`),
not the shared `.venv_win`. `.venv_win` is used by parallel folders
(Analysis, techtrade, and other dev paths) that share this machine, and
`pip install -e` operations bleed across every session using the same
interpreter. `.venv_pine_support` contains only:

- `openbb-core` (editable)
- `openbb-pine` (editable)
- `pyne_compiler` (editable from `third_party/pynecore`)
- `openbb-fmp-cached` (editable — the only provider Pine uses)
- Dev tooling: `pytest`, `pytest-mock`, `pytest-asyncio`, `pytest-recorder`,
  `pytest-cov`, `time-machine`, `pytest-subtests`, `pytest-order`,
  `pytest-spec`, `black`, `ruff`, `codespell`

To reproduce or bootstrap after a clean checkout:

```powershell
C:\Users\daaji\AppData\Local\Programs\Python\Python312\python.exe -m venv .venv_pine_support
.venv_pine_support\Scripts\python.exe -m pip install --upgrade pip
.venv_pine_support\Scripts\python.exe -m pip install `
  -e openbb_platform/core `
  -e third_party/pynecore `
  -e openbb_platform/providers/fmp_cached `
  -e openbb_platform/extensions/pine `
  pytest pytest-mock pytest-asyncio pytest-recorder pytest-cov `
  time-machine pytest-subtests pytest-order pytest-spec `
  black ruff codespell
```

Replace every `.venv_win\Scripts\python.exe` invocation in Pine-scope
work with `.venv_pine_support\Scripts\python.exe`. If a test needs
another extension (e.g. `openbb-backtest` for the #589 bridge), `pip
install -e openbb_platform/extensions/backtest` into
`.venv_pine_support` and note the addition here. **Do NOT run
`openbb_platform/dev_install.py -e`** — that installs every extension
and defeats the isolation.

`.venv_pine_support` is gitignored.

### Merge authorization for Pine-scope PRs

**Session-scoped, opt-in.** By default, Claude never runs `gh pr merge` in
any repo — merges are always a human action. The exception below only
activates when the user says something equivalent to *"apply the Pine
merge rule this session"* / *"you're authorized to merge Pine PRs this
session"*. New session = grant lapses. The rule stays disabled until
re-authorized.

Once authorized in-session, Claude MAY run `gh pr merge` on a PR without
further prompting **only when ALL of** the following hold:

1. **Repo:** `prajoria/OpenBB` (the fork; not `OpenBB-finance/OpenBB` upstream).
2. **Base branch:** `openbb_pine_support` (never `develop` or any other
   long-lived branch).
3. **Head branch matches Pine convention:** `feat/pine-*`, `fix/pine-*`,
   `docs/pine-*`, or `chore(pine)/*`.
4. **All CI checks on PR HEAD are `SUCCESS`.** No `PENDING`, `QUEUED`,
   `FAILURE`, `CANCELLED`, or `SKIPPED` on required checks. Verify with
   `gh pr view <N> --json statusCheckRollup` right before merge — CI can
   invalidate between the last check and the merge attempt.
5. **Phase 9 exit predicate holds** (per `openbb-dev-cycle` skill):
   - Every review finding either applied-and-verified or deferred with a
     GH issue link
   - Latest `code-review` invocation returned "no issues" or skip-per-HEAD
   - Latest `security-review` has 0 unaddressed HIGH/CRITICAL findings
   - Latest `coderabbit:autofix` reports 0 unresolved GH review threads
6. **PR body contains `Closes #NN`** for at least one issue on Project #5
   (Pine Script Support). Otherwise the merge orphans the tracker.
7. **No `[hold]`, `[wip]`, or `do-not-merge` label** on the PR.

**Any PR failing any clause requires explicit per-merge authorization**
from the user, even in an authorized session.

**Merge method:** default to `gh pr merge <N> --repo prajoria/OpenBB
--squash --delete-branch` unless the user has previously stated a different
preference this session or the PR body says otherwise. Squash keeps the
integration branch's history readable (one commit per feature).

**PRs outside Pine scope** (base `develop`, `portfolio`, or any non-Pine
branch; head not matching the Pine naming convention) **always** require
explicit per-merge authorization — this rule does not apply to them.

**After merging:**

- Verify referenced issues auto-closed (`gh issue view <NN>`)
- `git fetch origin openbb_pine_support && git pull` to sync local
- Delete the local feature branch if `--delete-branch` was used remotely
- Comment or notify in-chat: "Merged #NNN — issues #A, #B now closed."

**Escape hatch:** if the user says *"stop / cancel / don't merge that"*
mid-flow, abort immediately. Even under this rule, the last word is theirs.

## Overview

OpenBB is an open-source financial data platform that provides the "connect once, consume everywhere" infrastructure for integrating financial data sources. The project consists of multiple components:

- **OpenBB Platform** (Python): Core data integration platform with 50+ data providers
- **OpenBB CLI**: Command-line interface for the platform
- **Desktop App**: Tauri-based desktop application with React frontend
- **API Server**: FastAPI REST API server for external integrations

## Architecture

### Core Structure

- `openbb_platform/core/`: Core platform functionality and OBB object
- `openbb_platform/extensions/`: Domain-specific extensions (equity, crypto, economy, etc.)
- `openbb_platform/providers/`: Data provider integrations (yfinance, FRED, FMP, etc.)
- `cli/`: Command-line interface implementation
- `desktop/`: Tauri + React desktop application

### Key Concepts

- **Extensions**: Domain-specific modules (equity, crypto, economy) that group related functionality
- **Providers**: Data source integrations that implement standardized interfaces
- **OBB Object**: Central `obb` object that provides access to all platform features
- **Standardized Data Models**: Common data structures across all providers

## Development Commands

### Environment Setup

```bash
# Activate .venv_win (PowerShell — Windows)
.\.venv_win\Scripts\Activate.ps1

# Install for development (editable installs) — run inside .venv_win
cd openbb_platform && python dev_install.py -e
```

### Using Helper Script

```bash
./openbb.sh test         # Test installation
./openbb.sh api          # Start REST API server (port 8000)
./openbb.sh shell        # Python shell with OpenBB imported
./openbb.sh build        # Rebuild platform after changes
./openbb.sh install      # Run development installation
./openbb.sh pytest       # Run unit tests (excludes integration)
```

### Testing

```bash
# Run unit tests (excludes integration tests) — use .venv_win python
.venv_win\Scripts\python.exe -m pytest openbb_platform -m "not integration"

# Run Analysis module unit tests (no live API needed)
.venv_win\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "not integration" -v

# Run Analysis integration tests (requires fmp_cached API key — reads from user_settings.json + .env)
.venv_win\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "integration" -v

# Test specific provider
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/yfinance/tests/

# Run integration tests (requires API keys)
.venv_win\Scripts\python.exe -m pytest openbb_platform -m "integration"

# Test installation
.venv_win\Scripts\python.exe test_openbb.py
```

### API Server

```bash
# Start FastAPI server
cd openbb_platform
uvicorn openbb_core.api.rest_api:app --host 0.0.0.0 --port 8000 --reload

# Server will be available at http://127.0.0.1:8000
# API docs at http://127.0.0.1:8000/docs
```

### Desktop App

```bash
cd desktop/

# Install dependencies
npm install

# Development server
npm run dev          # Runs on port 1470

# Build application
npm run build

# Run Tauri desktop app
npm run tauri dev

# Lint frontend code
npm run lint
```

### CLI

```bash
cd cli/

# Install CLI in development mode
pip install -e .

# Run CLI
openbb-cli
```

## Platform Development

### Adding New Provider

1. Create new directory in `openbb_platform/providers/`
2. Implement provider following existing patterns (see `yfinance` provider)
3. Add to `pyproject.toml` dependencies
4. Run `python dev_install.py -e` to install

### Adding New Extension

1. Create new directory in `openbb_platform/extensions/`
2. Implement extension following existing patterns (see `equity` extension)
3. Add to `pyproject.toml` dependencies
4. Run `python dev_install.py -e` to install

### After Code Changes

```bash
# Rebuild platform to reflect changes (run with .venv_win python)
.venv_win\Scripts\python.exe -c "import openbb; openbb.build()"
```

## Code Quality

### Pre-commit Hooks

The repository uses extensive pre-commit hooks:

- **Black**: Code formatting
- **Ruff**: Linting and style checks
- **MyPy**: Type checking
- **PyLint**: Additional linting
- **PyDocStyle**: Docstring style checking
- **CodeSpell**: Spell checking
- **Detect-secrets**: Security scanning

### Running Quality Checks

```bash
# Install pre-commit hooks
pre-commit install

# Run all hooks manually
pre-commit run --all-files

# Run specific hook
pre-commit run black
pre-commit run ruff
```

## Configuration

### API Keys

Configure data provider API keys in `~/.openbb_platform/user_settings.json`:

```json
{
  "credentials": {
    "fmp_api_key": "YOUR_KEY",
    "fmp_cached_api_key": "YOUR_KEY",
    "fred_api_key": "YOUR_KEY"
  }
}
```

**Credentials** (configure once — never hardcode key values in source or docs):

- `fmp_api_key` and `fmp_cached_api_key`: set in `~/.openbb_platform/user_settings.json`
  (the platform resolves this per-user path automatically)
- Optionally also available as `FMP_API_KEY` in a `.env` file at the repo root
  (`<repo-root>/.env`)
- OpenBB reads `user_settings.json` automatically on import; `.env` is loaded via
  `python-dotenv` when needed
- Keep `.env` and `user_settings.json` gitignored — they must never be committed

**How to load `.env` in scripts or notebooks:**

```python
from dotenv import load_dotenv
import os
load_dotenv()   # run from the repo root so .env is found, or pass an explicit path
# openbb reads user_settings.json automatically — no manual credential setting needed
from openbb import obb
```

### Python Environment

- **Supported**: Python 3.10 - 3.13
- **Package Manager**: Poetry (for dependency management)
- **Virtual Environment**: Use the project venv for all Python execution in this repo.
  On Windows this checkout uses `.venv_win`; on other platforms use your local
  `.venv` equivalent. Paths below are shown repo-relative — resolve them against
  your own repo root.

#### Project venv — the canonical development environment

```text
Python:    .venv_win\Scripts\python.exe
pip:       .venv_win\Scripts\pip.exe
pytest:    .venv_win\Scripts\python.exe -m pytest
```

**IMPORTANT:** Never use the system/global Python interpreter for running OpenBB
code. It typically has a different (newer) set of extensions installed that does
not match the editable installs in the project venv. Always invoke the
project-venv interpreter (the repo-relative `.venv_win\Scripts\python.exe` above,
or your platform's equivalent — referred to as `$PYTHON` elsewhere).

All `python`, `pip`, and `pytest` commands in this CLAUDE.md should be run with the
project-venv interpreter, e.g.:

```bash
# Activate (PowerShell)
.\.venv_win\Scripts\Activate.ps1

# Or use the repo-relative path (always works without activation)
.venv_win\Scripts\python.exe -m pytest Analysis/tests/ -m "not integration"
.venv_win\Scripts\python.exe -m pytest Analysis/tests/ -m "integration"
```

## Important Notes

### File Structure

- Generated files in `openbb_platform/core/openbb/package/` should not be committed (except `__init__.py`)
- Use development installation (`dev_install.py`) for local development
- Use regular pip install for production deployments

### Testing Strategy

- Unit tests exclude integration marker by default
- Integration tests require external API access and keys
- Platform rebuild required after structural changes

### Testing Rules — Anti "mocks agree with themselves"

**Origin:** the `techtrade.movers` `Information Technology` bug — hand-crafted
mocks passed every assertion in the unit suite while the real code path
silently returned `movers: 0` in production. The suite was hermetic and
fast, but it was testing that the mocks agreed with themselves — not that
the code worked. Follow these six rules to prevent this class of mistake
from recurring anywhere in this repo.

1. **Realistic-shape fixtures, not hand-crafted mocks.**
   Record a real provider response once (VCR cassette or a JSON snapshot
   on disk) and feed it into a unit test that runs the true code path.
   A hand-crafted `Mock(return_value=...)` proves only that your mental
   model of the API is self-consistent — not that the real API returns
   what your model claims. Prefer:

   ```python
   # tests/fixtures/gainers_snapshot_2026-06-15.json  (recorded once)
   def test_build_mover_list_shape_matches_provider(fixture_gainers):
       result = build_mover_list(fetcher=lambda: fixture_gainers)
       assert len(result) > 0, "empty on realistic input = code path is broken"
   ```

2. **One "smoke" integration test per public entry point.**
   Mark it `@pytest.mark.integration`; it's skipped in CI without keys,
   but its *name* documents the gap. If you find yourself writing a
   `diag_*.py` script to reproduce a bug, that script *is* the missing
   integration test — promote it into the suite instead of leaving it
   as a scratch file.

3. **Loud empties. Empty results are not silent success.**
   In any function that reduces / filters / aggregates, an empty output
   from non-empty input is almost always a bug. Log it and (where
   appropriate) raise:

   ```python
   result = build_mover_list(universe)
   if len(universe) > 0 and len(result) == 0:
       logger.warning(
           "build_mover_list returned 0 movers from %d-symbol universe — "
           "likely shape mismatch between fetcher and consumer",
           len(universe),
       )
   ```

   The user sees the failure on run 1, not in a support ticket weeks later.

4. **Test the seams' assumptions, not their behavior.**
   When you inject a dependency (a `fetcher=`, `provider=`, `db=` seam),
   the seam's *contract* is what matters — its shape, its keys, its
   null-vs-missing semantics. Write a one-shot contract test:

   ```python
   def test_default_fetcher_output_shape_matches_universe_shape():
       """Fetcher output must be a superset of the columns the consumer reads."""
       sample = default_fetcher(limit=1)
       required = {"symbol", "market_cap", "sector", "price"}
       assert required.issubset(sample.columns), f"missing: {required - set(sample.columns)}"
   ```

   This is a schema check, not a ranking test — small, fast, and it
   fails the instant a provider changes its response shape.

5. **Prefer "narrow-then-fan-out" over "fan-out-then-filter".**
   `fetch(sector)` cannot silently return empty for a valid universe.
   `fetch(market) → filter(sector)` can — because the "market firehose"
   may not be a superset of your target sector. This is a design rule,
   not a test rule, but it eliminates a whole class of "silently zero"
   bugs at the architectural layer where tests can't reach.

6. **Write the real implementation before the mocks.**
   Injectable seams are a design tool, not a design shortcut. If you
   haven't called the real provider once during design, you don't yet
   know what shape it returns — you're building a mock of your
   assumption, and future mocks will inherit that assumption without
   ever being challenged. Walking-skeleton rule: **one honest live call
   first, mocks after.**

7. **Fixtures MUST produce different outputs under buggy vs. fixed code.**
   The strongest test of a regression test is: temporarily revert the
   production fix, run the test, and verify it FAILS. If the test still
   passes with the fix reverted, the fixture doesn't discriminate — the
   test is *ceremonial* even if the assertion is precise. Discovered
   the hard way across multiple review iterations of PR #331 (bd-0h2.9):
   3 of my first-draft regression tests passed under BOTH pre-fix and
   post-fix code because my fixtures had TARGET returns that dominated
   the perturbation the fix was meant to catch.

   **Discipline:** every load-bearing test gets a reverse-verification
   run at author-time. Mutate the production code the test claims to
   guard, observe the test fail, restore. If mutation doesn't fail the
   test, the fixture is wrong — reshape it (or convert to AST /
   `caplog` assertion, see R7.8 / R7.9).

8. **AST inspection beats `inspect.getsource` for wiring guards.**
   For "test that a specific kwarg is threaded through a constructor"
   or "test that this function is called with this argument," textual
   assertions on `inspect.getsource(fn)` are **defeatable by
   comment-poisoning**. Concrete failure caught in PR #331 iter-3:
   mutating `foo=foo,` → `foo=0.0,  # BUG: foo=foo disabled` passed a
   textual `"foo=foo" in src` check because the string still appeared
   inside the comment.

   ```python
   # WRONG — defeatable by comments
   assert "momentum_accel_63d=momentum_accel_63d" in inspect.getsource(fn)

   # RIGHT — walks the parsed AST, comments are stripped by the parser
   tree = ast.parse(inspect.getsource(fn))
   for node in ast.walk(tree):
       if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
           if node.func.id == "Phase6Result":
               for kw in node.keywords:
                   if kw.arg == "momentum_accel_63d":
                       assert isinstance(kw.value, ast.Name), "hardcoded literal!"
                       assert kw.value.id == "momentum_accel_63d"
   ```

   The AST is the code; the source text is the presentation. Any
   assertion at the presentation layer can be defeated by
   presentation-layer changes (comments, whitespace, formatting) that
   don't affect behavior.

9. **`caplog` assertions beat value assertions for R7.3 loud-empty branches.**
   When the load-bearing behavior is "the code emits a WARNING and
   returns 0.0," asserting on the value alone is **defeatable by
   coincidence** — the mutation may happen to produce 0.0 through a
   different code path. Assert on the WARNING substring instead:
   the warning fires only from the specific branch the mutation
   removes.

   ```python
   # WRONG — coincidence-defeatable
   assert accel == 0.0

   # RIGHT — the warning is the load-bearing signal
   with caplog.at_level(logging.WARNING, logger="my_module"):
       accel = my_function(degenerate_input)
   assert accel == 0.0
   warnings = [r for r in caplog.records if "peer set too thin" in r.getMessage()]
   assert len(warnings) == 1
   ```

   Verified via mutation testing in PR #331 iter-3: mutating
   `if len(x) < 3:` → `< 2:` correctly caused the caplog test to
   fail (0 warnings) while a naive `assert accel == 0.0` still passed.

10. **Test file module identity MUST match production module identity.**
    `caplog.at_level(logger="my_module")` targets a specific logger by
    name. If the test file imports the production module by one path
    and other code imports it by another, they resolve to DIFFERENT
    logger objects — and `caplog` captures nothing. Silent test skip.

    **Windows sys.path.insert gotcha (PR #331 iter-4):** the same file
    can be simultaneously importable as `stock_analysis` (via
    `sys.path.insert(0, ".../Analysis")`) AND `Analysis.stock_analysis`
    (via repo root). Both create distinct module identities with
    distinct loggers. Rule: within a test file, always import the
    production module by exactly one path, and use that same path in
    every `caplog.at_level(logger=...)` call.

11. **Ceremonial tests ship in EVERY iteration's first draft.**
    Empirically observed across 4 review iterations of PR #331: my
    first-draft regression tests were ceremonial in iter-1 (fixture
    dominance), iter-2 (fixture dominance), iter-3 (test duplicated
    the fixed arithmetic in the test body), and iter-4 (test used
    imported constant + wrong code path). The pattern is universal:
    if you don't reverse-verify, you ship ceremony.

    **Discipline:** the exit criterion for shipping a regression test
    is not "the test passes on the fix" — it's "the test *fails* on
    the reverted-fix and *passes* on the fix." Every load-bearing
    test needs both assertions, empirically observed.

### Applying these rules to `Analysis/` and `openbb_platform/extensions/techtrade/`

- **`Analysis/tests/`** — every new phase-level unit test that stubs a
  provider must have a matching integration test hitting `fmp_cached`
  live (they exist for P1-P7 already; keep the pattern for follow-ups).
- **`techtrade/tests/`** — for `signals`, `plan`, `scan`, `movers`,
  `segments`, `validate`, `tune`: each needs (a) a recorded-fixture
  unit test, (b) a `@pytest.mark.integration` smoke test, and
  (c) a loud-empty guard in the reducer/aggregator step.
- **`providers/fmp_cached/`** — contract tests here catch upstream API
  drift before it reaches consumers. Prefer one-per-endpoint schema
  assertions over full-fidelity response mocks.
- **Diagnostic scripts (`diag_*.py`, `investigate_*.py`)** — if you
  wrote one to root-cause a bug, it's a candidate for promotion into
  the test suite. Don't let them accumulate in `temp/` as tribal
  knowledge.

### Desktop Development

- Frontend: React + TypeScript + Tailwind CSS
- Backend: Rust with Tauri framework
- Build system: Vite for frontend, Cargo for Rust backend

---

## Analysis Module (`Analysis/`)

The `Analysis/` directory contains a standalone 7-phase single-stock investment analysis pipeline.

### Key files

| File | Purpose |
| --- | --- |
| `Analysis/stock_analysis.py` | Main module — 7 phase functions + helpers (2,100+ lines) |
| `Analysis/tests/test_stock_analysis.py` | pytest test suite — 118 tests (56 unit + 62 integration) |
| `Analysis/docs/PHASED_ANALYSIS_MASTER_PLAN.md` | Master planning document tying all phases together |
| `Analysis/docs/phases/PHASE_*.md` | Ground-truth spec for each of the 7 phases |
| `Analysis/docs/FINANCIAL_DOMAIN_GLOSSARY.md` | Beginner-friendly financial terminology reference |

### Quick start

```python
# Always use .venv_win python — credentials auto-loaded from user_settings.json
from stock_analysis import AnalysisConfig, run_full_analysis

results = run_full_analysis(AnalysisConfig(symbol="MSFT"))
p7 = results["p7"]
print(p7.action_label, p7.composite_score)
```

### Provider rule

**`fmp_cached` is the only provider used** — no `fmp` fallback, no yfinance.
`PRIMARY_PROVIDER = "fmp_cached"` is enforced as a constant in `stock_analysis.py`.

### Running Analysis tests

```bash
# Unit tests (no API needed, ~1s)
.venv_win\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "not integration" -v

# Integration tests against MSFT + AAPL via fmp_cached (~19 min)
.venv_win\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "integration" -v
```

<!-- BEGIN ISSUE TRACKING -->
## Issue Tracking — GitHub Issues (bd retired)

This project uses **GitHub Issues** for ALL work tracking, across every
branch. The prior `bd (beads)` system has been retired repository-wide.

### Quick Reference

```bash
gh issue list --state open --assignee @me     # Your open work
gh issue list --state open --label ready      # Work available to claim
gh issue view <NN>                             # Details
gh issue edit <NN> --add-assignee @me          # Claim work
gh issue close <NN> --reason completed         # Mark complete
gh issue create --title "..." --body "..."     # New issue
```

### Rules

- Use `gh` (GitHub CLI) for ALL task tracking — do NOT use `bd`, TodoWrite,
  TaskCreate, or ad-hoc markdown TODO lists.
- Do NOT run `bd` commands or create `.beads/` state in any branch.
- Cross-session memory belongs in `docs/MEMORIES.md` (checked-in file), not
  in `bd remember` or scratch `MEMORY.md` files.
- Historical `bd-XX` references in old commits/docs are read-only relics;
  do not create new ones.

## Session Completion

**When ending a work session**, complete ALL steps below. Work is NOT
complete until `git push` succeeds (when the current profile authorizes it).

**MANDATORY WORKFLOW:**

1. **File follow-up issues** — for anything discovered but not fixed,
   `gh issue create` before closing the session.
2. **Run quality gates** (if code changed) — tests, linters, builds.
3. **Update issue status** — `gh issue close <NN>` for finished work;
   comment progress on any that remain in-flight.
4. **Handle git per active profile**:

   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```

5. **Hand off** — summarize changes, validation, issue status, and any
   blocked commit/push step.

**Critical rules:**

- Explicit user or orchestrator instructions override this block.
- Do not commit or push without clear authority from the active profile
  or the current user request.
- If a required push is blocked, stop and report the exact command + error.
<!-- END ISSUE TRACKING -->
