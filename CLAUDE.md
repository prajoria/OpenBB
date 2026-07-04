# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Communication Conventions

**Always pair an issue number with its title/description — never cite a bare number.**
When referencing any issue (GitHub `#NN` or beads `bd-NN`) in a question, status
update, summary, commit message, or PR body, write it as `#NN (short description)`
so it is understandable without a lookup.

- Good: `#65 (Scaffold techtrade extension + entry point + green build)`
- Bad: `#65`

If you don't already know the title, look it up first (`gh issue view NN` /
`bd show <id>`) before mentioning it.

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

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

> These conventions apply to AI agents and contributors working **in this fork**,
> which has adopted Beads as its tracker. Contributors who do not use Beads should
> substitute their own task tracker — the intent is "use a real issue tracker, not
> scattered TODOs," not a mandate of one specific tool.

- Prefer `bd` for task tracking in this fork — avoid ad-hoc markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge rather than loose MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See <https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md> for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:

   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```

5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**

- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
