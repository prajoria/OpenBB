# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project ↔ Repo Mapping (do not lose this)

Portfolio work is tracked in a single GitHub Project bound to a single repo,
against a single long-lived integration branch. Recorded here so it survives
session context loss.

- **GitHub Project:** [Portfolio Intelligence Engine (#4)](https://github.com/users/prajoria/projects/4) — private, owned by `prajoria`, 90 items, all Issues
- **Repo (only one):** [`prajoria/OpenBB`](https://github.com/prajoria/OpenBB) — fork of `OpenBB-finance/OpenBB` (upstream)
- **Long-lived integration branch:** [`portfolio`](https://github.com/prajoria/OpenBB/tree/portfolio) — published on origin, this is where all portfolio-intel work converges
- **Base of `portfolio`:** `develop` (origin/HEAD)
- **Absorb-from-develop branches:** `chore/absorb-develop-plain`, `chore/absorb-develop-into-portfolio` — used to periodically bring `develop` INTO `portfolio` (one-way, see workflow below)
- **Feature branches:** `feat/pi-*` (e.g. `feat/pi-app/paper-migration`, `feat/pi-widgets/playwright-harness`) — cut FROM `portfolio`, PR back INTO `portfolio`
- **Bead epic:** `bd-qy83` (Portfolio Intelligence), children `bd-qy83.1.*`
- **Local workspace path:** `H:\masterswork\git\OpenBB-Portfolio\OpenBB` (distinct from `H:\masterswork\git\OpenBB` which tracks `develop` for non-portfolio work)

### Workflow rules — Portfolio Intelligence Engine

1. **One-way absorb only.** Merges/rebases flow **`develop` → `portfolio`** to
   keep portfolio current. Do **NOT** open a PR from `portfolio` → `develop`
   without an explicit, loud sign-off from the user (Daisy). Silence is not
   consent. Until that sign-off arrives, `portfolio` accumulates work
   locally-to-the-fork and never proposes back to base.
2. **Side branches only.** Never commit directly to `portfolio`. All work
   happens on side branches cut from `portfolio` (typically `feat/pi-*`),
   which PR **into `portfolio`**. `portfolio` is a merge target, not a
   worktop.
3. **Every unit of work is a tracked GitHub Issue in `prajoria/OpenBB`.**
   Every such issue is added to Project #4 (Portfolio Intelligence Engine).
   No issue → no work. Commits/PRs cite the issue per the "Communication
   Conventions" and "Coordination — GitHub Issues primary, bd fallback"
   sections below.
4. **Upstream promotion is user-initiated.** When Daisy explicitly says "open
   a PR from portfolio to develop" (or equivalent unambiguous instruction),
   only then create the PR from `portfolio` → `develop` (or upstream
   `OpenBB-finance/OpenBB:develop` if directed).

### Cross-check commands

```bash
gh project view 4 --owner prajoria
gh project item-list 4 --owner prajoria --format json | jq '.items | group_by(.repository) | map({repo:.[0].repository,count:length})'
git -C H:/masterswork/git/OpenBB-Portfolio/OpenBB remote -v
git ls-remote origin refs/heads/portfolio            # confirms origin/portfolio exists
git -C H:/masterswork/git/OpenBB-Portfolio/OpenBB log origin/portfolio -5 --oneline
```

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
2. Claim by self-assigning **AND** setting the Project #4 Status to
   `In Progress`:

   ```bash
   gh issue edit <NN> --add-assignee @me
   python scripts/pi_claim.py <NN> in-progress    # sets Project #4 Status
   ```

   The Project Status update is **mandatory, not optional**. Without it,
   the board's "In Progress" column stays empty and there is no way to
   see at a glance which agent has claimed what. `pi_claim.py` is a
   one-line wrapper around the GraphQL mutation — no excuse to skip it.
3. **Heartbeat every ≤10 minutes** while the task is claimed:

   ```bash
   python scripts/pi_claim.py <NN> heartbeat   # updates last-touch timestamp
   ```

   Any agent working on a claimed issue MUST run a heartbeat at least
   once every 10 minutes. If a claimed issue's last heartbeat is older
   than **2 hours**, the task is considered abandoned (agent crashed,
   session died, or context was lost) — another agent may forcibly
   reclaim it with `pi_claim.py <NN> reclaim`, which resets the
   heartbeat and posts an audit comment on the issue naming the old
   owner and the reclaim reason.
   - Run heartbeats at natural pause points (after a test run, after a
     commit, before/after a review round). Set a `ScheduleWakeup` or
     `CronCreate` reminder if the work runs for a stretch without
     natural pauses.
   - Anti-pattern: fire-and-forget heartbeats every 10 min with no work
     between them. If you're not making progress, don't fake it — post
     a comment on the issue explaining why you're blocked, then release
     with `pi_claim.py <NN> release` (moves back to `Todo`).
4. Branch names embed the issue number: `feat/topic-gh-<NN>`,
   `fix/topic-gh-<NN>`, `docs/topic-gh-<NN>`.
5. Every commit body cites its issue: `Refs #NN` (or `Closes #NN` on the
   final commit / PR body for auto-close on merge).
6. PR title cites the issue: `<type>(<scope>): <what> (#NN)`.
7. When the PR merges, the auto-close workflow closes the issue AND the
   Project #4 Status auto-transitions to `Done` (via the "closes an
   issue" workflow rule). No manual Status update needed on completion —
   just at claim time.

**Stale-claim reclaim protocol** (when picking up work from a
crashed/idle agent):

```bash
# Check every In Progress item's last heartbeat:
python scripts/pi_claim.py --list-stale        # prints issues with heartbeat > 2h

# Reclaim a specific one (posts an audit comment on the issue):
python scripts/pi_claim.py <NN> reclaim
```

The reclaim comment names the previous owner (from `--add-assignee`),
the last-heartbeat timestamp, and the reclaiming agent. This is the
audit trail — never quietly steal a claim; always leave the comment.

**Cross-session memory:** durable knowledge lives in `docs/MEMORIES.md`
(a plain checked-in markdown file). Append new entries; do NOT create
scratch `MEMORY.md` files in random locations.

**Legacy references:** any `bd-XX` identifier in old commit history, old
comments, or old docs is historical only — treat it as a permanent
identifier of past work, but never file new `bd-XX` items.

## General agent development rules

These rules apply to **any** agent doing development work in this
repository, regardless of program (portfolio-intel, techtrade, upstream
sync, docs, ops, etc.). The heartbeat rules above describe the
mechanism for the Portfolio Intelligence Engine specifically; the
principles below generalize.

### 1. Heartbeat every ≤10 minutes on any claimed task

If you have taken ownership of a task (via `pi_claim.py in-progress`,
via an `--add-assignee`, or by simply working on a branch named after
an issue), you MUST leave a visible signal at least every 10 minutes
that you are still alive:

- Portfolio Intelligence Engine tasks: `python scripts/pi_claim.py <NN> heartbeat`
- Other programs (no equivalent tool): post a lightweight comment on
  the issue every ≤10 min with the marker
  `<!-- pi-claim: owner=<login> hb=<ISO8601Z> action=heartbeat -->`
  so the same reclaim logic can be added later without breaking
  history.

A heartbeat is not a status update — it's an "I'm still here" signal.
Post it after a natural pause (finished a test run, finished a commit,
finished a review round). Set a `ScheduleWakeup` or `CronCreate`
reminder if the work runs long without natural pauses.

### 2. 2-hour staleness = abandoned = reclaimable

Any claimed task with no heartbeat in the last **2 hours** is
considered abandoned (agent crashed, session died, context was lost,
machine went to sleep, etc.). Any other agent may forcibly reclaim it
by:

- Running `pi_claim.py <NN> reclaim` for Portfolio Intelligence Engine
- For other programs: post a `reclaim` marker comment naming the
  previous owner, then take the branch/PR over

The reclaim MUST leave an audit comment on the issue naming the old
owner and reason. Never silently steal a claim.

### 3. Faked heartbeats are worse than missed ones

If you can't make progress, do NOT keep pinging heartbeats to hide
that fact. Instead:

- Post a comment explaining what's blocked
- Release the claim: `pi_claim.py <NN> release` (moves back to Todo)
- File a follow-up issue if the blocker needs someone else's attention

An empty heartbeat every 10 min for 2 hours reads exactly like real
progress to every other agent — but wastes 2 hours before anyone else
can pick it up.

### 4. Check the board before claiming

Before running `pi_claim.py <NN> in-progress`, always check:

```bash
python scripts/pi_claim.py --status <NN>       # is anyone on it?
python scripts/pi_claim.py --list-stale        # any orphans to reclaim first?
```

If someone else has a fresh (<2h) claim, pick a different task or
coordinate directly on the issue. If they have a stale (≥2h) claim,
reclaim it with the audit comment.

### 5. Session-start protocol for agents

Every agent starting a new session should:

1. `python scripts/pi_claim.py --list-stale` — see what's abandoned
2. `gh issue list --assignee @me --state open` — see what you still
   own (from a previous session that maybe crashed)
3. For each thing you still own but aren't actively working on:
   `pi_claim.py <NN> release` — free it up

This 30-second protocol prevents the "40 open claims none of which are
active" state that stalls parallel autopilot.

---

## Sensitive data — brokerage exports & credentials

Rules for **any** brokerage-account data (Fidelity Positions/Balances/
Activity CSVs, Schwab/Vanguard/etc. exports, account statements, tax
lots, cost bases). These override any general "look at the data to
understand it" instinct.

### 1. Downloaded data NEVER lives on the repo path

- All exports MUST be written under `H:\masterswork\browser_exports\`
  (or any other path OUTSIDE `H:\masterswork\git\OpenBB-Portfolio\`).
- The `portfolio_export` config layer enforces this at every CLI
  invocation via `Config._validate_outside_repo()` — raises `ConfigError`
  if `download_dir`, `profile_dir`, or `user_recordings_dir` resolves
  inside the repo root. Do NOT weaken or bypass this check.
- `.gitignore` is defense-in-depth, not primary defense. The path
  boundary is primary.

### 2. Never read exported data directly

- Do NOT open portfolio exports with `read_file`, `Get-Content`, `cat`,
  `grep_search`, notebook cell previews, Excel-viewer tools, or any
  inline preview that surfaces row content to the model.
- OK: metadata-only checks — `Get-Item` (path/size/mtime),
  `Measure-Object -Line` (row count), header-row inspection to confirm
  schema shape.
- All row-level inspection, transformation, and aggregation happens
  through Python tools we build (loaders, validators, aggregators).
  The tool's OUTPUT (aggregates, validation reports, summary stats) is
  what the model sees — not the raw rows.
- If a Python tool prints raw row data to stdout in a way the model
  will read, that's a bug in the tool — fix it to print aggregates or
  redact identifiers.

### 3. Credentials never appear in code, recordings, or chat

- Recording scaffolds (`portfolio_export/record.py` template) MUST NOT
  contain literal usernames or passwords. Login is manual-in-browser
  via `require_login()` + persistent Chrome profile.
- If a user pastes credentials in chat: warn immediately, do not echo
  the literal string in responses (each echo re-writes it to the local
  VS Code transcript at `AppData\Roaming\Code\User\workspaceStorage\
  <ws-id>\GitHub.copilot-chat\transcripts\`), instruct to rotate.
- The persistent Chrome profile at
  `C:\Users\daaji\.portfolio_export\chrome_profile\` holds session
  cookies — do NOT commit, back up, or copy this directory anywhere
  under the repo path.

### 4. Where things live

| Purpose | Location | Enforced by |
|---|---|---|
| Recordings (Playwright scaffolds) | `H:\masterswork\browser_recordings\` | `config._validate_outside_repo` |
| Downloaded exports | `H:\masterswork\browser_exports\<YYYY-MM-DD>\` | `config._validate_outside_repo` |
| Chromium profile | `C:\Users\daaji\.portfolio_export\chrome_profile\` | `config._validate_outside_repo` |
| Env overrides | `OpenBB\openbb_platform\tools\portfolio_export\.env` (gitignored) | `.gitignore` |

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

**Portfolio work uses `.venv_portfolio`, NOT `.venv_win`.** The shared
`.venv_win` is used by parallel dev paths in sibling worktrees and gets
polluted / overstepped when multiple checkouts touch it. `.venv_portfolio`
is the isolated Python environment for portfolio-intel branch work.

```bash
# One-time setup (fresh venv, Python 3.12+)
python -m venv .venv_portfolio
.venv_portfolio/Scripts/python.exe -m pip install --upgrade pip

# Install the extensions portfolio-intel work depends on (editable).
# The `dev_install.py` path via poetry doesn't populate a fresh pip venv;
# use direct pip -e for reliability.
.venv_portfolio/Scripts/python.exe -m pip install \
  -e openbb_platform/core \
  -e openbb_platform/extensions/backtest \
  -e openbb_platform/extensions/portfolio_intel \
  -e openbb_platform/providers/fmp_cached \
  -e openbb_platform/providers/fmp \
  -e openbb_platform/providers/yfinance
.venv_portfolio/Scripts/python.exe -m pip install pytest pytest-asyncio pytest-mock

# Smoke test — should print portfolio_intel + backtest in the extension list.
.venv_portfolio/Scripts/python.exe -c "from openbb import obb; print([a for a in dir(obb) if not a.startswith('_')])"

# Activate (PowerShell)
.\.venv_portfolio\Scripts\Activate.ps1
```

**Legacy `.venv_win` note:** older instructions and scripts (`openbb.sh`,
`start_desktop_dev.ps1`, `portfolio_app/setup.ps1`) still reference
`.venv_win`. Those paths remain valid for non-portfolio work, but portfolio
branch commits must be tested with `.venv_portfolio` to prove they work in
a clean environment. If a test passes on `.venv_win` but fails on
`.venv_portfolio`, treat it as an install-path bug (see #856-class issues).

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

Portfolio work runs against `.venv_portfolio` (see Environment Setup).

```bash
# Run unit tests (excludes integration tests)
.venv_portfolio\Scripts\python.exe -m pytest openbb_platform -m "not integration"

# Run Analysis module unit tests (no live API needed)
.venv_portfolio\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "not integration" -v

# Run Analysis integration tests (requires fmp_cached API key — reads from user_settings.json + .env)
.venv_portfolio\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "integration" -v

# Test specific provider
.venv_portfolio\Scripts\python.exe -m pytest openbb_platform/providers/yfinance/tests/

# Run integration tests (requires API keys)
.venv_portfolio\Scripts\python.exe -m pytest openbb_platform -m "integration"

# Test installation
.venv_portfolio\Scripts\python.exe test_openbb.py
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
# Rebuild platform to reflect changes (run with .venv_portfolio python)
.venv_portfolio\Scripts\python.exe -c "import openbb; openbb.build()"
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
  On Windows this checkout uses `.venv_portfolio`; on other platforms use your local
  `.venv` equivalent. Paths below are shown repo-relative — resolve them against
  your own repo root.

#### Project venv — the canonical development environment

```text
Python:    .venv_portfolio\Scripts\python.exe
pip:       .venv_portfolio\Scripts\pip.exe
pytest:    .venv_portfolio\Scripts\python.exe -m pytest
```

**IMPORTANT:** Never use the system/global Python interpreter for running OpenBB
code. It typically has a different (newer) set of extensions installed that does
not match the editable installs in the project venv. Always invoke the
project-venv interpreter (the repo-relative `.venv_portfolio\Scripts\python.exe` above,
or your platform's equivalent — referred to as `$PYTHON` elsewhere).

All `python`, `pip`, and `pytest` commands in this CLAUDE.md should be run with the
project-venv interpreter, e.g.:

```bash
# Activate (PowerShell)
.\.venv_portfolio\Scripts\Activate.ps1

# Or use the repo-relative path (always works without activation)
.venv_portfolio\Scripts\python.exe -m pytest Analysis/tests/ -m "not integration"
.venv_portfolio\Scripts\python.exe -m pytest Analysis/tests/ -m "integration"
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
# Always use .venv_portfolio python — credentials auto-loaded from user_settings.json
from stock_analysis import AnalysisConfig, run_full_analysis

results = run_full_analysis(AnalysisConfig(symbol="MSFT"))
p7 = results["p7"]
print(p7.action_label, p7.composite_score)
```

### Provider rule

**`fmp_cached` preferred, `fmp` is fallback, never yfinance.**

- Always use `fmp_cached` when the endpoint exists there. `PRIMARY_PROVIDER = "fmp_cached"` remains the default constant in `stock_analysis.py`.
- Fall back to raw `fmp` **only** when `fmp_cached` genuinely does not cover the endpoint. In that case:
  1. Use `fmp` for the immediate work so the roadmap isn't blocked. Same escape valve applies to any future provider swap (e.g. if we start pulling FRED, EOD-HD, etc.): use whatever is available, keep moving.
  2. **File a GH issue** in `prajoria/OpenBB`, add it to Project #4, label `area:fmp-cached-gap`. Body must include: missing endpoint, calling context, what needs to be added to `providers/fmp_cached/`.
  3. Reference that issue from the code path with a `# TODO(gh-<NN>): migrate to fmp_cached once endpoint lands` comment so the debt is visible in every future diff.
  4. **Do NOT implement the `fmp_cached` extension yourself.** A separate team owns `providers/fmp_cached/`. The portfolio team's job is to file the gap issue and unblock via fallback — never to open PRs adding endpoints to `fmp_cached`. If a gap looks trivial and you're tempted to fix it inline, resist: cross-team boundary violations create merge conflicts and duplicated work.
- **Reviewer discipline** (Mira gate, Zev veto): any PR introducing an `fmp` fallback that does *not* have a paired `area:fmp-cached-gap` GH issue is rejected. Codified rule, no judgment required.
- Rationale: `fmp_cached` gives reproducible tests, deterministic dev loops, and cost control. The fallback exists so a missing endpoint never blocks the roadmap — but every use of the fallback is tracked debt handed off to the `fmp_cached` team.

### Running Analysis tests

```bash
# Unit tests (no API needed, ~1s)
.venv_portfolio\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "not integration" -v

# Integration tests against MSFT + AAPL via fmp_cached (~19 min)
.venv_portfolio\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "integration" -v
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
