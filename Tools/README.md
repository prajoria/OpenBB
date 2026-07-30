# Tools/

Portfolio-specific ad-hoc utilities — one-off scripts that don't belong in
the packaged `openbb_platform/tools/` (which ships as pip-installable
sub-packages) or in `scripts/` (which holds repo-wide automation).

## Rough scope

| What lives here | What lives elsewhere |
|---|---|
| Portfolio data prep: `build_sp500_constituents.py`, `enrich_cusip_figi.py`, `export_basket_weight_comparison.py`, `ingest_sec_13f.py`, `load_espp_plan.py` | Repo-wide dev automation → `scripts/` |
| One-shot analyses: `mortgage_amortization.py`, `fetch_position_history.py` | Installable tools (import as packages) → `openbb_platform/tools/` |
| Portable-venv builder: `make_venv_portable.py` | |

## Where else to look

- **`scripts/`** — most repo-wide automation and CI helpers. Notably:
  - `pi_claim.py` — Portfolio Intelligence Engine issue-claim + heartbeat wrapper for Project #4
  - `reset_notebooks_for_checkin.py` — strip notebook state before commit (per CLAUDE.md notebook check-in hygiene rule)
  - `linkify_notebook_issue_refs.py` — convert bare `#NNN` issue refs in markdown cells to full GitHub URLs
  - `sync_notebooks_local.py` — one-way sync `notebooks/` → `notebooks_local/` sandbox (per CLAUDE.md notebook local sandbox rule)
  - `pi_fmp_record.py` — FMP fixture recording harness (Project #4 spec)
  - `pi_env_smoke.py` — `.venv_portfolio` smoke check
  - `migrate_pi_beads_to_gh.py`, `populate_pi_project.py`, `align_fmp_issues_to_convention.py` — one-shot migration helpers

- **`openbb_platform/tools/`** — installable sub-packages (`portfolio_export`, `portfolio_snapshot_importer`, `scrape_record`). These have their own `pyproject.toml` and are `pip install -e`-installable.

## Rule of thumb before adding a new file here

1. Will other repo automation (tests, CI, Claude sessions, cron) import or exec this file? → put it under `scripts/` instead — everything there is treated as first-class repo tooling and the paths are stable.
2. Does it need to ship to end users? → package it under `openbb_platform/tools/` as a sub-package with its own `pyproject.toml`.
3. Is it a one-off portfolio-domain script the operator runs by hand, ideally without touching any other file to invoke it? → `Tools/` is fine.
