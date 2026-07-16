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
```
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

### Desktop Development
- Frontend: React + TypeScript + Tailwind CSS
- Backend: Rust with Tauri framework
- Build system: Vite for frontend, Cargo for Rust backend

---

## Analysis Module (`Analysis/`)

The `Analysis/` directory contains a standalone 7-phase single-stock investment analysis pipeline.

### Key files
| File | Purpose |
|---|---|
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

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ccf33ec3 -->
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

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->

